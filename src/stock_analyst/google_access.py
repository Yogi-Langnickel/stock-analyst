"""Google Drive/Sheets access configuration and metadata-only helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import os
import re
from typing import Mapping


GOOGLE_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"

GOOGLE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")


class GoogleAccessError(ValueError):
    """Raised when Google Drive/Sheets access is not configured correctly."""


@dataclass(frozen=True)
class GoogleAccessConfig:
    drive_folder_id: str
    sheets_spreadsheet_id: str
    credentials_path: Path
    service_account_email: str | None = None

    def to_public_dict(self) -> dict[str, object]:
        return {
            "driveFolderId": self.drive_folder_id,
            "sheetsSpreadsheetId": self.sheets_spreadsheet_id,
            "credentialsPath": str(self.credentials_path),
            "serviceAccountEmail": self.service_account_email,
        }


@dataclass(frozen=True)
class DrivePdfMetadata:
    drive_file_id: str
    name: str
    mime_type: str
    size_bytes: int | None
    md5_checksum: str | None
    created_time: str | None
    modified_time: str | None
    web_view_link: str | None

    @property
    def source_pdf_id(self) -> str:
        return f"drive_{self.drive_file_id[:16]}"

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "sourcePdfId": self.source_pdf_id,
            "driveFileId": self.drive_file_id,
            "name": self.name,
            "mimeType": self.mime_type,
            "processingStatus": {
                "stage": "drive_metadata_imported",
                "status": "pending_local_download",
                "externalServicesEnabled": True,
            },
        }
        if self.size_bytes is not None:
            result["sizeBytes"] = self.size_bytes
        if self.md5_checksum is not None:
            result["md5Checksum"] = self.md5_checksum
        if self.created_time is not None:
            result["createdTime"] = self.created_time
        if self.modified_time is not None:
            result["modifiedTime"] = self.modified_time
        if self.web_view_link is not None:
            result["webViewLink"] = self.web_view_link
        return result


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise GoogleAccessError(f"env file does not exist: {path}")

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise GoogleAccessError(f"invalid env line {line_number}: expected KEY=VALUE")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            raise GoogleAccessError(f"invalid env line {line_number}: key is empty")
        values[key] = value

    return values


def load_google_access_config(
    *,
    env: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> GoogleAccessConfig:
    merged = dict(env or os.environ)
    if env_file is not None:
        merged.update(load_env_file(env_file))

    drive_folder_id = _required_value(merged, "GOOGLE_DRIVE_FOLDER_ID")
    spreadsheet_id = _required_value(merged, "GOOGLE_SHEETS_SPREADSHEET_ID")
    credentials_path = Path(_required_value(merged, "GOOGLE_APPLICATION_CREDENTIALS")).expanduser()
    service_account_email = merged.get("GOOGLE_SERVICE_ACCOUNT_EMAIL") or None

    _validate_google_id("GOOGLE_DRIVE_FOLDER_ID", drive_folder_id)
    _validate_google_id("GOOGLE_SHEETS_SPREADSHEET_ID", spreadsheet_id)
    if not credentials_path.exists():
        raise GoogleAccessError(
            f"GOOGLE_APPLICATION_CREDENTIALS does not exist: {credentials_path}"
        )

    return GoogleAccessConfig(
        drive_folder_id=drive_folder_id,
        sheets_spreadsheet_id=spreadsheet_id,
        credentials_path=credentials_path,
        service_account_email=service_account_email,
    )


def run_google_access_smoke(
    config: GoogleAccessConfig,
    *,
    drive_service_factory=None,
    sheets_service_factory=None,
) -> dict[str, object]:
    """Check scoped access to the configured Drive folder and Sheet."""

    if drive_service_factory is None or sheets_service_factory is None:
        drive_service_factory, sheets_service_factory = _google_service_factories(config)

    drive = drive_service_factory()
    sheets = sheets_service_factory()
    try:
        folder = (
            drive.files()
            .get(fileId=config.drive_folder_id, fields="id,name,mimeType", supportsAllDrives=True)
            .execute()
        )
        spreadsheet = (
            sheets.spreadsheets()
            .get(
                spreadsheetId=config.sheets_spreadsheet_id,
                fields="spreadsheetId,properties.title,sheets.properties.title",
            )
            .execute()
        )
    except Exception as error:
        raise GoogleAccessError(
            "Google Drive/Sheets smoke check failed. Verify network access, API enablement, "
            "service-account sharing, and configured folder/sheet IDs."
        ) from error

    if folder.get("mimeType") != "application/vnd.google-apps.folder":
        raise GoogleAccessError("GOOGLE_DRIVE_FOLDER_ID is accessible but is not a Drive folder")

    return {
        "ok": True,
        "externalServicesEnabled": True,
        "serviceAccountEmail": config.service_account_email,
        "drive": {
            "folderId": folder.get("id"),
            "folderName": folder.get("name"),
            "mimeType": folder.get("mimeType"),
        },
        "sheets": {
            "spreadsheetId": spreadsheet.get("spreadsheetId"),
            "title": spreadsheet.get("properties", {}).get("title"),
            "tabs": [
                sheet.get("properties", {}).get("title")
                for sheet in spreadsheet.get("sheets", [])
                if sheet.get("properties", {}).get("title")
            ],
        },
    }


def list_drive_pdf_metadata(
    config: GoogleAccessConfig,
    *,
    drive_service_factory=None,
    page_size: int = 100,
) -> tuple[DrivePdfMetadata, ...]:
    """List PDF metadata from the configured Drive folder without downloading files."""

    if page_size < 1 or page_size > 1000:
        raise GoogleAccessError("page_size must be between 1 and 1000")

    if drive_service_factory is None:
        drive_service_factory, _sheets_service_factory = _google_service_factories(config)

    drive = drive_service_factory()
    files_resource = drive.files()
    fields = (
        "nextPageToken,files(id,name,mimeType,md5Checksum,size,createdTime,"
        "modifiedTime,webViewLink)"
    )
    query = (
        f"'{config.drive_folder_id}' in parents and "
        "mimeType = 'application/pdf' and trashed = false"
    )
    page_token: str | None = None
    files: list[DrivePdfMetadata] = []

    try:
        while True:
            response = (
                files_resource.list(
                    q=query,
                    fields=fields,
                    pageSize=page_size,
                    pageToken=page_token,
                    orderBy="modifiedTime desc,name",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            files.extend(_drive_file_metadata_from_payload(item) for item in response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except Exception as error:
        raise GoogleAccessError(
            "Google Drive PDF metadata listing failed. Verify network access, API enablement, "
            "service-account sharing, and configured folder ID."
        ) from error

    return tuple(files)


def build_drive_pdf_metadata_result(
    config: GoogleAccessConfig,
    *,
    drive_service_factory=None,
    page_size: int = 100,
) -> dict[str, object]:
    files = list_drive_pdf_metadata(
        config,
        drive_service_factory=drive_service_factory,
        page_size=page_size,
    )
    return {
        "ok": True,
        "externalServicesEnabled": True,
        "driveFolderId": config.drive_folder_id,
        "listedAt": datetime.now(timezone.utc).isoformat(),
        "fileCount": len(files),
        "files": [file.to_dict() for file in files],
    }


def write_drive_pdf_metadata_manifest(
    result: Mapping[str, object],
    manifest_path: Path,
) -> Path:
    """Write metadata-only Drive PDF rows to a private local JSONL manifest."""

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    listed_at = result.get("listedAt")
    rows = result.get("files", [])
    if not isinstance(rows, list):
        raise GoogleAccessError("Drive metadata result does not contain a files list")

    with manifest_path.open("w", encoding="utf-8") as manifest:
        for row in rows:
            if not isinstance(row, dict):
                raise GoogleAccessError("Drive metadata row must be an object")
            manifest_row = dict(row)
            manifest_row["listedAt"] = listed_at
            manifest.write(f"{json.dumps(manifest_row, sort_keys=True)}\n")

    return manifest_path


def _google_service_factories(config: GoogleAccessConfig):
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ModuleNotFoundError as error:
        raise GoogleAccessError(
            "Google API dependencies are not installed. Run `pip install -e .` in a virtualenv."
        ) from error

    credentials = service_account.Credentials.from_service_account_file(
        str(config.credentials_path),
        scopes=[GOOGLE_DRIVE_READONLY_SCOPE, GOOGLE_SHEETS_SCOPE],
    )

    return (
        lambda: build("drive", "v3", credentials=credentials, cache_discovery=False),
        lambda: build("sheets", "v4", credentials=credentials, cache_discovery=False),
    )


def _required_value(env: Mapping[str, str], key: str) -> str:
    value = str(env.get(key) or "").strip()
    if not value:
        raise GoogleAccessError(f"{key} is required")
    return value


def _validate_google_id(name: str, value: str) -> None:
    if not GOOGLE_ID_RE.match(value):
        raise GoogleAccessError(f"{name} must look like a Google Drive/Sheets id")


def _drive_file_metadata_from_payload(payload: Mapping[str, object]) -> DrivePdfMetadata:
    drive_file_id = _required_payload_string(payload, "id")
    name = _required_payload_string(payload, "name")
    mime_type = _required_payload_string(payload, "mimeType")
    size_value = payload.get("size")
    size_bytes = int(size_value) if size_value not in (None, "") else None

    return DrivePdfMetadata(
        drive_file_id=drive_file_id,
        name=name,
        mime_type=mime_type,
        size_bytes=size_bytes,
        md5_checksum=_optional_payload_string(payload.get("md5Checksum")),
        created_time=_optional_payload_string(payload.get("createdTime")),
        modified_time=_optional_payload_string(payload.get("modifiedTime")),
        web_view_link=_optional_payload_string(payload.get("webViewLink")),
    )


def _required_payload_string(payload: Mapping[str, object], key: str) -> str:
    value = _optional_payload_string(payload.get(key))
    if value is None:
        raise GoogleAccessError(f"Drive file metadata is missing {key}")
    return value


def _optional_payload_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
