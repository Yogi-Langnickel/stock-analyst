"""Metadata-only OCR/page fixture planning.

Fixture definitions describe what reviewers should inspect. Artifact metadata
records whether local render/OCR outputs exist. Neither path returns OCR text or
article text.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Mapping, Sequence

from stock_analyst.intake import calculate_sha256


DEFAULT_OCR_FIXTURE_ISSUE_ID = "DA_2026_03"

PRIVATE_TEXT_KEYS = frozenset(
    {
        "articleText",
        "expectedText",
        "extractedText",
        "lines",
        "ocrText",
        "rawText",
        "sourceText",
        "text",
    }
)


@dataclass(frozen=True)
class OcrFixtureDefinition:
    fixture_id: str
    issue_id: str
    pages: tuple[int, ...]
    expected_section_labels: tuple[str, ...]
    intended_extraction_targets: tuple[str, ...]
    priority: str = "high"
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "fixtureId": self.fixture_id,
            "issueId": self.issue_id,
            "pages": list(self.pages),
            "expectedSectionLabels": list(self.expected_section_labels),
            "intendedExtractionTargets": list(self.intended_extraction_targets),
            "priority": self.priority,
        }
        if self.notes:
            result["notes"] = list(self.notes)
        return result


@dataclass(frozen=True)
class OcrArtifactMetadata:
    status: str
    path: Path | None = None
    sha256: str | None = None
    byte_count: int | None = None
    char_count: int | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"status": self.status}
        if self.path is not None:
            result["path"] = str(self.path)
        if self.sha256 is not None:
            result["sha256"] = self.sha256
        if self.byte_count is not None:
            result["byteCount"] = self.byte_count
        if self.char_count is not None:
            result["charCount"] = self.char_count
        return result


@dataclass(frozen=True)
class OcrFixturePageArtifacts:
    page_number: int
    render: OcrArtifactMetadata
    ocr_text: OcrArtifactMetadata

    def to_dict(self) -> dict[str, object]:
        return {
            "page": self.page_number,
            "render": self.render.to_dict(),
            "ocrText": self.ocr_text.to_dict(),
        }


@dataclass(frozen=True)
class OcrFixtureReviewItem:
    definition: OcrFixtureDefinition
    page_artifacts: tuple[OcrFixturePageArtifacts, ...]

    @property
    def render_available_count(self) -> int:
        return sum(1 for page in self.page_artifacts if page.render.status == "available")

    @property
    def ocr_text_available_count(self) -> int:
        return sum(1 for page in self.page_artifacts if page.ocr_text.status == "available")

    def to_dict(self) -> dict[str, object]:
        result = self.definition.to_dict()
        result["artifactSummary"] = {
            "pageCount": len(self.page_artifacts),
            "renderAvailableCount": self.render_available_count,
            "ocrTextAvailableCount": self.ocr_text_available_count,
        }
        result["pageArtifacts"] = [page.to_dict() for page in self.page_artifacts]
        return result


@dataclass(frozen=True)
class OcrFixtureReviewPlan:
    issue_id: str
    fixture_source: str
    fixtures: tuple[OcrFixtureReviewItem, ...]
    pdf_path: Path | None = None
    pdf_checksum_sha256: str | None = None
    artifact_dir: Path | None = None

    @property
    def unique_pages(self) -> tuple[int, ...]:
        pages = [
            page
            for fixture in self.fixtures
            for page in fixture.definition.pages
        ]
        return tuple(dict.fromkeys(sorted(pages)))

    @property
    def review_planning(self) -> "OcrFixtureArtifactReviewPlanning":
        return build_artifact_review_planning(self)

    def to_dict(self) -> dict[str, object]:
        render_available_count = sum(
            fixture.render_available_count for fixture in self.fixtures
        )
        ocr_text_available_count = sum(
            fixture.ocr_text_available_count for fixture in self.fixtures
        )
        result: dict[str, object] = {
            "issueId": self.issue_id,
            "fixtureSource": self.fixture_source,
            "privacyMode": "metadata_only",
            "externalServicesEnabled": False,
            "networkAccess": False,
            "fixtureCount": len(self.fixtures),
            "uniquePages": list(self.unique_pages),
            "uniquePageCount": len(self.unique_pages),
            "renderAvailableCount": render_available_count,
            "ocrTextAvailableCount": ocr_text_available_count,
            "artifactReviewPlanning": self.review_planning.to_dict(),
            "fixtures": [fixture.to_dict() for fixture in self.fixtures],
        }
        if self.pdf_path is not None:
            result["pdfPath"] = str(self.pdf_path)
        if self.pdf_checksum_sha256 is not None:
            result["pdfChecksumSha256"] = self.pdf_checksum_sha256
        if self.artifact_dir is not None:
            result["artifactDir"] = str(self.artifact_dir)
        return result


@dataclass(frozen=True)
class OcrFixtureArtifactAvailability:
    available_pages: tuple[int, ...]
    missing_pages: tuple[int, ...]
    not_configured_pages: tuple[int, ...]

    @property
    def available_count(self) -> int:
        return len(self.available_pages)

    @property
    def missing_count(self) -> int:
        return len(self.missing_pages)

    @property
    def not_configured_count(self) -> int:
        return len(self.not_configured_pages)

    def to_dict(self) -> dict[str, object]:
        return {
            "availablePages": list(self.available_pages),
            "missingPages": list(self.missing_pages),
            "notConfiguredPages": list(self.not_configured_pages),
            "availableCount": self.available_count,
            "missingCount": self.missing_count,
            "notConfiguredCount": self.not_configured_count,
        }


@dataclass(frozen=True)
class OcrFixtureReviewCommand:
    purpose: str
    pages: tuple[int, ...]
    command: str

    def to_dict(self) -> dict[str, object]:
        return {
            "purpose": self.purpose,
            "pages": list(self.pages),
            "pageSelection": format_page_selection(self.pages),
            "command": self.command,
        }


@dataclass(frozen=True)
class OcrFixtureArtifactReviewPlanning:
    status: str
    render: OcrFixtureArtifactAvailability
    ocr_text: OcrFixtureArtifactAvailability
    commands: tuple[OcrFixtureReviewCommand, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "render": self.render.to_dict(),
            "ocrText": self.ocr_text.to_dict(),
            "commands": [command.to_dict() for command in self.commands],
        }


DEFAULT_OCR_FIXTURES: tuple[OcrFixtureDefinition, ...] = (
    OcrFixtureDefinition(
        fixture_id="da-2026-03-p018-p019-dividend-focus",
        issue_id=DEFAULT_OCR_FIXTURE_ISSUE_ID,
        pages=(18, 19),
        expected_section_labels=("Dividend strategy table",),
        intended_extraction_targets=("Dividend Focus", "Extraction Audit"),
        notes=("Review table row boundaries and optional valuation cells.",),
    ),
    OcrFixtureDefinition(
        fixture_id="da-2026-03-p022-recommendation-cards",
        issue_id=DEFAULT_OCR_FIXTURE_ISSUE_ID,
        pages=(22,),
        expected_section_labels=("Recommendation card page",),
        intended_extraction_targets=("Stocks", "Derivative Tips", "Extraction Audit"),
        notes=("Review labelled card fields and source page references.",),
    ),
    OcrFixtureDefinition(
        fixture_id="da-2026-03-p037-chart-check",
        issue_id=DEFAULT_OCR_FIXTURE_ISSUE_ID,
        pages=(37,),
        expected_section_labels=("Chart Check",),
        intended_extraction_targets=("Chart Check", "Stocks", "Extraction Audit"),
        notes=("Review chart table fields without treating commentary as approved rows.",),
    ),
    OcrFixtureDefinition(
        fixture_id="da-2026-03-p061-p063-derivative-overview",
        issue_id=DEFAULT_OCR_FIXTURE_ISSUE_ID,
        pages=(61, 62, 63),
        expected_section_labels=("Derivative overview",),
        intended_extraction_targets=("Derivative Tips", "Extraction Audit"),
        notes=("Review base rows and retrospective metric alignment.",),
    ),
    OcrFixtureDefinition(
        fixture_id="da-2026-03-p066-depot",
        issue_id=DEFAULT_OCR_FIXTURE_ISSUE_ID,
        pages=(66,),
        expected_section_labels=("AKTIONAER depot", "Depot transactions"),
        intended_extraction_targets=(
            "AKTIONAER Depot",
            "Depot Transactions",
            "Extraction Audit",
        ),
        notes=("Review position and transaction boundaries as separate surfaces.",),
    ),
    OcrFixtureDefinition(
        fixture_id="da-2026-03-p078-p089-stock-review-pages",
        issue_id=DEFAULT_OCR_FIXTURE_ISSUE_ID,
        pages=tuple(range(78, 90)),
        expected_section_labels=("Stock review pages", "Chart Check", "Quick Check"),
        intended_extraction_targets=("Stocks", "Chart Check", "Stock Quickcheck"),
        notes=("Review high-value stock sections before broad parser expansion.",),
    ),
)


def build_ocr_fixture_review_plan(
    *,
    issue_id: str | None = None,
    pdf_path: Path | None = None,
    artifact_dir: Path | None = None,
    fixture_manifest: Path | None = None,
) -> OcrFixtureReviewPlan:
    definitions = (
        load_ocr_fixture_definitions(fixture_manifest)
        if fixture_manifest is not None
        else DEFAULT_OCR_FIXTURES
    )
    resolved_issue_id = issue_id or _issue_id_from_definitions(definitions)
    selected_definitions = tuple(
        definition for definition in definitions if definition.issue_id == resolved_issue_id
    )
    if not selected_definitions:
        raise ValueError(f"no OCR fixture definitions found for issue: {resolved_issue_id}")

    checksum = None
    if pdf_path is not None and pdf_path.exists():
        checksum = calculate_sha256(pdf_path)

    fixtures = tuple(
        OcrFixtureReviewItem(
            definition=definition,
            page_artifacts=tuple(
                build_page_artifact_metadata(
                    pdf_path=pdf_path,
                    artifact_dir=artifact_dir,
                    page_number=page_number,
                )
                for page_number in definition.pages
            ),
        )
        for definition in selected_definitions
    )

    return OcrFixtureReviewPlan(
        issue_id=resolved_issue_id,
        fixture_source=str(fixture_manifest) if fixture_manifest is not None else "default",
        pdf_path=pdf_path,
        pdf_checksum_sha256=checksum,
        artifact_dir=artifact_dir,
        fixtures=fixtures,
    )


def load_ocr_fixture_definitions(manifest_path: Path) -> tuple[OcrFixtureDefinition, ...]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    reject_private_text_payload(payload)
    if not isinstance(payload, Mapping):
        raise ValueError(f"OCR fixture manifest must be a JSON object: {manifest_path}")
    raw_fixtures = payload.get("fixtures")
    if not isinstance(raw_fixtures, list):
        raise ValueError("OCR fixture manifest must contain a fixtures list")

    default_issue_id = _string_value(payload.get("issueId")) or DEFAULT_OCR_FIXTURE_ISSUE_ID
    definitions = tuple(
        _definition_from_mapping(raw_fixture, default_issue_id=default_issue_id)
        for raw_fixture in raw_fixtures
    )
    if not definitions:
        raise ValueError("OCR fixture manifest must define at least one fixture")
    return definitions


def reject_private_text_payload(payload: object, *, path: str = "$") -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if str(key) in PRIVATE_TEXT_KEYS:
                raise ValueError(
                    f"OCR fixture manifest is metadata-only; remove private text key {path}.{key}"
                )
            reject_private_text_payload(value, path=f"{path}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            reject_private_text_payload(value, path=f"{path}[{index}]")


def build_page_artifact_metadata(
    *,
    pdf_path: Path | None,
    artifact_dir: Path | None,
    page_number: int,
) -> OcrFixturePageArtifacts:
    if pdf_path is None or artifact_dir is None:
        return OcrFixturePageArtifacts(
            page_number=page_number,
            render=OcrArtifactMetadata(status="not_configured"),
            ocr_text=OcrArtifactMetadata(status="not_configured"),
        )

    render_path, ocr_text_path = expected_visual_ocr_artifact_paths(
        pdf_path,
        artifact_dir=artifact_dir,
        page_number=page_number,
    )
    return OcrFixturePageArtifacts(
        page_number=page_number,
        render=_file_artifact_metadata(render_path, count_text_chars=False),
        ocr_text=_file_artifact_metadata(ocr_text_path, count_text_chars=True),
    )


def build_artifact_review_planning(
    plan: OcrFixtureReviewPlan,
) -> OcrFixtureArtifactReviewPlanning:
    render = _availability_by_page(plan, artifact_name="render")
    ocr_text = _availability_by_page(plan, artifact_name="ocr_text")
    commands = _missing_artifact_commands(plan, render=render, ocr_text=ocr_text)

    status = "complete"
    if render.not_configured_pages or ocr_text.not_configured_pages:
        status = "not_configured"
    elif render.missing_pages or ocr_text.missing_pages:
        status = "missing_artifacts"

    return OcrFixtureArtifactReviewPlanning(
        status=status,
        render=render,
        ocr_text=ocr_text,
        commands=commands,
    )


def expected_visual_ocr_artifact_paths(
    pdf_path: Path,
    *,
    artifact_dir: Path,
    page_number: int,
) -> tuple[Path, Path]:
    digest = sha256(str(pdf_path.name).encode("utf-8")).hexdigest()[:8]
    stem = f"{pdf_path.stem}-{digest}-p{page_number:03d}"
    return artifact_dir / f"{stem}.png", artifact_dir / f"{stem}.ocr.txt"


def format_page_selection(pages: Sequence[int]) -> str:
    """Return a deterministic compact page/range expression for CLI use."""

    selected = tuple(dict.fromkeys(sorted(pages)))
    if not selected:
        return ""

    ranges: list[str] = []
    start = selected[0]
    previous = selected[0]
    for page in selected[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append(_format_page_range(start, previous))
        start = previous = page
    ranges.append(_format_page_range(start, previous))
    return ",".join(ranges)


def _definition_from_mapping(
    value: object,
    *,
    default_issue_id: str,
) -> OcrFixtureDefinition:
    if not isinstance(value, Mapping):
        raise ValueError("each OCR fixture must be a JSON object")
    fixture_id = _required_string(value, "fixtureId")
    issue_id = _string_value(value.get("issueId")) or default_issue_id
    pages = _pages_from_value(value.get("pages"))
    labels = _string_tuple(value.get("expectedSectionLabels"), "expectedSectionLabels")
    targets = _string_tuple(value.get("intendedExtractionTargets"), "intendedExtractionTargets")
    priority = _string_value(value.get("priority")) or "high"
    notes = _string_tuple(value.get("notes", ()), "notes", allow_empty=True)
    return OcrFixtureDefinition(
        fixture_id=fixture_id,
        issue_id=issue_id,
        pages=pages,
        expected_section_labels=labels,
        intended_extraction_targets=targets,
        priority=priority,
        notes=notes,
    )


def _availability_by_page(
    plan: OcrFixtureReviewPlan,
    *,
    artifact_name: str,
) -> OcrFixtureArtifactAvailability:
    statuses: dict[int, str] = {}
    for fixture in plan.fixtures:
        for page_artifact in fixture.page_artifacts:
            metadata = getattr(page_artifact, artifact_name)
            statuses[page_artifact.page_number] = metadata.status

    available_pages = tuple(
        page for page in plan.unique_pages if statuses.get(page) == "available"
    )
    missing_pages = tuple(
        page for page in plan.unique_pages if statuses.get(page) == "missing"
    )
    not_configured_pages = tuple(
        page for page in plan.unique_pages if statuses.get(page) == "not_configured"
    )
    return OcrFixtureArtifactAvailability(
        available_pages=available_pages,
        missing_pages=missing_pages,
        not_configured_pages=not_configured_pages,
    )


def _missing_artifact_commands(
    plan: OcrFixtureReviewPlan,
    *,
    render: OcrFixtureArtifactAvailability,
    ocr_text: OcrFixtureArtifactAvailability,
) -> tuple[OcrFixtureReviewCommand, ...]:
    if plan.pdf_path is None or plan.artifact_dir is None:
        return ()

    commands: list[OcrFixtureReviewCommand] = []
    if render.missing_pages:
        commands.append(
            _visual_ocr_command(
                purpose="render_missing_pages",
                pdf_path=plan.pdf_path,
                artifact_dir=plan.artifact_dir,
                pages=render.missing_pages,
                ocr=False,
            )
        )
    if ocr_text.missing_pages:
        commands.append(
            _visual_ocr_command(
                purpose="ocr_missing_pages",
                pdf_path=plan.pdf_path,
                artifact_dir=plan.artifact_dir,
                pages=ocr_text.missing_pages,
                ocr=True,
            )
        )
    return tuple(commands)


def _visual_ocr_command(
    *,
    purpose: str,
    pdf_path: Path,
    artifact_dir: Path,
    pages: tuple[int, ...],
    ocr: bool,
) -> OcrFixtureReviewCommand:
    command_parts = [
        "scripts/stock-analyst",
        "visual-ocr-review",
        str(pdf_path),
        "--pages",
        format_page_selection(pages),
        "--render",
    ]
    if ocr:
        command_parts.extend(("--ocr", "--write-ocr-text"))
    command_parts.extend(("--output-dir", str(artifact_dir)))
    return OcrFixtureReviewCommand(
        purpose=purpose,
        pages=pages,
        command=" ".join(shlex.quote(part) for part in command_parts),
    )


def _file_artifact_metadata(path: Path, *, count_text_chars: bool) -> OcrArtifactMetadata:
    if not path.exists():
        return OcrArtifactMetadata(status="missing", path=path)
    content = path.read_bytes()
    char_count = None
    if count_text_chars:
        char_count = len(content.decode("utf-8", errors="replace"))
    return OcrArtifactMetadata(
        status="available",
        path=path,
        sha256=sha256(content).hexdigest(),
        byte_count=len(content),
        char_count=char_count,
    )


def _format_page_range(start: int, end: int) -> str:
    if start == end:
        return str(start)
    return f"{start}-{end}"


def _issue_id_from_definitions(definitions: Sequence[OcrFixtureDefinition]) -> str:
    if not definitions:
        return DEFAULT_OCR_FIXTURE_ISSUE_ID
    return definitions[0].issue_id


def _pages_from_value(value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise ValueError("fixture pages must be a list of positive integers")
    pages: list[int] = []
    for page in value:
        if not isinstance(page, int) or page < 1:
            raise ValueError("fixture pages must be positive integers")
        pages.append(page)
    if not pages:
        raise ValueError("fixture pages must not be empty")
    return tuple(dict.fromkeys(pages))


def _string_tuple(
    value: object,
    field_name: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list of strings")
    values = tuple(
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    )
    if not values and not allow_empty:
        raise ValueError(f"{field_name} must contain at least one non-empty string")
    return values


def _required_string(value: Mapping[str, object], field_name: str) -> str:
    string_value = _string_value(value.get(field_name))
    if string_value is None:
        raise ValueError(f"{field_name} must be a non-empty string")
    return string_value


def _string_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
