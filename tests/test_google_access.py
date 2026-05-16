import tempfile
import unittest
from pathlib import Path

from stock_analyst.google_access import (
    GoogleAccessError,
    load_env_file,
    load_google_access_config,
    run_google_access_smoke,
)


class _FakeExecute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _FakeDriveFiles:
    def __init__(self, payload):
        self.payload = payload
        self.request = None

    def get(self, **kwargs):
        self.request = kwargs
        return _FakeExecute(self.payload)


class _FakeDrive:
    def __init__(self, payload):
        self.files_resource = _FakeDriveFiles(payload)

    def files(self):
        return self.files_resource


class _FakeSpreadsheets:
    def __init__(self, payload):
        self.payload = payload

    def get(self, **_kwargs):
        return _FakeExecute(self.payload)


class _FakeSheets:
    def __init__(self, payload):
        self.spreadsheets_resource = _FakeSpreadsheets(payload)

    def spreadsheets(self):
        return self.spreadsheets_resource


class GoogleAccessTest(unittest.TestCase):
    def test_load_env_file_parses_quoted_google_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env.google"
            env_file.write_text(
                '\n'.join(
                    (
                        'GOOGLE_SERVICE_ACCOUNT_EMAIL="stock-analyst@example.iam.gserviceaccount.com"',
                        'GOOGLE_DRIVE_FOLDER_ID="1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb"',
                    )
                ),
                encoding="utf-8",
            )

            values = load_env_file(env_file)

        self.assertEqual(
            values["GOOGLE_SERVICE_ACCOUNT_EMAIL"],
            "stock-analyst@example.iam.gserviceaccount.com",
        )
        self.assertEqual(values["GOOGLE_DRIVE_FOLDER_ID"], "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb")

    def test_config_requires_existing_credentials_and_google_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text("{}", encoding="utf-8")

            config = load_google_access_config(
                env={
                    "GOOGLE_SERVICE_ACCOUNT_EMAIL": "stock-analyst@example.iam.gserviceaccount.com",
                    "GOOGLE_DRIVE_FOLDER_ID": "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "1vE0YAMOoAP3SeFI6vXnzmSlGdaFRfBkQcoCYVMwz4UE",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )

        self.assertEqual(config.drive_folder_id, "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb")
        self.assertEqual(config.service_account_email, "stock-analyst@example.iam.gserviceaccount.com")

    def test_config_rejects_missing_credentials_file(self) -> None:
        with self.assertRaisesRegex(GoogleAccessError, "GOOGLE_APPLICATION_CREDENTIALS does not exist"):
            load_google_access_config(
                env={
                    "GOOGLE_DRIVE_FOLDER_ID": "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "1vE0YAMOoAP3SeFI6vXnzmSlGdaFRfBkQcoCYVMwz4UE",
                    "GOOGLE_APPLICATION_CREDENTIALS": "/missing/service-account.json",
                }
            )

    def test_smoke_result_is_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_path = Path(temp_dir) / "service-account.json"
            credentials_path.write_text('{"private_key":"secret"}', encoding="utf-8")
            config = load_google_access_config(
                env={
                    "GOOGLE_SERVICE_ACCOUNT_EMAIL": "stock-analyst@example.iam.gserviceaccount.com",
                    "GOOGLE_DRIVE_FOLDER_ID": "1HqFI8-T1tXuyHedVx3U7D2AA0tHG53tb",
                    "GOOGLE_SHEETS_SPREADSHEET_ID": "1vE0YAMOoAP3SeFI6vXnzmSlGdaFRfBkQcoCYVMwz4UE",
                    "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
                }
            )

            result = run_google_access_smoke(
                config,
                drive_service_factory=lambda: _FakeDrive(
                    {
                        "id": config.drive_folder_id,
                        "name": "Der Aktionär Issues",
                        "mimeType": "application/vnd.google-apps.folder",
                    }
                ),
                sheets_service_factory=lambda: _FakeSheets(
                    {
                        "spreadsheetId": config.sheets_spreadsheet_id,
                        "properties": {"title": "Der Aktionär Summaries"},
                        "sheets": [
                            {"properties": {"title": "Navigation Dashboard"}},
                            {"properties": {"title": "Stocks"}},
                        ],
                    }
                ),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["drive"]["folderName"], "Der Aktionär Issues")
        self.assertEqual(result["sheets"]["title"], "Der Aktionär Summaries")
        self.assertNotIn("secret", str(result))


if __name__ == "__main__":
    unittest.main()
