import csv
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path

from stock_analyst.market_data import (
    MarketDataBudgetState,
    available_provider_metadata,
    build_market_data_cache_metadata,
    build_market_data_symbol_map_template_csv,
    describe_market_data_request,
    plan_bundesbank_sdmx_enrichment_requests,
    plan_gleif_lei_enrichment_requests,
    load_market_data_budget_state,
    load_market_data_planning_config,
    load_market_data_config,
    load_market_data_env_file,
    load_market_data_symbol_map_file,
    load_market_data_symbol_file,
    market_data_candidates_from_workbook_plan,
    market_data_disabled,
    plan_ecb_fx_enrichment_requests,
    plan_fmp_enrichment_requests,
    plan_openfigi_enrichment_requests,
    plan_market_data_enrichment_requests,
    plan_sec_companyfacts_enrichment_requests,
    plan_sec_edgar_form4_enrichment_requests,
    ready_market_data_symbols_from_workbook_candidates,
    read_market_data_cache_record,
    write_market_data_budget_state,
    write_market_data_cache_record,
    parse_stooq_daily_csv,
)
from stock_analyst.cli import run_market_data_plan_command, run_market_symbol_map_template_command
from stock_analyst.google_access import DEFAULT_SHEET_TABS


def headers_for(tab: str) -> tuple[str, ...]:
    for spec in DEFAULT_SHEET_TABS:
        if spec.title == tab:
            return spec.headers
    raise AssertionError(f"unknown tab: {tab}")


def stock_values(
    name: str,
    wkn: str,
    *,
    magazine_price: str = "",
    price_at_recommendation: str = "",
    target: str = "",
    stop: str = "",
    recommendation: str = "",
    issue: str = "2026-W03",
    page: str = "22",
    updated: str = "2026-05-17",
) -> list[str]:
    values_by_header = {
        "Company": name,
        "WKN": wkn,
        "Target": target,
        "Stop": stop,
        "Current price": magazine_price,
        "Recommendation": recommendation,
        "issue": issue,
        "page": page,
        "date updated": updated,
    }
    if price_at_recommendation:
        values_by_header["Comment"] = f"Price at recommendation: {price_at_recommendation}"
    return [values_by_header.get(header, "") for header in headers_for("Stocks")]


class MarketDataTest(unittest.TestCase):
    def test_provider_metadata_documents_free_options_without_live_network(self) -> None:
        providers = {provider.provider_id: provider for provider in available_provider_metadata()}

        self.assertIn("disabled", providers)
        self.assertIn("stooq_csv", providers)
        self.assertIn("alpha_vantage", providers)
        self.assertIn("twelve_data", providers)
        self.assertIn("finnhub", providers)
        self.assertIn("fmp", providers)
        self.assertIn("openfigi", providers)
        self.assertIn("ecb_fx", providers)
        self.assertIn("sec_companyfacts", providers)
        self.assertIn("sec_edgar_form4", providers)
        self.assertIn("gleif_lei", providers)
        self.assertIn("bundesbank_sdmx", providers)
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
        self.assertFalse(providers["openfigi"].credentials_required)
        self.assertEqual(providers["openfigi"].daily_call_budget, 100)
        self.assertFalse(providers["ecb_fx"].credentials_required)
        self.assertEqual(providers["ecb_fx"].daily_call_budget, 100)
        self.assertEqual(providers["sec_edgar_form4"].user_agent_env_var, "SEC_USER_AGENT")
        self.assertEqual(providers["sec_edgar_form4"].daily_call_budget, 100)
        self.assertIn("magazine-backed Stocks rows", providers["sec_edgar_form4"].safety_notes[1])
        self.assertFalse(providers["gleif_lei"].credentials_required)
        self.assertEqual(providers["gleif_lei"].daily_call_budget, 100)
        self.assertIn("issuer identity", providers["gleif_lei"].safety_notes[1])
        self.assertFalse(providers["bundesbank_sdmx"].credentials_required)
        self.assertEqual(providers["bundesbank_sdmx"].daily_call_budget, 100)
        self.assertIn("macro", providers["bundesbank_sdmx"].purpose)

    def test_no_key_provider_plans_have_provider_specific_safe_params(self) -> None:
        openfigi = plan_openfigi_enrichment_requests(("aapl",), endpoints=("mapping", "search"))
        ecb_fx = plan_ecb_fx_enrichment_requests(("usd",), endpoints=("euro-reference-rates",))
        companyfacts = plan_sec_companyfacts_enrichment_requests(("msft",), endpoints=("companyfacts",))
        form4 = plan_sec_edgar_form4_enrichment_requests(("tsla",), endpoints=("form4-xml",))
        gleif = plan_gleif_lei_enrichment_requests(
            ("US0378331005", "Banco Sabadell"),
            endpoints=("isin-lei-mapping", "lei-record-search"),
        )
        bundesbank = plan_bundesbank_sdmx_enrichment_requests(
            ("usd",),
            endpoints=("bbex3-eur-fx-reference",),
        )

        self.assertFalse(openfigi.network_access)
        self.assertEqual(openfigi.provider, "openfigi")
        self.assertEqual(openfigi.requests[0].descriptor.params, (("idtype", "TICKER"), ("idvalue", "AAPL")))
        self.assertEqual(openfigi.requests[1].descriptor.params, (("query", "AAPL"),))
        self.assertEqual(ecb_fx.provider, "ecb_fx")
        self.assertEqual(
            ecb_fx.requests[0].descriptor.params,
            (("basecurrency", "EUR"), ("quotecurrency", "USD")),
        )
        self.assertEqual(companyfacts.provider, "sec_companyfacts")
        self.assertEqual(
            companyfacts.requests[0].descriptor.params,
            (("form", "companyfacts"), ("requirescik", "true"), ("ticker", "MSFT")),
        )
        self.assertEqual(form4.provider, "sec_edgar_form4")
        self.assertEqual(
            form4.requests[0].descriptor.params,
            (("formtype", "4"), ("requirescik", "true"), ("ticker", "TSLA")),
        )
        self.assertEqual(gleif.provider, "gleif_lei")
        self.assertEqual(
            gleif.requests[0].descriptor.params,
            (("isin", "US0378331005"), ("mapping", "isin-lei")),
        )
        self.assertEqual(
            gleif.requests[3].descriptor.params,
            (("query", "BANCO SABADELL"), ("recordtype", "lei-record")),
        )
        self.assertEqual(bundesbank.provider, "bundesbank_sdmx")
        self.assertEqual(
            bundesbank.requests[0].descriptor.params,
            (
                ("basecurrency", "EUR"),
                ("flowref", "BBEX3"),
                ("frequency", "D"),
                ("quotecurrency", "USD"),
            ),
        )

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

    def test_openfigi_provider_remains_metadata_only_without_key(self) -> None:
        config = load_market_data_config({"STOCK_ANALYST_MARKET_DATA_PROVIDER": "openfigi"})

        self.assertEqual(config.provider.provider_id, "openfigi")
        self.assertFalse(config.enabled)
        self.assertFalse(config.provider.credentials_required)
        self.assertFalse(config.provider.network_access)
        self.assertEqual(config.reason, "live provider adapter is not implemented")

    def test_ecb_fx_provider_remains_metadata_only_without_credentials(self) -> None:
        config = load_market_data_config({"STOCK_ANALYST_MARKET_DATA_PROVIDER": "ecb_fx"})

        self.assertEqual(config.provider.provider_id, "ecb_fx")
        self.assertFalse(config.enabled)
        self.assertFalse(config.provider.credentials_required)
        self.assertFalse(config.provider.network_access)
        self.assertEqual(config.reason, "live provider adapter is not implemented")

    def test_new_no_key_public_providers_remain_metadata_only_without_credentials(self) -> None:
        gleif = load_market_data_config({"STOCK_ANALYST_MARKET_DATA_PROVIDER": "gleif_lei"})
        bundesbank = load_market_data_config(
            {"STOCK_ANALYST_MARKET_DATA_PROVIDER": "bundesbank_sdmx"}
        )

        self.assertEqual(gleif.provider.provider_id, "gleif_lei")
        self.assertFalse(gleif.enabled)
        self.assertFalse(gleif.provider.credentials_required)
        self.assertFalse(gleif.provider.network_access)
        self.assertEqual(gleif.reason, "live provider adapter is not implemented")
        self.assertEqual(bundesbank.provider.provider_id, "bundesbank_sdmx")
        self.assertFalse(bundesbank.enabled)
        self.assertFalse(bundesbank.provider.credentials_required)
        self.assertFalse(bundesbank.provider.network_access)
        self.assertEqual(bundesbank.reason, "live provider adapter is not implemented")

    def test_sec_edgar_form4_requires_user_agent_and_remains_metadata_only(self) -> None:
        missing_user_agent = load_market_data_config({"STOCK_ANALYST_MARKET_DATA_PROVIDER": "sec_edgar_form4"})
        configured = load_market_data_config(
            {
                "STOCK_ANALYST_MARKET_DATA_PROVIDER": "sec_edgar_form4",
                "SEC_USER_AGENT": "Stock Analyst private reviewer contact@example.test",
            }
        )

        self.assertEqual(missing_user_agent.provider.provider_id, "sec_edgar_form4")
        self.assertFalse(missing_user_agent.enabled)
        self.assertEqual(missing_user_agent.reason, "missing user-agent environment variable: SEC_USER_AGENT")
        self.assertEqual(configured.provider.provider_id, "sec_edgar_form4")
        self.assertFalse(configured.enabled)
        self.assertFalse(configured.provider.network_access)
        self.assertEqual(configured.reason, "live provider adapter is not implemented")

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

    def test_market_data_symbol_map_file_loads_private_workbook_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            symbol_map_file = Path(temp_dir) / "market-symbol-map.csv"
            symbol_map_file.write_text(
                "\n".join(
                    (
                        "source_id,wkn,name,symbol",
                        "stock:2026-W03:p22:A0MRD4:abc,A0MRD4,Banco Sabadell,SAB.MC",
                    )
                ),
                encoding="utf-8",
            )

            symbol_map = load_market_data_symbol_map_file(symbol_map_file)

        self.assertEqual(symbol_map["source_id:stock:2026-W03:p22:A0MRD4:abc"], "SAB.MC")
        self.assertEqual(symbol_map["wkn:A0MRD4"], "SAB.MC")
        self.assertEqual(symbol_map["name:banco sabadell"], "SAB.MC")

    def test_market_data_symbol_map_file_ignores_unmapped_template_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            symbol_map_file = Path(temp_dir) / "market-symbol-map.csv"
            symbol_map_file.write_text(
                "\n".join(
                    (
                        "source_id,wkn,name,symbol,status",
                        "stock:2026-W03:p22:A0MRD4:abc,A0MRD4,Banco Sabadell,,needs_symbol_lookup",
                        "stock:2026-W03:p42:A1CX3T:def,A1CX3T,Tesla,TSLA,mapped",
                    )
                ),
                encoding="utf-8",
            )

            symbol_map = load_market_data_symbol_map_file(symbol_map_file)

        self.assertNotIn("wkn:A0MRD4", symbol_map)
        self.assertEqual(symbol_map["wkn:A1CX3T"], "TSLA")

    def test_build_market_data_symbol_map_template_preserves_existing_symbols(self) -> None:
        payload = {
            "rows": [
                {
                    "tab": "Stocks",
                    "rowKind": "stock_recommendation",
                    "sourceId": "stock:2026-W03:p22:A0MRD4:abc",
                    "issueId": "2026-W03",
                    "page": 22,
                    "values": stock_values(
                        "Banco Sabadell",
                        "A0MRD4",
                        magazine_price="3,33 EUR",
                        price_at_recommendation="3,33 EUR",
                        target="4,30 EUR",
                        stop="2,70 EUR",
                        recommendation="new_recommendation",
                    ),
                },
                {
                    "tab": "Dividend Focus",
                    "rowKind": "dividend_strategy",
                    "sourceId": "dividend:2026-W03:p18:A0MRD4:def",
                    "issueId": "2026-W03",
                    "page": 18,
                    "values": [
                        "2026-W03",
                        "18",
                        "Banco Sabadell",
                        "A0MRD4",
                        "",
                        "18,6 %",
                        "Maerz",
                        "",
                        "needs_review",
                        "2026-05-17",
                    ],
                },
                {
                    "tab": "Stocks",
                    "rowKind": "stock_recommendation",
                    "sourceId": "stock:2026-W03:p42:A1CX3T:ghi",
                    "issueId": "2026-W03",
                    "page": 42,
                    "values": stock_values(
                        "Tesla",
                        "A1CX3T",
                        magazine_price="381,15 EUR",
                        target="480,00 EUR",
                        stop="295,00 EUR",
                        recommendation="follow_up",
                        page="42",
                    ),
                },
            ]
        }
        existing = "\n".join(
            (
                "source_id,wkn,name,symbol,status",
                ",A0MRD4,Banco Sabadell,SAB.MC,mapped",
            )
        )

        csv_text = build_market_data_symbol_map_template_csv(
            payload,
            existing_csv_text=existing,
        )
        rows = list(csv.DictReader(StringIO(csv_text)))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["wkn"], "A0MRD4")
        self.assertEqual(rows[0]["symbol"], "SAB.MC")
        self.assertEqual(rows[0]["status"], "mapped")
        self.assertEqual(rows[1]["wkn"], "A1CX3T")
        self.assertEqual(rows[1]["symbol"], "")
        self.assertEqual(rows[1]["status"], "needs_symbol_lookup")

    def test_workbook_plan_candidates_require_symbol_mapping(self) -> None:
        payload = {
            "rows": [
                {
                    "tab": "Stocks",
                    "rowKind": "stock_recommendation",
                    "sourceId": "stock:2026-W03:p22:A0MRD4:abc",
                    "values": stock_values(
                        "Banco Sabadell",
                        "A0MRD4",
                        magazine_price="3,33 EUR",
                        target="4,30 EUR",
                        stop="2,70 EUR",
                        recommendation="new_recommendation",
                    ),
                },
                {
                    "tab": "Extraction Audit",
                    "rowKind": "section_inventory",
                    "sourceId": "section:2026-W03:p62:abc",
                    "values": [],
                },
            ]
        }

        candidates = market_data_candidates_from_workbook_plan(payload)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].tab, "Stocks")
        self.assertEqual(candidates[0].name, "Banco Sabadell")
        self.assertEqual(candidates[0].wkn, "A0MRD4")
        self.assertEqual(candidates[0].status, "needs_symbol_mapping")
        self.assertIsNone(candidates[0].symbol)
        self.assertEqual(ready_market_data_symbols_from_workbook_candidates(candidates), ())

    def test_workbook_plan_candidates_reject_old_short_stock_rows(self) -> None:
        payload = {
            "rows": [
                {
                    "tab": "Stocks",
                    "rowKind": "stock_recommendation",
                    "sourceId": "stock:2026-W03:p22:A0MRD4:abc",
                    "values": [
                        "Banco Sabadell",
                        "A0MRD4",
                        "",
                        "3,33 EUR",
                        "",
                        "4,30 EUR",
                        "2,70 EUR",
                        "new_recommendation",
                        "2026-W03",
                        "22",
                        "2026-05-17",
                    ],
                },
            ]
        }

        with self.assertRaisesRegex(ValueError, "Stocks.*20 values.*got 11"):
            market_data_candidates_from_workbook_plan(payload)

    def test_workbook_plan_candidates_only_plan_mapped_stock_rows(self) -> None:
        payload = {
            "rows": [
                {
                    "tab": "Stocks",
                    "rowKind": "stock_recommendation",
                    "sourceId": "stock:2026-W03:p22:A0MRD4:abc",
                    "values": stock_values(
                        "Banco Sabadell",
                        "A0MRD4",
                        magazine_price="3,33 EUR",
                        target="4,30 EUR",
                        stop="2,70 EUR",
                        recommendation="new_recommendation",
                    ),
                },
                {
                    "tab": "Dividend Focus",
                    "rowKind": "dividend_strategy",
                    "sourceId": "dividend:2026-W03:p18:A0MRD4:def",
                    "values": [
                        "Banco Sabadell",
                        "A0MRD4",
                        "April",
                        "3,33 EUR",
                        "4,78",
                        "7,7 %",
                        "9,1",
                        "2",
                        "14.04.26",
                        "17.04.26",
                        "4,30 EUR",
                        "2,70 EUR",
                        "needs_review",
                        "2026-W03",
                        "18",
                        "2026-05-17",
                    ],
                },
                {
                    "tab": "Derivative Tips",
                    "rowKind": "derivative_overview",
                    "sourceId": "derivative-overview:2026-W03:p62:AA00AA:ghi",
                    "values": [
                        "Bayer",
                        "Bayer Discount-Call",
                        "Discount-Call",
                        "AA00AA",
                        "Example Issuer",
                        "1,0",
                        "",
                        "25,00 EUR",
                        "2,1",
                        "12/26",
                        "1,90 EUR",
                        "2,10 EUR",
                        "+10,5 %",
                        "3,00 EUR",
                        "1,40 EUR",
                        "watch",
                        "needs_review",
                        "2026-W03",
                        "62",
                        "2026-05-17",
                    ],
                },
            ]
        }

        candidates = market_data_candidates_from_workbook_plan(
            payload,
            symbol_map={
                "wkn:A0MRD4": "SAB.MC",
                "wkn:AA00AA": "SHOULD.NOT.PLAN",
            },
        )

        self.assertEqual(
            ready_market_data_symbols_from_workbook_candidates(candidates),
            ("SAB.MC",),
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].status, "ready")

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

    def test_market_data_cache_record_rejects_secret_response_payload_keys(self) -> None:
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
            )

            with self.assertRaisesRegex(ValueError, "must not contain secrets"):
                write_market_data_cache_record(
                    metadata,
                    {"quote": {"apiKey": "secret", "price": "190.00"}},
                    stored_at=datetime(2026, 5, 17, 1, 3, tzinfo=timezone.utc),
                )

            self.assertFalse(metadata.cache_path.exists())

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

    def test_sec_edgar_form4_dry_run_planner_uses_official_source_endpoints(self) -> None:
        plan = plan_sec_edgar_form4_enrichment_requests(("AAPL", "MSFT"))

        self.assertEqual(plan.provider, "sec_edgar_form4")
        self.assertEqual(plan.status, "planned")
        self.assertTrue(plan.dry_run)
        self.assertFalse(plan.network_access)
        self.assertEqual(plan.daily_call_limit, 100)
        self.assertEqual(plan.planned_call_count, 6)
        self.assertEqual(plan.remaining_daily_call_budget, 94)
        self.assertEqual(
            tuple(request.descriptor.endpoint for request in plan.requests[:3]),
            ("ticker-cik-map", "submissions", "form4-xml"),
        )
        self.assertTrue(all(request.descriptor.provider == "sec_edgar_form4" for request in plan.requests))

    def test_sec_edgar_form4_dry_run_planner_accounts_for_prior_daily_usage(self) -> None:
        plan = plan_sec_edgar_form4_enrichment_requests(
            ("AAPL", "MSFT"),
            endpoints=("submissions",),
            daily_call_limit=2,
            prior_charged_call_count=1,
        )

        self.assertEqual(plan.provider, "sec_edgar_form4")
        self.assertEqual(plan.status, "over_budget")
        self.assertFalse(plan.network_access)
        self.assertEqual(plan.prior_charged_call_count, 1)
        self.assertEqual(plan.charged_call_count, 1)
        self.assertEqual(plan.denied_call_count, 1)
        self.assertEqual(plan.remaining_daily_call_budget, 0)
        self.assertEqual(plan.requests[0].budget_action, "charge")
        self.assertEqual(plan.requests[1].budget_action, "denied")

    def test_market_data_plan_command_uses_env_file_and_redacts_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            env_file.write_text(
                "\n".join(
                    (
                        "FMP_API_KEY=test-secret-key",
                        "STOCK_ANALYST_MARKET_DATA_PROVIDER=fmp",
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

    def test_market_data_plan_command_defaults_to_disabled_even_with_manual_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            env_file.write_text(
                "\n".join(
                    (
                        "FMP_API_KEY=test-secret-key",
                        f"STOCK_ANALYST_MARKET_DATA_CACHE_DIR={root / 'cache'}",
                    )
                ),
                encoding="utf-8",
            )

            result = run_market_data_plan_command(
                env_file=env_file,
                symbols=("AAPL",),
                endpoints=("profile",),
            )

        self.assertEqual(result["provider"], "disabled")
        self.assertFalse(result["providerEnabled"])
        self.assertFalse(result["credentialConfigured"])
        self.assertFalse(result["networkAccess"])
        self.assertEqual(result["status"], "disabled")
        self.assertEqual(result["plannedCallCount"], 0)
        self.assertEqual(result["chargedCallCount"], 0)
        self.assertEqual(result["requests"], [])
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
                        "STOCK_ANALYST_MARKET_DATA_PROVIDER=fmp",
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
                        "STOCK_ANALYST_MARKET_DATA_PROVIDER=fmp",
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

    def test_market_data_plan_command_accepts_workbook_plan_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env"
            workbook_plan = root / "workbook-plan.json"
            symbol_map = root / "market-symbol-map.csv"
            env_file.write_text(
                "\n".join(
                    (
                        "FMP_API_KEY=test-secret-key",
                        "STOCK_ANALYST_MARKET_DATA_PROVIDER=fmp",
                        f"STOCK_ANALYST_MARKET_DATA_CACHE_DIR={root / 'cache'}",
                        "STOCK_ANALYST_MARKET_DATA_DAILY_CALL_LIMIT=5",
                    )
                ),
                encoding="utf-8",
            )
            workbook_plan.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "tab": "Stocks",
                                "rowKind": "stock_recommendation",
                                "sourceId": "stock:2026-W03:p22:A0MRD4:abc",
                                "values": stock_values(
                                    "Banco Sabadell",
                                    "A0MRD4",
                                    magazine_price="3,33 EUR",
                                    target="4,30 EUR",
                                    stop="2,70 EUR",
                                    recommendation="new_recommendation",
                                ),
                            },
                            {
                                "tab": "ETF",
                                "rowKind": "etf_recommendation",
                                "sourceId": "etf:2026-W03:p12:ETF123:def",
                                "values": [
                                    "Example ETF",
                                    "ETF123",
                                    "",
                                    "10 EUR",
                                    "",
                                    "watch",
                                    "2026-W03",
                                    "12",
                                    "needs_review",
                                    "2026-05-17",
                                ],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            symbol_map.write_text(
                "\n".join(
                    (
                        "source_id,wkn,name,symbol",
                        ",A0MRD4,,SAB.MC",
                    )
                ),
                encoding="utf-8",
            )

            result = run_market_data_plan_command(
                env_file=env_file,
                workbook_plan_file=workbook_plan,
                symbol_map_file=symbol_map,
                endpoints=("profile",),
            )

        self.assertEqual(result["sourceMode"], "workbook_plan")
        self.assertTrue(result["sheetRowsRequiredBeforeLiveCalls"])
        self.assertEqual(result["candidateCount"], 1)
        self.assertEqual(result["readyCandidateCount"], 1)
        self.assertEqual(result["blockedCandidateCount"], 0)
        self.assertEqual(result["plannedCallCount"], 1)
        self.assertEqual(result["requests"][0]["symbol"], "SAB.MC")

    def test_market_symbol_map_template_command_writes_private_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workbook_plan = root / "workbook-plan.json"
            output = root / "market-symbol-map.csv"
            workbook_plan.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "tab": "Stocks",
                                "rowKind": "stock_recommendation",
                                "sourceId": "stock:2026-W03:p22:A0MRD4:abc",
                                "issueId": "2026-W03",
                                "page": 22,
                                "values": stock_values(
                                    "Banco Sabadell",
                                    "A0MRD4",
                                    magazine_price="3,33 EUR",
                                    target="4,30 EUR",
                                    stop="2,70 EUR",
                                    recommendation="new_recommendation",
                                ),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = run_market_symbol_map_template_command(
                workbook_plan_file=workbook_plan,
                output=output,
            )
            rows = list(csv.DictReader(StringIO(output.read_text(encoding="utf-8"))))

        self.assertEqual(result["rowCount"], 1)
        self.assertEqual(result["needsLookupCount"], 1)
        self.assertFalse(result["externalServicesEnabled"])
        self.assertFalse(result["networkAccess"])
        self.assertEqual(rows[0]["wkn"], "A0MRD4")
        self.assertEqual(rows[0]["symbol"], "")

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
