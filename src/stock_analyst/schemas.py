"""Shared data shapes for extracted and reviewed recommendation rows."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class InstrumentType(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    FUND = "fund"
    DERIVATIVE = "derivative"
    COMMODITY = "commodity"
    CRYPTO = "crypto"
    FOREX = "forex"
    OTHER = "other"


class ReviewStatus(str, Enum):
    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class SourceReference:
    issue_id: str
    page: int
    block_id: str | None = None


@dataclass
class RecommendationDraft:
    source: SourceReference
    article_title: str | None = None
    printed_name: str | None = None
    normalized_name: str | None = None
    ticker: str | None = None
    exchange: str | None = None
    isin: str | None = None
    wkn: str | None = None
    instrument_type: InstrumentType = InstrumentType.OTHER
    current_price: str | None = None
    currency: str | None = None
    recommendation_type: str | None = None
    stop_loss: str | None = None
    take_profit_or_target: str | None = None
    horizon: str | None = None
    thesis: str | None = None
    risks: list[str] = field(default_factory=list)
    confidence: float = 0.0
    review_status: ReviewStatus = ReviewStatus.DRAFT

    def requires_review(self) -> bool:
        return (
            self.confidence < 0.85
            or not self.printed_name
            or not (self.ticker or self.isin or self.wkn)
        )

    def mark_review_gate(self) -> None:
        if self.review_status == ReviewStatus.DRAFT and self.requires_review():
            self.review_status = ReviewStatus.NEEDS_REVIEW
