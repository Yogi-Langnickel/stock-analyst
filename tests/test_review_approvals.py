import csv
import hashlib
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from stock_analyst.review_approvals import (
    approved_workbook_rows_fingerprint,
    apply_workbook_approvals,
    approval_template_csv_from_workbook_plan,
    load_workbook_approvals_csv,
    workbook_row_values_sha256,
    ReviewApprovalError,
    WorkbookRowApproval,
)
from stock_analyst.cli import (
    run_workbook_approval_audit_command,
    run_workbook_approval_template_command,
)


def workbook_plan() -> dict[str, object]:
    return {
        "issueId": "2026-W03",
        "manualReviewRequired": True,
        "approvedRows": 0,
        "rows": [
            {
                "tab": "Stocks",
                "rowKind": "stock_recommendation",
                "sourceId": "stock:2026-W03:p22:A0MRD4:abc",
                "issueId": "2026-W03",
                "page": 22,
                "reviewStatus": "needs_review",
                "exportable": False,
                "requiresManualReview": True,
                "sourceBlock": "manual_review_pending",
                "values": [
                    "Banco Sabadell",
                    "A0MRD4",
                    "4,30 EUR",
                    "2,70 EUR",
                ],
                "warnings": ["manual_review_required_before_family_visible_export"],
            },
            {
                "tab": "Stocks",
                "rowKind": "stock_recommendation",
                "sourceId": "stock:2026-W03:p42:A1CX3T:def",
                "issueId": "2026-W03",
                "page": 42,
                "reviewStatus": "needs_review",
                "exportable": False,
                "requiresManualReview": True,
                "sourceBlock": "manual_review_pending",
                "values": [
                    "Tesla",
                    "A1CX3T",
                    "480,00 EUR",
                    "295,00 EUR",
                ],
                "warnings": ["manual_review_required_before_family_visible_export"],
            },
        ],
    }


class ReviewApprovalTest(unittest.TestCase):
    def test_row_values_hash_preserves_json_value_types(self) -> None:
        self.assertNotEqual(
            workbook_row_values_sha256(["2"]),
            workbook_row_values_sha256([2]),
        )
        self.assertNotEqual(
            workbook_row_values_sha256([None]),
            workbook_row_values_sha256([""]),
        )

    def test_approved_rows_fingerprint_uses_documented_canonical_payload(self) -> None:
        rows = [
            {
                "sourceId": "row-z",
                "reviewStatus": "approved",
                "values": ["Zürich", None, 2],
            },
            {
                "sourceId": "row-a",
                "reviewStatus": "approved",
                "values": ["Alpha", 1],
            },
            {
                "sourceId": "ignored",
                "reviewStatus": "needs_review",
                "values": ["not fingerprinted"],
            },
        ]
        canonical = json.dumps(
            [
                {
                    "sourceId": "row-a",
                    "rowValuesSha256": workbook_row_values_sha256(["Alpha", 1]),
                },
                {
                    "sourceId": "row-z",
                    "rowValuesSha256": workbook_row_values_sha256(["Zürich", None, 2]),
                },
            ],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        self.assertEqual(
            approved_workbook_rows_fingerprint(rows),
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )

    def test_approval_template_includes_exact_row_hashes_without_approving_rows(self) -> None:
        plan = workbook_plan()

        csv_text = approval_template_csv_from_workbook_plan(plan)
        rows = list(csv.DictReader(StringIO(csv_text)))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["source_id"], "stock:2026-W03:p22:A0MRD4:abc")
        self.assertEqual(rows[0]["review_status"], "needs_review")
        self.assertEqual(
            rows[0]["row_values_sha256"],
            workbook_row_values_sha256(plan["rows"][0]["values"]),
        )
        self.assertEqual(rows[0]["reviewer"], "")

    def test_apply_approval_import_marks_exact_rows_exportable(self) -> None:
        plan = workbook_plan()
        row = plan["rows"][0]
        approval = WorkbookRowApproval(
            source_id=row["sourceId"],
            review_status="approved",
            reviewer="reviewer@example.test",
            reviewed_at="2026-06-06T10:00:00+00:00",
            source_block="reviewed_card_page_22",
            row_values_sha256=workbook_row_values_sha256(row["values"]),
            review_notes="verified against source page",
        )

        reviewed = apply_workbook_approvals(plan, (approval,))

        approved_row = reviewed["rows"][0]
        untouched_row = reviewed["rows"][1]
        self.assertEqual(approved_row["reviewStatus"], "approved")
        self.assertTrue(approved_row["exportable"])
        self.assertFalse(approved_row["requiresManualReview"])
        self.assertEqual(approved_row["sourceBlock"], "reviewed_card_page_22")
        self.assertEqual(approved_row["reviewedBy"], "reviewer@example.test")
        self.assertEqual(approved_row["reviewNotes"], "verified against source page")
        self.assertEqual(approved_row["warnings"], [])
        self.assertEqual(untouched_row["reviewStatus"], "needs_review")
        self.assertFalse(untouched_row["exportable"])
        self.assertEqual(reviewed["approvedRows"], 1)
        self.assertEqual(
            reviewed["approvalAudit"],
            {
                "externalServicesEnabled": False,
                "networkAccess": False,
                "approvalSource": "private_reviewer_csv",
                "rowCount": 2,
                "approvalRowsImported": 1,
                "matchedApprovalRows": 1,
                "unmatchedApprovalRows": 0,
                "approvedRows": 1,
                "rejectedRows": 0,
                "needsReviewRows": 1,
                "hashMismatchRows": 0,
                "invalidEvidenceRows": 0,
                "staleApprovalDetected": False,
                "approvedRowsFingerprint": approved_workbook_rows_fingerprint(
                    reviewed["rows"]
                ),
            },
        )

    def test_stale_approval_hash_keeps_row_non_exportable(self) -> None:
        plan = workbook_plan()
        row = plan["rows"][0]
        approval = WorkbookRowApproval(
            source_id=row["sourceId"],
            review_status="approved",
            reviewer="reviewer@example.test",
            reviewed_at="2026-06-06T10:00:00+00:00",
            source_block="reviewed_card_page_22",
            row_values_sha256="0" * 64,
        )

        reviewed = apply_workbook_approvals(plan, (approval,))

        self.assertEqual(reviewed["rows"][0]["reviewStatus"], "needs_review")
        self.assertFalse(reviewed["rows"][0]["exportable"])
        self.assertTrue(reviewed["rows"][0]["approvalHashMismatch"])
        self.assertEqual(reviewed["approvalAudit"]["hashMismatchRows"], 1)
        self.assertTrue(reviewed["approvalAudit"]["staleApprovalDetected"])

    def test_missing_final_review_evidence_keeps_direct_approval_non_exportable(self) -> None:
        plan = workbook_plan()
        row = plan["rows"][0]
        approval = WorkbookRowApproval(
            source_id=row["sourceId"],
            review_status="approved",
            reviewer="reviewer@example.test",
            reviewed_at="2026-06-06T10:00:00+00:00",
            source_block="reviewed_card_page_22",
            row_values_sha256="",
        )

        reviewed = apply_workbook_approvals(plan, (approval,))

        self.assertEqual(reviewed["rows"][0]["reviewStatus"], "needs_review")
        self.assertFalse(reviewed["rows"][0]["exportable"])
        self.assertTrue(reviewed["rows"][0]["approvalEvidenceInvalid"])
        self.assertEqual(reviewed["approvalAudit"]["invalidEvidenceRows"], 1)
        self.assertTrue(reviewed["approvalAudit"]["staleApprovalDetected"])

    def test_rejected_approval_keeps_row_non_exportable_with_warning(self) -> None:
        plan = workbook_plan()
        row = plan["rows"][0]
        approval = WorkbookRowApproval(
            source_id=row["sourceId"],
            review_status="rejected",
            reviewer="reviewer@example.test",
            reviewed_at="2026-06-06T10:00:00+00:00",
            source_block="reviewed_card_page_22",
            row_values_sha256=workbook_row_values_sha256(row["values"]),
        )

        reviewed = apply_workbook_approvals(plan, (approval,))

        self.assertEqual(reviewed["rows"][0]["reviewStatus"], "rejected")
        self.assertFalse(reviewed["rows"][0]["exportable"])
        self.assertTrue(reviewed["rows"][0]["requiresManualReview"])
        self.assertIn("review_rejected", reviewed["rows"][0]["warnings"])
        self.assertEqual(reviewed["approvalAudit"]["rejectedRows"], 1)

    def test_load_approval_csv_requires_full_approval_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "approval.csv"
            path.write_text(
                "\n".join(
                    (
                        "source_id,review_status,reviewer,reviewed_at,source_block,row_values_sha256,review_notes",
                        "stock:1,approved,,2026-06-06T10:00:00+00:00,block," + "a" * 64 + ",",
                    )
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ReviewApprovalError, "missing reviewer"):
                load_workbook_approvals_csv(path)

    def test_load_approval_csv_requires_rejection_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "approval.csv"
            path.write_text(
                "\n".join(
                    (
                        "source_id,review_status,reviewer,reviewed_at,source_block,row_values_sha256,review_notes",
                        "stock:1,rejected,,2026-06-06T10:00:00+00:00,block," + "a" * 64 + ",",
                    )
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ReviewApprovalError, "missing reviewer"):
                load_workbook_approvals_csv(path)

    def test_load_approval_csv_round_trips_private_decisions(self) -> None:
        row_hash = "b" * 64
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "approval.csv"
            path.write_text(
                "\n".join(
                    (
                        "source_id,review_status,reviewer,reviewed_at,source_block,row_values_sha256,review_notes",
                        f"stock:1,approved,reviewer@example.test,2026-06-06T10:00:00+00:00,block,{row_hash},ok",
                    )
                ),
                encoding="utf-8",
            )

            approvals = load_workbook_approvals_csv(path)

        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0].source_id, "stock:1")
        self.assertEqual(approvals[0].review_status, "approved")
        self.assertEqual(approvals[0].row_values_sha256, row_hash)

    def test_approval_payload_is_json_serializable(self) -> None:
        plan = workbook_plan()
        reviewed = apply_workbook_approvals(plan, ())

        json.dumps(reviewed, sort_keys=True)

    def test_cli_template_and_audit_write_private_files_without_returning_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            private_dir = root / "private" / "review"
            plan_path = private_dir / "workbook-plan.json"
            approval_path = private_dir / "approvals.csv"
            reviewed_path = private_dir / "reviewed-plan.json"
            plan = workbook_plan()
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            template_result = run_workbook_approval_template_command(
                workbook_plan_file=plan_path,
                output=approval_path,
            )
            rows = list(csv.DictReader(StringIO(approval_path.read_text(encoding="utf-8"))))
            rows[0]["review_status"] = "approved"
            rows[0]["reviewer"] = "reviewer@example.test"
            rows[0]["reviewed_at"] = "2026-06-06T10:00:00+00:00"
            rows[0]["source_block"] = "reviewed_card_page_22"
            output = StringIO()
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
            approval_path.write_text(output.getvalue(), encoding="utf-8")

            audit_result = run_workbook_approval_audit_command(
                workbook_plan_file=plan_path,
                approval_csv=approval_path,
                output=reviewed_path,
            )
            reviewed_payload = json.loads(reviewed_path.read_text(encoding="utf-8"))

        self.assertTrue(template_result["ok"])
        self.assertEqual(template_result["rowCount"], 2)
        self.assertFalse(template_result["rowContentReturned"])
        self.assertTrue(audit_result["ok"])
        self.assertFalse(audit_result["rowContentReturned"])
        self.assertEqual(audit_result["approvedRows"], 1)
        self.assertNotIn("rows", audit_result)
        self.assertEqual(reviewed_payload["rows"][0]["reviewStatus"], "approved")
        self.assertTrue(reviewed_payload["rows"][0]["exportable"])

    def test_cli_requires_private_paths_for_approval_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path = root / "workbook-plan.json"
            plan_path.write_text(json.dumps(workbook_plan()), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "private path"):
                run_workbook_approval_template_command(
                    workbook_plan_file=plan_path,
                    output=root / "approvals.csv",
                )


if __name__ == "__main__":
    unittest.main()
