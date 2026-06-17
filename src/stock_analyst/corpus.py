"""Metadata-only local corpus readiness helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

ISSUE_FILENAME_PATTERN = re.compile(r"^DA_(?P<year>20\d{2})_(?P<number>\d{2})\.pdf$", re.IGNORECASE)


@dataclass(frozen=True, order=True)
class LocalIssueFile:
    year: int
    number: int
    path: Path

    @property
    def issue_id(self) -> str:
        return f"DA_{self.year}_{self.number:02d}"

    @property
    def filename(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class LocalCorpusStatus:
    issues_dir: Path
    folder_exists: bool
    matched_issues: tuple[LocalIssueFile, ...]
    malformed_filenames: tuple[str, ...]
    missing_issue_numbers_by_year: dict[str, tuple[int, ...]]

    @property
    def latest_issue(self) -> LocalIssueFile | None:
        if not self.matched_issues:
            return None
        return max(self.matched_issues, key=lambda issue: (issue.year, issue.number))

    @property
    def expected_issue_count(self) -> int:
        if not self.matched_issues:
            return 0
        return len(self.matched_issues) + sum(
            len(numbers) for numbers in self.missing_issue_numbers_by_year.values()
        )

    @property
    def status(self) -> str:
        if not self.folder_exists:
            return "missing_folder"
        if not self.matched_issues:
            return "no_valid_issue_files"
        return "local_corpus_files_available"

    @property
    def blocking(self) -> bool:
        return self.status != "local_corpus_files_available"

    @property
    def missing_issue_ids(self) -> tuple[str, ...]:
        issue_ids: list[str] = []
        for year, numbers in sorted(self.missing_issue_numbers_by_year.items()):
            issue_ids.extend(f"DA_{year}_{number:02d}" for number in numbers)
        return tuple(issue_ids)

    def to_dict(self) -> dict[str, object]:
        latest = self.latest_issue
        status = self.status
        return {
            "available": status == "local_corpus_files_available",
            "readinessStatus": status,
            "status": status,
            "readinessScope": "local_corpus_file_metadata_only",
            "filePresenceOnly": True,
            "blocking": self.blocking,
            "blockingReason": None if not self.blocking else status,
            "blockingScope": "local_corpus_file_availability",
            "commandExitCode": 0,
            "issuesDir": str(self.issues_dir),
            "folderExists": self.folder_exists,
            "matchedIssueCount": len(self.matched_issues),
            "availableIssueCount": len(self.matched_issues),
            "expectedIssueCount": self.expected_issue_count,
            "expectedCountBasis": "numeric_span_between_min_and_max_matched_issue_per_year",
            "missingIssueCount": len(self.missing_issue_ids),
            "latestIssueId": latest.issue_id if latest is not None else None,
            "latestPath": str(latest.path) if latest is not None else None,
            "latestIssue": (
                {
                    "issueId": latest.issue_id,
                    "year": latest.year,
                    "issueNumber": latest.number,
                    "filename": latest.filename,
                    "path": str(latest.path),
                }
                if latest is not None
                else None
            ),
            "missingIssues": list(self.missing_issue_ids),
            "missingIssueNumbersByYear": {
                year: list(numbers)
                for year, numbers in sorted(self.missing_issue_numbers_by_year.items())
            },
            "gaps": list(self.missing_issue_ids),
            "gapsByYear": {
                year: list(numbers)
                for year, numbers in sorted(self.missing_issue_numbers_by_year.items())
            },
            "malformedCount": len(self.malformed_filenames),
            "ignoredPdfCount": len(self.malformed_filenames),
            "malformedFilenames": list(self.malformed_filenames),
            "externalServicesEnabled": False,
            "networkAccess": False,
            "textExtractionEnabled": False,
            "pdfContentsRead": False,
            "extractionSuccessInferred": False,
            "workbookReadinessInferred": False,
            "recommendationCoverageInferred": False,
            "marketDataReadinessInferred": False,
            "familyVisibleReadinessInferred": False,
        }


def parse_local_issue_filename(path: Path) -> LocalIssueFile | None:
    """Parse DA_YYYY_NN.pdf filenames without opening the PDF."""

    match = ISSUE_FILENAME_PATTERN.match(path.name)
    if not match:
        return None

    return LocalIssueFile(
        year=int(match.group("year")),
        number=int(match.group("number")),
        path=path,
    )


def build_local_corpus_status(issues_dir: Path) -> LocalCorpusStatus:
    """Summarize local issue-file availability using filename metadata only."""

    if not issues_dir.is_dir():
        return LocalCorpusStatus(
            issues_dir=issues_dir,
            folder_exists=False,
            matched_issues=(),
            malformed_filenames=(),
            missing_issue_numbers_by_year={},
        )

    matched_issues: list[LocalIssueFile] = []
    malformed_filenames: list[str] = []
    for path in sorted(issues_dir.iterdir(), key=lambda entry: entry.name.lower()):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue

        issue = parse_local_issue_filename(path)
        if issue is None:
            malformed_filenames.append(path.name)
            continue

        matched_issues.append(issue)

    missing_by_year: dict[str, tuple[int, ...]] = {}
    numbers_by_year: dict[int, set[int]] = {}
    for issue in matched_issues:
        numbers_by_year.setdefault(issue.year, set()).add(issue.number)

    for year, numbers in numbers_by_year.items():
        if not numbers:
            continue
        expected = set(range(min(numbers), max(numbers) + 1))
        missing = tuple(sorted(expected - numbers))
        if missing:
            missing_by_year[str(year)] = missing

    return LocalCorpusStatus(
        issues_dir=issues_dir,
        folder_exists=True,
        matched_issues=tuple(sorted(matched_issues)),
        malformed_filenames=tuple(sorted(malformed_filenames, key=str.lower)),
        missing_issue_numbers_by_year=missing_by_year,
    )
