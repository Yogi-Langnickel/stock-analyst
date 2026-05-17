"""Command-line entrypoint for local prototype operations."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from stock_analyst.dividend_strategy import build_dividend_strategy_from_pdf
from stock_analyst.google_access import (
    GoogleAccessError,
    bootstrap_google_sheet,
    build_drive_pdf_metadata_result,
    load_google_access_config,
    run_google_access_smoke,
    write_drive_pdf_metadata_manifest,
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
    plan_market_data_enrichment_requests,
    ready_market_data_symbols_from_workbook_candidates,
)
from stock_analyst.pipeline import (
    PdfProcessingError,
    build_draft_review_status,
    calculate_processing_steps,
)
from stock_analyst.quality_report import build_extraction_quality_report
from stock_analyst.recommendation_cards import extract_recommendation_cards_from_pdf
from stock_analyst.review_queue import build_review_queue_from_manifest
from stock_analyst.section_inventory import build_section_inventory_from_pdf
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
        default_provider="fmp",
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


def run_google_drive_pdfs_command(
    *,
    env_file: Path | None = None,
    page_size: int = 100,
    manifest: Path | None = None,
) -> dict[str, object]:
    config = load_google_access_config(env_file=env_file)
    result = build_drive_pdf_metadata_result(config, page_size=page_size)
    if manifest is not None:
        write_drive_pdf_metadata_manifest(result, manifest)
        result["manifestPath"] = str(manifest)
    return result


def run_google_sheets_bootstrap_command(
    *,
    env_file: Path | None = None,
    write_headers: bool = True,
) -> dict[str, object]:
    config = load_google_access_config(env_file=env_file)
    return bootstrap_google_sheet(config, write_headers=write_headers)


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
        elif args.command == "workbook-export-plan":
            result = run_workbook_export_plan(
                args.pdf,
                issue_id=args.issue_id,
                min_embedded_chars=args.min_embedded_chars,
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
            )
        elif args.command == "google-sheets-bootstrap":
            result = run_google_sheets_bootstrap_command(
                env_file=args.env_file,
                write_headers=not args.skip_headers,
            )
        else:
            parser.error(f"Unsupported command: {args.command}")
    except (FileNotFoundError, GoogleAccessError, IntakeError, PdfProcessingError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
