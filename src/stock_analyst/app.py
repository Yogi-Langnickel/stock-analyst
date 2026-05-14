"""Minimal API placeholder for the Stock Analyst local prototype."""

from __future__ import annotations

from pathlib import Path

from stock_analyst.pipeline import calculate_processing_steps


def health() -> dict[str, str]:
    return {"status": "ok", "service": "stock-analyst"}


def preview_processing_plan(filename: str) -> dict[str, object]:
    path = Path(filename)
    return {"filename": path.name, "steps": calculate_processing_steps(path)}
