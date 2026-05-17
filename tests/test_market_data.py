import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from stock_analyst.market_data import (
    MarketDataBudgetState,
    available_provider_metadata,
    build_market_data_cache_metadata,
    describe_market_data_request,
    load_market_data_budget_state,
    load_market_data_planning_config,
    load_market_data_config,
    load_market_data_env_file,
    load_market_data_symbol_file,
    market_data_disabled,
    plan_fmp_enrichment_requests,
    plan_market_data_enrichment_requests,
    read_market_data_cache_record,
    write_market_data_budget_state,
    write_market_data_cache_record,
    parse_stooq_daily_csv,
)
from stock_analyst.cli import run_market_data_plan_command


class MarketDataTest(unittest.TestCase):
    def test_provider_metadata_documents_free_options_without_live_network(self) -> None:
        providers = {provider.provider_id: provider for provider in available_provider_metadata()}

        self.assertIn("disabled", providers)
        self.assertIn("stooq_csv", providers)
        self.assertIn("alpha_vantage", providers)
        self.assertIn("twelve_data", providers)
        self.assertIn("finnhub", providers)
        self.assertIn("fmp", providers)
        self.assertIn("sec_companyfacts", providers)
        self.assertFalse(any(provider.network_access for provider in providers.values()))
        self.assertTrue(providers["alpha_vantage"].cache_required_before_live)
        self.assertTrue(providers["alpha_vantage"].rate_limit_notes)
        self.assertEqual(providers["alpha_vantage"].credential_env_var, "ALPHAVANTAGE_API_KEY")
        self.assertEqual(providers["alpha_vantage"].daily_call_budget, 25)
        self.assertEqual(providers["twelve_data"].credential_env_var, "TWELVEDATA_API_KEY")
        self.assertEqual(providers["twelve_data"].daily_call_budget, 800)
        self.assertEqual(providers["finnhub"].credential_env_var, "FINNHUB_API_KEY")
        self.assertEqual(providers["finnhub"].daily_call_budget, 500)
        self.assertEqual(providers["fmp"].credential_env_var, "FMP_API_KEY")
        self.assertEqual(providers["fmp"].daily_call_budget, 235)
        self.assertIn("512MB/month", providers["fmp"].bandwidth_notes[0])

    def test_market_data_config_defaults_to_disabled(self) -> None:
        config = load_market_data_config({})

        self.assertEqual(config.provider.provider_id, "disabled")
        self.assertFalse(config.enabled)
        self.assertEqual(config.reason, "market data enrichment is disabled by default")

    def test_market_data_config_allows_local_stooq_csv_parser_only(self) -> None:
        config = load_market_data_config({"STOCK_ANALYST_MARKET_DATA_PROVIDER": "stooq_csv"})

        self.assertEqual(config.provider.provider_id, "stooq_csv")
        self.assertTrue(config.enabled)
        self.assertFalse(config.provider.network_access)

    def test_market_data_config_rejects_unknown_provider(self) -> None:
        config = load_market_data_config({"STOCK_ANALYST_MARKET_DATA_PROVIDER": "live_guess"})

        self.assertEqual(config.requested_provider, "live_guess")
        self.assertEqual(config.provider.provider_id, "disabled")
        self.assertFalse(config.enabled)
        self.assertIn("unknown market data provider", config.reason)

    def test_key_based_provider_remains_disabled_without_credentials(self) -> None:
        config = load_market_data_config({"STOCK_ANALYST_MARKET_DATA_PROVIDER": "alpha_vantage"})

        self.assertEqual(config.provider.provider_id, "alpha_vantage")
        self.assertFalse(config.enabled)
        self.assertEqual(
            config.reason,
            "missing credential environment variable: ALPHAVANTAGE_API_KEY",
        )

    def test_key_based_provider_with_credentials_is_still_metadata_only(self) -> None:
        config = load_market_data_config(
            {
                "STOCK_ANALYST_MARKET_DATA_PROVIDER": "twelve_data",
                "TWELVEDATA_API_KEY": "test-key",
            }
        )

        self.assertEqual(config.provider.provider_id, "twelve_data")
        self.assertFalse(config.enabled)
        self.assertEqual(config.reason, "live provider adapter is not implemented")

    def test_key_based_provider_accepts_legacy_credential_aliases(self) -> None:
        alpha_config = load_market_data_config(
            {
                "STOCK_ANALYST_MARKET_DATA_PROVIDER": "alpha_vantage",
                "ALPHA_VANTAGE_API_KEY": "test-key",
            }
        )
        twelve_config = load_market_data_config(
            {
                "STOCK_ANALYST_MARKET_DATA_PROVIDER": "twelve_data",
                "TWELVE_DATA_API_KEY": "test-key",
            }
        )

        self.assertEqual(alpha_config.reason, "live provider adapter is not implemented")
        self.assertEqual(twelve_config.reason, "live provider adapter is not implemented")

    def test_finnhub_provider_with_key_is_still_metadata_only(self) -> None:
        config = load_market_data_config(
            {
                "STOCK_ANALYST_MARKET_DATA_PROVIDER": "finnhub",
                "FINNHUB_API_KEY": "test-key",
                "FINNHUB_SECRET": "test-secret",
            }
        )

        self.assertEqual(config.provider.provider_id, "finnhub")
        self.assertFalse(config.enabled)
        self.assertFalse(config.provider.network_access)
        self.assertEqual(config.reason, "live provider adapter is not implemented")

    def test_fmp_provider_with_credentials_is_still_metadata_only(self) -> None:
        config = load_market_data_config(
            {
                "STOCK_ANALYST_MARKET_DATA_PROVIDER": "fmp",
                "FMP_API_KEY": "test-key",
            }
        )

        self.assertEqual(config.provider.provider_id, "fmp")
        self.assertFalse(config.enabled)
        self.assertFalse(config.provider.network_access)
        self.assertEqual(config.reason, "live provider adapter is not implemented")

    def test_fmp_provider_without_credentials_is_known_but_disabled(self) -> None:
        config = load_market_data_config({"STOCK_ANALYST_MARKET_DATA_PROVIDER": "fmp"})

        self.assertEqual(config.requested_provider, "fmp")
        self.assertEqual(config.provider.provider_id, "fmp")
        self.assertFalse(config.enabled)
        self.assertEqual(config.reason, "missing credential environment variable: FMP_API_KEY")

    def test_market_data_planning_config_loads_env_file_without_exposing_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            env_file.write_text(
                "\n".join(
                    (
                        "STOCK_ANALYST_MARKET_DATA_PROVIDER=fmp",
                        "FMP_API_KEY='test-secret-key'",
                        f"STOCK_ANALYST_MARKET_DATA_CACHE_DIR={root / 'cache'}",
                        f"STOCK_ANALYST_MARKET_DATA_BUDGET_DIR={root / 'budget'}",
                        "STOCK_ANALYST_MARKET_DATA_DAILY_CALL_LIMIT=17",
                        "STOCK_ANALYST_MARKET_DATA_TERMS_VERSION=fmp-review-2026-05-17",
                    )
                ),
                encoding="utf-8",
            )

            values = load_market_data_env_file(env_file)
            config = load_market_data_planning_config(env={}, env_file=env_file)

        self.assertEqual(values["FMP_API_KEY"], "test-secret-key")
        self.assertEqual(config.provider_config.provider.provider_id, "fmp")
        self.assertFalse(config.provider_config.enabled)
        self.assertTrue(config.credential_configured)
        self.assertEqual(config.daily_call_limit, 17)
        self.assertEqual(config.budget_dir, root / "budget")
        self.assertEqual(config.terms_version, "fmp-review-2026-05-17")
        self.assertNotIn("test-secret-key", repr(config))

    def test_market_data_symbol_file_normalizes_comments_and_comma_lists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            symbol_file = Path(temp_dir) / "symbols.txt"
            symbol_file.write_text(
                "\n".join(
                    (
                        "# reviewer-controlled symbols",
                        " aapl ",
                        "MSFT, nvda",
                        "",
                        "AAPL",
                    )
                ),
                encoding="utf-8",
            )

            symbols = load_market_data_symbol_file(symbol_file)

        self.assertEqual(symbols, ("AAPL", "MSFT", "NVDA"))

    def test_market_data_symbol_file_rejects_whitespace_inside_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            symbol_file = Path(temp_dir) / "symbols.txt"
            symbol_file.write_text("BAD SYMBOL\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                load_market_data_symbol_file(symbol_file)

    def test_market_data_is_disabled_by_default(self) -> None:
        result = market_data_disabled("AAPL.US")

        self.assertEqual(result.provider, "disabled")
        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.quote)

    def test_stooq_daily_csv_parser_returns_latest_valid_close(self) -> None:
        result = parse_stooq_daily_csv(
            """Date,Open,High,Low,Close,Volume
2026-05-12,10,11,9,10.50,1000
2026-05-14,12,13,11,12.75,1200
""",
            symbol="AAPL.US",
        )

        self.assertEqual(result.status, "available")
        self.assertEqual(result.quote.close, Decimal("12.75"))
        self.assertEqual(result.quote.observed_on.isoformat(), "2026-05-14")

    def test_stooq_daily_csv_parser_does_not_invent_missing_prices(self) -> None:
        result = parse_stooq_daily_csv(
            """Date,Open,High,Low,Close,Volume
2026-05-14,12,13,11,,1200
""",
            symbol="AAPL.US",
        )

        self.assertEqual(result.status, "needs_review")
        self.assertIsNone(result.quote)

    def test_market_data_request_descriptor_normalizes_safe_cache_identity(self) -> None:
        descriptor = describe_market_data_request(
            provider=" Stooq_CSV ",
            symbol=" aapl.us ",
            endpoint=" Daily ",
            params={"Interval": "1d", "OutputSize": 30},
        )
        cache = build_market_data_cache_metadata(
            descriptor,
            cache_root=Path("data/market-cache"),
        )

        self.assertEqual(descriptor.provider, "stooq_csv")
        self.assertEqual(descriptor.symbol, "AAPL.US")
        self.assertEqual(descriptor.params, (("interval", "1d"), ("outputsize", "30")))
        self.assertEqual(cache.provider, "stooq_csv")
        self.assertEqual(cache.cache_path.parent, Path("data/market-cache/stooq_csv"))
        self.assertTrue(cache.cache_path.name.startswith("aapl.us-daily-"))
        self.assertEqual(cache.cache_path.suffix, ".json")
        self.assertIsNone(cache.retrieved_at)
        self.assertIsNone(cache.observed_on)
        self.assertIsNone(cache.ttl_seconds)
        self.assertIsNone(cache.expires_at)
        self.assertIsNone(cache.source_url_hash)
        self.assertIsNone(cache.terms_checked_at)
        self.assertIsNone(cache.terms_version)

    def test_market_data_cache_metadata_records_freshness_and_terms_without_raw_url(
        self,
    ) -> None:
        descriptor = describe_market_data_request(
            provider="stooq_csv",
            symbol="AAPL.US",
            endpoint="daily",
        )
        cache = build_market_data_cache_metadata(
            descriptor,
            retrieved_at=datetime(2026, 5, 15, 8, 30, tzinfo=timezone.utc),
            observed_on=date(2026, 5, 14),
            ttl_seconds=86_400,
            source_url="https://stooq.example/q/d/l/?s=aapl.us&i=d",
            terms_checked_at=date(2026, 5, 15),
            terms_version="stooq-manual-review-2026-05-15",
        )

        self.assertEqual(cache.retrieved_at.isoformat(), "2026-05-15T08:30:00+00:00")
        self.assertEqual(cache.observed_on.isoformat(), "2026-05-14")
        self.assertEqual(cache.ttl_seconds, 86_400)
        self.assertEqual(cache.expires_at.isoformat(), "2026-05-16T08:30:00+00:00")
        self.assertEqual(cache.source_url_hash, "0d4f4a3a2dc26821")
        self.assertNotIn("source_url", cache.safe_identity)
        self.assertNotIn("stooq.example", repr(cache))
        self.assertEqual(cache.terms_checked_at.isoformat(), "2026-05-15")
        self.assertEqual(cache.terms_version, "stooq-manual-review-2026-05-15")

    def test_market_data_cache_record_round_trips_without_raw_url_or_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            descriptor = describe_market_data_request(
                provider="twelve_data",
                symbol="AAPL",
                endpoint="price",
                params={"symbol": "AAPL"},
            )
            metadata = build_market_data_cache_metadata(
                descriptor,
                cache_root=Path(temp_dir) / "cache",
                retrieved_at=datetime(2026, 5, 17, 1, 2, tzinfo=timezone.utc),
                observed_on=date(2026, 5, 16),
                ttl_seconds=3600,
                source_url="https://api.twelvedata.com/price?symbol=AAPL&apikey=secret",
                terms_checked_at=date(2026, 5, 17),
                terms_version="twelve-data-review-2026-05-17",
            )

            path = write_market_data_cache_record(
                metadata,
                {"price": "190.00"},
                stored_at=datetime(2026, 5, 17, 1, 3, tzinfo=timezone.utc),
            )
            record_text = path.read_text(encoding="utf-8")
            loaded = read_market_data_cache_record(path)

        self.assertEqual(loaded.metadata.provider, "twelve_data")
        self.assertEqual(loaded.metadata.symbol, "AAPL")
        self.assertEqual(loaded.metadata.observed_on, date(2026, 5, 16))
        self.assertEqual(loaded.metadata.ttl_seconds, 3600)
        self.assertEqual(loaded.metadata.terms_version, "twelve-data-review-2026-05-17")
        self.assertEqual(loaded.response_payload, {"price": "190.00"})
        self.assertNotIn("apikey", record_text.lower())
        self.assertNotIn("secret", record_text.lower())
        self.assertNotIn("api.twelvedata.com", record_text)

    def test_market_data_cache_metadata_rejects_negative_ttl(self) -> None:
        descriptor = describe_market_data_request(
            provider="stooq_csv",
            symbol="AAPL.US",
            endpoint="daily",
        )

        with self.assertRaises(ValueError):
            build_market_data_cache_metadata(descriptor, ttl_seconds=-1)

    def test_market_data_budget_state_round_trips_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            budget_root = Path(temp_dir) / "budget"
            state = MarketDataBudgetState(
                provider="fmp",
                budget_date=date(2026, 5, 17),
                daily_call_limit=235,
                charged_call_count=17,
                updated_at=datetime(2026, 5, 17, 1, 2, tzinfo=timezone.utc),
            )

            path = write_market_data_budget_state(state, budget_root=budget_root)
            loaded = load_market_data_budget_state(
                provider="fmp",
                budget_date=date(2026, 5, 17),
                daily_call_limit=235,
                budget_root=budget_root,
            )
            ledger_text = path.read_text(encoding="utf-8")

        self.assertTrue(path.name.endswith("-fmp.json"))
        self.assertEqual(loaded.provider, "fmp")
        self.assertEqual(loaded.charged_call_count, 17)
        self.assertEqual(loaded.daily_call_limit, 235)
        self.assertNotIn("API_KEY", ledger_text)

    def test_missing_market_data_budget_state_defaults_to_zero_usage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            loaded = load_market_data_budget_state(
                provider="twelve_data",
                budget_date=date(2026, 5, 17),
                daily_call_limit=800,
                budget_root=Path(temp_dir),
            )

        self.assertEqual(loaded.charged_call_count, 0)
        self.assertEqual(loaded.daily_call_limit, 800)

    def test_market_data_request_descriptor_rejects_secret_cache_params(self) -> None:
        with self.assertRaises(ValueError):
            describe_market_data_request(
                provider="alpha_vantage",
                symbol="MSFT",
                endpoint="daily",
                params={"apikey": "should-not-enter-cache-identity"},
            )

    def test_market_data_request_descriptor_rejects_unknown_provider(self) -> None:
        with self.assertRaises(ValueError):
            describe_market_data_request(
                provider="../unknown",
                symbol="MSFT",
                endpoint="daily",
            )

    def test_fmp_dry_run_enrichment_planner_builds_secret_free_descriptors(self) -> None:
        plan = plan_fmp_enrichment_requests(
            (" aapl ", "MSFT", "AAPL"),
            endpoints=("batch-quote-short", "profile"),
        )

        self.assertEqual(plan.provider, "fmp")
        self.assertEqual(plan.status, "planned")
        self.assertTrue(plan.dry_run)
        self.assertFalse(plan.network_access)
        self.assertEqual(plan.daily_call_limit, 235)
        self.assertEqual(plan.planned_call_count, 4)
        self.assertEqual(plan.charged_call_count, 4)
        self.assertEqual(plan.cache_hit_count, 0)
        self.assertEqual(plan.denied_call_count, 0)
        self.assertEqual(plan.remaining_daily_call_budget, 231)
        self.assertEqual(plan.ledger.charged_call_count, 4)
        self.assertIn("512MB/month", plan.bandwidth_note)
        self.assertEqual(len(plan.requests), 4)
        self.assertEqual(plan.requests[0].descriptor.provider, "fmp")
        self.assertEqual(plan.requests[0].descriptor.symbol, "AAPL")
        self.assertEqual(plan.requests[0].descriptor.endpoint, "batch-quote-short")
        self.assertEqual(plan.requests[0].descriptor.params, (("symbol", "AAPL"),))
        self.assertEqual(plan.requests[0].budget_action, "charge")
        self.assertTrue(plan.requests[0].consumes_budget)
        self.assertNotIn("FMP_API_KEY", plan.requests[0].cache_key)
        self.assertNotIn("FMP_API_KEY", repr(plan))
        self.assertNotIn("test-key", repr(plan))

    def test_fmp_dry_run_enrichment_planner_enforces_daily_budget(self) -> None:
        symbols = tuple(f"TICKER{i}" for i in range(236))

        plan = plan_fmp_enrichment_requests(symbols, endpoints=("quote",))

        self.assertEqual(plan.status, "over_budget")
        self.assertTrue(plan.dry_run)
        self.assertFalse(plan.network_access)
        self.assertEqual(plan.daily_call_limit, 235)
        self.assertEqual(plan.planned_call_count, 236)
        self.assertEqual(plan.charged_call_count, 235)
        self.assertEqual(plan.denied_call_count, 1)
        self.assertEqual(plan.remaining_daily_call_budget, 0)
        self.assertEqual(plan.requests[-1].budget_action, "denied")
        self.assertFalse(plan.requests[-1].consumes_budget)
        self.assertIn("235 calls", plan.requests[-1].reason)

    def test_fmp_dry_run_enrichment_planner_accounts_for_prior_daily_usage(self) -> None:
        plan = plan_fmp_enrichment_requests(
            ("AAPL", "MSFT"),
            endpoints=("quote",),
            daily_call_limit=2,
            prior_charged_call_count=1,
        )

        self.assertEqual(plan.status, "over_budget")
        self.assertEqual(plan.prior_charged_call_count, 1)
        self.assertEqual(plan.charged_call_count, 1)
        self.assertEqual(plan.denied_call_count, 1)
        self.assertEqual(plan.remaining_daily_call_budget, 0)
        self.assertEqual(plan.requests[0].budget_action, "charge")
        self.assertEqual(plan.requests[1].budget_action, "denied")

    def test_fmp_dry_run_enrichment_planner_does_not_charge_cache_hits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir) / "cache"
            descriptor = describe_market_data_request(
                provider="fmp",
                symbol="AAPL",
                endpoint="profile",
                params={"symbol": "AAPL"},
            )
            cache = build_market_data_cache_metadata(descriptor, cache_root=cache_root)
            cache.cache_path.parent.mkdir(parents=True)
            cache.cache_path.write_text('{"status":"cached"}', encoding="utf-8")

            plan = plan_fmp_enrichment_requests(
                ("AAPL", "MSFT"),
                endpoints=("profile",),
                cache_root=cache_root,
                daily_call_limit=1,
            )

        self.assertEqual(plan.planned_call_count, 2)
        self.assertEqual(plan.cache_hit_count, 1)
        self.assertEqual(plan.charged_call_count, 1)
        self.assertEqual(plan.denied_call_count, 0)
        self.assertEqual(plan.remaining_daily_call_budget, 0)
        self.assertEqual(plan.requests[0].budget_action, "cache_hit")
        self.assertFalse(plan.requests[0].consumes_budget)
        self.assertEqual(plan.requests[1].budget_action, "charge")

    def test_alpha_vantage_dry_run_enrichment_planner_uses_25_call_budget(self) -> None:
        symbols = tuple(f"TICKER{i}" for i in range(26))

        plan = plan_market_data_enrichment_requests(
            "alpha_vantage",
            symbols,
            endpoints=("global-quote",),
        )

        self.assertEqual(plan.provider, "alpha_vantage")
        self.assertEqual(plan.status, "over_budget")
        self.assertEqual(plan.daily_call_limit, 25)
        self.assertEqual(plan.charged_call_count, 25)
        self.assertEqual(plan.denied_call_count, 1)
        self.assertFalse(plan.network_access)

    def test_twelve_data_dry_run_enrichment_planner_uses_800_credit_budget(self) -> None:
        plan = plan_market_data_enrichment_requests(
            "twelve_data",
            ("AAPL", "MSFT"),
            endpoints=("price", "quote"),
        )

        self.assertEqual(plan.provider, "twelve_data")
        self.assertEqual(plan.status, "planned")
        self.assertEqual(plan.daily_call_limit, 800)
        self.assertEqual(plan.planned_call_count, 4)
        self.assertEqual(plan.remaining_daily_call_budget, 796)

    def test_finnhub_dry_run_enrichment_planner_uses_local_default_budget(self) -> None:
        plan = plan_market_data_enrichment_requests(
            "finnhub",
            ("AAPL",),
            endpoints=("quote", "recommendation-trends", "insider-sentiment"),
        )

        self.assertEqual(plan.provider, "finnhub")
        self.assertEqual(plan.status, "planned")
        self.assertEqual(plan.daily_call_limit, 500)
        self.assertEqual(plan.planned_call_count, 3)
        self.assertFalse(plan.network_access)

    def test_market_data_plan_command_uses_env_file_and_redacts_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            env_file.write_text(
                "\n".join(
                    (
                        "FMP_API_KEY=test-secret-key",
                        f"STOCK_ANALYST_MARKET_DATA_CACHE_DIR={root / 'cache'}",
                        f"STOCK_ANALYST_MARKET_DATA_BUDGET_DIR={root / 'budget'}",
                        "STOCK_ANALYST_MARKET_DATA_DAILY_CALL_LIMIT=1",
                    )
                ),
                encoding="utf-8",
            )

            result = run_market_data_plan_command(
                env_file=env_file,
                symbols=("AAPL", "MSFT"),
                endpoints=("profile",),
            )

        self.assertTrue(result["dryRun"])
        self.assertEqual(result["provider"], "fmp")
        self.assertFalse(result["providerEnabled"])
        self.assertTrue(result["credentialConfigured"])
        self.assertFalse(result["networkAccess"])
        self.assertEqual(result["dailyCallLimit"], 1)
        self.assertEqual(result["priorChargedCallCount"], 0)
        self.assertEqual(result["chargedCallCount"], 1)
        self.assertEqual(result["deniedCallCount"], 1)
        self.assertEqual(result["budgetDir"], str(root / "budget"))
        self.assertIn("budgetDate", result)
        self.assertNotIn("test-secret-key", repr(result))

    def test_market_data_plan_command_uses_persisted_daily_budget_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            budget_root = root / "budget"
            write_market_data_budget_state(
                MarketDataBudgetState(
                    provider="fmp",
                    budget_date=datetime.now(timezone.utc).date(),
                    daily_call_limit=2,
                    charged_call_count=1,
                ),
                budget_root=budget_root,
            )
            env_file.write_text(
                "\n".join(
                    (
                        "FMP_API_KEY=test-secret-key",
                        f"STOCK_ANALYST_MARKET_DATA_CACHE_DIR={root / 'cache'}",
                        f"STOCK_ANALYST_MARKET_DATA_BUDGET_DIR={budget_root}",
                        "STOCK_ANALYST_MARKET_DATA_DAILY_CALL_LIMIT=2",
                    )
                ),
                encoding="utf-8",
            )

            result = run_market_data_plan_command(
                env_file=env_file,
                symbols=("AAPL", "MSFT"),
                endpoints=("profile",),
            )

        self.assertEqual(result["priorChargedCallCount"], 1)
        self.assertEqual(result["chargedCallCount"], 1)
        self.assertEqual(result["deniedCallCount"], 1)
        self.assertEqual(result["remainingDailyCallBudget"], 0)

    def test_market_data_plan_command_accepts_symbol_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            symbol_file = root / "symbols.txt"
            env_file.write_text(
                "\n".join(
                    (
                        "FMP_API_KEY=test-secret-key",
                        f"STOCK_ANALYST_MARKET_DATA_CACHE_DIR={root / 'cache'}",
                        "STOCK_ANALYST_MARKET_DATA_DAILY_CALL_LIMIT=5",
                    )
                ),
                encoding="utf-8",
            )
            symbol_file.write_text("AAPL\nMSFT\n", encoding="utf-8")

            result = run_market_data_plan_command(
                env_file=env_file,
                symbol_files=(symbol_file,),
                endpoints=("profile",),
            )

        self.assertEqual(result["plannedCallCount"], 2)
        self.assertEqual(result["chargedCallCount"], 2)
        self.assertEqual(result["requests"][0]["symbol"], "AAPL")
        self.assertEqual(result["requests"][1]["symbol"], "MSFT")

    def test_market_data_plan_command_supports_alpha_vantage_env_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            env_file.write_text(
                "\n".join(
                    (
                        "STOCK_ANALYST_MARKET_DATA_PROVIDER=alpha_vantage",
                        "ALPHAVANTAGE_API_KEY=test-secret-key",
                        f"STOCK_ANALYST_MARKET_DATA_CACHE_DIR={root / 'cache'}",
                    )
                ),
                encoding="utf-8",
            )

            result = run_market_data_plan_command(
                env_file=env_file,
                symbols=("AAPL",),
                endpoints=("overview",),
            )

        self.assertEqual(result["provider"], "alpha_vantage")
        self.assertEqual(result["dailyCallLimit"], 25)
        self.assertTrue(result["credentialConfigured"])
        self.assertNotIn("test-secret-key", repr(result))

    def test_market_data_plan_command_supports_twelve_data_env_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            env_file.write_text(
                "\n".join(
                    (
                        "STOCK_ANALYST_MARKET_DATA_PROVIDER=twelve_data",
                        "TWELVEDATA_API_KEY=test-secret-key",
                        f"STOCK_ANALYST_MARKET_DATA_CACHE_DIR={root / 'cache'}",
                    )
                ),
                encoding="utf-8",
            )

            result = run_market_data_plan_command(
                env_file=env_file,
                symbols=("AAPL",),
                endpoints=("price",),
            )

        self.assertEqual(result["provider"], "twelve_data")
        self.assertEqual(result["dailyCallLimit"], 800)
        self.assertTrue(result["credentialConfigured"])
        self.assertNotIn("test-secret-key", repr(result))


if __name__ == "__main__":
    unittest.main()
