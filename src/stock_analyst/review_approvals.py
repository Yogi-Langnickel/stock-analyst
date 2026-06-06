"""Private reviewer approval import for workbook export plans."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Mapping, Sequence


APPROVAL_CSV_HEADERS = (
    "source_id",
    "review_status",
    "reviewer",
    "reviewed_at",
    "source_block",
    "row_values_sha256",
    "review_notes",
)
APPROVABLE_REVIEW_STATUSES = {"approved", "rejected", "needs_review"}


class ReviewApprovalError(ValueError):
    """Raised when reviewer approval state cannot be imported safely."""


@dataclass(frozen=True)
class WorkbookRowApproval:
    source_id: str
    review_status: str
    reviewer: str
    reviewed_at: str
    source_block: str
    row_values_sha256: str
    review_notes: str = ""


def workbook_row_values_sha256(values: Sequence[object]) -> str:
    """Hash exact workbook row cell values for stale-approval detection."""

    payload = json.dumps(
        ["" if value is None else str(value) for value in values],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def approval_template_csv_from_workbook_plan(
    workbook_plan: Mapping[str, object],
) -> str:
    """Return a private reviewer CSV template for source-linked workbook rows."""

    rows = _workbook_plan_rows(workbook_plan)
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=APPROVAL_CSV_HEADERS)
    writer.writeheader()
    for row in rows:
        values = _row_values(row)
        writer.writerow(
            {
                "source_id": _source_id(row),
                "review_status": "needs_review",
                "reviewer": "",
                "reviewed_at": "",
                "source_block": str(row.get("sourceBlock") or ""),
                "row_values_sha256": workbook_row_values_sha256(values),
                "review_notes": "",
            }
        )
    return output.getvalue()


def load_workbook_approvals_csv(path: Path) -> tuple[WorkbookRowApproval, ...]:
    """Load reviewer approval decisions from a private local CSV file."""

    if not path.exists():
        raise ReviewApprovalError(f"approval CSV does not exist: {path}")

    reader = csv.DictReader(StringIO(path.read_text(encoding="utf-8")))
    if reader.fieldnames is None:
        raise ReviewApprovalError(f"approval CSV is empty: {path}")

    missing_headers = set(APPROVAL_CSV_HEADERS) - {
        header.strip() for header in reader.fieldnames if header
    }
    if missing_headers:
        raise ReviewApprovalError(
            "approval CSV is missing required columns: "
            + ", ".join(sorted(missing_headers))
        )

    approvals: list[WorkbookRowApproval] = []
    seen_source_ids: set[str] = set()
    for line_number, row in enumerate(reader, 2):
        normalized = {
            (key or "").strip(): (value or "").strip()
            for key, value in row.items()
        }
        source_id = normalized.get("source_id", "")
        review_status = normalized.get("review_status", "").lower()
        reviewer = normalized.get("reviewer", "")
        reviewed_at = normalized.get("reviewed_at", "")
        source_block = normalized.get("source_block", "")
        row_hash = normalized.get("row_values_sha256", "").lower()
        review_notes = normalized.get("review_notes", "")

        if not source_id:
            raise ReviewApprovalError(f"approval CSV line {line_number} is missing source_id")
        if source_id in seen_source_ids:
            raise ReviewApprovalError(
                f"approval CSV line {line_number} duplicates source_id"
            )
        seen_source_ids.add(source_id)
        if review_status not in APPROVABLE_REVIEW_STATUSES:
            raise ReviewApprovalError(
                f"approval CSV line {line_number} has unsupported review_status"
            )
        if review_status == "approved":
            _validate_approval_fields(
                line_number=line_number,
                reviewer=reviewer,
                reviewed_at=reviewed_at,
                source_block=source_block,
                row_hash=row_hash,
            )
        elif row_hash and not _is_sha256(row_hash):
            raise ReviewApprovalError(
                f"approval CSV line {line_number} has invalid row_values_sha256"
            )
        if reviewed_at:
            _parse_reviewed_at(reviewed_at, line_number=line_number)

        approvals.append(
            WorkbookRowApproval(
                source_id=source_id,
                review_status=review_status,
                reviewer=reviewer,
                reviewed_at=reviewed_at,
                source_block=source_block,
                row_values_sha256=row_hash,
                review_notes=review_notes,
            )
        )
    return tuple(approvals)


def apply_workbook_approvals(
    workbook_plan: Mapping[str, object],
    approvals: Sequence[WorkbookRowApproval],
) -> dict[str, object]:
    """Apply private reviewer approvals to exact workbook-plan rows."""

    rows = _workbook_plan_rows(workbook_plan)
    approval_by_source_id = {approval.source_id: approval for approval in approvals}
    matched_approval_ids: set[str] = set()
    updated_rows: list[object] = []
    approved_count = 0
    rejected_count = 0
    needs_review_count = 0
    hash_mismatch_count = 0

    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            updated_rows.append(raw_row)
            continue
        row = dict(raw_row)
        source_id = _source_id(row)
        approval = approval_by_source_id.get(source_id)

        if approval is None:
            row["reviewStatus"] = "needs_review"
            row["exportable"] = False
            row["requiresManualReview"] = True
            needs_review_count += 1
            updated_rows.append(row)
            continue

        matched_approval_ids.add(source_id)
        values_hash = workbook_row_values_sha256(_row_values(row))
        if approval.row_values_sha256 and approval.row_values_sha256 != values_hash:
            row["reviewStatus"] = "needs_review"
            row["exportable"] = False
            row["requiresManualReview"] = True
            row["approvalHashMismatch"] = True
            hash_mismatch_count += 1
            needs_review_count += 1
            updated_rows.append(row)
            continue

        row["reviewStatus"] = approval.review_status
        row["reviewedBy"] = approval.reviewer or None
        row["reviewedAt"] = approval.reviewed_at or None
        row["reviewNotes"] = approval.review_notes or None
        if approval.source_block:
            row["sourceBlock"] = approval.source_block

        if approval.review_status == "approved":
            row["exportable"] = True
            row["requiresManualReview"] = False
            row["warnings"] = [
                warning
                for warning in row.get("warnings", [])
                if warning != "manual_review_required_before_family_visible_export"
            ]
            approved_count += 1
        elif approval.review_status == "rejected":
            row["exportable"] = False
            row["requiresManualReview"] = True
            row["warnings"] = _append_warning(row, "review_rejected")
            rejected_count += 1
        else:
            row["exportable"] = False
            row["requiresManualReview"] = True
            needs_review_count += 1
        updated_rows.append(row)

    unmatched_approval_count = len(set(approval_by_source_id) - matched_approval_ids)
    result = dict(workbook_plan)
    result["rows"] = updated_rows
    result["manualReviewRequired"] = needs_review_count > 0 or rejected_count > 0
    result["approvedRows"] = approved_count
    result["approvalAudit"] = {
        "externalServicesEnabled": False,
        "networkAccess": False,
        "approvalSource": "private_reviewer_csv",
        "rowCount": len(updated_rows),
        "approvalRowsImported": len(approvals),
        "matchedApprovalRows": len(matched_approval_ids),
        "unmatchedApprovalRows": unmatched_approval_count,
        "approvedRows": approved_count,
        "rejectedRows": rejected_count,
        "needsReviewRows": needs_review_count,
        "hashMismatchRows": hash_mismatch_count,
        "staleApprovalDetected": hash_mismatch_count > 0,
    }
    return result


def write_approval_template_csv(
    workbook_plan: Mapping[str, object],
    output: Path,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        approval_template_csv_from_workbook_plan(workbook_plan),
        encoding="utf-8",
    )
    return output


def write_reviewed_workbook_plan(
    workbook_plan: Mapping[str, object],
    output: Path,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        f"{json.dumps(workbook_plan, ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    return output


def _workbook_plan_rows(workbook_plan: Mapping[str, object]) -> list[object]:
    rows = workbook_plan.get("rows")
    if not isinstance(rows, list):
        raise ReviewApprovalError("workbook plan is missing rows list")
    return rows


def _source_id(row: Mapping[str, object]) -> str:
    source_id = str(row.get("sourceId") or "").strip()
    if not source_id:
        raise ReviewApprovalError("workbook row is missing sourceId")
    return source_id


def _row_values(row: Mapping[str, object]) -> list[object]:
    values = row.get("values")
    if not isinstance(values, list):
        raise ReviewApprovalError("workbook row is missing values list")
    return values


def _validate_approval_fields(
    *,
    line_number: int,
    reviewer: str,
    reviewed_at: str,
    source_block: str,
    row_hash: str,
) -> None:
    if not reviewer:
        raise ReviewApprovalError(f"approval CSV line {line_number} is missing reviewer")
    if not reviewed_at:
        raise ReviewApprovalError(f"approval CSV line {line_number} is missing reviewed_at")
    if not source_block:
        raise ReviewApprovalError(f"approval CSV line {line_number} is missing source_block")
    if not _is_sha256(row_hash):
        raise ReviewApprovalError(
            f"approval CSV line {line_number} has invalid row_values_sha256"
        )
    _parse_reviewed_at(reviewed_at, line_number=line_number)


def _parse_reviewed_at(value: str, *, line_number: int) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReviewApprovalError(
            f"approval CSV line {line_number} has invalid reviewed_at"
        ) from error


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _append_warning(row: Mapping[str, object], warning: str) -> list[str]:
    warnings = [
        str(existing)
        for existing in row.get("warnings", [])
        if str(existing).strip()
    ]
    if warning not in warnings:
        warnings.append(warning)
    return warnings
