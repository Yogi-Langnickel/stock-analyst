#!/usr/bin/env python3
"""Build or validate a private-safe whole-issue reconciliation manifest."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 3
KEY_BYTES = 32
PLAN_ISSUE_ID = re.compile(r"^(20\d{2})-W(\d{2})$")
TAB_ISSUE_ID = re.compile(r"^DA_(20\d{2})_(\d{2})$")
HASH_REF = re.compile(r"^[0-9a-f]{24}$")
SOURCE_KINDS = {
    "labelled_card",
    "structured_action_table",
    "paired_action_table",
    "following_action_table",
    "recommendation_card",
    "current_action_table",
    "other_actionable_candidate",
    "stock_recommendation",
    "derivative_card",
    "derivative_overview",
    "stock_chart_check_summary",
    "stock_quickcheck_summary",
}
EXCEPTION_REASONS = {
    "missing_following_action_table",
    "ambiguous_source_mapping",
    "parser_miss",
    "unresolved_candidate",
    "reviewer_deferred",
}
TOP_KEYS = {
    "schemaVersion", "planIssueId", "issueTabId", "discoveryScope",
    "documentPageCount", "candidates",
}
CANDIDATE_KEYS = {
    "candidateId", "page", "sourceKind", "disposition", "rowSourceId",
    "exceptionOwner", "exceptionReasonCode", "visuallyInspected", "sourcePages",
}
MANIFEST_KEYS = {
    "schemaVersion", "planIssueId", "issueTabId", "discoveryScope", "documentPageCount",
    "hashKeyFingerprint", "planStructuralFingerprint", "planRowCount", "candidateCount",
    "mappedCandidateCount", "exceptionCandidateCount",
    "visuallyInspectedCandidateCount", "pagesWithCandidates", "reconciliation",
    "manifestHmacSha256",
}
ENTRY_BASE_KEYS = {
    "candidateRef", "page", "sourcePages", "sourceKind", "disposition",
    "visuallyInspected",
}
LEGACY_TOP_KEYS = {
    "issueId", "candidates", "exceptions", "visuallyInspectedPages",
    "private", "sourceTextIncluded",
}
LEGACY_CANDIDATE_KEYS = {
    "page", "rowKind", "sourceId", "reconciliation", "visualInspection",
    "reviewStatus", "sourcePages",
}
LEGACY_ROW_KINDS = {
    "stock_recommendation",
    "derivative_card",
    "derivative_overview",
    "stock_chart_check_summary",
    "stock_quickcheck_summary",
}


class ManifestError(ValueError):
    pass


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError(f"cannot read valid {label} JSON") from error
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be a JSON object")
    return value


def _require_private(path: Path, label: str) -> None:
    if "private" not in {part.lower() for part in path.expanduser().parts}:
        raise ManifestError(f"{label} path must include a private directory component")


def _require_distinct_output(output_path: Path, *protected_paths: Path) -> None:
    output_absolute = os.path.abspath(output_path.expanduser())
    for protected_path in protected_paths:
        protected_absolute = os.path.abspath(protected_path.expanduser())
        aliases = output_absolute == protected_absolute
        if not aliases and output_path.exists() and protected_path.exists():
            try:
                aliases = os.path.samefile(output_path, protected_path)
            except OSError:
                aliases = False
        if aliases:
            raise ManifestError("manifest output must not overwrite an input or HMAC key")


def _key_fingerprint(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


def initialize_key(key_path: Path) -> str:
    _require_private(key_path, "manifest HMAC key")
    key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(key_path, flags, 0o600)
    except FileExistsError as error:
        raise ManifestError("manifest HMAC key already exists; refusing to overwrite") from error
    key = secrets.token_bytes(KEY_BYTES)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(key)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        key_path.unlink(missing_ok=True)
        raise
    return _key_fingerprint(key)


def _load_key(key_path: Path) -> bytes:
    _require_private(key_path, "manifest HMAC key")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(key_path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            key = handle.read()
    except OSError as error:
        raise ManifestError("cannot read manifest HMAC key") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise ManifestError("manifest HMAC key must be a regular non-symlink file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ManifestError("manifest HMAC key permissions must deny group and other access")
    if len(key) != KEY_BYTES:
        raise ManifestError(f"manifest HMAC key must contain exactly {KEY_BYTES} bytes")
    return key


def _hash_ref(key: bytes, plan_issue_id: str, kind: str, raw: str) -> str:
    payload = f"stock-analyst-weekly-refresh:v3|{plan_issue_id}|{kind}|{raw}"
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def _manifest_mac(manifest: dict[str, Any], key: bytes) -> str:
    payload = {
        field: value
        for field, value in manifest.items()
        if field != "manifestHmacSha256"
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hmac.new(key, encoded, hashlib.sha256).hexdigest()


def _seal_manifest(manifest: dict[str, Any], key: bytes) -> dict[str, Any]:
    sealed = dict(manifest)
    sealed["manifestHmacSha256"] = _manifest_mac(sealed, key)
    return sealed


def _verify_manifest_mac(manifest: dict[str, Any], key: bytes) -> None:
    supplied = manifest.get("manifestHmacSha256")
    if not isinstance(supplied, str) or not re.fullmatch(r"[0-9a-f]{64}", supplied):
        raise ManifestError("manifest integrity MAC is missing or malformed")
    if not hmac.compare_digest(supplied, _manifest_mac(manifest, key)):
        raise ManifestError("manifest integrity MAC validation failed")


def _validate_issue_pair(plan_issue_id: Any, issue_tab_id: Any, label: str) -> None:
    if not isinstance(plan_issue_id, str) or not isinstance(issue_tab_id, str):
        raise ManifestError(f"{label} issue identifiers are missing")
    plan_match = PLAN_ISSUE_ID.fullmatch(plan_issue_id)
    tab_match = TAB_ISSUE_ID.fullmatch(issue_tab_id)
    if plan_match is None:
        raise ManifestError(f"{label} plan issue ID must match YYYY-WNN")
    if tab_match is None:
        raise ManifestError(f"{label} PDF/tab issue ID must match DA_YYYY_NN")
    if plan_match.groups() != tab_match.groups():
        raise ManifestError(f"{label} plan and PDF/tab issue IDs differ")


def _plan_structure(
    plan: dict[str, Any],
    plan_issue_id: str,
    key: bytes,
    source_pages_by_row_ref: dict[str, list[int]] | None = None,
) -> tuple[str, dict[str, dict[str, Any]]]:
    if plan.get("issueId") != plan_issue_id:
        raise ManifestError("candidate inventory and workbook plan issue IDs differ")
    rows = plan.get("rows")
    if not isinstance(rows, list):
        raise ManifestError("workbook plan must contain a rows list")

    by_source: dict[str, dict[str, Any]] = {}
    structural_rows: list[dict[str, Any]] = []
    for index, raw_row in enumerate(rows):
        if not isinstance(raw_row, dict):
            raise ManifestError(f"workbook row {index} must be an object")
        source_id = raw_row.get("sourceId")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ManifestError(f"workbook row {index} lacks a source ID")
        if source_id in by_source:
            raise ManifestError("workbook plan contains duplicate source IDs")
        page = raw_row.get("page")
        if page is not None and (
            not isinstance(page, int) or isinstance(page, bool) or page < 1
        ):
            raise ManifestError(f"workbook row {index} has an invalid page")
        by_source[source_id] = raw_row
        source_ref = _hash_ref(key, plan_issue_id, "row", source_id)
        structural_rows.append(
            {
                "sourceRef": source_ref,
                "tabRef": _hash_ref(key, plan_issue_id, "tab", str(raw_row.get("tab") or "")),
                "rowKind": str(raw_row.get("rowKind") or ""),
                "issueId": str(raw_row.get("issueId") or ""),
                "page": page,
                "sourcePages": (
                    source_pages_by_row_ref[source_ref]
                    if source_pages_by_row_ref is not None
                    and source_ref in source_pages_by_row_ref
                    else [page] if page is not None else []
                ),
                "sourceBlockRef": _hash_ref(
                    key, plan_issue_id, "source-block", str(raw_row.get("sourceBlock") or "")
                ),
            }
        )
    encoded = json.dumps(
        sorted(structural_rows, key=lambda row: row["sourceRef"]),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), by_source


def _candidate_entries(
    inventory: dict[str, Any], plan_rows: dict[str, dict[str, Any]], key: bytes
) -> list[dict[str, Any]]:
    if set(inventory) - TOP_KEYS:
        raise ManifestError("candidate inventory contains unsupported top-level fields")
    candidates = inventory.get("candidates")
    if not isinstance(candidates, list):
        raise ManifestError("candidate inventory must contain a candidates list")
    plan_issue_id = str(inventory["planIssueId"])
    page_count = inventory.get("documentPageCount")
    if not isinstance(page_count, int) or isinstance(page_count, bool) or page_count < 1:
        raise ManifestError("documentPageCount must be a positive integer")

    seen_candidates: set[str] = set()
    seen_rows: set[str] = set()
    entries: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise ManifestError(f"candidate {index} must be an object")
        if set(candidate) - CANDIDATE_KEYS:
            raise ManifestError(f"candidate {index} contains unsupported fields")
        candidate_id = candidate.get("candidateId")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ManifestError(f"candidate {index} lacks an opaque candidate ID")
        if candidate_id in seen_candidates:
            raise ManifestError("candidate inventory contains duplicate candidate IDs")
        seen_candidates.add(candidate_id)
        page = candidate.get("page")
        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= page_count:
            raise ManifestError(f"candidate {index} has an invalid page")
        source_kind = candidate.get("sourceKind")
        if source_kind not in SOURCE_KINDS:
            raise ManifestError(f"candidate {index} has an invalid source kind")
        if candidate.get("visuallyInspected") is not True:
            raise ManifestError(f"candidate {index} is not visually inspected")
        source_pages = _legacy_pages(
            candidate.get("sourcePages", [page]),
            label=f"candidate {index} sourcePages",
            page_count=page_count,
        )
        if not source_pages or source_pages[0] != page:
            raise ManifestError(
                f"candidate {index} sourcePages must start with its primary page"
            )

        disposition = candidate.get("disposition")
        entry: dict[str, Any] = {
            "candidateRef": _hash_ref(key, plan_issue_id, "candidate", candidate_id),
            "page": page,
            "sourcePages": source_pages,
            "sourceKind": source_kind,
            "disposition": disposition,
            "visuallyInspected": True,
        }
        if disposition == "mapped":
            row_source_id = candidate.get("rowSourceId")
            if not isinstance(row_source_id, str) or not row_source_id.strip():
                raise ManifestError(f"mapped candidate {index} lacks a row source ID")
            if any(
                candidate.get(key) is not None
                for key in ("exceptionOwner", "exceptionReasonCode")
            ):
                raise ManifestError(f"mapped candidate {index} contains exception fields")
            if row_source_id in seen_rows:
                raise ManifestError("multiple candidates map to the same workbook row")
            row = plan_rows.get(row_source_id)
            if row is None:
                raise ManifestError(f"mapped candidate {index} references no workbook row")
            if row.get("page") is not None and row.get("page") != page:
                raise ManifestError(f"mapped candidate {index} and workbook row pages differ")
            seen_rows.add(row_source_id)
            entry["rowRef"] = _hash_ref(key, plan_issue_id, "row", row_source_id)
        elif disposition == "exception":
            if candidate.get("rowSourceId") is not None:
                raise ManifestError(f"exception candidate {index} contains a row source ID")
            owner = candidate.get("exceptionOwner")
            reason = candidate.get("exceptionReasonCode")
            if not isinstance(owner, str) or not owner.strip():
                raise ManifestError(f"exception candidate {index} lacks an opaque owner")
            if reason not in EXCEPTION_REASONS:
                raise ManifestError(f"exception candidate {index} has an invalid reason code")
            entry["exceptionOwnerRef"] = _hash_ref(key, plan_issue_id, "owner", owner)
            entry["exceptionReasonCode"] = reason
        else:
            raise ManifestError(f"candidate {index} has an invalid disposition")
        entries.append(entry)
    return sorted(entries, key=lambda entry: entry["candidateRef"])


def _manifest_from_inventory(
    inventory: dict[str, Any], plan: dict[str, Any], key: bytes
) -> dict[str, Any]:
    if inventory.get("schemaVersion") != SCHEMA_VERSION:
        raise ManifestError("candidate inventory schema version is unsupported")
    plan_issue_id = inventory.get("planIssueId")
    issue_tab_id = inventory.get("issueTabId")
    _validate_issue_pair(plan_issue_id, issue_tab_id, "candidate inventory")
    if inventory.get("discoveryScope") != "whole_issue":
        raise ManifestError("candidate discovery scope must be whole_issue")
    _, plan_rows = _plan_structure(plan, plan_issue_id, key)
    entries = _candidate_entries(inventory, plan_rows, key)
    source_pages_by_row_ref = {
        entry["rowRef"]: entry["sourcePages"]
        for entry in entries
        if entry["disposition"] == "mapped"
    }
    fingerprint, _ = _plan_structure(
        plan,
        plan_issue_id,
        key,
        source_pages_by_row_ref,
    )
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "planIssueId": plan_issue_id,
        "issueTabId": issue_tab_id,
        "discoveryScope": "whole_issue",
        "documentPageCount": inventory["documentPageCount"],
        "hashKeyFingerprint": _key_fingerprint(key),
        "planStructuralFingerprint": fingerprint,
        "planRowCount": len(plan_rows),
        "candidateCount": len(entries),
        "mappedCandidateCount": sum(e["disposition"] == "mapped" for e in entries),
        "exceptionCandidateCount": sum(e["disposition"] == "exception" for e in entries),
        "visuallyInspectedCandidateCount": len(entries),
        "pagesWithCandidates": sorted(
            {page for entry in entries for page in entry["sourcePages"]}
        ),
        "reconciliation": entries,
    }
    return _seal_manifest(manifest, key)


def _write_manifest(manifest: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def build(
    candidates_path: Path, plan_path: Path, output_path: Path, key_path: Path
) -> dict[str, Any]:
    for path, label in (
        (candidates_path, "candidate inventory"),
        (plan_path, "workbook plan"),
        (output_path, "manifest output"),
    ):
        _require_private(path, label)
    _require_distinct_output(output_path, candidates_path, plan_path, key_path)
    inventory = _load_object(candidates_path, "candidate inventory")
    plan = _load_object(plan_path, "workbook plan")
    key = _load_key(key_path)
    manifest = _manifest_from_inventory(inventory, plan, key)
    _write_manifest(manifest, output_path)
    return manifest


def _legacy_pages(value: Any, *, label: str, page_count: int) -> list[int]:
    if not isinstance(value, list):
        raise ManifestError(f"{label} must be a page list")
    pages: list[int] = []
    for page in value:
        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= page_count:
            raise ManifestError(f"{label} contains an invalid page")
        pages.append(page)
    if len(pages) != len(set(pages)):
        raise ManifestError(f"{label} contains duplicate pages")
    return pages


def _legacy_candidate(
    candidate: Any,
    *,
    index: int,
    inspected_pages: set[int],
    page_count: int,
    plan_rows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(candidate, dict) or set(candidate) - LEGACY_CANDIDATE_KEYS:
        raise ManifestError(f"legacy candidate {index} contains unsafe fields")
    required = {
        "page", "rowKind", "sourceId", "reconciliation", "visualInspection",
        "reviewStatus",
    }
    if not required <= set(candidate):
        raise ManifestError(f"legacy candidate {index} is structurally incomplete")
    page = candidate.get("page")
    if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= page_count:
        raise ManifestError(f"legacy candidate {index} has an invalid page")
    if page not in inspected_pages:
        raise ManifestError(f"legacy candidate {index} page is not visually inspected")
    parsed_source_pages = _legacy_pages(
        candidate.get("sourcePages", [page]),
        label=f"legacy candidate {index} sourcePages",
        page_count=page_count,
    )
    if not parsed_source_pages or parsed_source_pages[0] != page:
        raise ManifestError(
            f"legacy candidate {index} source pages must start with its primary page"
        )
    if not set(parsed_source_pages) <= inspected_pages:
        raise ManifestError(f"legacy candidate {index} source pages are not all inspected")
    if candidate.get("reconciliation") != "one_normalized_row":
        raise ManifestError(f"legacy candidate {index} is not mapped one-to-one")
    if candidate.get("visualInspection") != "complete":
        raise ManifestError(f"legacy candidate {index} visual inspection is incomplete")
    if candidate.get("reviewStatus") != "needs_review":
        raise ManifestError(f"legacy candidate {index} has an unsafe review status")
    row_kind = candidate.get("rowKind")
    if row_kind not in LEGACY_ROW_KINDS:
        raise ManifestError(f"legacy candidate {index} has an unsupported row kind")
    source_id = candidate.get("sourceId")
    if not isinstance(source_id, str) or not source_id.strip():
        raise ManifestError(f"legacy candidate {index} lacks an opaque source ID")
    row = plan_rows.get(source_id)
    if row is None:
        raise ManifestError(f"legacy candidate {index} is unmapped in the workbook plan")
    if row.get("page") != page:
        raise ManifestError(f"legacy candidate {index} disagrees with its workbook row page")
    return {
        "candidateId": source_id,
        "page": page,
        "sourcePages": parsed_source_pages,
        "sourceKind": row_kind,
        "disposition": "mapped",
        "rowSourceId": source_id,
        "visuallyInspected": True,
    }


def _legacy_exception(
    exception: Any,
    *,
    index: int,
    inspected_pages: set[int],
    page_count: int,
    owner: str | None,
    reason: str | None,
) -> dict[str, Any]:
    if owner is None or reason is None:
        raise ManifestError(
            "legacy exceptions require --exception-owner and --exception-reason"
        )
    if reason not in EXCEPTION_REASONS:
        raise ManifestError("legacy exception reason is not controlled")
    if not isinstance(exception, dict) or set(exception) - LEGACY_CANDIDATE_KEYS:
        raise ManifestError(f"legacy exception {index} contains unsafe fields")
    page = exception.get("page")
    if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= page_count:
        raise ManifestError(f"legacy exception {index} has an invalid page")
    if page not in inspected_pages or exception.get("visualInspection") != "complete":
        raise ManifestError(f"legacy exception {index} is not visually complete")
    row_kind = exception.get("rowKind")
    if row_kind not in LEGACY_ROW_KINDS:
        raise ManifestError(f"legacy exception {index} has an unsupported row kind")
    source_id = exception.get("sourceId")
    if not isinstance(source_id, str) or not source_id.strip():
        raise ManifestError(f"legacy exception {index} lacks an opaque source ID")
    parsed_source_pages = _legacy_pages(
        exception.get("sourcePages", [page]),
        label=f"legacy exception {index} sourcePages",
        page_count=page_count,
    )
    if not parsed_source_pages or parsed_source_pages[0] != page:
        raise ManifestError(
            f"legacy exception {index} source pages must start with its primary page"
        )
    if not set(parsed_source_pages) <= inspected_pages:
        raise ManifestError(f"legacy exception {index} source pages are not all inspected")
    return {
        "candidateId": source_id,
        "page": page,
        "sourcePages": parsed_source_pages,
        "sourceKind": row_kind,
        "disposition": "exception",
        "exceptionOwner": owner,
        "exceptionReasonCode": reason,
        "visuallyInspected": True,
    }


def migrate_legacy(
    legacy_path: Path,
    plan_path: Path,
    issue_tab_id: str,
    document_page_count: int,
    output_path: Path,
    key_path: Path,
    *,
    exception_owner: str | None = None,
    exception_reason: str | None = None,
) -> dict[str, Any]:
    for path, label in (
        (legacy_path, "legacy manifest"),
        (plan_path, "workbook plan"),
        (output_path, "manifest output"),
    ):
        _require_private(path, label)
    _require_distinct_output(output_path, legacy_path, plan_path, key_path)
    legacy = _load_object(legacy_path, "legacy manifest")
    if set(legacy) != LEGACY_TOP_KEYS:
        raise ManifestError("legacy manifest fields do not match the private schema")
    if legacy.get("private") is not True or legacy.get("sourceTextIncluded") is not False:
        raise ManifestError("legacy manifest is not marked private and source-text-free")
    plan_issue_id = legacy.get("issueId")
    _validate_issue_pair(plan_issue_id, issue_tab_id, "legacy manifest")
    if not isinstance(document_page_count, int) or document_page_count < 1:
        raise ManifestError("document page count must be positive")
    plan = _load_object(plan_path, "workbook plan")
    key = _load_key(key_path)
    _, plan_rows = _plan_structure(plan, plan_issue_id, key)
    inspected = _legacy_pages(
        legacy.get("visuallyInspectedPages"),
        label="legacy visuallyInspectedPages",
        page_count=document_page_count,
    )
    inspected_set = set(inspected)
    raw_candidates = legacy.get("candidates")
    raw_exceptions = legacy.get("exceptions")
    if not isinstance(raw_candidates, list) or not isinstance(raw_exceptions, list):
        raise ManifestError("legacy candidates and exceptions must be lists")
    candidates = [
        _legacy_candidate(
            candidate,
            index=index,
            inspected_pages=inspected_set,
            page_count=document_page_count,
            plan_rows=plan_rows,
        )
        for index, candidate in enumerate(raw_candidates)
    ]
    candidates.extend(
        _legacy_exception(
            exception,
            index=index,
            inspected_pages=inspected_set,
            page_count=document_page_count,
            owner=exception_owner,
            reason=exception_reason,
        )
        for index, exception in enumerate(raw_exceptions)
    )
    inventory = {
        "schemaVersion": SCHEMA_VERSION,
        "planIssueId": plan_issue_id,
        "issueTabId": issue_tab_id,
        "discoveryScope": "whole_issue",
        "documentPageCount": document_page_count,
        "candidates": candidates,
    }
    manifest = _manifest_from_inventory(inventory, plan, key)
    _write_manifest(manifest, output_path)
    return manifest


def validate(
    manifest_path: Path, plan_path: Path | None, key_path: Path
) -> dict[str, Any]:
    _require_private(manifest_path, "manifest")
    manifest = _load_object(manifest_path, "manifest")
    key = _load_key(key_path)
    _verify_manifest_mac(manifest, key)
    if set(manifest) != MANIFEST_KEYS:
        raise ManifestError("manifest fields do not match the redacted schema")
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise ManifestError("manifest schema version is unsupported")
    if manifest.get("hashKeyFingerprint") != _key_fingerprint(key):
        raise ManifestError("manifest HMAC key does not match the manifest")
    plan_issue_id = manifest.get("planIssueId")
    issue_tab_id = manifest.get("issueTabId")
    _validate_issue_pair(plan_issue_id, issue_tab_id, "manifest")
    if manifest.get("discoveryScope") != "whole_issue":
        raise ManifestError("manifest discovery scope must be whole_issue")
    page_count = manifest.get("documentPageCount")
    if not isinstance(page_count, int) or isinstance(page_count, bool) or page_count < 1:
        raise ManifestError("manifest document page count is invalid")
    if not isinstance(manifest.get("planRowCount"), int) or isinstance(
        manifest.get("planRowCount"), bool
    ) or manifest["planRowCount"] < 0:
        raise ManifestError("manifest plan row count is invalid")
    fingerprint = manifest.get("planStructuralFingerprint")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ManifestError("manifest plan fingerprint is invalid")
    entries = manifest.get("reconciliation")
    if not isinstance(entries, list):
        raise ManifestError("manifest reconciliation must be a list")
    if manifest.get("candidateCount") != len(entries):
        raise ManifestError("manifest candidate count is inconsistent")
    mapped = sum(isinstance(e, dict) and e.get("disposition") == "mapped" for e in entries)
    exceptions = sum(
        isinstance(e, dict) and e.get("disposition") == "exception" for e in entries
    )
    if mapped + exceptions != len(entries):
        raise ManifestError("manifest contains invalid dispositions")
    if (
        manifest.get("mappedCandidateCount") != mapped
        or manifest.get("exceptionCandidateCount") != exceptions
    ):
        raise ManifestError("manifest reconciliation counts are inconsistent")
    if manifest.get("visuallyInspectedCandidateCount") != len(entries):
        raise ManifestError("manifest visual inspection count is incomplete")
    refs = [e.get("candidateRef") for e in entries if isinstance(e, dict)]
    if len(refs) != len(set(refs)) or any(
        not isinstance(ref, str) or not HASH_REF.fullmatch(ref) for ref in refs
    ):
        raise ManifestError("manifest candidate references are invalid")
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or entry.get("visuallyInspected") is not True:
            raise ManifestError(f"manifest candidate {index} is not visually inspected")
        if entry.get("sourceKind") not in SOURCE_KINDS:
            raise ManifestError(f"manifest candidate {index} has an invalid source kind")
        page = entry.get("page")
        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= page_count:
            raise ManifestError(f"manifest candidate {index} has an invalid page")
        source_pages = entry.get("sourcePages")
        if (
            not isinstance(source_pages, list)
            or not source_pages
            or source_pages[0] != page
            or any(
                not isinstance(source_page, int)
                or isinstance(source_page, bool)
                or not 1 <= source_page <= page_count
                for source_page in source_pages
            )
            or len(source_pages) != len(set(source_pages))
        ):
            raise ManifestError(f"manifest candidate {index} source pages are invalid")
        if entry.get("disposition") == "mapped":
            if set(entry) != ENTRY_BASE_KEYS | {"rowRef"}:
                raise ManifestError(f"manifest mapped candidate {index} has unsafe fields")
            if not isinstance(entry.get("rowRef"), str) or not HASH_REF.fullmatch(entry["rowRef"]):
                raise ManifestError(f"manifest mapped candidate {index} lacks a row reference")
        elif entry.get("disposition") == "exception":
            if set(entry) != ENTRY_BASE_KEYS | {"exceptionOwnerRef", "exceptionReasonCode"}:
                raise ManifestError(f"manifest exception candidate {index} has unsafe fields")
            if (
                not isinstance(entry.get("exceptionOwnerRef"), str)
                or not HASH_REF.fullmatch(entry["exceptionOwnerRef"])
                or entry.get("exceptionReasonCode") not in EXCEPTION_REASONS
            ):
                raise ManifestError(f"manifest exception candidate {index} is incomplete")
    pages = manifest.get("pagesWithCandidates")
    expected_pages = sorted(
        {page for entry in entries for page in entry["sourcePages"]}
    )
    if pages != expected_pages:
        raise ManifestError("manifest candidate pages are inconsistent")

    plan_verified = False
    if plan_path is not None:
        _require_private(plan_path, "workbook plan")
        plan = _load_object(plan_path, "workbook plan")
        source_pages_by_row_ref = {
            entry["rowRef"]: entry["sourcePages"]
            for entry in entries
            if entry["disposition"] == "mapped"
        }
        fingerprint, plan_rows = _plan_structure(
            plan,
            plan_issue_id,
            key,
            source_pages_by_row_ref,
        )
        if fingerprint != manifest.get("planStructuralFingerprint"):
            raise ManifestError("workbook plan structure does not match the manifest")
        if len(plan_rows) != manifest.get("planRowCount"):
            raise ManifestError("workbook plan row count does not match the manifest")
        row_refs = {
            _hash_ref(key, plan_issue_id, "row", source_id) for source_id in plan_rows
        }
        mapped_refs = [
            e.get("rowRef") for e in entries if e.get("disposition") == "mapped"
        ]
        if len(mapped_refs) != len(set(mapped_refs)) or not set(mapped_refs) <= row_refs:
            raise ManifestError("manifest mapped row references are invalid")
        plan_verified = True
    return {
        "ok": True,
        "planIssueId": plan_issue_id,
        "issueTabId": issue_tab_id,
        "candidateCount": len(entries),
        "mappedCandidateCount": mapped,
        "exceptionCandidateCount": exceptions,
        "visuallyInspectedCandidateCount": len(entries),
        "planVerified": plan_verified,
        "privateValuesEmitted": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    key_parser = subparsers.add_parser(
        "init-key", help="create a private stable HMAC key without overwriting"
    )
    key_parser.add_argument("--key-file", required=True, type=Path)
    build_parser = subparsers.add_parser("build", help="build a redacted manifest")
    build_parser.add_argument("--candidates", required=True, type=Path)
    build_parser.add_argument("--plan", required=True, type=Path)
    build_parser.add_argument("--output", required=True, type=Path)
    build_parser.add_argument("--key-file", required=True, type=Path)
    migrate_parser = subparsers.add_parser(
        "migrate-legacy", help="migrate a source-text-free legacy manifest"
    )
    migrate_parser.add_argument("--legacy-manifest", required=True, type=Path)
    migrate_parser.add_argument("--plan", required=True, type=Path)
    migrate_parser.add_argument("--issue-tab-id", required=True)
    migrate_parser.add_argument("--document-page-count", required=True, type=int)
    migrate_parser.add_argument("--output", required=True, type=Path)
    migrate_parser.add_argument("--key-file", required=True, type=Path)
    migrate_parser.add_argument("--exception-owner")
    migrate_parser.add_argument("--exception-reason", choices=sorted(EXCEPTION_REASONS))
    validate_parser = subparsers.add_parser("validate", help="validate a manifest")
    validate_parser.add_argument("manifest", type=Path)
    validate_parser.add_argument("--plan", type=Path)
    validate_parser.add_argument("--key-file", required=True, type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "init-key":
            fingerprint = initialize_key(args.key_file)
            print(json.dumps({"ok": True, "keyFingerprint": fingerprint}, sort_keys=True))
            return 0
        if args.command == "build":
            manifest = build(args.candidates, args.plan, args.output, args.key_file)
        elif args.command == "migrate-legacy":
            manifest = migrate_legacy(
                args.legacy_manifest,
                args.plan,
                args.issue_tab_id,
                args.document_page_count,
                args.output,
                args.key_file,
                exception_owner=args.exception_owner,
                exception_reason=args.exception_reason,
            )
        else:
            manifest = None
        if manifest is not None:
            summary = {
                "ok": True,
                "planIssueId": manifest["planIssueId"],
                "issueTabId": manifest["issueTabId"],
                "candidateCount": manifest["candidateCount"],
                "mappedCandidateCount": manifest["mappedCandidateCount"],
                "exceptionCandidateCount": manifest["exceptionCandidateCount"],
                "visuallyInspectedCandidateCount": manifest[
                    "visuallyInspectedCandidateCount"
                ],
                "privateValuesEmitted": False,
            }
        else:
            summary = validate(args.manifest, args.plan, args.key_file)
    except ManifestError as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
