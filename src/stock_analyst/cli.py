"""Command-line entrypoint for local prototype operations."""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from stock_analyst.chart_check import extract_chart_check_rows_from_page_lines
from stock_analyst.corpus import build_local_corpus_status
from stock_analyst.dividend_strategy import build_dividend_strategy_from_pdf
from stock_analyst.google_access import (
    GoogleAccessError,
    bootstrap_google_sheet,
    build_drive_pdf_metadata_result,
    clear_google_sheet_data_rows,
    load_env_file,
    load_google_access_config,
    preflight_workbook_plan_google_sheet_export,
    redact_google_identifier,
    refresh_google_sheet_search,
    run_google_access_smoke,
    write_refinement_plan_to_google_sheet,
    write_drive_pdf_metadata_manifest,
    write_insider_activity_rows_to_google_sheet,
    write_workbook_plan_to_google_sheet,
)
from stock_analyst.intake import (
    BatchPdfIntakeItem,
    IntakeError,
    import_pdf_folder,
    preview_pdf_intake,
    store_pdf_upload,
)
from stock_analyst.market_data import (
    DEFAULT_PROVIDER_ENDPOINTS,
    MarketDataEnrichmentPlan,
    MarketDataPlanningConfig,
    build_market_data_symbol_map_template_csv,
    load_market_data_budget_state,
    load_market_data_symbol_map_file,
    load_market_data_symbol_file,
    load_market_data_planning_config,
    market_data_candidates_from_workbook_plan,
    market_data_candidates_from_symbol_map_template_csv,
    plan_market_data_enrichment_requests,
    ready_market_data_symbols_from_workbook_candidates,
)
from stock_analyst.ocr_fixtures import build_ocr_fixture_review_plan
from stock_analyst.ocr_needed import build_ocr_needed_report_from_manifest
from stock_analyst.pipeline import (
    PdfProcessingError,
    build_draft_review_status,
    calculate_processing_steps,
)
from stock_analyst.quality_report import build_extraction_quality_report
from stock_analyst.quickcheck import extract_quickcheck_rows_from_page_lines
from stock_analyst.refinement import build_refinement_plan_from_pdf
from stock_analyst.refinement_summary import build_corpus_refinement_summary
from stock_analyst.recommendation_cards import extract_recommendation_cards_from_pdf
from stock_analyst.review_approvals import (
    apply_workbook_approvals,
    load_workbook_approvals_csv,
    write_approval_template_csv,
    write_reviewed_workbook_plan,
)
from stock_analyst.review_queue import build_review_queue_from_manifest
from stock_analyst.sec_insider import (
    SecStockCandidate,
    enrich_sec_form4,
    load_sec_insider_config,
)
from stock_analyst.section_inventory import build_section_inventory_from_pdf
from stock_analyst.visual_ocr import build_visual_ocr_bundle, parse_page_selection
from stock_analyst.workbook_export import build_workbook_export_plan_from_pdf


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stock-analyst")
    subcommands = parser.add_subparsers(dest="command", required=True)

    process_pdf = subcommands.add_parser(
        "process-pdf",
        help="Validate a PDF and show the local processing plan.",
    )
    process_pdf.add_argument("pdf", type=Path)
    process_pdf.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate only. Do not copy, OCR, extract, or export.",
    )
    process_pdf.add_argument(
        "--upload-dir",
        type=Path,
        default=Path("data/uploads"),
        help="Private local upload directory used when --dry-run is not set.",
    )

    import_folder = subcommands.add_parser(
        "import-pdf-folder",
        help="Batch validate or store PDFs from a local folder.",
    )
    import_folder.add_argument("folder", type=Path)
    import_folder.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate only. Do not copy files or write the manifest.",
    )
    import_folder.add_argument(
        "--recursive",
        action="store_true",
        help="Include PDFs in nested folders.",
    )
    import_folder.add_argument(
        "--upload-dir",
        type=Path,
        default=Path("data/uploads"),
        help="Private local upload directory used when --dry-run is not set.",
    )
    import_folder.add_argument(
        "--manifest-name",
        default="uploads.jsonl",
        help="Manifest filename inside the upload directory.",
    )

    corpus_status = subcommands.add_parser(
        "corpus-status",
        help="Report metadata-only readiness for local DA_YYYY_NN.pdf issues.",
    )
    corpus_status.add_argument(
        "folder",
        type=Path,
        nargs="?",
        default=Path("data/private/issues"),
        help="Local private issues folder to scan. Defaults to data/private/issues.",
    )

    corpus_refinement_summary = subcommands.add_parser(
        "corpus-refinement-summary",
        help="Summarize page classification coverage across local issues without source text.",
    )
    corpus_refinement_summary.add_argument(
        "folder",
        type=Path,
        nargs="?",
        default=Path("data/private/issues"),
        help="Local private issues folder to scan. Defaults to data/private/issues.",
    )
    corpus_refinement_summary.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of matched issues processed from oldest to newest.",
    )
    corpus_refinement_summary.add_argument(
        "--min-embedded-chars",
        type=int,
        default=40,
        help="Minimum trimmed embedded characters required before OCR is not queued.",
    )

    quality_report = subcommands.add_parser(
        "extraction-quality-report",
        help="Summarize local embedded-text extraction quality for imported PDFs.",
    )
    quality_report.add_argument(
        "manifest",
        type=Path,
        help="Local JSONL upload manifest created by import-pdf-folder.",
    )
    quality_report.add_argument(
        "--upload-dir",
        type=Path,
        default=None,
        help="Private local upload directory. Defaults to the manifest parent.",
    )
    quality_report.add_argument(
        "--min-embedded-chars",
        type=int,
        default=40,
        help="Minimum trimmed embedded characters required before OCR is not queued.",
    )

    review_queue = subcommands.add_parser(
        "review-queue",
        help="List local draft-review and reprocess-needed actions from an upload manifest.",
    )
    review_queue.add_argument(
        "manifest",
        type=Path,
        help="Local JSONL upload manifest created by import-pdf-folder.",
    )
    review_queue.add_argument(
        "--upload-dir",
        type=Path,
        default=None,
        help="Private local upload directory. Defaults to the manifest parent.",
    )
    review_queue.add_argument(
        "--min-embedded-chars",
        type=int,
        default=40,
        help="Minimum trimmed embedded characters required before OCR is not queued.",
    )

    ocr_needed = subcommands.add_parser(
        "ocr-needed",
        help="List imported PDF pages that need local OCR before draft review.",
    )
    ocr_needed.add_argument(
        "manifest",
        type=Path,
        help="Local JSONL upload manifest created by import-pdf-folder.",
    )
    ocr_needed.add_argument(
        "--upload-dir",
        type=Path,
        default=None,
        help="Private local upload directory. Defaults to the manifest parent.",
    )
    ocr_needed.add_argument(
        "--min-embedded-chars",
        type=int,
        default=40,
        help="Minimum trimmed embedded characters required before OCR is not queued.",
    )
    ocr_needed.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/private/visual-ocr"),
        help="Private output directory to use in suggested local OCR commands.",
    )

    recommendation_cards = subcommands.add_parser(
        "recommendation-cards",
        help="Extract local draft recommendation cards from embedded PDF text.",
    )
    recommendation_cards.add_argument("pdf", type=Path)
    recommendation_cards.add_argument(
        "--issue-id",
        default=None,
        help="Override issue ID. Defaults to DA_YYYY_week filename parsing.",
    )
    recommendation_cards.add_argument(
        "--min-embedded-chars",
        type=int,
        default=40,
        help="Minimum trimmed embedded characters required before OCR is not queued.",
    )

    section_inventory = subcommands.add_parser(
        "section-inventory",
        help="Find important table and section surfaces from embedded PDF text.",
    )
    section_inventory.add_argument("pdf", type=Path)
    section_inventory.add_argument(
        "--issue-id",
        default=None,
        help="Override issue ID. Defaults to DA_YYYY_week filename parsing.",
    )
    section_inventory.add_argument(
        "--min-embedded-chars",
        type=int,
        default=40,
        help="Minimum trimmed embedded characters required before OCR is not queued.",
    )

    dividend_strategy = subcommands.add_parser(
        "dividend-strategy",
        help="Extract local draft dividend strategy rows from embedded PDF text.",
    )
    dividend_strategy.add_argument("pdf", type=Path)
    dividend_strategy.add_argument(
        "--issue-id",
        default=None,
        help="Override issue ID. Defaults to DA_YYYY_week filename parsing.",
    )
    dividend_strategy.add_argument(
        "--min-embedded-chars",
        type=int,
        default=40,
        help="Minimum trimmed embedded characters required before OCR is not queued.",
    )

    quick_check = subcommands.add_parser(
        "quick-check",
        help="Extract local draft Aktien im Quick-Check rows from embedded PDF text.",
    )
    quick_check.add_argument("pdf", type=Path)
    quick_check.add_argument(
        "--issue-id",
        default=None,
        help="Override issue ID. Defaults to DA_YYYY_week filename parsing.",
    )
    quick_check.add_argument(
        "--min-embedded-chars",
        type=int,
        default=40,
        help="Minimum trimmed embedded characters required before OCR is not queued.",
    )

    chart_check = subcommands.add_parser(
        "chart-check",
        help="Extract local draft Chart-Check rows from embedded PDF text.",
    )
    chart_check.add_argument("pdf", type=Path)
    chart_check.add_argument(
        "--issue-id",
        default=None,
        help="Override issue ID. Defaults to DA_YYYY_week filename parsing.",
    )
    chart_check.add_argument(
        "--min-embedded-chars",
        type=int,
        default=40,
        help="Minimum trimmed embedded characters required before OCR is not queued.",
    )

    workbook_export_plan = subcommands.add_parser(
        "workbook-export-plan",
        help="Build a local dry-run Google Sheets row plan without writing to Sheets.",
    )
    workbook_export_plan.add_argument("pdf", type=Path)
    workbook_export_plan.add_argument(
        "--issue-id",
        default=None,
        help="Override issue ID. Defaults to DA_YYYY_week filename parsing.",
    )
    workbook_export_plan.add_argument(
        "--min-embedded-chars",
        type=int,
        default=40,
        help="Minimum trimmed embedded characters required before OCR is not queued.",
    )

    refinement_plan = subcommands.add_parser(
        "refinement-plan",
        help="Build a page-by-page refinement classification plan without writing to Sheets.",
    )
    refinement_plan.add_argument("pdf", type=Path)
    refinement_plan.add_argument(
        "--issue-id",
        default=None,
        help="Override issue ID. Defaults to DA_YYYY_week filename parsing.",
    )
    refinement_plan.add_argument(
        "--min-embedded-chars",
        type=int,
        default=40,
        help="Minimum trimmed embedded characters required before OCR is not queued.",
    )

    visual_ocr = subcommands.add_parser(
        "visual-ocr-review",
        help="Plan or run local page rendering/OCR for private visual review.",
    )
    visual_ocr.add_argument("pdf", type=Path)
    visual_ocr.add_argument(
        "--page",
        type=int,
        action="append",
        default=[],
        help="1-based page number to review. Repeat for multiple pages.",
    )
    visual_ocr.add_argument(
        "--pages",
        default=None,
        help="Comma-separated 1-based pages/ranges to review, for example 22,62-63.",
    )
    visual_ocr.add_argument(
        "--render",
        action="store_true",
        help="Accepted for clarity; selected pages are rendered by this command.",
    )
    visual_ocr.add_argument(
        "--ocr",
        action="store_true",
        help="Run local Tesseract OCR against rendered page images.",
    )
    visual_ocr.add_argument(
        "--write-ocr-text",
        action="store_true",
        help="Write OCR text to private output files; result only reports path/hash/count.",
    )
    visual_ocr.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/private/visual-ocr"),
        help="Private output directory for rendered pages and optional OCR text.",
    )
    visual_ocr.add_argument(
        "--dpi",
        type=int,
        default=180,
        help="Render DPI for page images.",
    )
    visual_ocr.add_argument(
        "--ocr-language",
        default="deu+eng",
        help="Tesseract language string used with --ocr.",
    )

    ocr_fixture_plan = subcommands.add_parser(
        "ocr-fixture-plan",
        help="Review metadata-only OCR/page fixture coverage and local artifacts.",
    )
    ocr_fixture_plan.add_argument(
        "--issue-id",
        default=None,
        help="Issue ID to review. Defaults to the fixture manifest/default issue.",
    )
    ocr_fixture_plan.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="Optional private PDF path used only for checksum and artifact path matching.",
    )
    ocr_fixture_plan.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path("data/private/visual-ocr"),
        help="Private local visual-ocr artifact directory to inspect for hashes/counts.",
    )
    ocr_fixture_plan.add_argument(
        "--fixture-manifest",
        type=Path,
        default=None,
        help="Optional metadata-only JSON fixture manifest. Must not contain OCR text.",
    )

    market_data_plan = subcommands.add_parser(
        "market-data-plan",
        help="Build a dry-run market-data enrichment request and budget plan.",
    )
    market_data_plan.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional local env file with market-data config. Do not commit it.",
    )
    market_data_plan.add_argument(
        "--symbol",
        action="append",
        default=[],
        help="Ticker symbol to include. Repeat for multiple symbols.",
    )
    market_data_plan.add_argument(
        "--symbol-file",
        type=Path,
        action="append",
        default=[],
        help=(
            "Optional private text file with one ticker per line, or comma-separated "
            "tickers. Blank lines and # comments are ignored."
        ),
    )
    market_data_plan.add_argument(
        "--workbook-plan-file",
        type=Path,
        default=None,
        help=(
            "Preferred source for enrichment planning. Read a JSON workbook-export-plan "
            "and only plan symbols mapped from magazine-backed workbook rows."
        ),
    )
    market_data_plan.add_argument(
        "--symbol-map-file",
        type=Path,
        default=None,
        help=(
            "Private CSV mapping workbook rows to provider symbols. Columns: "
            "source_id,wkn,name,symbol."
        ),
    )
    market_data_plan.add_argument(
        "--endpoint",
        action="append",
        default=None,
        help=(
            "Dry-run endpoint to plan. Defaults depend on "
            "STOCK_ANALYST_MARKET_DATA_PROVIDER."
        ),
    )

    market_symbol_map_template = subcommands.add_parser(
        "market-symbol-map-template",
        help="Create or refresh a private provider-symbol mapping CSV from workbook rows.",
    )
    market_symbol_map_template.add_argument(
        "--workbook-plan-file",
        type=Path,
        required=True,
        help="JSON workbook-export-plan produced from magazine extraction.",
    )
    market_symbol_map_template.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Private CSV path to write. Existing symbols are preserved.",
    )

    google_access_smoke = subcommands.add_parser(
        "google-access-smoke",
        help="Check configured Google Drive folder and Sheets access.",
    )
    google_access_smoke.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional local env file with GOOGLE_* config. Do not commit it.",
    )

    google_drive_pdfs = subcommands.add_parser(
        "google-drive-pdfs",
        help="List configured Drive folder PDF metadata without downloading files.",
    )
    google_drive_pdfs.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional local env file with GOOGLE_* config. Do not commit it.",
    )
    google_drive_pdfs.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Drive API page size for listing PDF metadata.",
    )
    google_drive_pdfs.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Optional private local JSONL path for metadata-only Drive import rows.",
    )
    google_drive_pdfs.add_argument(
        "--include-private-identifiers",
        action="store_true",
        help="Include raw Drive identifiers in stdout. Use only for local debugging.",
    )

    google_sheets_bootstrap = subcommands.add_parser(
        "google-sheets-bootstrap",
        help="Create missing workbook tabs and write stable header rows.",
    )
    google_sheets_bootstrap.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional local env file with GOOGLE_* config. Do not commit it.",
    )
    google_sheets_bootstrap.add_argument(
        "--skip-headers",
        action="store_true",
        help="Create missing tabs without writing header rows.",
    )

    google_sheets_clear_data = subcommands.add_parser(
        "google-sheets-clear-data",
        help="Clear configured workbook data rows while preserving tab headers.",
    )
    google_sheets_clear_data.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional local env file with GOOGLE_* config. Do not commit it.",
    )
    google_sheets_clear_data.add_argument(
        "--skip-headers",
        action="store_true",
        help="Clear data rows without rewriting header rows.",
    )

    google_sheets_refresh_search = subcommands.add_parser(
        "google-sheets-refresh-search",
        help="Prune retired generated tabs and rebuild issue-only company/WKN search.",
    )
    google_sheets_refresh_search.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional local env file with GOOGLE_* config. Do not commit it.",
    )

    google_sheets_export_plan = subcommands.add_parser(
        "google-sheets-export-plan",
        help="Write approved workbook-plan rows into the configured Sheet.",
    )
    google_sheets_export_plan.add_argument(
        "workbook_plan_file",
        type=Path,
        help="JSON workbook-export-plan produced from local magazine extraction.",
    )
    google_sheets_export_plan.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional local env file with GOOGLE_* config. Do not commit it.",
    )
    google_sheets_export_plan.add_argument(
        "--append",
        action="store_true",
        help="Append rows instead of replacing existing rows for the same issue.",
    )
    google_sheets_export_plan.add_argument(
        "--allow-draft-rows",
        action="store_true",
        help="Opt in to writing unapproved reviewer-draft rows to the private workbook.",
    )

    workbook_approval_template = subcommands.add_parser(
        "workbook-approval-template",
        help="Write a private CSV template for reviewer approval decisions.",
    )
    workbook_approval_template.add_argument(
        "workbook_plan_file",
        type=Path,
        help="JSON workbook-export-plan produced from local magazine extraction.",
    )
    workbook_approval_template.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Private CSV output path such as data/private/review/approvals.csv.",
    )

    workbook_approval_audit = subcommands.add_parser(
        "workbook-approval-audit",
        help="Apply private reviewer approvals to an exact workbook-export-plan.",
    )
    workbook_approval_audit.add_argument(
        "workbook_plan_file",
        type=Path,
        help="JSON workbook-export-plan produced from local magazine extraction.",
    )
    workbook_approval_audit.add_argument(
        "--approval-csv",
        type=Path,
        required=True,
        help="Private reviewer approval CSV generated from workbook-approval-template.",
    )
    workbook_approval_audit.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Private reviewed workbook-plan JSON output path.",
    )

    google_sheets_refinement = subcommands.add_parser(
        "google-sheets-refinement",
        help="Create/populate the Refinement tab from a local PDF page map.",
    )
    google_sheets_refinement.add_argument("pdf", type=Path)
    google_sheets_refinement.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional local env file with GOOGLE_* config. Do not commit it.",
    )
    google_sheets_refinement.add_argument(
        "--issue-id",
        default=None,
        help="Override issue ID. Defaults to DA_YYYY_week filename parsing.",
    )
    google_sheets_refinement.add_argument(
        "--min-embedded-chars",
        type=int,
        default=40,
        help="Minimum trimmed embedded characters required before OCR is not queued.",
    )

    return parser


def run_process_pdf(
    pdf_path: Path,
    *,
    dry_run: bool,
    upload_dir: Path = Path("data/uploads"),
) -> dict[str, object]:
    intake = preview_pdf_intake(pdf_path)
    storage: dict[str, object] = {"stored": False}

    if not dry_run:
        stored = store_pdf_upload(pdf_path, upload_dir)
        storage = {
            "stored": True,
            "duplicate": stored.duplicate,
            "status": stored.status,
            "storedPath": str(stored.stored_path),
            "manifestPath": str(stored.manifest_path),
        }
        processing_status = build_draft_review_status(upload_status=stored.status)
    else:
        processing_status = {
            "stage": "intake",
            "status": "dry_run",
            "readyForDraftReview": False,
            "message": "Validated only; no file was copied or extracted.",
        }

    return {
        "dryRun": dry_run,
        "filename": intake.filename,
        "checksumSha256": intake.checksum_sha256,
        "sizeBytes": intake.size_bytes,
        "sourcePdfId": intake.source_pdf_id,
        "issueDateGuess": intake.issue_date_guess,
        "status": intake.status,
        "processingStatus": processing_status,
        "storage": storage,
        "steps": calculate_processing_steps(pdf_path),
    }


def _batch_item_to_dict(item: BatchPdfIntakeItem) -> dict[str, object]:
    result: dict[str, object] = {
        "filename": item.filename,
        "path": str(item.path),
        "status": item.status,
    }

    if item.checksum_sha256 is not None:
        result["checksumSha256"] = item.checksum_sha256
    if item.source_pdf_id is not None:
        result["sourcePdfId"] = item.source_pdf_id
    if item.issue_date_guess is not None:
        result["issueDateGuess"] = item.issue_date_guess
    if item.size_bytes is not None:
        result["sizeBytes"] = item.size_bytes
    if item.stored_path is not None:
        result["storedPath"] = str(item.stored_path)
    if item.manifest_path is not None:
        result["manifestPath"] = str(item.manifest_path)
    if item.error is not None:
        result["error"] = item.error

    return result


def run_import_pdf_folder(
    folder: Path,
    *,
    dry_run: bool,
    recursive: bool,
    upload_dir: Path = Path("data/uploads"),
    manifest_name: str = "uploads.jsonl",
) -> dict[str, object]:
    batch = import_pdf_folder(
        folder,
        upload_dir,
        dry_run=dry_run,
        recursive=recursive,
        manifest_name=manifest_name,
    )

    return {
        "dryRun": batch.dry_run,
        "recursive": batch.recursive,
        "sourceDir": str(batch.source_dir),
        "uploadDir": str(batch.upload_dir),
        "manifestPath": str(batch.manifest_path),
        "totalPdfCandidates": batch.total_pdf_candidates,
        "uploadedCount": batch.uploaded_count,
        "duplicateCount": batch.duplicate_count,
        "invalidCount": batch.invalid_count,
        "dryRunValidCount": batch.dry_run_valid_count,
        "externalServicesEnabled": False,
        "items": [_batch_item_to_dict(item) for item in batch.items],
    }


def run_corpus_status(folder: Path = Path("data/private/issues")) -> dict[str, object]:
    status = build_local_corpus_status(folder)
    return status.to_dict()


def run_corpus_refinement_summary(
    folder: Path = Path("data/private/issues"),
    *,
    limit: int | None = None,
    min_embedded_chars: int = 40,
) -> dict[str, object]:
    current_utc_date = datetime.now(timezone.utc).date()
    summary = build_corpus_refinement_summary(
        folder,
        limit=limit,
        min_embedded_chars=min_embedded_chars,
        current_utc_date=current_utc_date,
    )
    return summary.to_dict()


def run_extraction_quality_report(
    manifest_path: Path,
    *,
    upload_dir: Path | None = None,
    min_embedded_chars: int = 40,
) -> dict[str, object]:
    report = build_extraction_quality_report(
        manifest_path,
        upload_dir=upload_dir,
        min_embedded_chars=min_embedded_chars,
    )
    return report.to_dict()


def run_review_queue(
    manifest_path: Path,
    *,
    upload_dir: Path | None = None,
    min_embedded_chars: int = 40,
) -> dict[str, object]:
    queue = build_review_queue_from_manifest(
        manifest_path,
        upload_dir=upload_dir,
        min_embedded_chars=min_embedded_chars,
    )
    return queue.to_dict()


def run_ocr_needed(
    manifest_path: Path,
    *,
    upload_dir: Path | None = None,
    min_embedded_chars: int = 40,
    output_dir: Path = Path("data/private/visual-ocr"),
) -> dict[str, object]:
    report = build_ocr_needed_report_from_manifest(
        manifest_path,
        upload_dir=upload_dir,
        min_embedded_chars=min_embedded_chars,
        output_dir=output_dir,
    )
    return report.to_dict()


def run_recommendation_cards(
    pdf_path: Path,
    *,
    issue_id: str | None = None,
    min_embedded_chars: int = 40,
) -> dict[str, object]:
    cards = extract_recommendation_cards_from_pdf(
        pdf_path,
        issue_id=issue_id,
        min_embedded_chars=min_embedded_chars,
    )
    return cards.to_dict()


def run_section_inventory(
    pdf_path: Path,
    *,
    issue_id: str | None = None,
    min_embedded_chars: int = 40,
) -> dict[str, object]:
    inventory = build_section_inventory_from_pdf(
        pdf_path,
        issue_id=issue_id,
        min_embedded_chars=min_embedded_chars,
    )
    return inventory.to_dict()


def run_dividend_strategy(
    pdf_path: Path,
    *,
    issue_id: str | None = None,
    min_embedded_chars: int = 40,
) -> dict[str, object]:
    extraction = build_dividend_strategy_from_pdf(
        pdf_path,
        issue_id=issue_id,
        min_embedded_chars=min_embedded_chars,
    )
    return extraction.to_dict()


def run_quick_check(
    pdf_path: Path,
    *,
    issue_id: str | None = None,
    min_embedded_chars: int = 40,
) -> dict[str, object]:
    from stock_analyst.extraction import extract_pdf_text
    from stock_analyst.workbook_export import _issue_id_from_filename

    extraction = extract_pdf_text(pdf_path, min_embedded_chars=min_embedded_chars)
    resolved_issue_id = issue_id or _issue_id_from_filename(pdf_path)
    rows = extract_quickcheck_rows_from_page_lines(
        tuple((page.page_number, page.text.splitlines()) for page in extraction.pages),
        issue_id=resolved_issue_id,
    )
    return {
        "issueId": resolved_issue_id,
        "pdfPath": str(pdf_path),
        "pageCount": extraction.page_count,
        "externalServicesEnabled": False,
        "rows": [row.to_dict() for row in rows],
    }


def run_chart_check(
    pdf_path: Path,
    *,
    issue_id: str | None = None,
    min_embedded_chars: int = 40,
) -> dict[str, object]:
    from stock_analyst.extraction import extract_pdf_text
    from stock_analyst.workbook_export import _issue_id_from_filename

    extraction = extract_pdf_text(pdf_path, min_embedded_chars=min_embedded_chars)
    resolved_issue_id = issue_id or _issue_id_from_filename(pdf_path)
    rows = extract_chart_check_rows_from_page_lines(
        tuple((page.page_number, page.text.splitlines()) for page in extraction.pages),
        issue_id=resolved_issue_id,
    )
    return {
        "issueId": resolved_issue_id,
        "pdfPath": str(pdf_path),
        "pageCount": extraction.page_count,
        "externalServicesEnabled": False,
        "rows": [row.to_dict() for row in rows],
    }


def run_workbook_export_plan(
    pdf_path: Path,
    *,
    issue_id: str | None = None,
    min_embedded_chars: int = 40,
) -> dict[str, object]:
    current_utc_date = datetime.now(timezone.utc).date()
    plan = build_workbook_export_plan_from_pdf(
        pdf_path,
        issue_id=issue_id,
        min_embedded_chars=min_embedded_chars,
        current_utc_date=current_utc_date,
    )
    return plan.to_dict()


def run_refinement_plan(
    pdf_path: Path,
    *,
    issue_id: str | None = None,
    min_embedded_chars: int = 40,
) -> dict[str, object]:
    current_utc_date = datetime.now(timezone.utc).date()
    plan = build_refinement_plan_from_pdf(
        pdf_path,
        issue_id=issue_id,
        min_embedded_chars=min_embedded_chars,
        current_utc_date=current_utc_date,
    )
    return plan.to_dict()


def run_visual_ocr_review(
    pdf_path: Path,
    *,
    pages: tuple[int, ...] | None = None,
    ocr: bool = False,
    write_ocr_text: bool = False,
    output_dir: Path = Path("data/private/visual-ocr"),
    dpi: int = 180,
    ocr_language: str = "deu+eng",
) -> dict[str, object]:
    bundle = build_visual_ocr_bundle(
        pdf_path,
        pages=pages,
        run_ocr=ocr,
        write_ocr_text=write_ocr_text,
        output_dir=output_dir,
        dpi=dpi,
        ocr_language=ocr_language,
    )
    return bundle.to_dict()


def run_ocr_fixture_plan_command(
    *,
    issue_id: str | None = None,
    pdf_path: Path | None = None,
    artifact_dir: Path | None = Path("data/private/visual-ocr"),
    fixture_manifest: Path | None = None,
) -> dict[str, object]:
    plan = build_ocr_fixture_review_plan(
        issue_id=issue_id,
        pdf_path=pdf_path,
        artifact_dir=artifact_dir,
        fixture_manifest=fixture_manifest,
    )
    return plan.to_dict()


def run_market_data_plan_command(
    *,
    env_file: Path | None = None,
    symbols: tuple[str, ...] = (),
    symbol_files: tuple[Path, ...] = (),
    workbook_plan_file: Path | None = None,
    symbol_map_file: Path | None = None,
    endpoints: tuple[str, ...] | None = None,
) -> dict[str, object]:
    config = load_market_data_planning_config(
        env_file=env_file,
        default_provider="disabled",
    )
    provider_id = config.provider_config.provider.provider_id

    all_symbols = list(symbols)
    for symbol_file in symbol_files:
        all_symbols.extend(load_market_data_symbol_file(symbol_file))

    source_mode = "manual_symbols" if all_symbols else "empty"
    workbook_candidates = ()
    if workbook_plan_file is not None:
        symbol_map = (
            load_market_data_symbol_map_file(symbol_map_file)
            if symbol_map_file is not None
            else {}
        )
        payload = json.loads(workbook_plan_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"workbook plan file is not a JSON object: {workbook_plan_file}")
        workbook_candidates = market_data_candidates_from_workbook_plan(
            payload,
            symbol_map=symbol_map,
        )
        all_symbols.extend(ready_market_data_symbols_from_workbook_candidates(workbook_candidates))
        source_mode = "mixed" if symbols or symbol_files else "workbook_plan"

    budget_date = datetime.now(timezone.utc).date()
    budget_state = load_market_data_budget_state(
        provider=provider_id,
        budget_date=budget_date,
        daily_call_limit=config.daily_call_limit,
        budget_root=config.budget_dir,
    )
    plan = plan_market_data_enrichment_requests(
        provider_id,
        tuple(all_symbols),
        endpoints=endpoints or DEFAULT_PROVIDER_ENDPOINTS.get(provider_id),
        cache_root=config.cache_dir,
        daily_call_limit=config.daily_call_limit,
        prior_charged_call_count=budget_state.charged_call_count,
        terms_version=config.terms_version,
    )
    return _market_data_plan_to_dict(
        plan,
        config,
        budget_date=budget_date.isoformat(),
        source_mode=source_mode,
        workbook_candidates=workbook_candidates,
    )


def run_market_symbol_map_template_command(
    *,
    workbook_plan_file: Path,
    output: Path,
) -> dict[str, object]:
    payload = json.loads(workbook_plan_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"workbook plan file is not a JSON object: {workbook_plan_file}")
    existing_csv_text = output.read_text(encoding="utf-8") if output.exists() else ""
    csv_text = build_market_data_symbol_map_template_csv(
        payload,
        existing_csv_text=existing_csv_text,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(csv_text, encoding="utf-8")
    rows = list(csv.DictReader(StringIO(csv_text)))
    mapped_count = len([row for row in rows if (row.get("symbol") or "").strip()])
    return {
        "output": str(output),
        "rowCount": len(rows),
        "mappedCount": mapped_count,
        "needsLookupCount": len(rows) - mapped_count,
        "externalServicesEnabled": False,
        "networkAccess": False,
        "preservedExistingSymbols": True,
    }


def run_google_access_smoke_command(
    *,
    env_file: Path | None = None,
) -> dict[str, object]:
    config = load_google_access_config(env_file=env_file)
    return run_google_access_smoke(config)


def _is_private_manifest_path(path: Path) -> bool:
    return "private" in {part.lower() for part in path.expanduser().parts}


def _validate_private_output_path(path: Path, *, artifact_name: str) -> None:
    if not _is_private_manifest_path(path):
        raise ValueError(
            f"{artifact_name} must be written under a private path such as "
            "data/private/review/artifact"
        )


def _validate_private_drive_manifest_path(path: Path) -> None:
    if not _is_private_manifest_path(path):
        raise ValueError(
            "Drive manifests with private identifiers must be written under a private path "
            "such as data/private/drive/pdf-metadata.jsonl"
        )


def _redact_drive_pdf_metadata_command_result(result: dict[str, object]) -> dict[str, object]:
    redacted = dict(result)

    if "driveFolderId" in redacted:
        redacted["driveFolderId"] = redact_google_identifier(redacted["driveFolderId"])

    redacted_files: list[object] = []
    for item in result.get("files", []):
        if not isinstance(item, dict):
            redacted_files.append(item)
            continue

        redacted_file = dict(item)
        if "driveFileId" in redacted_file:
            redacted_file["driveFileId"] = redact_google_identifier(redacted_file["driveFileId"])
        if "webViewLink" in redacted_file:
            redacted_file["webViewLink"] = redact_google_identifier(redacted_file["webViewLink"])
        redacted_files.append(redacted_file)

    if "files" in redacted:
        redacted["files"] = redacted_files

    return redacted


def run_google_drive_pdfs_command(
    *,
    env_file: Path | None = None,
    page_size: int = 100,
    manifest: Path | None = None,
    include_private_identifiers: bool = False,
) -> dict[str, object]:
    if include_private_identifiers and manifest is None:
        raise ValueError(
            "Drive metadata with private identifiers must be written to a private manifest path"
        )
    if include_private_identifiers and manifest is not None:
        _validate_private_drive_manifest_path(manifest)

    config = load_google_access_config(env_file=env_file)
    result = build_drive_pdf_metadata_result(
        config,
        page_size=page_size,
        include_private_identifiers=include_private_identifiers,
    )
    if manifest is not None:
        write_drive_pdf_metadata_manifest(result, manifest)
        command_result = dict(result)
        command_result["manifestPath"] = str(manifest)
        if include_private_identifiers:
            command_result = _redact_drive_pdf_metadata_command_result(command_result)
            command_result["manifestPath"] = str(manifest)
            command_result["privateIdentifiersWritten"] = True
        return command_result
    return result


def run_google_sheets_bootstrap_command(
    *,
    env_file: Path | None = None,
    write_headers: bool = True,
) -> dict[str, object]:
    config = load_google_access_config(env_file=env_file)
    return bootstrap_google_sheet(config, write_headers=write_headers)


def run_google_sheets_clear_data_command(
    *,
    env_file: Path | None = None,
    write_headers: bool = True,
) -> dict[str, object]:
    config = load_google_access_config(env_file=env_file)
    return clear_google_sheet_data_rows(config, write_headers=write_headers)


def run_google_sheets_refresh_search_command(
    *,
    env_file: Path | None = None,
) -> dict[str, object]:
    config = load_google_access_config(env_file=env_file)
    return refresh_google_sheet_search(config)


def _mark_insider_review_required(sheet_result: dict[str, object]) -> None:
    """Downgrade a combined Sheet result that exposes unapproved insider context."""

    sheet_result["exportMode"] = "private_draft_review_export"
    sheet_result["familyVisibleSafe"] = False
    sheet_result["privateDraftReviewOnly"] = True
    sheet_result["insiderReviewRequired"] = True


def run_google_sheets_export_plan_command(
    workbook_plan_file: Path,
    *,
    env_file: Path | None = None,
    replace_issue: bool = True,
    allow_draft_rows: bool = False,
) -> dict[str, object]:
    payload = json.loads(workbook_plan_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"workbook plan file is not a JSON object: {workbook_plan_file}")
    preflight_workbook_plan_google_sheet_export(
        payload,
        allow_draft_rows=allow_draft_rows,
    )
    config = load_google_access_config(env_file=env_file)
    env_values = dict(os.environ)
    if env_file is not None:
        env_values.update(load_env_file(env_file))
    sec_config = load_sec_insider_config(env_values)

    symbol_map_path: Path | None = None
    refreshed_csv = ""
    sec_candidates: tuple[SecStockCandidate, ...] = ()
    if sec_config is not None:
        # Complete every deterministic/local preparation before the first
        # Google mutation so a malformed private map or plan fails closed.
        symbol_map_path = Path(
            env_values.get("STOCK_ANALYST_SYMBOL_MAP_FILE")
            or "data/private/market-symbol-map.csv"
        ).expanduser()
        existing_csv_text = (
            symbol_map_path.read_text(encoding="utf-8")
            if symbol_map_path.exists()
            else ""
        )
        refreshed_csv = build_market_data_symbol_map_template_csv(
            payload,
            existing_csv_text=existing_csv_text,
        )
        workbook_candidates = market_data_candidates_from_symbol_map_template_csv(
            refreshed_csv
        )
        source_refs_by_id = {
            str(row.get("sourceId") or ""): (
                f"{str(row.get('issueId') or payload.get('issueId') or '').strip()}:"
                f"{str(row.get('page') or '').strip()}"
            ).rstrip(":")
            for row in payload.get("rows", [])
            if isinstance(row, dict)
        }
        sec_candidates = tuple(
            SecStockCandidate(
                company=candidate.name,
                wkn=candidate.wkn,
                symbol=candidate.symbol,
                source_ref=source_refs_by_id.get(candidate.source_id, ""),
            )
            for candidate in workbook_candidates
        )
        symbol_map_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_symbol_map = symbol_map_path.with_suffix(
            f"{symbol_map_path.suffix}.tmp"
        )
        temporary_symbol_map.write_text(refreshed_csv, encoding="utf-8")
        temporary_symbol_map.replace(symbol_map_path)

    insider_schema_migration = write_insider_activity_rows_to_google_sheet(
        config,
        (),
    )
    sheet_result = write_workbook_plan_to_google_sheet(
        config,
        payload,
        replace_issue=replace_issue,
        allow_draft_rows=allow_draft_rows,
    )
    if sec_config is None:
        sheet_result["insiderSchemaMigration"] = insider_schema_migration
        sheet_result["insiderEnrichment"] = {
            "status": "skipped",
            "reason": "SEC_USER_AGENT is not configured",
            "networkAccess": False,
        }
        if int(insider_schema_migration.get("rowsRetained") or 0) > 0:
            _mark_insider_review_required(sheet_result)
        return sheet_result
    sheet_result["insiderSchemaMigration"] = insider_schema_migration
    try:
        enrichment = enrich_sec_form4(sec_candidates, sec_config)
        insider_sheet_result = write_insider_activity_rows_to_google_sheet(
            config,
            [transaction.to_sheet_row() for transaction in enrichment.transactions],
            source_urls=[transaction.filing_url for transaction in enrichment.transactions],
        )
    except Exception as error:
        sheet_result["insiderEnrichment"] = {
            "status": "failed",
            "complete": False,
            "phase": "sec_refresh_or_sheet_merge",
            "errorType": type(error).__name__,
            "networkAccess": None,
        }
        if int(insider_schema_migration.get("rowsRetained") or 0) > 0:
            _mark_insider_review_required(sheet_result)
        return sheet_result
    enrichment_complete = (
        not enrichment.request_budget_exhausted
        and enrichment.failed_issuer_count == 0
        and enrichment.failed_filing_count == 0
    )
    sheet_result["insiderEnrichment"] = {
        "status": "completed" if enrichment_complete else "partial",
        "complete": enrichment_complete,
        "networkAccess": enrichment.network_request_count > 0,
        "candidateCount": enrichment.candidate_count,
        "resolvedIssuerCount": enrichment.resolved_issuer_count,
        "unresolvedCandidateCount": enrichment.unresolved_candidate_count,
        "filingCount": enrichment.filing_count,
        "failedIssuerCount": enrichment.failed_issuer_count,
        "failedFilingCount": enrichment.failed_filing_count,
        "transactionCount": len(enrichment.transactions),
        "networkRequestCount": enrichment.network_request_count,
        "cacheHitCount": enrichment.cache_hit_count,
        "requestBudgetExhausted": enrichment.request_budget_exhausted,
        "sheet": insider_sheet_result,
    }
    if (
        enrichment.transactions
        or int(insider_sheet_result.get("rowsRetained") or 0) > 0
        or int(insider_schema_migration.get("rowsRetained") or 0) > 0
    ):
        # The exact 12-column ledger intentionally has no review-status field.
        # New parsed rows are therefore reviewer-only until a separate,
        # source-linked approval mechanism exists.
        _mark_insider_review_required(sheet_result)
    return sheet_result


def run_workbook_approval_template_command(
    *,
    workbook_plan_file: Path,
    output: Path,
) -> dict[str, object]:
    _validate_private_output_path(output, artifact_name="approval CSV template")
    payload = json.loads(workbook_plan_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"workbook plan file is not a JSON object: {workbook_plan_file}")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"workbook plan file is missing rows list: {workbook_plan_file}")

    write_approval_template_csv(payload, output)
    return {
        "ok": True,
        "externalServicesEnabled": False,
        "networkAccess": False,
        "output": str(output),
        "rowCount": len(rows),
        "rowContentReturned": False,
        "approvalTemplateOnly": True,
    }


def run_workbook_approval_audit_command(
    *,
    workbook_plan_file: Path,
    approval_csv: Path,
    output: Path,
) -> dict[str, object]:
    _validate_private_output_path(approval_csv, artifact_name="approval CSV")
    _validate_private_output_path(output, artifact_name="reviewed workbook plan")
    payload = json.loads(workbook_plan_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"workbook plan file is not a JSON object: {workbook_plan_file}")
    approvals = load_workbook_approvals_csv(approval_csv)
    reviewed = apply_workbook_approvals(payload, approvals)
    write_reviewed_workbook_plan(reviewed, output)
    audit = reviewed["approvalAudit"]
    return {
        "ok": True,
        "externalServicesEnabled": False,
        "networkAccess": False,
        "output": str(output),
        "rowContentReturned": False,
        "approvalSource": audit["approvalSource"],
        "rowCount": audit["rowCount"],
        "approvalRowsImported": audit["approvalRowsImported"],
        "matchedApprovalRows": audit["matchedApprovalRows"],
        "unmatchedApprovalRows": audit["unmatchedApprovalRows"],
        "approvedRows": audit["approvedRows"],
        "rejectedRows": audit["rejectedRows"],
        "needsReviewRows": audit["needsReviewRows"],
        "hashMismatchRows": audit["hashMismatchRows"],
        "invalidEvidenceRows": audit["invalidEvidenceRows"],
        "staleApprovalDetected": audit["staleApprovalDetected"],
    }


def run_google_sheets_refinement_command(
    pdf_path: Path,
    *,
    env_file: Path | None = None,
    issue_id: str | None = None,
    min_embedded_chars: int = 40,
) -> dict[str, object]:
    config = load_google_access_config(env_file=env_file)
    refinement_plan = build_refinement_plan_from_pdf(
        pdf_path,
        issue_id=issue_id,
        min_embedded_chars=min_embedded_chars,
        current_utc_date=datetime.now(timezone.utc).date(),
    )
    return write_refinement_plan_to_google_sheet(config, refinement_plan.to_dict())


def _market_data_plan_to_dict(
    plan: MarketDataEnrichmentPlan,
    config: MarketDataPlanningConfig,
    *,
    budget_date: str | None = None,
    source_mode: str = "manual_symbols",
    workbook_candidates: tuple[object, ...] = (),
) -> dict[str, object]:
    candidate_dicts = [
        candidate.to_dict()
        for candidate in workbook_candidates
        if hasattr(candidate, "to_dict")
    ]
    return {
        "dryRun": plan.dry_run,
        "provider": plan.provider,
        "providerEnabled": config.provider_config.enabled,
        "providerStatus": config.provider_config.provider.status,
        "providerReason": config.provider_config.reason,
        "credentialConfigured": config.credential_configured,
        "networkAccess": plan.network_access,
        "cacheDir": str(config.cache_dir),
        "budgetDir": str(config.budget_dir),
        "budgetDate": budget_date,
        "sourceMode": source_mode,
        "sheetRowsRequiredBeforeLiveCalls": True,
        "candidateCount": len(candidate_dicts),
        "readyCandidateCount": len(
            [candidate for candidate in candidate_dicts if candidate["status"] == "ready"]
        ),
        "blockedCandidateCount": len(
            [
                candidate
                for candidate in candidate_dicts
                if candidate["status"] != "ready"
            ]
        ),
        "workbookCandidates": candidate_dicts,
        "termsVersion": config.terms_version,
        "dailyCallLimit": plan.daily_call_limit,
        "plannedCallCount": plan.planned_call_count,
        "priorChargedCallCount": plan.prior_charged_call_count,
        "chargedCallCount": plan.charged_call_count,
        "cacheHitCount": plan.cache_hit_count,
        "deniedCallCount": plan.denied_call_count,
        "remainingDailyCallBudget": plan.remaining_daily_call_budget,
        "bandwidthNote": plan.bandwidth_note,
        "status": plan.status,
        "reason": plan.reason,
        "requests": [
            {
                "provider": request.descriptor.provider,
                "symbol": request.descriptor.symbol,
                "endpoint": request.descriptor.endpoint,
                "params": dict(request.descriptor.params),
                "cacheKey": request.cache_key,
                "cachePath": str(request.cache_path),
                "budgetAction": request.budget_action,
                "consumesBudget": request.consumes_budget,
                "reason": request.reason,
            }
            for request in plan.requests
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "process-pdf":
            result = run_process_pdf(args.pdf, dry_run=args.dry_run, upload_dir=args.upload_dir)
        elif args.command == "import-pdf-folder":
            result = run_import_pdf_folder(
                args.folder,
                dry_run=args.dry_run,
                recursive=args.recursive,
                upload_dir=args.upload_dir,
                manifest_name=args.manifest_name,
            )
        elif args.command == "corpus-status":
            result = run_corpus_status(args.folder)
        elif args.command == "corpus-refinement-summary":
            result = run_corpus_refinement_summary(
                args.folder,
                limit=args.limit,
                min_embedded_chars=args.min_embedded_chars,
            )
        elif args.command == "extraction-quality-report":
            result = run_extraction_quality_report(
                args.manifest,
                upload_dir=args.upload_dir,
                min_embedded_chars=args.min_embedded_chars,
            )
        elif args.command == "review-queue":
            result = run_review_queue(
                args.manifest,
                upload_dir=args.upload_dir,
                min_embedded_chars=args.min_embedded_chars,
            )
        elif args.command == "ocr-needed":
            result = run_ocr_needed(
                args.manifest,
                upload_dir=args.upload_dir,
                min_embedded_chars=args.min_embedded_chars,
                output_dir=args.output_dir,
            )
        elif args.command == "recommendation-cards":
            result = run_recommendation_cards(
                args.pdf,
                issue_id=args.issue_id,
                min_embedded_chars=args.min_embedded_chars,
            )
        elif args.command == "section-inventory":
            result = run_section_inventory(
                args.pdf,
                issue_id=args.issue_id,
                min_embedded_chars=args.min_embedded_chars,
            )
        elif args.command == "dividend-strategy":
            result = run_dividend_strategy(
                args.pdf,
                issue_id=args.issue_id,
                min_embedded_chars=args.min_embedded_chars,
            )
        elif args.command == "quick-check":
            result = run_quick_check(
                args.pdf,
                issue_id=args.issue_id,
                min_embedded_chars=args.min_embedded_chars,
            )
        elif args.command == "chart-check":
            result = run_chart_check(
                args.pdf,
                issue_id=args.issue_id,
                min_embedded_chars=args.min_embedded_chars,
            )
        elif args.command == "workbook-export-plan":
            result = run_workbook_export_plan(
                args.pdf,
                issue_id=args.issue_id,
                min_embedded_chars=args.min_embedded_chars,
            )
        elif args.command == "refinement-plan":
            result = run_refinement_plan(
                args.pdf,
                issue_id=args.issue_id,
                min_embedded_chars=args.min_embedded_chars,
            )
        elif args.command == "visual-ocr-review":
            selected_pages = parse_page_selection(args.pages)
            if args.page:
                selected_pages = tuple(dict.fromkeys((selected_pages or ()) + tuple(args.page)))
            result = run_visual_ocr_review(
                args.pdf,
                pages=selected_pages,
                ocr=args.ocr,
                write_ocr_text=args.write_ocr_text,
                output_dir=args.output_dir,
                dpi=args.dpi,
                ocr_language=args.ocr_language,
            )
        elif args.command == "ocr-fixture-plan":
            result = run_ocr_fixture_plan_command(
                issue_id=args.issue_id,
                pdf_path=args.pdf,
                artifact_dir=args.artifact_dir,
                fixture_manifest=args.fixture_manifest,
            )
        elif args.command == "market-data-plan":
            result = run_market_data_plan_command(
                env_file=args.env_file,
                symbols=tuple(args.symbol),
                symbol_files=tuple(args.symbol_file),
                workbook_plan_file=args.workbook_plan_file,
                symbol_map_file=args.symbol_map_file,
                endpoints=tuple(args.endpoint) if args.endpoint else None,
            )
        elif args.command == "market-symbol-map-template":
            result = run_market_symbol_map_template_command(
                workbook_plan_file=args.workbook_plan_file,
                output=args.output,
            )
        elif args.command == "google-access-smoke":
            result = run_google_access_smoke_command(env_file=args.env_file)
        elif args.command == "google-drive-pdfs":
            result = run_google_drive_pdfs_command(
                env_file=args.env_file,
                page_size=args.page_size,
                manifest=args.manifest,
                include_private_identifiers=args.include_private_identifiers,
            )
        elif args.command == "google-sheets-bootstrap":
            result = run_google_sheets_bootstrap_command(
                env_file=args.env_file,
                write_headers=not args.skip_headers,
            )
        elif args.command == "google-sheets-clear-data":
            result = run_google_sheets_clear_data_command(
                env_file=args.env_file,
                write_headers=not args.skip_headers,
            )
        elif args.command == "google-sheets-refresh-search":
            result = run_google_sheets_refresh_search_command(
                env_file=args.env_file,
            )
        elif args.command == "google-sheets-export-plan":
            result = run_google_sheets_export_plan_command(
                args.workbook_plan_file,
                env_file=args.env_file,
                replace_issue=not args.append,
                allow_draft_rows=args.allow_draft_rows,
            )
        elif args.command == "workbook-approval-template":
            result = run_workbook_approval_template_command(
                workbook_plan_file=args.workbook_plan_file,
                output=args.output,
            )
        elif args.command == "workbook-approval-audit":
            result = run_workbook_approval_audit_command(
                workbook_plan_file=args.workbook_plan_file,
                approval_csv=args.approval_csv,
                output=args.output,
            )
        elif args.command == "google-sheets-refinement":
            result = run_google_sheets_refinement_command(
                args.pdf,
                env_file=args.env_file,
                issue_id=args.issue_id,
                min_embedded_chars=args.min_embedded_chars,
            )
        else:
            parser.error(f"Unsupported command: {args.command}")
    except (FileNotFoundError, GoogleAccessError, IntakeError, PdfProcessingError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
