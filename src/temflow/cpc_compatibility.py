"""Validation of newly measured CPC against an TEM-FLOW identified interval.

The comparison is deliberately source/product compatible.  Chemistry already
attached to a source-product state is never propagated to consumption above
its identified CPC envelope.  Above-envelope consumption is retained as an
unmatched product-state influx until compatible chemistry is supplied.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math


def _finite_nonnegative(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return number


@dataclass(frozen=True)
class CPCComparison:
    identified_lower: float
    identified_upper: float
    measured_lower: float
    measured_upper: float
    status: str
    gap: float
    overlap_lower: float | None
    overlap_upper: float | None
    matched_cpc_lower: float | None
    matched_cpc_upper: float | None
    unmatched_cpc_lower: float
    unmatched_cpc_upper: float
    chemistry_rule: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def compare_cpc(
    identified_lower: float,
    identified_upper: float,
    measured_lower: float,
    measured_upper: float | None = None,
) -> CPCComparison:
    """Compare an independently measured CPC interval with identified CPC.

    All quantities must use the same commodity, product, population, period,
    and units before this function is called.
    """
    lower = _finite_nonnegative(identified_lower, "identified_lower")
    upper = _finite_nonnegative(identified_upper, "identified_upper")
    measured_lo = _finite_nonnegative(measured_lower, "measured_lower")
    measured_hi = measured_lo if measured_upper is None else _finite_nonnegative(measured_upper, "measured_upper")
    if lower > upper:
        raise ValueError("identified_lower cannot exceed identified_upper")
    if measured_lo > measured_hi:
        raise ValueError("measured_lower cannot exceed measured_upper")

    if measured_lo > upper:
        status = "upper_envelope_miss"
        gap = measured_lo - upper
        overlap_lo = overlap_hi = None
        matched_lo, matched_hi = lower, upper
        unmatched_lo = max(0.0, measured_lo - upper)
        unmatched_hi = max(0.0, measured_hi - lower)
        rule = (
            "Existing source-product chemistry and HI apply only to the identified CPC interval; "
            "the residual is an unmatched product-state influx with no chemistry or HI attribution."
        )
    elif measured_hi < lower:
        status = "lower_envelope_miss"
        gap = lower - measured_hi
        overlap_lo = overlap_hi = None
        matched_lo = matched_hi = None
        unmatched_lo = unmatched_hi = 0.0
        rule = (
            "Additional influx cannot explain a lower-envelope miss.  No certified chemistry-linked HI "
            "is produced until consumption, population, period, product identity, loss, export, or absorption is adjudicated."
        )
    else:
        status = "covered"
        gap = 0.0
        overlap_lo = max(lower, measured_lo)
        overlap_hi = min(upper, measured_hi)
        matched_lo, matched_hi = overlap_lo, overlap_hi
        unmatched_lo = unmatched_hi = 0.0
        rule = "The measured CPC overlaps the source-product compatible identified interval."

    return CPCComparison(
        lower,
        upper,
        measured_lo,
        measured_hi,
        status,
        gap,
        overlap_lo,
        overlap_hi,
        matched_lo,
        matched_hi,
        unmatched_lo,
        unmatched_hi,
        rule,
    )


def matched_hazard_quotient(
    comparison: CPCComparison,
    concentration_mg_per_kg_food: float,
    body_weight_kg: float,
    reference_dose_mg_per_kg_day: float,
) -> dict[str, float | str | None]:
    """Calculate HQ only for CPC supported by existing compatible chemistry."""
    concentration = _finite_nonnegative(concentration_mg_per_kg_food, "concentration_mg_per_kg_food")
    body_weight = _finite_nonnegative(body_weight_kg, "body_weight_kg")
    reference_dose = _finite_nonnegative(reference_dose_mg_per_kg_day, "reference_dose_mg_per_kg_day")
    if body_weight <= 0 or reference_dose <= 0:
        raise ValueError("body_weight_kg and reference_dose_mg_per_kg_day must be positive")
    if comparison.matched_cpc_lower is None or comparison.matched_cpc_upper is None:
        return {
            "hq_matched_lower": None,
            "hq_matched_upper": None,
            "hi_total_status": "not_identified",
            "reason": comparison.chemistry_rule,
        }

    factor = concentration / (365.0 * body_weight * reference_dose)
    return {
        "hq_matched_lower": factor * comparison.matched_cpc_lower,
        "hq_matched_upper": factor * comparison.matched_cpc_upper,
        "hi_total_status": "partial" if comparison.status == "upper_envelope_miss" else "identified_for_selected_analyte",
        "reason": comparison.chemistry_rule,
    }


def recalculate_cpc(
    allocated_mass_lower_kg_year: float,
    consumer_population: float,
    allocated_mass_upper_kg_year: float | None = None,
) -> dict[str, float | str]:
    """Calculate local CPC from source-compatible annual mass and population."""
    mass_lower = _finite_nonnegative(allocated_mass_lower_kg_year, "allocated_mass_lower_kg_year")
    mass_upper = mass_lower if allocated_mass_upper_kg_year is None else _finite_nonnegative(
        allocated_mass_upper_kg_year, "allocated_mass_upper_kg_year"
    )
    population = _finite_nonnegative(consumer_population, "consumer_population")
    if mass_lower > mass_upper:
        raise ValueError("allocated_mass_lower_kg_year cannot exceed allocated_mass_upper_kg_year")
    if population <= 0:
        raise ValueError("consumer_population must be positive")
    return {
        "status": "computed",
        "allocated_mass_lower_kg_year": mass_lower,
        "allocated_mass_upper_kg_year": mass_upper,
        "consumer_population": population,
        "cpc_lower_kg_person_year": mass_lower / population,
        "cpc_upper_kg_person_year": mass_upper / population,
        "rule": "CPC equals source-compatible annual commodity mass divided by the corresponding consumer population.",
    }


def hazard_alarm_projection(hazard: dict[str, object]) -> dict[str, object]:
    """Classify the fixed HQ=1 decision rule over the matched CPC interval."""
    lower = hazard.get("hq_matched_lower")
    upper = hazard.get("hq_matched_upper")
    if lower is None or upper is None:
        return {
            "status": "not_computable",
            "threshold_hq": 1.0,
            "scope": "matched source-product CPC only",
            "reason": str(hazard.get("reason") or "Compatible CPC and chemistry are required."),
        }
    lower_number, upper_number = float(lower), float(upper)
    if lower_number >= 1.0:
        status = "alarm_across_matched_interval"
    elif upper_number >= 1.0:
        status = "threshold_crossing_within_matched_interval"
    else:
        status = "no_alarm_within_matched_interval"
    return {
        "status": status,
        "threshold_hq": 1.0,
        "hq_lower": lower_number,
        "hq_upper": upper_number,
        "scope": "matched source-product CPC only",
        "completeness": "partial" if hazard.get("hi_total_status") == "partial" else "identified",
        "reason": str(hazard.get("reason") or ""),
    }


def compare_and_screen(payload: dict[str, object]) -> dict[str, object]:
    comparison = compare_cpc(
        float(payload["identified_lower"]),
        float(payload["identified_upper"]),
        float(payload["measured_lower"]),
        None if payload.get("measured_upper") in (None, "") else float(payload["measured_upper"]),
    )
    result: dict[str, object] = {"comparison": comparison.to_dict()}
    chemistry_fields = ("concentration_mg_per_kg_food", "body_weight_kg", "reference_dose_mg_per_kg_day")
    if all(payload.get(field) not in (None, "") for field in chemistry_fields):
        hazard = matched_hazard_quotient(
            comparison,
            float(payload["concentration_mg_per_kg_food"]),
            float(payload["body_weight_kg"]),
            float(payload["reference_dose_mg_per_kg_day"]),
        )
    else:
        hazard = {
            "hq_matched_lower": None,
            "hq_matched_upper": None,
            "hi_total_status": "chemistry_not_supplied",
            "reason": comparison.chemistry_rule,
        }
    result["hazard"] = hazard
    result["alarm_projection"] = hazard_alarm_projection(hazard)
    return result

