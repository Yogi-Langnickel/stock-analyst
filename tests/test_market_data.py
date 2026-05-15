import unittest
from decimal import Decimal

from stock_analyst.market_data import (
    available_provider_metadata,
    load_market_data_config,
    market_data_disabled,
    parse_stooq_daily_csv,
)


class MarketDataTest(unittest.TestCase):
    def test_provider_metadata_documents_free_options_without_live_network(self) -> None:
        providers = {provider.provider_id: provider for provider in available_provider_metadata()}

        self.assertIn("disabled", providers)
        self.assertIn("stooq_csv", providers)
        self.assertIn("alpha_vantage", providers)
        self.assertIn("twelve_data", providers)
        self.assertIn("sec_companyfacts", providers)
        self.assertFalse(any(provider.network_access for provider in providers.values()))

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
            "missing credential environment variable: ALPHA_VANTAGE_API_KEY",
        )

    def test_key_based_provider_with_credentials_is_still_metadata_only(self) -> None:
        config = load_market_data_config(
            {
                "STOCK_ANALYST_MARKET_DATA_PROVIDER": "twelve_data",
                "TWELVE_DATA_API_KEY": "test-key",
            }
        )

        self.assertEqual(config.provider.provider_id, "twelve_data")
        self.assertFalse(config.enabled)
        self.assertEqual(config.reason, "live provider adapter is not implemented")

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


if __name__ == "__main__":
    unittest.main()
