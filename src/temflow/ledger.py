"""Append-only evidence records and deterministic compatibility decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
from typing import Iterable, Mapping, Sequence


def _iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid ISO date/time: {value}") from exc


@dataclass(frozen=True)
class EvidenceRecord:
    record_id: str
    entered_at: str
    observed_at: str
    evidence_type: str
    source_uri: str
    commodity: str
    origin: str | None = None
    destination: str | None = None
    species: str | None = None
    product: str | None = None
    matrix: str | None = None
    stage: str | None = None
    value: float | None = None
    unit: str | None = None
    denominator: str | None = None
    coverage_lower: float | None = None
    supersedes: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.record_id.strip() or not self.source_uri.strip() or not self.commodity.strip():
            raise ValueError("record_id, source_uri and commodity are required")
        _iso(self.entered_at)
        _iso(self.observed_at)
        if self.value is not None and not isinstance(self.value, (int, float)):
            raise ValueError("value must be numeric")
        if self.coverage_lower is not None and not 0 <= self.coverage_lower <= 1:
            raise ValueError("coverage_lower must be in [0, 1]")


@dataclass(frozen=True)
class EstimandSpec:
    commodity: str
    allowed_stages: Sequence[str] = ()
    origin: str | None = None
    destination: str | None = None
    species: str | None = None
    product: str | None = None
    edible_matrices: Sequence[str] = ("muscle", "edible tissue", "whole edible product")
    environmental_matrices: Sequence[str] = ("water", "sediment", "soil")
    required_denominator: str | None = None


@dataclass(frozen=True)
class CompatibilityDecision:
    record_id: str
    compatible: bool
    model_use: str
    reason: str


def compatibility_gate(record: EvidenceRecord, spec: EstimandSpec) -> CompatibilityDecision:
    """Classify a record without discarding incompatible or alert evidence."""
    if record.commodity.casefold() != spec.commodity.casefold():
        return CompatibilityDecision(record.record_id, False, "retain_only", "commodity mismatch")
    for field_name in ("origin", "destination", "species", "product"):
        wanted = getattr(spec, field_name)
        observed = getattr(record, field_name)
        if wanted is not None and observed is not None and wanted.casefold() != observed.casefold():
            return CompatibilityDecision(record.record_id, False, "retain_only", f"{field_name} mismatch")
    if spec.allowed_stages and record.stage not in spec.allowed_stages:
        return CompatibilityDecision(record.record_id, False, "retain_only", "stage mismatch")
    if spec.required_denominator and record.denominator != spec.required_denominator:
        return CompatibilityDecision(record.record_id, False, "retain_only", "denominator mismatch")

    if record.evidence_type == "contaminant":
        matrix = (record.matrix or "").casefold()
        if matrix in {m.casefold() for m in spec.edible_matrices}:
            return CompatibilityDecision(record.record_id, True, "dose", "edible matrix and identity keys match")
        if matrix in {m.casefold() for m in spec.environmental_matrices}:
            return CompatibilityDecision(record.record_id, True, "alert", "environmental matrix is an alert, not an edible dose")
        return CompatibilityDecision(record.record_id, False, "retain_only", "matrix is not valid for edible-dose propagation")
    if record.evidence_type == "route" and record.value is None:
        return CompatibilityDecision(record.record_id, True, "topology", "named route without compatible quantity")
    if record.evidence_type in {"share", "flow", "production", "consumption"}:
        return CompatibilityDecision(record.record_id, True, "constraint", "compatible quantitative evidence")
    return CompatibilityDecision(record.record_id, True, "prior", "compatible ancillary evidence")


class EvidenceLedger:
    """Append-only ledger with supersession and reproducible as-of snapshots."""

    def __init__(self, records: Iterable[EvidenceRecord] = ()) -> None:
        self._records: list[EvidenceRecord] = []
        self._ids: set[str] = set()
        for record in records:
            self.append(record)

    def append(self, record: EvidenceRecord) -> None:
        record.validate()
        if record.record_id in self._ids:
            raise ValueError(f"duplicate record_id: {record.record_id}")
        if record.supersedes is not None and record.supersedes not in self._ids:
            raise ValueError("superseded record must already exist")
        self._records.append(record)
        self._ids.add(record.record_id)

    @property
    def records(self) -> tuple[EvidenceRecord, ...]:
        return tuple(self._records)

    def active(self, as_of: str) -> tuple[EvidenceRecord, ...]:
        cutoff = _iso(as_of)
        eligible = [record for record in self._records if _iso(record.entered_at) <= cutoff]
        superseded = {record.supersedes for record in eligible if record.supersedes is not None}
        return tuple(record for record in eligible if record.record_id not in superseded)

    def digest(self, as_of: str) -> str:
        payload = [asdict(record) for record in self.active(as_of)]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

