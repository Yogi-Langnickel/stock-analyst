"""Local-first PDF intake helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

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
