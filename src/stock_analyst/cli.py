"""Command-line entrypoint for local prototype operations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stock_analyst.intake import IntakeError, preview_pdf_intake
from stock_analyst.pipeline import PdfProcessingError, calculate_processing_steps


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

    return parser


def run_process_pdf(pdf_path: Path, *, dry_run: bool) -> dict[str, object]:
    intake = preview_pdf_intake(pdf_path)

    return {
        "dryRun": dry_run,
        "filename": intake.filename,
        "checksumSha256": intake.checksum_sha256,
        "sizeBytes": intake.size_bytes,
        "status": intake.status,
        "steps": calculate_processing_steps(pdf_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "process-pdf":
            result = run_process_pdf(args.pdf, dry_run=args.dry_run)
        else:
            parser.error(f"Unsupported command: {args.command}")
    except (IntakeError, PdfProcessingError) as error:
        parser.exit(2, f"error: {error}\n")

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
