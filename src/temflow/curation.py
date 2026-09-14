"""Append-only topology curation and approval-gated AI intake.

The frozen TEM-FLOW registers remain package data.  Records written here are
private, additive user records and are never allowed to alter those registers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4


KINDS = {"node", "route"}
TOPOLOGY_STATUSES = {"draft", "approved", "rejected"}
PROPOSAL_DECISIONS = {"approved", "rejected"}
AI_PROMPT_VERSION = "temflow-evidence-extraction-v1"


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


def _clean_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_").upper()
    return cleaned[:44]


@dataclass(frozen=True)
class TopologyRecord:
    record_id: str
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
    source: str = "manual-curator"
    proposal_id: str | None = None
    supersedes: str | None = None

    def validate(self) -> None:
        if self.object_kind not in KINDS:
            raise ValueError("object_kind must be node or route")
        if self.status not in TOPOLOGY_STATUSES:
            raise ValueError("status must be draft, approved, or rejected")
        for name, value in (
            ("record_id", self.record_id),
            ("object_id", self.object_id),
            ("actor", self.actor),
            ("provenance", self.provenance),
            ("change_reason", self.change_reason),
        ):
            if not str(value).strip():
                raise ValueError(f"{name} is required")
        _datetime(self.entered_at)
        _datetime(self.observed_at)
        _datetime(self.effective_at)
        if not isinstance(self.attributes, Mapping):
            raise ValueError("attributes must be an object")
        if str(self.attributes.get("id", "")) != self.object_id:
            raise ValueError("attributes.id must equal object_id")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "TopologyRecord":
        record = cls(
            record_id=str(value["record_id"]),
            object_kind=str(value["object_kind"]),
            object_id=str(value["object_id"]),
            entered_at=str(value["entered_at"]),
            observed_at=str(value["observed_at"]),
            effective_at=str(value["effective_at"]),
            status=str(value["status"]),
            actor=str(value["actor"]),
            provenance=str(value["provenance"]),
            change_reason=str(value["change_reason"]),
            attributes=dict(value.get("attributes", {})),
            source=str(value.get("source", "manual-curator")),
            proposal_id=None if value.get("proposal_id") in (None, "") else str(value["proposal_id"]),
            supersedes=None if value.get("supersedes") in (None, "") else str(value["supersedes"]),
        )
        record.validate()
        return record


class TopologyStore:
    """Thread-safe append-only store of private nodes and routes."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "topology_objects.jsonl"
        self._lock = threading.Lock()

    def records(self) -> tuple[TopologyRecord, ...]:
        if not self.path.exists():
            return ()
        records: list[TopologyRecord] = []
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    records.append(TopologyRecord.from_dict(json.loads(line)))
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(f"invalid topology ledger line {line_number}: {exc}") from exc
        return tuple(records)

    def latest(self, object_kind: str, object_id: str, *, include_drafts: bool = False) -> TopologyRecord | None:
        candidates = [
            record
            for record in self.records()
            if record.object_kind == object_kind
            and record.object_id == object_id
            and (include_drafts or record.status == "approved")
            and record.status != "rejected"
        ]
        return max(candidates, key=lambda record: (_datetime(record.effective_at), _datetime(record.entered_at), record.record_id), default=None)

    def objects(self, *, include_drafts: bool = False, as_of: str | None = None) -> dict[str, dict[str, TopologyRecord]]:
        cutoff = _datetime(as_of) if as_of else None
        grouped: dict[str, dict[str, list[TopologyRecord]]] = {"node": {}, "route": {}}
        for record in self.records():
            if cutoff is not None and _datetime(record.effective_at) > cutoff:
                continue
            if record.status == "rejected" or (not include_drafts and record.status != "approved"):
                continue
            grouped[record.object_kind].setdefault(record.object_id, []).append(record)
        result: dict[str, dict[str, TopologyRecord]] = {"node": {}, "route": {}}
        for kind, objects in grouped.items():
            for object_id, records in objects.items():
                result[kind][object_id] = max(
                    records,
                    key=lambda record: (_datetime(record.effective_at), _datetime(record.entered_at), record.record_id),
                )
        return result

    def append(self, payload: Mapping[str, object]) -> TopologyRecord:
        object_kind = str(payload.get("object_kind", "")).strip().casefold()
        attributes = dict(payload.get("attributes", {}))
        object_id = str(payload.get("object_id") or attributes.get("id") or "").strip()
        if not object_id:
            label = _clean_id(str(attributes.get("name", ""))) or uuid4().hex[:12].upper()
            object_id = f"USR_{object_kind.upper()}_{label}_{uuid4().hex[:6].upper()}"
        attributes["id"] = object_id
        entered_at = _now()
        effective_at = str(payload.get("effective_at") or payload.get("observed_at") or entered_at)
        observed_at = str(payload.get("observed_at") or effective_at)
        record = TopologyRecord(
            record_id=str(payload.get("record_id") or f"TOPO_{object_kind.upper()}_{uuid4().hex[:16].upper()}"),
            object_kind=object_kind,
            object_id=object_id,
            entered_at=entered_at,
            observed_at=observed_at,
            effective_at=effective_at,
            status=str(payload.get("status", "draft")).strip().casefold(),
            actor=str(payload.get("actor", "private-engine-curator")).strip(),
            provenance=str(payload.get("provenance", "")).strip(),
            change_reason=str(payload.get("change_reason", "")).strip(),
            attributes=attributes,
            source=str(payload.get("source", "manual-curator")).strip(),
            proposal_id=None if payload.get("proposal_id") in (None, "") else str(payload["proposal_id"]),
            supersedes=None if payload.get("supersedes") in (None, "") else str(payload["supersedes"]),
        )
        record.validate()
        with self._lock:
            existing = self.records()
            if any(item.record_id == record.record_id for item in existing):
                raise ValueError(f"duplicate topology record_id: {record.record_id}")
            same_object = [item for item in existing if item.object_kind == object_kind and item.object_id == object_id]
            if same_object:
                if record.supersedes is None:
                    raise ValueError("an existing user object requires an explicit supersedes record")
                target = next((item for item in same_object if item.record_id == record.supersedes), None)
                if target is None:
                    raise ValueError("supersedes must name a record for the same user object")
            encoded = json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded + "\n")
                handle.flush()
        return record

    def digest(self, *, approved_only: bool = True) -> str:
        values: Iterable[TopologyRecord] = self.records()
        if approved_only:
            values = (record for record in values if record.status == "approved")
        encoded = json.dumps([record.to_dict() for record in values], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class AIProposalStore:
    """Append-only proposal and human-decision events."""

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "ai_proposals.jsonl"
        self._lock = threading.Lock()

    def events(self) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            return ()
        events: list[dict[str, Any]] = []
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    if event.get("event") not in {"proposal", "decision"}:
                        raise ValueError("event must be proposal or decision")
                    _datetime(str(event["entered_at"]))
                    if not str(event.get("proposal_id", "")).strip():
                        raise ValueError("proposal_id is required")
                    events.append(event)
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(f"invalid AI proposal ledger line {line_number}: {exc}") from exc
        return tuple(events)

    def create(self, payload: Mapping[str, object]) -> dict[str, Any]:
        candidate = payload.get("candidate")
        if not isinstance(candidate, Mapping):
            raise ValueError("candidate must be a structured object")
        candidate_kind = str(candidate.get("candidate_kind", "")).strip().casefold()
        if candidate_kind not in {"node", "route", "revision"}:
            raise ValueError("candidate_kind must be node, route, or revision")
        source_uri = str(payload.get("source_uri", "")).strip()
        if not source_uri:
            raise ValueError("source_uri or an explicit local provenance identifier is required")
        source_text = str(payload.get("source_text", ""))
        if not source_text.strip():
            raise ValueError("source_text is required so the proposal remains reviewable")
        proposal = {
            "event": "proposal",
            "proposal_id": str(payload.get("proposal_id") or f"AIP_{uuid4().hex[:16].upper()}"),
            "entered_at": _now(),
            "actor": str(payload.get("actor", "private-engine-curator")).strip(),
            "source_uri": source_uri,
            "source_text": source_text,
            "source_text_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
            "candidate": dict(candidate),
            "ai_metadata": dict(payload.get("ai_metadata", {})),
        }
        with self._lock:
            if any(event["proposal_id"] == proposal["proposal_id"] and event["event"] == "proposal" for event in self.events()):
                raise ValueError("duplicate proposal_id")
            self._write(proposal)
        return proposal

    def decide(self, proposal_id: str, decision: str, actor: str, note: str, activation: Mapping[str, object] | None = None) -> dict[str, Any]:
        decision = decision.strip().casefold()
        if decision not in PROPOSAL_DECISIONS:
            raise ValueError("decision must be approved or rejected")
        if not note.strip():
            raise ValueError("a human review note is required")
        current = self.current(proposal_id)
        if current is None:
            raise ValueError("unknown proposal_id")
        if current["status"] != "pending":
            raise ValueError("proposal already has a human decision")
        event = {
            "event": "decision",
            "proposal_id": proposal_id,
            "entered_at": _now(),
            "actor": actor.strip() or "private-engine-curator",
            "decision": decision,
            "note": note.strip(),
            "activation": dict(activation or {}),
        }
        with self._lock:
            self._write(event)
        return event

    def _write(self, value: Mapping[str, object]) -> None:
        encoded = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded + "\n")
            handle.flush()

    def proposals(self) -> list[dict[str, Any]]:
        proposals: dict[str, dict[str, Any]] = {}
        for event in self.events():
            proposal_id = str(event["proposal_id"])
            if event["event"] == "proposal":
                proposals[proposal_id] = {**event, "status": "pending", "decision_event": None}
            elif proposal_id in proposals:
                proposals[proposal_id]["status"] = event["decision"]
                proposals[proposal_id]["decision_event"] = event
        return sorted(proposals.values(), key=lambda item: (item["entered_at"], item["proposal_id"]), reverse=True)

    def current(self, proposal_id: str) -> dict[str, Any] | None:
        return next((item for item in self.proposals() if item["proposal_id"] == proposal_id), None)

    def digest(self) -> str:
        encoded = json.dumps(list(self.events()), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class AIProviderConfig:
    base_url: str
    model: str
    api_key: str
    timeout_seconds: float = 60.0

    @classmethod
    def from_environment(cls) -> "AIProviderConfig":
        return cls(
            base_url=os.environ.get("TEMFLOW_AI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            model=os.environ.get("TEMFLOW_AI_MODEL", "").strip(),
            api_key=os.environ.get("TEMFLOW_AI_API_KEY", "").strip(),
            timeout_seconds=float(os.environ.get("TEMFLOW_AI_TIMEOUT_SECONDS", "60")),
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)

    def public_metadata(self) -> dict[str, object]:
        parsed = urlparse(self.base_url)
        return {
            "configured": self.configured,
            "model": self.model if self.configured else "",
            "provider_host": parsed.hostname or "",
            "prompt_version": AI_PROMPT_VERSION,
            "secrets_exposed_to_browser": False,
        }


def _json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("AI provider did not return one valid JSON object") from exc
    if not isinstance(decoded, dict):
        raise ValueError("AI provider response must be a JSON object")
    return decoded


def extract_candidate(config: AIProviderConfig, *, source_uri: str, source_text: str, requested_kind: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call a server-side OpenAI-compatible provider and return a proposal only."""
    if not config.configured:
        raise ValueError("AI provider is not configured on the private server")
    requested_kind = requested_kind.strip().casefold()
    if requested_kind not in {"node", "route", "revision", "auto"}:
        raise ValueError("requested_kind must be node, route, revision, or auto")
    if not source_uri.strip() or not source_text.strip():
        raise ValueError("source_uri and source_text are required")
    system = (
        "You extract one auditable TEM-FLOW curation candidate from supplied evidence. "
        "Never infer a route, coordinate, contaminant, quantity, consumption value, threshold, or date that is not explicit. "
        "Return JSON only. candidate_kind must be node, route, or revision. "
        "For a node include name, iso3, roles, food_domains, commodity, product_form, lon, lat, observed_at, provenance, and change_reason. "
        "For a route include from_node_id, to_node_id, food_domains, commodity, evidence_class, quantity, quantity_period, observed_at, provenance, and change_reason. "
        "For a revision include object_kind, object_id, observed_at, effective_at, provenance, change_reason, and attributes. "
        "Use null for an explicit missing value and preserve uncertainty or ambiguity in a warnings array."
    )
    user = f"Requested candidate kind: {requested_kind}\nSource identifier: {source_uri}\nEvidence text:\n{source_text}"
    body = json.dumps(
        {
            "model": config.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
    ).encode("utf-8")
    request = Request(
        f"{config.base_url}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=config.timeout_seconds) as response:  # noqa: S310 - curator-controlled server configuration
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ValueError(f"AI provider returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise ValueError(f"AI provider connection failed: {exc.reason}") from exc
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("AI provider response omitted choices[0].message.content") from exc
    candidate = _json_object(str(content))
    if candidate.get("candidate_kind") not in {"node", "route", "revision"}:
        raise ValueError("AI candidate_kind must be node, route, or revision")
    metadata = {
        **config.public_metadata(),
        "extracted_at": _now(),
        "response_id": str(result.get("id", "")),
        "source_text_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "human_approval_required": True,
    }
    return candidate, metadata

