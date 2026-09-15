"""Validated CSV intake for dated TEM-FLOW records.

The converter is deliberately separate from the numerical engine.  It turns a
human-editable, wide CSV table into the same private-layer JSON object already
accepted by the model workflow; it does not infer missing values or construct
ERR constraints from observations.
"""

from __future__ import annotations

import csv
import io
import math
import re
from datetime import datetime
from typing import Mapping


OBJECT_LAYERS = {"cpc_compatibility", "exposure_scenario"}
ARRAY_LAYERS = {
    "od_evidence",
    "contaminant_trace",
    "market_access",
    "flow_irregularity",
    "postharvest_loss",
    "supply_continuity",
    "price_affordability",
}
SUPPORTED_LAYERS = OBJECT_LAYERS | ARRAY_LAYERS
REQUIRED_COLUMNS = {"layer", "record_id", "observed_at"}

TEXT_FIELDS = {
    "layer", "record_id", "observed_at", "status", "node_id", "route_id",
    "source_node_id", "origin", "destination", "country", "iso3",
    "food_domain", "commodity", "product_form", "material", "period",
    "denominator", "unit", "mass_unit_period", "mass_basis",
    "population_basis", "chemistry_basis", "evidence_ids", "provenance",
    "source_uri", "certificate_id", "claim_boundary", "notes",
}
NUMERIC_FIELDS = {
    "value", "lower", "upper", "reported_mass", "quantity",
    "identified_lower", "identified_upper", "measured_lower", "measured_upper",
    "allocated_mass_lower_kg_year", "allocated_mass_upper_kg_year",
    "retained_mass_lower_kg_year", "retained_mass_upper_kg_year",
    "consumer_population", "concentration_mg_per_kg_food", "body_weight_kg",
    "reference_dose_mg_per_kg_day", "declared_thq_threshold",
}
BOOLEAN_FIELDS = {"trigger", "requested"}
ALLOWED_COLUMNS = TEXT_FIELDS | NUMERIC_FIELDS | BOOLEAN_FIELDS
INTERVAL_PAIRS = (
    ("lower", "upper"),
    ("identified_lower", "identified_upper"),
    ("measured_lower", "measured_upper"),
    ("allocated_mass_lower_kg_year", "allocated_mass_upper_kg_year"),
    ("retained_mass_lower_kg_year", "retained_mass_upper_kg_year"),
)
TRUE_VALUES = {"1", "true", "yes", "y"}
FALSE_VALUES = {"0", "false", "no", "n"}


def _header(value: object) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold())).strip("_")


def _number(value: str, field: str, row_number: int) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"row {row_number}: {field} must be a number") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"row {row_number}: {field} must be finite and non-negative")
    return number


def _boolean(value: str, field: str, row_number: int) -> bool:
    normalized = value.strip().casefold()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(f"row {row_number}: {field} must be yes/no, true/false, or 1/0")


def _signature(record: Mapping[str, object], row_number: int) -> dict[str, object]:
    required = ("country", "food_domain", "commodity", "product_form", "destination", "period", "denominator", "unit")
    missing = [field for field in required if not record.get(field)]
    if missing:
        raise ValueError(f"row {row_number}: certified CPC requires {', '.join(missing)}")
    return {field: record[field] for field in required}


def convert_csv_text(csv_text: str, *, filename: str = "input.csv") -> dict[str, object]:
    """Convert a validated CSV string to the private-layer JSON contract."""
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise ValueError("CSV file is empty")
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    if reader.fieldnames is None:
        raise ValueError("CSV header row is missing")
    normalized = [_header(name) for name in reader.fieldnames]
    if any(not name for name in normalized):
        raise ValueError("CSV contains a blank column name")
    duplicates = sorted({name for name in normalized if normalized.count(name) > 1})
    if duplicates:
        raise ValueError(f"duplicate CSV columns after normalization: {', '.join(duplicates)}")
    missing_columns = sorted(REQUIRED_COLUMNS - set(normalized))
    if missing_columns:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing_columns)}")
    unknown = sorted(set(normalized) - ALLOWED_COLUMNS)
    if unknown:
        raise ValueError(f"unknown CSV columns: {', '.join(unknown)}")
    reader.fieldnames = normalized

    private_data: dict[str, object] = {layer: [] for layer in ARRAY_LAYERS}
    counts = {layer: 0 for layer in SUPPORTED_LAYERS}
    certificates: dict[str, object] = {}
    row_count = 0
    for row_number, raw in enumerate(reader, start=2):
        if not any(str(value or "").strip() for value in raw.values()):
            continue
        row_count += 1
        record: dict[str, object] = {}
        for field, raw_value in raw.items():
            value = str(raw_value or "").strip()
            if not value:
                continue
            if field in NUMERIC_FIELDS:
                record[field] = _number(value, field, row_number)
            elif field in BOOLEAN_FIELDS:
                record[field] = _boolean(value, field, row_number)
            elif field == "evidence_ids":
                record[field] = [item.strip() for item in re.split(r"[;|]", value) if item.strip()]
            else:
                record[field] = value

        layer = str(record.pop("layer", "")).casefold()
        if layer not in SUPPORTED_LAYERS:
            raise ValueError(f"row {row_number}: unsupported layer '{layer}'")
        record_id = str(record.get("record_id", ""))
        observed_at = str(record.get("observed_at", ""))
        if not record_id:
            raise ValueError(f"row {row_number}: record_id is required")
        try:
            parsed_date = datetime.strptime(observed_at, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"row {row_number}: observed_at must be a real date in YYYY-MM-DD form") from exc
        if parsed_date.strftime("%Y-%m-%d") != observed_at:
            raise ValueError(f"row {row_number}: observed_at must use YYYY-MM-DD form")
        for lower, upper in INTERVAL_PAIRS:
            if lower in record and upper in record and float(record[lower]) > float(record[upper]):
                raise ValueError(f"row {row_number}: {lower} cannot exceed {upper}")

        counts[layer] += 1
        if layer in OBJECT_LAYERS and counts[layer] > 1:
            raise ValueError(f"row {row_number}: only one {layer} row is allowed per file")
        if layer == "cpc_compatibility":
            for field in ("identified_lower", "identified_upper", "measured_lower"):
                if field not in record:
                    raise ValueError(f"row {row_number}: CPC row requires {field}")
            if "measured_upper" not in record:
                record["measured_upper"] = record["measured_lower"]
            if "certificate_id" in record:
                evidence_ids = record.get("evidence_ids")
                if not evidence_ids:
                    raise ValueError(f"row {row_number}: certified CPC requires evidence_ids")
                boundary = str(record.pop("claim_boundary", ""))
                if not boundary:
                    raise ValueError(f"row {row_number}: certified CPC requires claim_boundary")
                signature = _signature(record, row_number)
                record["signature"] = signature
                certificates["direct_cpc"] = {
                    "status": "certified",
                    "certificate_id": record.pop("certificate_id"),
                    "signature": signature,
                    "evidence_ids": evidence_ids,
                    "boundary": boundary,
                    "evidence_date": observed_at,
                }
            private_data[layer] = record
        elif layer == "exposure_scenario":
            record.setdefault("requested", True)
            private_data[layer] = record
        else:
            records = private_data[layer]
            assert isinstance(records, list)
            records.append(record)

    if not row_count:
        raise ValueError("CSV contains no dated records")
    if certificates:
        private_data["certificates"] = certificates
    return {
        "status": "converted",
        "filename": filename,
        "row_count": row_count,
        "records_by_layer": {key: value for key, value in sorted(counts.items()) if value},
        "private_layer_data": private_data,
        "boundary": (
            "Blank cells remain missing; they are never converted to zero. Uploaded OD evidence is retained in the run "
            "manifest and is not converted into ERR constraints."
        ),
    }
