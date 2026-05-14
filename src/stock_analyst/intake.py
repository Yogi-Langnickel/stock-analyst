"""Local-first PDF intake helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil

PDF_MAGIC = b"%PDF-"
READ_CHUNK_SIZE = 1024 * 1024


class IntakeError(ValueError):
    """Raised when an upload cannot enter the local processing queue."""


@dataclass(frozen=True)
class IntakePreview:
    filename: str
    checksum_sha256: str
    size_bytes: int
    accepted_at: str
    status: str


@dataclass(frozen=True)
class StoredPdfUpload:
    filename: str
    checksum_sha256: str
    size_bytes: int
    stored_path: Path
    manifest_path: Path
    accepted_at: str
    status: str
    duplicate: bool


def calculate_sha256(path: Path) -> str:
    digest = sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(READ_CHUNK_SIZE), b""):
            digest.update(chunk)

    return digest.hexdigest()


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

    return IntakePreview(
        filename=path.name,
        checksum_sha256=calculate_sha256(path),
        size_bytes=path.stat().st_size,
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
            "storedPath": stored_path.name,
            "acceptedAt": preview.accepted_at,
            "status": "uploaded",
        }

        with manifest_path.open("a", encoding="utf-8") as manifest:
            manifest.write(f"{json.dumps(record, sort_keys=True)}\n")

    return StoredPdfUpload(
        filename=preview.filename,
        checksum_sha256=preview.checksum_sha256,
        size_bytes=preview.size_bytes,
        stored_path=stored_path,
        manifest_path=manifest_path,
        accepted_at=preview.accepted_at,
        status="duplicate" if duplicate else "uploaded",
        duplicate=duplicate,
    )
