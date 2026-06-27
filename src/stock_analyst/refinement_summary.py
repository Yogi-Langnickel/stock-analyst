"""Safe corpus-level summaries for refinement planner coverage."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from stock_analyst.corpus import LocalIssueFile, build_local_corpus_status
from stock_analyst.refinement import RefinementPlan, build_refinement_plan_from_pdf


RefinementPlanBuilder = Callable[..., RefinementPlan]


@dataclass(frozen=True)
class CorpusRefinementIssueSummary:
    issue_id: str
    filename: str
    status: str
    page_count: int
    useful_page_count: int
    not_useful_page_count: int
    section_counts: dict[str, int]
    destination_counts: dict[str, int]
    parser_hint_counts: dict[str, int]
    manual_seed_page_count: int
    future_parser_page_count: int
    unknown_page_count: int
    error_type: str | None = None

    @property
    def no_useful_pages(self) -> bool:
        return self.status == "ok" and self.useful_page_count == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "issueId": self.issue_id,
            "filename": self.filename,
            "status": self.status,
            "pageCount": self.page_count,
            "usefulPageCount": self.useful_page_count,
            "notUsefulPageCount": self.not_useful_page_count,
            "noUsefulPages": self.no_useful_pages,
            "sectionCounts": self.section_counts,
            "destinationCounts": self.destination_counts,
            "parserHintCounts": self.parser_hint_counts,
            "manualSeedPageCount": self.manual_seed_page_count,
            "futureParserPageCount": self.future_parser_page_count,
            "unknownPageCount": self.unknown_page_count,
            "errorType": self.error_type,
        }


@dataclass(frozen=True)
class CorpusRefinementSummary:
    issues_dir: Path
    folder_exists: bool
    matched_issue_count: int
    processed_issue_count: int
    limit: int | None
    malformed_filenames: tuple[str, ...]
    issue_summaries: tuple[CorpusRefinementIssueSummary, ...]

    def to_dict(self) -> dict[str, object]:
        section_counts = Counter()
        destination_counts = Counter()
        parser_hint_counts = Counter()
        page_count = 0
        useful_count = 0
        not_useful_count = 0
        error_count = 0
        for issue in self.issue_summaries:
            page_count += issue.page_count
            useful_count += issue.useful_page_count
            not_useful_count += issue.not_useful_page_count
            section_counts.update(issue.section_counts)
            destination_counts.update(issue.destination_counts)
            parser_hint_counts.update(issue.parser_hint_counts)
            if issue.status != "ok":
                error_count += 1

        no_useful_issue_ids = tuple(
            issue.issue_id for issue in self.issue_summaries if issue.no_useful_pages
        )
        return {
            "issuesDir": str(self.issues_dir),
            "folderExists": self.folder_exists,
            "matchedIssueCount": self.matched_issue_count,
            "processedIssueCount": self.processed_issue_count,
            "limit": self.limit,
            "malformedCount": len(self.malformed_filenames),
            "malformedFilenames": list(self.malformed_filenames),
            "externalServicesEnabled": False,
            "networkAccess": False,
            "sourcePdfTextIncluded": False,
            "pageTitlesIncluded": False,
            "pageRowsIncluded": False,
            "reviewNotesIncluded": False,
            "summaryScope": "corpus_refinement_aggregate_counts",
            "errorIssueCount": error_count,
            "totalPageCount": page_count,
            "usefulPageCount": useful_count,
            "notUsefulPageCount": not_useful_count,
            "noUsefulIssueCount": len(no_useful_issue_ids),
            "noUsefulIssueIds": list(no_useful_issue_ids),
            "sectionCounts": dict(sorted(section_counts.items())),
            "destinationCounts": dict(sorted(destination_counts.items())),
            "parserHintCounts": dict(sorted(parser_hint_counts.items())),
            "issues": [issue.to_dict() for issue in self.issue_summaries],
        }


def build_corpus_refinement_summary(
    issues_dir: Path,
    *,
    limit: int | None = None,
    min_embedded_chars: int = 40,
    current_utc_date: date | str | None = None,
    plan_builder: RefinementPlanBuilder = build_refinement_plan_from_pdf,
) -> CorpusRefinementSummary:
    """Summarize per-issue refinement coverage without returning source text."""

    if limit is not None and limit < 1:
        raise ValueError("limit must be greater than zero")

    corpus_status = build_local_corpus_status(issues_dir)
    selected_issues = corpus_status.matched_issues
    if limit is not None:
        selected_issues = selected_issues[:limit]

    return CorpusRefinementSummary(
        issues_dir=issues_dir,
        folder_exists=corpus_status.folder_exists,
        matched_issue_count=len(corpus_status.matched_issues),
        processed_issue_count=len(selected_issues),
        limit=limit,
        malformed_filenames=corpus_status.malformed_filenames,
        issue_summaries=tuple(
            _summarize_issue(
                issue,
                min_embedded_chars=min_embedded_chars,
                current_utc_date=current_utc_date,
                plan_builder=plan_builder,
            )
            for issue in selected_issues
        ),
    )


def _summarize_issue(
    issue: LocalIssueFile,
    *,
    min_embedded_chars: int,
    current_utc_date: date | str | None,
    plan_builder: RefinementPlanBuilder,
) -> CorpusRefinementIssueSummary:
    try:
        plan = plan_builder(
            issue.path,
            issue_id=issue.issue_id,
            min_embedded_chars=min_embedded_chars,
            current_utc_date=current_utc_date,
        )
    except Exception as error:  # noqa: BLE001 - keep corpus scans partial and safe.
        return CorpusRefinementIssueSummary(
            issue_id=issue.issue_id,
            filename=issue.filename,
            status="error",
            page_count=0,
            useful_page_count=0,
            not_useful_page_count=0,
            section_counts={},
            destination_counts={},
            parser_hint_counts={},
            manual_seed_page_count=0,
            future_parser_page_count=0,
            unknown_page_count=0,
            error_type=type(error).__name__,
        )

    section_counts = Counter(row.section for row in plan.rows)
    destination_counts = Counter(row.suggested_destination for row in plan.rows)
    parser_hint_counts = Counter(row.parser_hint for row in plan.rows)
    useful_count = sum(1 for row in plan.rows if row.useful_info == "yes")
    return CorpusRefinementIssueSummary(
        issue_id=issue.issue_id,
        filename=issue.filename,
        status="ok",
        page_count=len(plan.rows),
        useful_page_count=useful_count,
        not_useful_page_count=len(plan.rows) - useful_count,
        section_counts=dict(sorted(section_counts.items())),
        destination_counts=dict(sorted(destination_counts.items())),
        parser_hint_counts=dict(sorted(parser_hint_counts.items())),
        manual_seed_page_count=parser_hint_counts.get("manual_classification_seed", 0),
        future_parser_page_count=parser_hint_counts.get("future_parser_needed", 0),
        unknown_page_count=section_counts.get("unknown", 0),
        error_type=None,
    )
