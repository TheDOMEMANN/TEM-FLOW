"""Open the sealed truth only after the prediction artifact is frozen."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


HERE = Path(__file__).resolve()
RELEASE = HERE.parents[1]
LOCK_PATH = RELEASE / "01_PROTOCOL" / "ANALYSIS_LOCK_V1_0_0.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def key(row: dict[str, object]) -> tuple[str, str, str]:
    return str(row["commodity"]), str(row["reporter_code"]), str(row["partner_code"])


def safe_fraction(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator > 0 else None


def subset_metrics(predictions: list[dict[str, object]], truth: dict[tuple[str, str, str], float]) -> dict[str, object]:
    positive = [p for p in predictions if truth[key(p)] > 0]
    certified_positive = [p for p in positive if p["claim_status"] == "certified_interval"]
    positive_mass = sum(truth[key(p)] for p in positive)
    certified_mass = sum(truth[key(p)] for p in certified_positive)
    contained = []
    normalized_widths = []
    narrowed = []
    for p in certified_positive:
        value = truth[key(p)]
        lower = float(p["tem_lower_kg"])
        upper = float(p["tem_upper_kg"])
        tolerance = max(1e-8, abs(value) * 1e-12)
        contained.append(lower - tolerance <= value <= upper + tolerance)
        source_width = float(p["source_only_upper_kg"]) - float(p["source_only_lower_kg"])
        ratio = (upper - lower) / source_width if source_width > 0 else 0.0
        normalized_widths.append(ratio)
        narrowed.append(ratio <= 0.80 + 1e-12)

    point_fields = [
        "independent_margins_point_kg",
        "historical_route_share_point_kg",
        "tem_midpoint_kg",
    ]
    point_errors: dict[str, object] = {}
    for field in point_fields:
        eligible = [p for p in predictions if p[field] is not None]
        errors = [float(p[field]) - truth[key(p)] for p in eligible]
        absolute = [abs(value) for value in errors]
        eligible_truth_mass = sum(truth[key(p)] for p in eligible)
        point_errors[field] = {
            "cell_count": len(eligible),
            "mae_kg": statistics.fmean(absolute) if absolute else None,
            "rmse_kg": math.sqrt(statistics.fmean([value * value for value in errors])) if errors else None,
            "sum_absolute_error_over_eligible_truth_mass": safe_fraction(sum(absolute), eligible_truth_mass),
        }

    certified_candidates = [p for p in predictions if p["claim_status"] == "certified_interval"]
    common_truth_mass = sum(truth[key(p)] for p in certified_candidates)
    common_point_errors: dict[str, object] = {}
    for field in point_fields:
        errors = [float(p[field]) - truth[key(p)] for p in certified_candidates]
        absolute = [abs(value) for value in errors]
        common_point_errors[field] = {
            "cell_count": len(certified_candidates),
            "mae_kg": statistics.fmean(absolute) if absolute else None,
            "rmse_kg": math.sqrt(statistics.fmean([value * value for value in errors])) if errors else None,
            "sum_absolute_error_over_common_truth_mass": safe_fraction(sum(absolute), common_truth_mass),
        }

    return {
        "candidate_cell_count": len(predictions),
        "positive_truth_cell_count": len(positive),
        "positive_truth_mass_kg": positive_mass,
        "certified_positive_cell_count": len(certified_positive),
        "certified_positive_mass_kg": certified_mass,
        "positive_route_certificate_coverage": safe_fraction(len(certified_positive), len(positive)),
        "positive_mass_certificate_coverage": safe_fraction(certified_mass, positive_mass),
        "positive_certified_interval_coverage": safe_fraction(sum(contained), len(contained)),
        "median_normalized_interval_width": statistics.median(normalized_widths) if normalized_widths else None,
        "fraction_positive_certified_narrowed_20pct": safe_fraction(sum(narrowed), len(narrowed)),
        "point_errors": point_errors,
        "point_errors_on_common_certified_candidates": common_point_errors,
    }


def gate(value: float | None, threshold: float, relation: str) -> bool:
    if value is None:
        return False
    if relation == "min":
        return value >= threshold
    if relation == "max":
        return value <= threshold
    raise ValueError(relation)


def decision_gates(metrics: dict[str, object], lock: dict[str, object], mismatch_admissions: int) -> dict[str, bool]:
    thresholds = lock["gates"]
    return {
        "positive_route_certificate_coverage": gate(metrics["positive_route_certificate_coverage"], thresholds["positive_route_certificate_coverage_min"], "min"),
        "positive_mass_certificate_coverage": gate(metrics["positive_mass_certificate_coverage"], thresholds["positive_mass_certificate_coverage_min"], "min"),
        "positive_certified_interval_coverage": gate(metrics["positive_certified_interval_coverage"], thresholds["positive_certified_interval_coverage_min"], "min"),
        "median_normalized_interval_width": gate(metrics["median_normalized_interval_width"], thresholds["median_normalized_interval_width_max"], "max"),
        "fraction_positive_certified_narrowed_20pct": gate(metrics["fraction_positive_certified_narrowed_20pct"], thresholds["fraction_positive_certified_narrowed_20pct_min"], "min"),
        "identity_mismatch_admissions": mismatch_admissions <= thresholds["identity_mismatch_admissions_max"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prediction-dir", type=Path, default=RELEASE / "04_RESULTS" / "main")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir or args.prediction_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    prediction_path = args.prediction_dir / "FROZEN_PREDICTIONS_V1_0_0.json"
    freeze_path = args.prediction_dir / "PREDICTION_FREEZE_MANIFEST_V1_0_0.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if sha256(prediction_path) != freeze["prediction_sha256"]:
        raise ValueError("prediction changed after freeze")
    payload = json.loads(prediction_path.read_text(encoding="utf-8"))
    if payload.get("truth_access") is not False:
        raise ValueError("prediction artifact does not declare truth isolation")

    truth_path = RELEASE / "02_DATA" / "derived" / "sealed_truth" / "SEALED_test_bilateral_truth.csv"
    truth_rows = read_csv(truth_path)
    truth = {key(row): float(row["heldout_bilateral_net_weight_kg"]) for row in truth_rows}
    predictions = payload["predictions"]
    if set(map(key, predictions)) != set(truth):
        raise ValueError("prediction and truth candidate universes differ")

    overall = subset_metrics(predictions, truth)
    groups: dict[str, dict[str, object]] = {}
    for class_name in sorted({str(p["commodity_class"]) for p in predictions}):
        selected = [p for p in predictions if p["commodity_class"] == class_name]
        groups[class_name] = subset_metrics(selected, truth)
    commodities: dict[str, dict[str, object]] = {}
    for commodity in sorted({str(p["commodity"]) for p in predictions}):
        selected = [p for p in predictions if p["commodity"] == commodity]
        commodities[commodity] = subset_metrics(selected, truth)

    mismatch_admissions = int(payload["identity_mismatch_admissions"])
    full_gates = decision_gates(overall, lock, mismatch_admissions)
    industrial = groups.get("industrial_agricultural_raw_material", {})
    nonfood_gates = decision_gates(industrial, lock, mismatch_admissions) if industrial else {}
    acquisition_path = RELEASE / "02_DATA" / "raw" / "uncomtrade" / "ACQUISITION_MANIFEST_V1_0_0.json"
    acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
    acquisition_gate = int(acquisition["truncated_response_count"]) <= lock["gates"]["acquisition_truncated_responses_max"]

    result = {
        "analysis_id": lock["analysis_id"],
        "prediction_sha256": sha256(prediction_path),
        "truth_sha256": sha256(truth_path),
        "scoring_opened_truth_after_prediction_freeze": True,
        "overall_metrics": overall,
        "group_metrics": groups,
        "commodity_metrics": commodities,
        "full_panel_gates_1_to_6": full_gates,
        "acquisition_not_truncated_gate_7": acquisition_gate,
        "provisional_full_panel_pass_gates_1_to_7": all(full_gates.values()) and acquisition_gate,
        "nonfood_industrial_gates_1_to_6": nonfood_gates,
        "nonfood_industrial_claim_pass": bool(nonfood_gates) and all(nonfood_gates.values()),
        "reproduction_gate_8": "pending independent runtime check",
        "claim_boundary": lock["claim_boundary"],
    }
    result_path = output_dir / "HOLDOUT_SCORE_V1_0_0.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    scored_rows: list[dict[str, object]] = []
    for p in predictions:
        observed = truth[key(p)]
        scored_rows.append(
            {
                "commodity": p["commodity"],
                "commodity_class": p["commodity_class"],
                "reporter_name": p["reporter_name"],
                "partner_name": p["partner_name"],
                "heldout_bilateral_net_weight_kg": format(observed, ".15g"),
                "claim_status": p["claim_status"],
                "tem_lower_kg": "" if p["tem_lower_kg"] is None else format(float(p["tem_lower_kg"]), ".15g"),
                "tem_upper_kg": "" if p["tem_upper_kg"] is None else format(float(p["tem_upper_kg"]), ".15g"),
                "contained": "" if p["tem_lower_kg"] is None else str(float(p["tem_lower_kg"]) - max(1e-8, abs(observed) * 1e-12) <= observed <= float(p["tem_upper_kg"]) + max(1e-8, abs(observed) * 1e-12)).lower(),
                "independent_margins_point_kg": format(float(p["independent_margins_point_kg"]), ".15g"),
                "historical_route_share_point_kg": format(float(p["historical_route_share_point_kg"]), ".15g"),
            }
        )
    scored_path = output_dir / "SCORED_CELLS_V1_0_0.csv"
    with scored_path.open("w", encoding="utf-8", newline="") as handle:
        fields = list(scored_rows[0]) if scored_rows else []
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(scored_rows)
    print(json.dumps({"score_sha256": sha256(result_path), "provisional_pass_1_to_7": result["provisional_full_panel_pass_gates_1_to_7"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
