"""Exact-value, exact-provenance observation identity for private local review."""

from __future__ import annotations

from hashlib import sha256
import json

EXTRACTION_VERSION = 'tsi-local-v1'
RECORD_TYPES = {'recommendation', 'ranking', 'portfolio_snapshot', 'transaction', 'commentary'}
REVIEW_KEYS = {'review_status', 'review_hash', 'exportable', 'manual_review_required',
               'review_decision', 'approved_at', 'approved_by'}


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def review_fingerprint(record: dict) -> str:
    """Recompute identity from actual evidence; never trust a persisted hash."""
    return _digest({key: value for key, value in record.items() if key not in REVIEW_KEYS})


def review_decision_matches(record: dict, decision: dict) -> bool:
    """Matching evidence does not grant approval or export authority."""
    return decision.get('review_hash') == review_fingerprint(record)


def make_observation(document: dict, record_type: str, page: int, bbox: list,
                     printed_fields: dict, *, as_of_date: str | None = None,
                     transaction_effective_date: str | None = None,
                     strategy: str | None = None, universe: str | None = None,
                     source_text: str = '', extraction_method: str = 'embedded_text',
                     unresolved: list | None = None) -> dict:
    if record_type not in RECORD_TYPES:
        raise ValueError('Unsupported observation type')
    evidence = dict(document_sha256=document['sha256'], page=page, bbox=list(bbox),
                    extraction_method=extraction_method, extraction_version=EXTRACTION_VERSION,
                    source_text_sha256=sha256(source_text.encode()).hexdigest())
    identifiers = {key: printed_fields[key] for key in ('isin', 'wkn', 'ticker')
                   if printed_fields.get(key)}
    # Printed names alone are evidence, not canonical instrument identifiers.
    instrument_id = ('instrument_' + _digest(identifiers)) if identifiers else None
    row = dict(record_type=record_type, document_id=document['document_id'],
               original_publication=document.get('original_publication'),
               product=document.get('product'), publication_date=document.get('publication_date'),
               as_of_date=as_of_date, transaction_effective_date=transaction_effective_date,
               ingested_at=document['ingested_at'], strategy=strategy, universe=universe,
               instrument_id=instrument_id, printed_fields=dict(printed_fields),
               source_text=source_text, evidence=evidence, unresolved=list(unresolved or []))
    row['observation_id'] = 'observation_' + _digest(row)
    row.update(review_status='needs_review', exportable=False, manual_review_required=True)
    row['review_hash'] = review_fingerprint(row)
    return row
