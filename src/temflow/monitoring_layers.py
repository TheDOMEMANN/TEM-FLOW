"""Privacy-preserving summaries for optional TEM-FLOW monitoring layers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


LAYER_KEYS = (
    "err",
    "cpc_compatibility",
    "contaminant_trace",
    "exposure_scenario",
    "market_access",
    "flow_irregularity",
    "postharvest_loss",
    "supply_continuity",
    "price_affordability",
)

PRIVATE_MONITORING_KEYS = LAYER_KEYS[4:]
TRIGGER_STATUSES = {"alert", "exceeded", "irregular", "disrupted", "critical", "warning"}


def normalize_layer_selection(value: object) -> dict[str, bool]:
    """Return a complete, stable layer selection with privacy-safe defaults."""
    if not isinstance(value, Mapping):
        # Preserve the pre-layer API contract for programmatic clients. The UI
        # always sends an explicit selection with optional layers off.
        return {key: key in LAYER_KEYS[:4] for key in LAYER_KEYS}
    return {key: bool(value.get(key, key == "err")) for key in LAYER_KEYS}


def summarize_private_layers(selection: Mapping[str, bool], payload: object) -> dict[str, dict[str, Any]]:
    """Summarize optional records without returning their potentially sensitive values."""
    data = payload if isinstance(payload, Mapping) else {}
    results: dict[str, dict[str, Any]] = {}
    for key in PRIVATE_MONITORING_KEYS:
        if not selection.get(key, False):
            results[key] = {"status": "excluded_by_user", "record_count": 0, "trigger_count": 0}
            continue
        raw_records = data.get(key, [])
        if not isinstance(raw_records, list):
            raise ValueError(f"private_layer_data.{key} must be an array")
        triggers = sum(
            bool(record.get("trigger"))
            or str(record.get("status", "")).casefold() in TRIGGER_STATUSES
            for record in raw_records
            if isinstance(record, Mapping)
        )
        results[key] = {
            "status": "monitoring_active" if raw_records else "awaiting_private_file",
            "record_count": len(raw_records),
            "trigger_count": triggers,
        }
    return results
