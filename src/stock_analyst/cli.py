"""Command-line entrypoint for local prototype operations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stock_analyst.intake import IntakeError, preview_pdf_intake, store_pdf_upload
from stock_analyst.pipeline import (
    PdfProcessingError,
    build_draft_review_status,
    calculate_processing_steps,
)


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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "process-pdf":
            result = run_process_pdf(args.pdf, dry_run=args.dry_run, upload_dir=args.upload_dir)
        else:
            parser.error(f"Unsupported command: {args.command}")
    except (IntakeError, PdfProcessingError) as error:
        parser.exit(2, f"error: {error}\n")

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
