"""Snapshot utilities for selective, time-aware TEM-FLOW updates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .core import channel_share_bounds
from .ledger import CompatibilityDecision, EstimandSpec, EvidenceLedger, EvidenceRecord, compatibility_gate


@dataclass(frozen=True)
class SnapshotEffect:
    as_of: str
    record_id: str
    model_use: str
    output_key: str


def latest_compatible_record(
    ledger: EvidenceLedger, as_of: str, spec: EstimandSpec, model_use: str
) -> EvidenceRecord | None:
    candidates = []
    for record in ledger.active(as_of):
        decision = compatibility_gate(record, spec)
        if decision.compatible and decision.model_use == model_use:
            candidates.append(record)
    if not candidates:
        return None
    return max(candidates, key=lambda record: (record.observed_at, record.entered_at, record.record_id))


def channel_bounds_from_record(record: EvidenceRecord) -> tuple[list[float], list[float]]:
    if record.evidence_type != "share" or record.coverage_lower is None:
        raise ValueError("a share record with coverage_lower is required")
    shares = record.metadata.get("within_channel_shares")
    if not isinstance(shares, (list, tuple)):
        raise ValueError("within_channel_shares must be stored in metadata")
    lower, upper = channel_share_bounds(shares, record.coverage_lower)
    return lower.tolist(), upper.tolist()


def affected_outputs(
    ledger: EvidenceLedger,
    as_of: str,
    specs: Iterable[tuple[str, EstimandSpec]],
) -> tuple[SnapshotEffect, ...]:
    """Return only outputs touched by active compatible records."""
    effects: list[SnapshotEffect] = []
    for record in ledger.active(as_of):
        for output_key, spec in specs:
            decision: CompatibilityDecision = compatibility_gate(record, spec)
            if decision.compatible and decision.model_use not in {"retain_only", "prior"}:
                effects.append(SnapshotEffect(as_of, record.record_id, decision.model_use, output_key))
    return tuple(effects)

