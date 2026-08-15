import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from stock_analyst.sec_insider import (
    SEC_SUBMISSIONS_ARCHIVE_URL,
    SEC_SUBMISSIONS_URL,
    SEC_TICKER_MAP_URL,
    SecInsiderConfig,
    SecInsiderError,
    SecResolvedIssuer,
    SecStockCandidate,
    enrich_sec_form4,
    load_sec_insider_config,
    parse_form4_transactions,
    parse_sec_ticker_records,
    recent_form4_filings,
    resolve_sec_issuers,
)


FORM4_XML = b"""<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerName>Example Corp</issuerName><issuerTradingSymbol>EXM</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>1</isOfficer><officerTitle>CEO</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-07-30</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>10</value></transactionShares>
        <transactionPricePerShare><value>12.50</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>110</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-07-31</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>5</value></transactionShares>
        <transactionPricePerShare><value>15</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>105</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""

AMENDED_FORM4_XML = FORM4_XML.replace(
    b"<ownershipDocument>",
    b"<ownershipDocument><periodOfReport>2026-07-31</periodOfReport>"
    b"<dateOfOriginalSubmission>2026-08-01</dateOfOriginalSubmission>",
).replace(b"<value>10</value>", b"<value>12</value>", 1)


class SecInsiderTests(unittest.TestCase):
    def test_ticker_payload_without_usable_record_is_not_cached_and_recovers(self) -> None:
        invalid_ticker_payload = json.dumps({"error": {}}).encode()
        valid_ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        valid_submissions = self._submissions_payload(
            forms=[], accessions=[], documents=[], filing_dates=[]
        )
        ticker_attempts = 0

        def fetch(url: str, _user_agent: str) -> bytes:
            nonlocal ticker_attempts
            if url == SEC_TICKER_MAP_URL:
                ticker_attempts += 1
                return invalid_ticker_payload if ticker_attempts == 1 else valid_ticker_payload
            return valid_submissions

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            config = SecInsiderConfig("Stock Analyst owner@example.com", cache_dir)
            candidate = SecStockCandidate("Example", "A0TEST", "EXM", "2026-W34:10")
            with self.assertRaisesRegex(SecInsiderError, "ticker response"):
                enrich_sec_form4(
                    (candidate,), config, fetch_bytes=fetch,
                    now=datetime(2026, 8, 3, tzinfo=timezone.utc),
                )
            self.assertFalse((cache_dir / "company-tickers.json").exists())

            recovered = enrich_sec_form4(
                (candidate,), config, fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )

        self.assertEqual(ticker_attempts, 2)
        self.assertEqual(recovered.resolved_issuer_count, 1)
        self.assertFalse(recovered.archive_coverage_partial)

    def test_semantically_invalid_cached_ticker_is_quarantined_and_refetched(self) -> None:
        valid_ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        valid_submissions = self._submissions_payload(
            forms=[], accessions=[], documents=[], filing_dates=[]
        )

        def fetch(url: str, _user_agent: str) -> bytes:
            return valid_ticker_payload if url == SEC_TICKER_MAP_URL else valid_submissions

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            ticker_cache = cache_dir / "company-tickers.json"
            ticker_cache.write_bytes(json.dumps({"error": {}}).encode())
            result = enrich_sec_form4(
                (SecStockCandidate("Example", "A0TEST", "EXM", "2026-W34:10"),),
                SecInsiderConfig("Stock Analyst owner@example.com", cache_dir),
                fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )

            self.assertTrue(ticker_cache.with_suffix(".json.corrupt").exists())
            self.assertEqual(ticker_cache.read_bytes(), valid_ticker_payload)

        self.assertEqual(result.resolved_issuer_count, 1)

    def test_invalid_fetched_submissions_json_is_not_promoted_and_recovers(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        valid_submissions = self._submissions_payload(
            forms=[], accessions=[], documents=[], filing_dates=[]
        )
        submission_attempts = 0

        def fetch(url: str, _user_agent: str) -> bytes:
            nonlocal submission_attempts
            if url == SEC_TICKER_MAP_URL:
                return ticker_payload
            submission_attempts += 1
            return b'{"error": "rate limited"}' if submission_attempts == 1 else valid_submissions

        with tempfile.TemporaryDirectory() as temp_dir:
            config = SecInsiderConfig("Stock Analyst owner@example.com", Path(temp_dir))
            candidate = SecStockCandidate("Example", "A0TEST", None, "2026-W34:10")
            first = enrich_sec_form4(
                (candidate,),
                config,
                fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )
            second = enrich_sec_form4(
                (candidate,),
                config,
                fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )

        self.assertEqual(first.failed_issuer_count, 1)
        self.assertEqual(second.failed_issuer_count, 0)
        self.assertEqual(submission_attempts, 2)

    def test_invalid_fetched_filing_is_not_promoted_and_next_run_recovers(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        submissions_payload = self._submissions_payload(
            forms=["4"],
            accessions=["0000001234-26-000001"],
            documents=["form4.xml"],
            filing_dates=["2026-08-01"],
        )
        filing_attempts = 0

        def fetch(url: str, _user_agent: str) -> bytes:
            nonlocal filing_attempts
            if url == SEC_TICKER_MAP_URL:
                return ticker_payload
            if url == SEC_SUBMISSIONS_URL.format(cik="0000001234"):
                return submissions_payload
            filing_attempts += 1
            return b"not xml" if filing_attempts == 1 else FORM4_XML

        with tempfile.TemporaryDirectory() as temp_dir:
            config = SecInsiderConfig("Stock Analyst owner@example.com", Path(temp_dir))
            candidate = SecStockCandidate("Example", "A0TEST", None, "2026-W34:10")
            first = enrich_sec_form4(
                (candidate,), config, fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )
            second = enrich_sec_form4(
                (candidate,), config, fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )
            filing_cache = Path(temp_dir) / "filings" / "1234" / "000000123426000001-raw.xml"
            self.assertEqual(filing_cache.read_bytes(), FORM4_XML)

        self.assertEqual(first.failed_filing_count, 1)
        self.assertEqual(second.failed_filing_count, 0)
        self.assertEqual(len(second.transactions), 2)
        self.assertEqual(filing_attempts, 2)

    def test_corrupt_cached_filing_is_quarantined_and_refetched(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        submissions_payload = self._submissions_payload(
            forms=["4"], accessions=["0000001234-26-000001"],
            documents=["form4.xml"], filing_dates=["2026-08-01"],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            filing_cache = cache_dir / "filings" / "1234" / "000000123426000001-raw.xml"
            filing_cache.parent.mkdir(parents=True)
            filing_cache.write_bytes(b"cached garbage")
            calls = []

            def fetch(url: str, _user_agent: str) -> bytes:
                calls.append(url)
                if url == SEC_TICKER_MAP_URL:
                    return ticker_payload
                if url == SEC_SUBMISSIONS_URL.format(cik="0000001234"):
                    return submissions_payload
                return FORM4_XML

            result = enrich_sec_form4(
                (SecStockCandidate("Example", "A0TEST", None, "2026-W34:10"),),
                SecInsiderConfig("Stock Analyst owner@example.com", cache_dir),
                fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )

            self.assertTrue((filing_cache.with_suffix(".xml.corrupt")).exists())
            self.assertEqual(filing_cache.read_bytes(), FORM4_XML)

        self.assertEqual(result.failed_filing_count, 0)
        self.assertEqual(len(result.transactions), 2)
        self.assertEqual(result.network_request_count, 3)

    def test_mismatched_cached_recent_arrays_are_quarantined_and_refetched(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        malformed = json.dumps(
            {
                "filings": {
                    "recent": {
                        "form": ["4", "4"],
                        "accessionNumber": ["one"],
                        "primaryDocument": ["one.xml", "two.xml"],
                        "filingDate": ["2026-08-01", "2026-08-02"],
                    },
                    "files": [],
                }
            }
        ).encode()
        valid = self._submissions_payload(
            forms=[], accessions=[], documents=[], filing_dates=[]
        )

        def fetch(url: str, _user_agent: str) -> bytes:
            return ticker_payload if url == SEC_TICKER_MAP_URL else valid

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            submission_cache = cache_dir / "submissions" / "CIK0000001234.json"
            submission_cache.parent.mkdir(parents=True)
            submission_cache.write_bytes(malformed)
            result = enrich_sec_form4(
                (SecStockCandidate("Example", "A0TEST", None, "2026-W34:10"),),
                SecInsiderConfig("Stock Analyst owner@example.com", cache_dir),
                fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )

            self.assertTrue(submission_cache.with_suffix(".json.corrupt").exists())
            self.assertEqual(submission_cache.read_bytes(), valid)

        self.assertEqual(result.failed_issuer_count, 0)
        self.assertFalse(result.archive_coverage_partial)

    def test_mismatched_cached_archive_arrays_are_quarantined_and_refetched(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        archive_name = "CIK0000001234-submissions-001.json"
        submissions_payload = json.dumps(
            {
                "filings": {
                    "recent": {
                        "form": [], "accessionNumber": [],
                        "primaryDocument": [], "filingDate": [],
                    },
                    "files": [{"name": archive_name, "filingTo": "2026-08-01"}],
                }
            }
        ).encode()
        malformed = json.dumps(
            {
                "form": ["4", "4"],
                "accessionNumber": ["one"],
                "primaryDocument": ["one.xml", "two.xml"],
                "filingDate": ["2026-08-01", "2026-08-02"],
            }
        ).encode()
        valid = self._submissions_payload(
            forms=[], accessions=[], documents=[], filing_dates=[],
            recent_wrapper=False,
        )

        def fetch(url: str, _user_agent: str) -> bytes:
            if url == SEC_TICKER_MAP_URL:
                return ticker_payload
            if url == SEC_SUBMISSIONS_URL.format(cik="0000001234"):
                return submissions_payload
            return valid

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            archive_cache = cache_dir / "submissions" / "archives" / archive_name
            archive_cache.parent.mkdir(parents=True)
            archive_cache.write_bytes(malformed)
            result = enrich_sec_form4(
                (SecStockCandidate("Example", "A0TEST", None, "2026-W34:10"),),
                SecInsiderConfig("Stock Analyst owner@example.com", cache_dir),
                fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )

            self.assertTrue(archive_cache.with_suffix(".json.corrupt").exists())
            self.assertEqual(archive_cache.read_bytes(), valid)

        self.assertEqual(result.failed_issuer_count, 0)
        self.assertEqual(result.archive_file_count, 1)
        self.assertFalse(result.archive_coverage_partial)

    def test_form4_amendment_supersedes_original_in_active_projection(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        submissions_payload = self._submissions_payload(
            forms=["4/A", "4"],
            accessions=["0000001234-26-000002", "0000001234-26-000001"],
            documents=["amended.xml", "original.xml"],
            filing_dates=["2026-08-02", "2026-08-01"],
        )

        def fetch(url: str, _user_agent: str) -> bytes:
            if url == SEC_TICKER_MAP_URL:
                return ticker_payload
            if url == SEC_SUBMISSIONS_URL.format(cik="0000001234"):
                return submissions_payload
            return (
                AMENDED_FORM4_XML
                if url.endswith("amended.xml")
                else FORM4_XML.replace(
                    b"<ownershipDocument>",
                    b"<ownershipDocument><periodOfReport>2026-07-31</periodOfReport>",
                )
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            result = enrich_sec_form4(
                (SecStockCandidate("Example", "A0TEST", None, "2026-W34:10"),),
                SecInsiderConfig("Stock Analyst owner@example.com", Path(temp_dir)),
                fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )

        self.assertEqual(len(result.transactions), 2)
        self.assertEqual(len(result.transaction_revisions), 4)
        self.assertTrue(
            all(
                row.correction_status == "effective_correction"
                for row in result.transactions
            )
        )
        self.assertTrue(
            all(
                "Form 4/A correction" in row.to_sheet_row()[4]
                for row in result.transactions
            )
        )
        self.assertTrue(all(len(row.to_sheet_row()) == 12 for row in result.transactions))
        self.assertEqual({row.to_sheet_row()[7] for row in result.transactions}, {"purchase", "sale"})
        self.assertEqual(
            {row.correction_status for row in result.transaction_revisions},
            {"superseded", "effective_correction"},
        )

    def test_amendment_matches_unique_original_by_period(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        submissions_payload = self._submissions_payload(
            forms=["4/A", "4", "4"],
            accessions=[
                "0000001234-26-000003",
                "0000001234-26-000002",
                "0000001234-26-000001",
            ],
            documents=["amended.xml", "other-period.xml", "matching-period.xml"],
            filing_dates=["2026-08-02", "2026-08-01", "2026-08-01"],
        )

        def fetch(url: str, _user_agent: str) -> bytes:
            if url == SEC_TICKER_MAP_URL:
                return ticker_payload
            if url == SEC_SUBMISSIONS_URL.format(cik="0000001234"):
                return submissions_payload
            if url.endswith("amended.xml"):
                return AMENDED_FORM4_XML
            period = b"2026-07-30" if url.endswith("other-period.xml") else b"2026-07-31"
            return FORM4_XML.replace(
                b"<ownershipDocument>",
                b"<ownershipDocument><periodOfReport>" + period + b"</periodOfReport>",
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            result = enrich_sec_form4(
                (SecStockCandidate("Example", "A0TEST", None, "2026-W34:10"),),
                SecInsiderConfig("Stock Analyst owner@example.com", Path(temp_dir)),
                fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )

        self.assertEqual(len(result.transactions), 4)
        self.assertEqual(
            [row.correction_status for row in result.transaction_revisions].count("superseded"),
            2,
        )
        self.assertEqual(
            {row.correction_status for row in result.transactions},
            {"original", "effective_correction"},
        )

    def test_amendment_retains_ambiguous_same_period_originals(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        submissions_payload = self._submissions_payload(
            forms=["4/A", "4", "4"],
            accessions=[
                "0000001234-26-000003",
                "0000001234-26-000002",
                "0000001234-26-000001",
            ],
            documents=["amended.xml", "original-b.xml", "original-a.xml"],
            filing_dates=["2026-08-02", "2026-08-01", "2026-08-01"],
        )

        def fetch(url: str, _user_agent: str) -> bytes:
            if url == SEC_TICKER_MAP_URL:
                return ticker_payload
            if url == SEC_SUBMISSIONS_URL.format(cik="0000001234"):
                return submissions_payload
            if url.endswith("amended.xml"):
                return AMENDED_FORM4_XML
            return FORM4_XML.replace(
                b"<ownershipDocument>",
                b"<ownershipDocument><periodOfReport>2026-07-31</periodOfReport>",
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            result = enrich_sec_form4(
                (SecStockCandidate("Example", "A0TEST", None, "2026-W34:10"),),
                SecInsiderConfig("Stock Analyst owner@example.com", Path(temp_dir)),
                fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )

        self.assertEqual(len(result.transactions), 6)
        self.assertNotIn("superseded", {
            row.correction_status for row in result.transaction_revisions
        })
        ambiguous = [
            row for row in result.transactions
            if row.correction_status == "ambiguous_correction"
        ]
        self.assertEqual(len(ambiguous), 2)
        self.assertTrue(
            all("original ambiguous" in row.to_sheet_row()[4] for row in ambiguous)
        )
        self.assertTrue(all(len(row.to_sheet_row()) == 12 for row in result.transactions))

    def test_fetches_archive_file_with_in_window_form4_and_replays_from_cache(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        archive_name = "CIK0000001234-submissions-001.json"
        submissions_payload = json.dumps(
            {
                "filings": {
                    "recent": {
                        "form": [],
                        "accessionNumber": [],
                        "primaryDocument": [],
                        "filingDate": [],
                    },
                    "files": [
                        {
                            "name": archive_name,
                            "filingFrom": "2026-01-01",
                            "filingTo": "2026-08-01",
                        }
                    ],
                }
            }
        ).encode()
        archive_payload = self._submissions_payload(
            forms=["4"], accessions=["0000001234-26-000001"],
            documents=["form4.xml"], filing_dates=["2026-08-01"],
            recent_wrapper=False,
        )
        calls = []

        def fetch(url: str, _user_agent: str) -> bytes:
            calls.append(url)
            if url == SEC_TICKER_MAP_URL:
                return ticker_payload
            if url == SEC_SUBMISSIONS_URL.format(cik="0000001234"):
                return submissions_payload
            if url == SEC_SUBMISSIONS_ARCHIVE_URL.format(name=archive_name):
                return archive_payload
            return FORM4_XML

        with tempfile.TemporaryDirectory() as temp_dir:
            config = SecInsiderConfig("Stock Analyst owner@example.com", Path(temp_dir))
            candidate = SecStockCandidate("Example", "A0TEST", None, "2026-W34:10")
            first = enrich_sec_form4(
                (candidate,), config, fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )
            second = enrich_sec_form4(
                (candidate,), config, fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )

        self.assertEqual(len(first.transactions), 2)
        self.assertEqual(first.archive_file_count, 1)
        self.assertFalse(first.archive_coverage_partial)
        self.assertEqual(first.network_request_count, 4)
        self.assertEqual(second.network_request_count, 0)
        self.assertEqual(second.cache_hit_count, 4)
        self.assertEqual(len(calls), 4)

    def test_archive_required_beyond_budget_marks_coverage_partial(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        archive_name = "CIK0000001234-submissions-001.json"
        submissions_payload = json.dumps(
            {
                "filings": {
                    "recent": {
                        "form": [],
                        "accessionNumber": [],
                        "primaryDocument": [],
                        "filingDate": [],
                    },
                    "files": [
                        {
                            "name": archive_name,
                            "filingFrom": "2026-01-01",
                            "filingTo": "2026-08-01",
                        }
                    ],
                }
            }
        ).encode()

        def fetch(url: str, _user_agent: str) -> bytes:
            if url == SEC_TICKER_MAP_URL:
                return ticker_payload
            if url == SEC_SUBMISSIONS_URL.format(cik="0000001234"):
                return submissions_payload
            self.fail("archive fetch should be blocked by the request budget")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = enrich_sec_form4(
                (SecStockCandidate("Example", "A0TEST", None, "2026-W34:10"),),
                SecInsiderConfig(
                    "Stock Analyst owner@example.com",
                    Path(temp_dir),
                    max_requests=2,
                ),
                fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )

        self.assertTrue(result.request_budget_exhausted)
        self.assertTrue(result.archive_coverage_partial)
        self.assertEqual(result.archive_file_count, 0)
        self.assertEqual(result.failed_issuer_count, 1)
        self.assertEqual(result.network_request_count, 2)
        self.assertEqual(result.transactions, ())

    def test_recent_mismatched_arrays_are_partial_and_not_cached(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        malformed = json.dumps(
            {
                "filings": {
                    "recent": {
                        "form": ["4", "4"],
                        "accessionNumber": ["0000001234-26-000001"],
                        "primaryDocument": ["one.xml", "two.xml"],
                        "filingDate": ["2026-08-01", "2026-08-02"],
                    },
                    "files": [],
                }
            }
        ).encode()

        def fetch(url: str, _user_agent: str) -> bytes:
            return ticker_payload if url == SEC_TICKER_MAP_URL else malformed

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            result = enrich_sec_form4(
                (SecStockCandidate("Example", "A0TEST", None, "2026-W34:10"),),
                SecInsiderConfig("Stock Analyst owner@example.com", cache_dir),
                fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )
            self.assertFalse((cache_dir / "submissions" / "CIK0000001234.json").exists())

        self.assertEqual(result.failed_issuer_count, 1)
        self.assertTrue(result.archive_coverage_partial)
        self.assertFalse(result.request_budget_exhausted)

    def test_semantically_invalid_recent_rows_are_partial_and_not_cached(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        invalid_rows = {
            "form": ("", "0000001234-26-000001", "one.xml", "2026-08-01"),
            "accession": ("4", "../../unsafe", "one.xml", "2026-08-01"),
            "document": ("4", "0000001234-26-000001", "../unsafe.xml", "2026-08-01"),
            "filing_date": ("4", "0000001234-26-000001", "one.xml", "2026-02-30"),
        }
        for label, (form, accession, document, filing_date) in invalid_rows.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                malformed = self._submissions_payload(
                    forms=[form], accessions=[accession], documents=[document],
                    filing_dates=[filing_date],
                )

                def fetch(url: str, _user_agent: str) -> bytes:
                    return ticker_payload if url == SEC_TICKER_MAP_URL else malformed

                cache_dir = Path(temp_dir)
                result = enrich_sec_form4(
                    (SecStockCandidate("Example", "A0TEST", "EXM", "2026-W34:10"),),
                    SecInsiderConfig("Stock Analyst owner@example.com", cache_dir),
                    fetch_bytes=fetch,
                    now=datetime(2026, 8, 3, tzinfo=timezone.utc),
                )

                self.assertEqual(result.failed_issuer_count, 1)
                self.assertTrue(result.archive_coverage_partial)
                self.assertFalse(
                    (cache_dir / "submissions" / "CIK0000001234.json").exists()
                )

    def test_semantically_invalid_cached_recent_rows_are_quarantined_and_refetched(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        invalid = self._submissions_payload(
            forms=["4"], accessions=["0000001234-26-000001"],
            documents=["one.xml"], filing_dates=["not-a-date"],
        )
        valid = self._submissions_payload(
            forms=[], accessions=[], documents=[], filing_dates=[]
        )

        def fetch(url: str, _user_agent: str) -> bytes:
            return ticker_payload if url == SEC_TICKER_MAP_URL else valid

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            submission_cache = cache_dir / "submissions" / "CIK0000001234.json"
            submission_cache.parent.mkdir(parents=True)
            submission_cache.write_bytes(invalid)
            result = enrich_sec_form4(
                (SecStockCandidate("Example", "A0TEST", "EXM", "2026-W34:10"),),
                SecInsiderConfig("Stock Analyst owner@example.com", cache_dir),
                fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )

            self.assertTrue(submission_cache.with_suffix(".json.corrupt").exists())
            self.assertEqual(submission_cache.read_bytes(), valid)

        self.assertEqual(result.failed_issuer_count, 0)
        self.assertFalse(result.archive_coverage_partial)

    def test_semantically_invalid_archive_row_is_partial_and_not_cached(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        archive_name = "CIK0000001234-submissions-001.json"
        submissions_payload = json.dumps(
            {
                "filings": {
                    "recent": {
                        "form": [], "accessionNumber": [],
                        "primaryDocument": [], "filingDate": [],
                    },
                    "files": [{"name": archive_name, "filingTo": "2026-08-01"}],
                }
            }
        ).encode()
        invalid_archive = self._submissions_payload(
            forms=["4"], accessions=["0000001234-26-000001"],
            documents=["one.xml"], filing_dates=["not-a-date"],
            recent_wrapper=False,
        )

        def fetch(url: str, _user_agent: str) -> bytes:
            if url == SEC_TICKER_MAP_URL:
                return ticker_payload
            if url == SEC_SUBMISSIONS_URL.format(cik="0000001234"):
                return submissions_payload
            return invalid_archive

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            result = enrich_sec_form4(
                (SecStockCandidate("Example", "A0TEST", "EXM", "2026-W34:10"),),
                SecInsiderConfig("Stock Analyst owner@example.com", cache_dir),
                fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )

            self.assertFalse(
                (cache_dir / "submissions" / "archives" / archive_name).exists()
            )

        self.assertEqual(result.failed_issuer_count, 1)
        self.assertTrue(result.archive_coverage_partial)
        self.assertEqual(result.archive_file_count, 0)

    def test_archive_mismatched_arrays_are_partial_and_not_cached(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        archive_name = "CIK0000001234-submissions-001.json"
        submissions_payload = json.dumps(
            {
                "filings": {
                    "recent": {
                        "form": [], "accessionNumber": [],
                        "primaryDocument": [], "filingDate": [],
                    },
                    "files": [{"name": archive_name, "filingTo": "2026-08-01"}],
                }
            }
        ).encode()
        malformed_archive = json.dumps(
            {
                "form": ["4", "4"],
                "accessionNumber": ["0000001234-26-000001"],
                "primaryDocument": ["one.xml", "two.xml"],
                "filingDate": ["2026-08-01", "2026-08-02"],
            }
        ).encode()

        def fetch(url: str, _user_agent: str) -> bytes:
            if url == SEC_TICKER_MAP_URL:
                return ticker_payload
            if url == SEC_SUBMISSIONS_URL.format(cik="0000001234"):
                return submissions_payload
            return malformed_archive

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            result = enrich_sec_form4(
                (SecStockCandidate("Example", "A0TEST", None, "2026-W34:10"),),
                SecInsiderConfig("Stock Analyst owner@example.com", cache_dir),
                fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )
            self.assertFalse(
                (cache_dir / "submissions" / "archives" / archive_name).exists()
            )

        self.assertEqual(result.failed_issuer_count, 1)
        self.assertTrue(result.archive_coverage_partial)
        self.assertEqual(result.archive_file_count, 0)

    def test_missing_archive_file_metadata_is_partial(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        missing_files = json.dumps(
            {
                "filings": {
                    "recent": {
                        "form": [], "accessionNumber": [],
                        "primaryDocument": [], "filingDate": [],
                    }
                }
            }
        ).encode()

        def fetch(url: str, _user_agent: str) -> bytes:
            return ticker_payload if url == SEC_TICKER_MAP_URL else missing_files

        with tempfile.TemporaryDirectory() as temp_dir:
            result = enrich_sec_form4(
                (SecStockCandidate("Example", "A0TEST", None, "2026-W34:10"),),
                SecInsiderConfig("Stock Analyst owner@example.com", Path(temp_dir)),
                fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )

        self.assertEqual(result.failed_issuer_count, 1)
        self.assertTrue(result.archive_coverage_partial)
        self.assertFalse(result.request_budget_exhausted)

    def test_plain_contact_email_gets_application_prefix(self) -> None:
        config = load_sec_insider_config({"SEC_USER_AGENT": "owner@example.com"})
        self.assertIsNotNone(config)
        self.assertEqual(config.user_agent, "Stock Analyst owner@example.com")

    def test_resolves_reviewed_ticker_or_unique_exact_company_only(self) -> None:
        records = parse_sec_ticker_records(
            json.dumps(
                {
                    "0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"},
                    "1": {"cik_str": 5678, "ticker": "OTHER", "title": "OTHER INC"},
                }
            ).encode()
        )
        resolved, unresolved = resolve_sec_issuers(
            (
                SecStockCandidate("Example", "A0ONE", None, "2026-W32:10"),
                SecStockCandidate("Magazine alias", "A0TWO", "EXM", "2026-W32:12"),
                SecStockCandidate("Exam", "A0BAD", None, "2026-W32:14"),
            ),
            records,
        )
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].ticker, "EXM")
        self.assertEqual(resolved[0].wkn, "A0ONE | A0TWO")
        self.assertEqual(unresolved, 1)

    def test_filters_recent_form4_and_amendments(self) -> None:
        payload = json.dumps(
            {
                "filings": {
                    "recent": {
                        "form": ["4", "4/A", "10-K", "4"],
                        "accessionNumber": ["a", "b", "c", "d"],
                        "primaryDocument": [
                            "xslF345X06/a.xml",
                            "b.xml",
                            "c.htm",
                            "d.xml",
                        ],
                        "filingDate": ["2026-07-30", "2026-07-29", "2026-07-28", "2025-01-01"],
                    },
                    "files": [],
                }
            }
        ).encode()
        self.assertEqual(
            recent_form4_filings(payload, cutoff=date(2026, 1, 1)),
            (("a", "a.xml", "2026-07-30"), ("b", "b.xml", "2026-07-29")),
        )

    def test_parses_all_transactions_with_unique_filing_identities(self) -> None:
        issuer = SecResolvedIssuer(
            cik="0000001234",
            ticker="EXM",
            company="Example",
            wkn="A0TEST",
            source_ref="2026-W32:10",
        )
        rows = parse_form4_transactions(
            FORM4_XML,
            issuer=issuer,
            filing_date="2026-08-01",
            filing_url="https://www.sec.gov/filing.xml",
            date_updated="2026-08-03",
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].transaction_value, "125.00")
        self.assertEqual(rows[0].signal, "Open-market purchase")
        self.assertEqual(rows[1].signal, "Open-market sale")
        self.assertNotEqual(rows[0].filing_url, rows[1].filing_url)
        self.assertEqual(
            rows[0].to_sheet_row(),
            [
                "Example",
                "A0TEST",
                "EXM",
                "DOE JANE",
                "Director | Officer | CEO",
                "110",
                "2026-07-30",
                "purchase",
                "Acquired",
                "10",
                "12.50",
                "125.00",
            ],
        )

    def test_simplifies_supported_transaction_codes(self) -> None:
        expected = {
            "P": "purchase",
            "S": "sale",
            "M": "Conversion",
            "F": "Payment",
            "G": "Gift",
            "A": "Awarded",
            "J": "Other",
        }
        for code, label in expected.items():
            xml = FORM4_XML.replace(
                b"<transactionCode>P</transactionCode>",
                f"<transactionCode>{code}</transactionCode>".encode(),
                1,
            )
            row = parse_form4_transactions(
                xml,
                issuer=SecResolvedIssuer(
                    cik="0000001234",
                    ticker="EXM",
                    company="Example",
                    wkn="A0TEST",
                    source_ref="2026-W33:10",
                ),
                filing_date="2026-08-06",
                filing_url="https://www.sec.gov/filing.xml",
                date_updated="2026-08-06",
            )[0]
            self.assertEqual(row.to_sheet_row()[7], label)

    def test_enrichment_uses_cache_and_does_not_duplicate_transactions(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        submissions_payload = json.dumps(
            {
                "filings": {
                    "recent": {
                        "form": ["4"],
                        "accessionNumber": ["0000001234-26-000001"],
                        "primaryDocument": ["form4.xml"],
                        "filingDate": ["2026-08-01"],
                    },
                    "files": [],
                }
            }
        ).encode()
        calls = []

        def fetch(url: str, user_agent: str) -> bytes:
            calls.append((url, user_agent))
            if url == SEC_TICKER_MAP_URL:
                return ticker_payload
            if url == SEC_SUBMISSIONS_URL.format(cik="0000001234"):
                return submissions_payload
            return FORM4_XML

        with tempfile.TemporaryDirectory() as temp_dir:
            config = SecInsiderConfig(
                user_agent="Stock Analyst owner@example.com",
                cache_dir=Path(temp_dir),
            )
            candidate = SecStockCandidate("Example", "A0TEST", None, "2026-W32:10")
            now = datetime(2026, 8, 3, tzinfo=timezone.utc)
            first = enrich_sec_form4((candidate,), config, fetch_bytes=fetch, now=now)
            second = enrich_sec_form4((candidate,), config, fetch_bytes=fetch, now=now)

        self.assertEqual(first.network_request_count, 3)
        self.assertEqual(len(first.transactions), 2)
        self.assertEqual(second.network_request_count, 0)
        self.assertEqual(second.cache_hit_count, 3)
        self.assertEqual(len(second.transactions), 2)
        self.assertEqual(len(calls), 3)

    def test_malformed_filing_does_not_block_later_valid_filings(self) -> None:
        ticker_payload = json.dumps(
            {"0": {"cik_str": 1234, "ticker": "EXM", "title": "EXAMPLE CORP"}}
        ).encode()
        submissions_payload = json.dumps(
            {
                "filings": {
                    "recent": {
                        "form": ["4", "4"],
                        "accessionNumber": [
                            "0000001234-26-000002",
                            "0000001234-26-000001",
                        ],
                        "primaryDocument": ["broken.xml", "valid.xml"],
                        "filingDate": ["2026-08-02", "2026-08-01"],
                    },
                    "files": [],
                }
            }
        ).encode()

        def fetch(url: str, _user_agent: str) -> bytes:
            if url == SEC_TICKER_MAP_URL:
                return ticker_payload
            if url == SEC_SUBMISSIONS_URL.format(cik="0000001234"):
                return submissions_payload
            if url.endswith("broken.xml"):
                return b"not XML"
            return FORM4_XML

        with tempfile.TemporaryDirectory() as temp_dir:
            result = enrich_sec_form4(
                (SecStockCandidate("Example", "A0TEST", None, "2026-W32:10"),),
                SecInsiderConfig(
                    user_agent="Stock Analyst owner@example.com",
                    cache_dir=Path(temp_dir),
                ),
                fetch_bytes=fetch,
                now=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )

        self.assertEqual(result.filing_count, 2)
        self.assertEqual(result.failed_filing_count, 1)
        self.assertEqual(len(result.transactions), 2)

    @staticmethod
    def _submissions_payload(
        *, forms, accessions, documents, filing_dates, recent_wrapper=True,
    ) -> bytes:
        rows = {
            "form": forms,
            "accessionNumber": accessions,
            "primaryDocument": documents,
            "filingDate": filing_dates,
        }
        payload = {"filings": {"recent": rows, "files": []}} if recent_wrapper else rows
        return json.dumps(payload).encode()


if __name__ == "__main__":
    unittest.main()
