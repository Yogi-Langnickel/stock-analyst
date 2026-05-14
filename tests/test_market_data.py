import unittest
from decimal import Decimal

from stock_analyst.market_data import market_data_disabled, parse_stooq_daily_csv


class MarketDataTest(unittest.TestCase):
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
