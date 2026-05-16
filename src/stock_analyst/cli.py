"""Command-line entrypoint for local prototype operations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stock_analyst.dividend_strategy import build_dividend_strategy_from_pdf
from stock_analyst.intake import (
    BatchPdfIntakeItem,
    IntakeError,
    import_pdf_folder,
    preview_pdf_intake,
    store_pdf_upload,
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
        else:
            parser.error(f"Unsupported command: {args.command}")
    except (FileNotFoundError, IntakeError, PdfProcessingError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
