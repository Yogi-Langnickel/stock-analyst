"""Google Drive/Sheets access configuration and smoke checks."""

from __future__ import annotations

from dataclasses import dataclass
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
