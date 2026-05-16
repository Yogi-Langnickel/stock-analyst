"""Local-first PDF intake helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil

PDF_MAGIC = b"%PDF-"
READ_CHUNK_SIZE = 1024 * 1024
ISSUE_DATE_PATTERNS = (
    re.compile(
        r"(?P<year>20\d{2})[-_. ]?"
        r"(?P<month>0[1-9]|1[0-2])[-_. ]?"
        r"(?P<day>0[1-9]|[12]\d|3[01])"
    ),
    re.compile(
        r"(?P<day>0[1-9]|[12]\d|3[01])[-_. ]"
        r"(?P<month>0[1-9]|1[0-2])[-_. ]"
        r"(?P<year>20\d{2})"
    ),
    re.compile(
        r"(?P<day>0[1-9]|[12]\d|3[01])"
        r"(?P<month>0[1-9]|1[0-2])"
        r"(?P<year>20\d{2})"
    ),
)


class IntakeError(ValueError):
    """Raised when an upload cannot enter the local processing queue."""


@dataclass(frozen=True)
class IntakePreview:
    filename: str
    checksum_sha256: str
    size_bytes: int
    source_pdf_id: str
    issue_date_guess: str | None
    accepted_at: str
    status: str


@dataclass(frozen=True)
class StoredPdfUpload:
    filename: str
    checksum_sha256: str
    size_bytes: int
    source_pdf_id: str
    issue_date_guess: str | None
    stored_path: Path
    manifest_path: Path
    accepted_at: str
    status: str
    duplicate: bool


@dataclass(frozen=True)
class BatchPdfIntakeItem:
    filename: str
    path: Path
    status: str
    checksum_sha256: str | None = None
    source_pdf_id: str | None = None
    issue_date_guess: str | None = None
    size_bytes: int | None = None
    stored_path: Path | None = None
    manifest_path: Path | None = None
    error: str | None = None


@dataclass(frozen=True)
class BatchPdfIntakeResult:
    source_dir: Path
    upload_dir: Path
    dry_run: bool
    recursive: bool
    manifest_path: Path
    total_pdf_candidates: int
    uploaded_count: int
    duplicate_count: int
    invalid_count: int
    dry_run_valid_count: int
    items: tuple[BatchPdfIntakeItem, ...]


def calculate_sha256(path: Path) -> str:
    digest = sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(READ_CHUNK_SIZE), b""):
            digest.update(chunk)

    return digest.hexdigest()


def guess_issue_date(filename: str) -> str | None:
    """Return an ISO date guessed from a filename, without inferring missing parts."""

    for pattern in ISSUE_DATE_PATTERNS:
        match = pattern.search(filename)
        if match:
            year = match.group("year")
            month = match.group("month")
            day = match.group("day")
            try:
                return date.fromisoformat(f"{year}-{month}-{day}").isoformat()
            except ValueError:
                continue

    return None


def assert_pdf_upload(path: Path) -> None:
    if path.suffix.lower() != ".pdf":
        raise IntakeError("Only PDF files can be uploaded.")

    if not path.is_file():
        raise IntakeError("Upload path does not point to a file.")

    with path.open("rb") as file:
        magic = file.read(len(PDF_MAGIC))

    if magic != PDF_MAGIC:
        raise IntakeError("The selected file does not look like a valid PDF.")


def preview_pdf_intake(path: Path) -> IntakePreview:
    """Validate and summarize a PDF without copying or processing it."""

    assert_pdf_upload(path)
    checksum = calculate_sha256(path)

    return IntakePreview(
        filename=path.name,
        checksum_sha256=checksum,
        size_bytes=path.stat().st_size,
        source_pdf_id=f"pdf_{checksum[:16]}",
        issue_date_guess=guess_issue_date(path.name),
        accepted_at=datetime.now(timezone.utc).isoformat(),
        status="ready_for_review",
    )


def _read_manifest_records(manifest_path: Path) -> list[dict[str, object]]:
    if not manifest_path.exists():
        return []

    records: list[dict[str, object]] = []

    with manifest_path.open("r", encoding="utf-8") as manifest:
        for line in manifest:
            if line.strip():
                records.append(json.loads(line))

    return records


def store_pdf_upload(
    source_path: Path,
    upload_dir: Path,
    *,
    manifest_name: str = "uploads.jsonl",
) -> StoredPdfUpload:
    """Copy a validated PDF into private local storage and record a manifest row."""

    preview = preview_pdf_intake(source_path)
    upload_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = upload_dir / manifest_name
    records = _read_manifest_records(manifest_path)
    existing = next(
        (
            record
            for record in records
            if record.get("checksumSha256") == preview.checksum_sha256
        ),
        None,
    )
    stored_path = upload_dir / f"{preview.checksum_sha256}.pdf"
    duplicate = existing is not None or stored_path.exists()

    if not duplicate:
        shutil.copy2(source_path, stored_path)
        record = {
            "filename": preview.filename,
            "checksumSha256": preview.checksum_sha256,
            "sizeBytes": preview.size_bytes,
            "sourcePdfId": preview.source_pdf_id,
            "issueDateGuess": preview.issue_date_guess,
            "storedPath": stored_path.name,
            "acceptedAt": preview.accepted_at,
            "status": "uploaded",
            "processingStatus": {
                "stage": "queued_for_text_extraction",
                "status": "pending",
                "externalServicesEnabled": False,
            },
        }

        with manifest_path.open("a", encoding="utf-8") as manifest:
            manifest.write(f"{json.dumps(record, sort_keys=True)}\n")

    return StoredPdfUpload(
        filename=preview.filename,
        checksum_sha256=preview.checksum_sha256,
        size_bytes=preview.size_bytes,
        source_pdf_id=preview.source_pdf_id,
        issue_date_guess=preview.issue_date_guess,
        stored_path=stored_path,
        manifest_path=manifest_path,
        accepted_at=preview.accepted_at,
        status="duplicate" if duplicate else "uploaded",
        duplicate=duplicate,
    )


def import_pdf_folder(
    source_dir: Path,
    upload_dir: Path,
    *,
    dry_run: bool = False,
    recursive: bool = False,
    manifest_name: str = "uploads.jsonl",
) -> BatchPdfIntakeResult:
    """Import valid PDFs from a local folder into private storage.

    This intentionally handles only local filesystem intake. It does not call
    Google Drive, Google Sheets, OCR, extraction, market data, or LLM providers.
    """

    if not source_dir.is_dir():
        raise IntakeError("Batch intake source path must be a folder.")

    folder_entries = source_dir.rglob("*") if recursive else source_dir.glob("*")
    candidates = sorted(
        (path for path in folder_entries if path.is_file() and path.suffix.lower() == ".pdf"),
        key=lambda path: str(path.relative_to(source_dir)).lower(),
    )
    manifest_path = upload_dir / manifest_name
    items: list[BatchPdfIntakeItem] = []
    uploaded_count = 0
    duplicate_count = 0
    invalid_count = 0
    dry_run_valid_count = 0

    for pdf_path in candidates:
        try:
            if dry_run:
                preview = preview_pdf_intake(pdf_path)
                dry_run_valid_count += 1
                items.append(
                    BatchPdfIntakeItem(
                        filename=preview.filename,
                        path=pdf_path,
                        status="valid",
                        checksum_sha256=preview.checksum_sha256,
                        source_pdf_id=preview.source_pdf_id,
                        issue_date_guess=preview.issue_date_guess,
                        size_bytes=preview.size_bytes,
                    )
                )
                continue

            stored = store_pdf_upload(
                pdf_path,
                upload_dir,
                manifest_name=manifest_name,
            )
            if stored.duplicate:
                duplicate_count += 1
            else:
                uploaded_count += 1
            items.append(
                BatchPdfIntakeItem(
                    filename=stored.filename,
                    path=pdf_path,
                    status=stored.status,
                    checksum_sha256=stored.checksum_sha256,
                    source_pdf_id=stored.source_pdf_id,
                    issue_date_guess=stored.issue_date_guess,
                    size_bytes=stored.size_bytes,
                    stored_path=stored.stored_path,
                    manifest_path=stored.manifest_path,
                )
            )
        except IntakeError as error:
            invalid_count += 1
            items.append(
                BatchPdfIntakeItem(
                    filename=pdf_path.name,
                    path=pdf_path,
                    status="invalid",
                    error=str(error),
                )
            )

    return BatchPdfIntakeResult(
        source_dir=source_dir,
        upload_dir=upload_dir,
        dry_run=dry_run,
        recursive=recursive,
        manifest_path=manifest_path,
        total_pdf_candidates=len(candidates),
        uploaded_count=uploaded_count,
        duplicate_count=duplicate_count,
        invalid_count=invalid_count,
        dry_run_valid_count=dry_run_valid_count,
        items=tuple(items),
    )
