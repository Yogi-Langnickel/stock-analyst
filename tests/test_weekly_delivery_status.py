"""Combined write outcomes must never conceal failed required enrichment."""

import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from stock_analyst import cli


def _enrichment(**overrides):
    values = dict(
        transactions=(), candidate_count=1, resolved_issuer_count=1,
        unresolved_candidate_count=0, filing_count=0, failed_issuer_count=0,
        failed_filing_count=0, network_request_count=1, cache_hit_count=0,
        request_budget_exhausted=False, archive_file_count=0,
        archive_coverage_partial=False, transaction_revisions=(),
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class WeeklyDeliveryStatusTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.plan = Path(directory) / "plan.json"
        self.plan.write_text(json.dumps({"issueId": "2026-W44", "rows": []}))
        self.stack.enter_context(patch.dict("os.environ", {"STOCK_ANALYST_SYMBOL_MAP_FILE": str(Path(directory) / "symbols.csv")}, clear=True))
        self.stack.enter_context(patch("stock_analyst.cli.load_google_access_config", return_value=object()))
        self.sec_config = self.stack.enter_context(patch("stock_analyst.cli.load_sec_insider_config", return_value=object()))
        self.issue_write = self.stack.enter_context(patch("stock_analyst.cli.write_workbook_plan_to_google_sheet", side_effect=lambda *args, **kwargs: {
            "ok": True, "rowsWritten": 2, "privateDraftReviewOnly": True,
            "familyVisibleSafe": False, "exportMode": "private_draft_review_export",
        }))
        self.ledger_write = self.stack.enter_context(patch("stock_analyst.cli.write_insider_activity_rows_to_google_sheet", return_value={"ok": True, "rowsRetained": 1}))
        self.stack.enter_context(patch("stock_analyst.cli.build_market_data_symbol_map_template_csv", return_value="source_id,wkn,name,symbol\n"))
        self.stack.enter_context(patch("stock_analyst.cli.market_data_candidates_from_symbol_map_template_csv", return_value=()))
        self.enrich = self.stack.enter_context(patch("stock_analyst.cli.enrich_sec_form4", return_value=_enrichment()))

    def export(self, **kwargs):
        return cli.run_google_sheets_export_plan_command(self.plan, allow_draft_rows=True, **kwargs)

    def test_successful_write_remains_pending_independent_verification(self):
        result = self.export(require_sec_enrichment=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["deliveryStatus"], "written")
        self.assertEqual(result["verificationStatus"], "pending")
        self.assertFalse(result["weeklyRefreshComplete"])
        self.assertTrue(result["issueExport"]["ok"])
        self.assertEqual(result["issueExport"]["rowsWritten"], 2)
        self.assertNotIn("insiderEnrichment", result["issueExport"])

    def test_each_partial_sec_condition_marks_combined_result_incomplete(self):
        for fault in (
            {"failed_filing_count": 1}, {"failed_issuer_count": 1},
            {"request_budget_exhausted": True}, {"archive_coverage_partial": True},
        ):
            with self.subTest(fault=fault):
                self.enrich.return_value = _enrichment(**fault)
                result = self.export()
                self.assertFalse(result["ok"])
                self.assertEqual(result["deliveryStatus"], "incomplete")
                self.assertEqual(result["insiderEnrichment"]["status"], "partial")
                self.assertTrue(result["secEnrichmentRequired"])
                self.assertTrue(result["issueExport"]["ok"])

    def test_failed_refresh_preserves_issue_receipt_without_private_error_text(self):
        self.enrich.side_effect = RuntimeError("PRIVATE filing-url sheet-id company secret")
        result = self.export()
        self.assertFalse(result["ok"])
        self.assertEqual(result["deliveryStatus"], "incomplete")
        self.assertEqual(result["insiderEnrichment"]["status"], "failed")
        self.assertTrue(result["issueExport"]["ok"])
        self.assertFalse(result["familyVisibleSafe"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_required_missing_configuration_stops_before_any_google_write(self):
        self.sec_config.return_value = None
        result = self.export(require_sec_enrichment=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["issueExport"], {"ok": False, "status": "not_started"})
        self.assertEqual(result["insiderEnrichment"]["reason"], "required_sec_configuration_missing")
        self.issue_write.assert_not_called()
        self.ledger_write.assert_not_called()
        self.enrich.assert_not_called()

    def test_optional_absent_sec_is_explicit_issue_only_not_a_complete_weekly_refresh(self):
        self.sec_config.return_value = None
        result = self.export()
        self.assertTrue(result["ok"])
        self.assertEqual(result["deliveryScope"], "issue_only")
        self.assertFalse(result["secEnrichmentRequired"])
        self.assertEqual(result["insiderEnrichment"]["status"], "skipped")
        self.assertFalse(result["insiderEnrichment"]["complete"])
        self.assertFalse(result["weeklyRefreshComplete"])

    def test_cli_returns_nonzero_for_partial_and_failed_required_delivery(self):
        for enrichment in (_enrichment(failed_filing_count=1), RuntimeError("PRIVATE error")):
            with self.subTest(enrichment=type(enrichment).__name__):
                if isinstance(enrichment, Exception):
                    self.enrich.side_effect = enrichment
                else:
                    self.enrich.return_value = enrichment
                output = io.StringIO()
                with redirect_stdout(output):
                    code = cli.main(["google-sheets-export-plan", str(self.plan), "--allow-draft-rows", "--require-sec-enrichment"])
                self.assertEqual(code, 1)
                self.assertEqual(json.loads(output.getvalue())["deliveryStatus"], "incomplete")
                self.assertNotIn("PRIVATE", output.getvalue())

    def test_verifier_cli_returns_nonzero_for_live_mismatch(self):
        output = io.StringIO()
        with patch("stock_analyst.cli.verify_google_sheet_workbook", return_value={"ok": False, "status": "incomplete", "checks": {"issuePlanLiteralProjectionCorrect": False}}), redirect_stdout(output):
            code = cli.main(["google-sheets-verify-plan", str(self.plan), "--expected-ledger-rows", "7"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
