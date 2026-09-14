"""Append-only node and route revisions for the private TEM-FLOW engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
from typing import Iterable, Mapping
from uuid import uuid4


KINDS = {"node", "route"}
STATUSES = {"draft", "approved", "rejected"}


def _datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid ISO date/time: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ObjectRevision:
    revision_id: str
    object_kind: str
    object_id: str
    entered_at: str
    observed_at: str
    effective_at: str
    status: str
    actor: str
    provenance: str
    change_reason: str
    attributes: Mapping[str, object] = field(default_factory=dict)
    supersedes: str | None = None

    def validate(self) -> None:
        if self.object_kind not in KINDS:
            raise ValueError("object_kind must be node or route")
        if self.status not in STATUSES:
            raise ValueError("status must be draft, approved, or rejected")
        for name, value in (
            ("revision_id", self.revision_id),
            ("object_id", self.object_id),
            ("actor", self.actor),
            ("provenance", self.provenance),
        ):
            if not str(value).strip():
                raise ValueError(f"{name} is required")
        _datetime(self.entered_at)
        _datetime(self.observed_at)
        _datetime(self.effective_at)
        if not isinstance(self.attributes, Mapping):
            raise ValueError("attributes must be an object")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ObjectRevision":
        revision = cls(
            revision_id=str(value["revision_id"]),
            object_kind=str(value["object_kind"]),
            object_id=str(value["object_id"]),
            entered_at=str(value["entered_at"]),
            observed_at=str(value["observed_at"]),
            effective_at=str(value["effective_at"]),
            status=str(value["status"]),
            actor=str(value["actor"]),
            provenance=str(value["provenance"]),
            change_reason=str(value.get("change_reason", "")),
            attributes=dict(value.get("attributes", {})),
            supersedes=None if value.get("supersedes") in (None, "") else str(value["supersedes"]),
        )
        revision.validate()
        return revision


class RevisionStore:
    """Thread-safe append-only JSONL store with approved as-of snapshots."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "object_revisions.jsonl"
        self._lock = threading.Lock()

    def records(self) -> tuple[ObjectRevision, ...]:
        if not self.path.exists():
            return ()
        result: list[ObjectRevision] = []
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    result.append(ObjectRevision.from_dict(json.loads(line)))
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(f"invalid revision ledger line {line_number}: {exc}") from exc
        return tuple(result)

    def history(
        self,
        object_kind: str,
        object_id: str,
        *,
        include_drafts: bool = False,
        as_of: str | None = None,
    ) -> tuple[ObjectRevision, ...]:
        cutoff = None if as_of is None else _datetime(as_of)
        records = [
            record
            for record in self.records()
            if record.object_kind == object_kind
            and record.object_id == object_id
            and (include_drafts or record.status == "approved")
            and (cutoff is None or _datetime(record.effective_at) <= cutoff)
        ]
        return tuple(sorted(records, key=lambda record: (_datetime(record.effective_at), _datetime(record.entered_at), record.revision_id)))

    def latest(
        self,
        object_kind: str,
        object_id: str,
        *,
        include_drafts: bool = False,
        as_of: str | None = None,
    ) -> ObjectRevision | None:
        history = self.history(object_kind, object_id, include_drafts=include_drafts, as_of=as_of)
        return history[-1] if history else None

    def append(self, payload: Mapping[str, object]) -> ObjectRevision:
        object_kind = str(payload.get("object_kind", "")).strip()
        object_id = str(payload.get("object_id", "")).strip()
        entered_at = _now()
        effective_at = str(payload.get("effective_at") or payload.get("observed_at") or entered_at)
        observed_at = str(payload.get("observed_at") or effective_at)
        revision_id = str(payload.get("revision_id") or f"{object_kind.upper()}-{object_id}-{uuid4().hex[:12].upper()}")
        revision = ObjectRevision(
            revision_id=revision_id,
            object_kind=object_kind,
            object_id=object_id,
            entered_at=entered_at,
            observed_at=observed_at,
            effective_at=effective_at,
            status=str(payload.get("status", "draft")).strip(),
            actor=str(payload.get("actor", "local-curator")).strip(),
            provenance=str(payload.get("provenance", "")).strip(),
            change_reason=str(payload.get("change_reason", "")).strip(),
            attributes=dict(payload.get("attributes", {})),
            supersedes=None if payload.get("supersedes") in (None, "") else str(payload["supersedes"]),
        )
        revision.validate()
        with self._lock:
            existing = self.records()
            ids = {record.revision_id for record in existing}
            if revision.revision_id in ids:
                raise ValueError(f"duplicate revision_id: {revision.revision_id}")
            if revision.supersedes is not None:
                target = next((record for record in existing if record.revision_id == revision.supersedes), None)
                if target is None:
                    raise ValueError("supersedes must name an existing revision")
                if target.object_kind != revision.object_kind or target.object_id != revision.object_id:
                    raise ValueError("supersedes must refer to the same node or route")
            encoded = json.dumps(revision.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded + "\n")
                handle.flush()
        return revision

    def digest(self, *, approved_only: bool = True) -> str:
        payload: Iterable[ObjectRevision] = self.records()
        if approved_only:
            payload = (record for record in payload if record.status == "approved")
        encoded = json.dumps([record.to_dict() for record in payload], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

