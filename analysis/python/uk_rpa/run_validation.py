"""Run the sealed UK RPA TEM-FLOW branching validation."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path


HERE = Path(__file__).resolve()
PACKAGE = HERE.parents[1]
RAW = PACKAGE / "02_DATA" / "raw" / "cattle-movements-to-slaughterhouses-during-2010.csv"
PROTOCOL = PACKAGE / "01_PROTOCOL" / "VALIDATION_PROTOCOL_V1_0_0.md"
SEAL = PACKAGE / "01_PROTOCOL" / "PREANALYSIS_SEAL_V1_0_0.json"
EXPECTED_RAW_SHA256 = "23584327dde9a6f6e59efe1281204cdaf5b9f6a3c69aed9233e43c0c7c163875"
EXPECTED_PROTOCOL_SHA256 = "aa8d59273fdb77f845e4bd683c9450d5f6197c7b77636b646b981500a5d8e353"
CLASSES = ("direct", "indirect")
FIT_MONTHS = frozenset(range(1, 6))
CALIBRATION_MONTHS = frozenset(range(6, 9))
TEST_MONTHS = frozenset(range(9, 13))
TOLERANCE = 1e-8


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def finite_quantile(values: list[float], coverage: float) -> float:
    if not values:
        raise RuntimeError("no eligible calibration residuals")
    ordered = sorted(float(value) for value in values)
    rank = min(len(ordered), max(1, math.ceil((len(ordered) + 1) * coverage)))
    return ordered[rank - 1]


def parse_count(value: str) -> float | None:
    text = value.strip().replace(",", "")
    if text == "":
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def target_id(source: str, month: int, movement_class: str) -> str:
    token = f"{source}|2010-{month:02d}|{movement_class}"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:20].upper()


def main() -> int:
    if sha256(RAW) != EXPECTED_RAW_SHA256:
        raise RuntimeError("raw file differs from the sealed acquisition")
    if sha256(PROTOCOL) != EXPECTED_PROTOCOL_SHA256:
        raise RuntimeError("protocol differs from the pre-analysis seal")
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    if seal["target_state"] != "sealed_not_opened":
        raise RuntimeError("unexpected pre-analysis target state")

    aggregate: dict[tuple[int, str, str], dict[str, float]] = defaultdict(
        lambda: {"direct": 0.0, "indirect": 0.0}
    )
    raw_rows = 0
    eligible_rows = 0
    excluded_missing_count = 0
    excluded_other_year = 0
    excluded_blank_node = 0
    with RAW.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        expected = {
            "Month & Year of Movement",
            "From County",
            "To County",
            "To Location Type",
            "Direct Movements",
            "Indirect Movements",
        }
        if set(reader.fieldnames or ()) != expected:
            raise RuntimeError(f"unexpected columns: {reader.fieldnames}")
        for row in reader:
            raw_rows += 1
            source = row["From County"].strip().upper()
            destination = row["To County"].strip().upper()
            if not source or not destination:
                excluded_blank_node += 1
                continue
            try:
                observed_date = datetime.strptime(row["Month & Year of Movement"].strip(), "%b-%y")
            except ValueError:
                excluded_other_year += 1
                continue
            if observed_date.year != 2010:
                excluded_other_year += 1
                continue
            direct = parse_count(row["Direct Movements"])
            indirect = parse_count(row["Indirect Movements"])
            if direct is None or indirect is None:
                excluded_missing_count += 1
                continue
            item = aggregate[(observed_date.month, source, destination)]
            item["direct"] += direct
            item["indirect"] += indirect
            eligible_rows += 1

    sources = sorted({key[1] for key in aggregate})

    def source_split_total(source: str, months: frozenset[int]) -> float:
        return sum(
            values["direct"] + values["indirect"]
            for (month, current_source, _), values in aggregate.items()
            if current_source == source and month in months
        )

    eligible_sources: list[str] = []
    anchors: dict[str, str] = {}
    for source in sources:
        if any(
            source_split_total(source, months) <= 0
            for months in (FIT_MONTHS, CALIBRATION_MONTHS, TEST_MONTHS)
        ):
            continue
        nonlocal_fit: dict[str, float] = defaultdict(float)
        for (month, current_source, destination), values in aggregate.items():
            if current_source == source and month in FIT_MONTHS and destination != source:
                nonlocal_fit[destination] += values["direct"] + values["indirect"]
        positive_nonlocal = {name: value for name, value in nonlocal_fit.items() if value > 0}
        if not positive_nonlocal:
            continue
        anchor = sorted(positive_nonlocal, key=lambda name: (-positive_nonlocal[name], name))[0]
        eligible_sources.append(source)
        anchors[source] = anchor

    support: dict[tuple[str, str], list[str]] = {}
    fitted_share: dict[tuple[str, str], dict[str, float]] = {}
    for source in eligible_sources:
        anchor = anchors[source]
        for movement_class in CLASSES:
            fitted: dict[str, float] = defaultdict(float)
            for (month, current_source, destination), values in aggregate.items():
                if (
                    current_source == source
                    and month in FIT_MONTHS
                    and destination != anchor
                    and values[movement_class] > 0
                ):
                    fitted[destination] += values[movement_class]
            names = sorted(fitted)
            support[(source, movement_class)] = names
            total = sum(fitted.values())
            if total > 0:
                shares = {name: fitted[name] / total for name in names}
                shares["UNRESOLVED_DESTINATION"] = 0.0
            else:
                shares = {"UNRESOLVED_DESTINATION": 1.0}
            fitted_share[(source, movement_class)] = shares

    calibration_rows: list[dict[str, object]] = []
    residuals_by_class: dict[str, list[float]] = {name: [] for name in CLASSES}
    for source in eligible_sources:
        anchor = anchors[source]
        for month in sorted(CALIBRATION_MONTHS):
            for movement_class in CLASSES:
                class_rows = {
                    destination: values[movement_class]
                    for (current_month, current_source, destination), values in aggregate.items()
                    if current_month == month and current_source == source
                }
                class_total = sum(class_rows.values())
                anchor_count = class_rows.get(anchor, 0.0)
                remainder = class_total - anchor_count
                if remainder <= 0:
                    continue
                names = support[(source, movement_class)]
                shares = fitted_share[(source, movement_class)]
                actual_known = {name: class_rows.get(name, 0.0) for name in names}
                unresolved = sum(
                    value
                    for name, value in class_rows.items()
                    if name != anchor and name not in set(names)
                )
                tv = 0.5 * (
                    sum(abs(actual_known[name] / remainder - shares[name]) for name in names)
                    + abs(unresolved / remainder - shares["UNRESOLVED_DESTINATION"])
                )
                tv = min(1.0, max(0.0, tv))
                residuals_by_class[movement_class].append(tv)
                calibration_rows.append(
                    {
                        "source_county": source,
                        "month": month,
                        "movement_class": movement_class,
                        "class_total": class_total,
                        "anchor_destination": anchor,
                        "anchor_count": anchor_count,
                        "conditional_remainder": remainder,
                        "total_variation_residual": tv,
                    }
                )

    pooled = residuals_by_class["direct"] + residuals_by_class["indirect"]
    radii: dict[str, dict[str, object]] = {}
    for movement_class in CLASSES:
        class_values = residuals_by_class[movement_class]
        selected = class_values if len(class_values) >= 30 else pooled
        radii[movement_class] = {
            "epsilon": finite_quantile(selected, 0.90),
            "residual_count": len(selected),
            "scope": movement_class if len(class_values) >= 30 else "pooled",
            "finite_sample_coverage": 0.90,
        }

    calibration_path = PACKAGE / "02_DATA" / "derived" / "CALIBRATION_RESIDUALS_V1_0_0.csv"
    calibration_path.parent.mkdir(parents=True, exist_ok=True)
    with calibration_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(calibration_rows[0]))
        writer.writeheader()
        writer.writerows(calibration_rows)

    predictions: list[dict[str, object]] = []
    max_balance_violation = 0.0
    for source in eligible_sources:
        anchor = anchors[source]
        for month in sorted(TEST_MONTHS):
            source_total = sum(
                values[movement_class]
                for (current_month, current_source, _), values in aggregate.items()
                if current_month == month and current_source == source
                for movement_class in CLASSES
            )
            for movement_class in CLASSES:
                class_rows = {
                    destination: values[movement_class]
                    for (current_month, current_source, destination), values in aggregate.items()
                    if current_month == month and current_source == source
                }
                class_total = sum(class_rows.values())
                anchor_count = class_rows.get(anchor, 0.0)
                remainder = max(0.0, class_total - anchor_count)
                names = support[(source, movement_class)] + ["UNRESOLVED_DESTINATION"]
                shares = fitted_share[(source, movement_class)]
                epsilon = float(radii[movement_class]["epsilon"])
                coordinates: list[dict[str, object]] = []
                for name in names:
                    p = shares[name]
                    if remainder == 0:
                        lower = upper = 0.0
                    else:
                        lower = max(0.0, p - epsilon) * remainder
                        upper = min(1.0, p + epsilon) * remainder
                    coordinates.append(
                        {
                            "destination": name,
                            "historical_conditional_share": p,
                            "interval_count": [lower, upper],
                            "named_report_status": (
                                "blocked_unresolved_identity"
                                if name == "UNRESOLVED_DESTINATION"
                                else "eligible_fitted_destination"
                            ),
                        }
                    )
                sum_lower = sum(float(item["interval_count"][0]) for item in coordinates)
                sum_upper = sum(float(item["interval_count"][1]) for item in coordinates)
                violation = max(0.0, sum_lower - remainder, remainder - sum_upper)
                max_balance_violation = max(max_balance_violation, violation)
                predictions.append(
                    {
                        "target_id": target_id(source, month, movement_class),
                        "source_county": source,
                        "month": f"2010-{month:02d}",
                        "movement_class": movement_class,
                        "source_total_count": source_total,
                        "class_total_count": class_total,
                        "anchor_destination": anchor,
                        "anchor_observed_count": anchor_count,
                        "conditional_remainder_count": remainder,
                        "epsilon": epsilon,
                        "coordinates": coordinates,
                        "operational_point_allocation": None,
                    }
                )

    predictions_path = PACKAGE / "04_RESULTS" / "FROZEN_PREDICTIONS_V1_0_0.json"
    predictions_payload = {
        "method": "TEM-FLOW joint compositional ambiguity set",
        "raw_sha256": sha256(RAW),
        "protocol_sha256": sha256(PROTOCOL),
        "radii": radii,
        "eligible_source_count": len(eligible_sources),
        "target_count": len(predictions),
        "predictions": predictions,
    }
    write_json(predictions_path, predictions_payload)
    predictions_sha = sha256(predictions_path)

    truth_rows: list[dict[str, object]] = []
    prediction_lookup = {item["target_id"]: item for item in predictions}
    for prediction in predictions:
        source = str(prediction["source_county"])
        month = int(str(prediction["month"])[-2:])
        movement_class = str(prediction["movement_class"])
        anchor = str(prediction["anchor_destination"])
        names = [
            str(item["destination"])
            for item in prediction["coordinates"]
            if item["destination"] != "UNRESOLVED_DESTINATION"
        ]
        class_rows = {
            destination: values[movement_class]
            for (current_month, current_source, destination), values in aggregate.items()
            if current_month == month and current_source == source
        }
        unresolved = sum(
            value
            for name, value in class_rows.items()
            if name != anchor and name not in set(names)
        )
        for name in names + ["UNRESOLVED_DESTINATION"]:
            actual = unresolved if name == "UNRESOLVED_DESTINATION" else class_rows.get(name, 0.0)
            truth_rows.append(
                {
                    "target_id": prediction["target_id"],
                    "source_county": source,
                    "month": prediction["month"],
                    "movement_class": movement_class,
                    "destination": name,
                    "actual_count": actual,
                    "truth_role": (
                        "withheld_unresolved_destination_sum"
                        if name == "UNRESOLVED_DESTINATION"
                        else "withheld_fitted_destination_count"
                    ),
                    "same_county_destination": name == source,
                }
            )

    truth_path = PACKAGE / "02_DATA" / "derived" / "UNBLINDED_DESTINATION_TRUTH_V1_0_0.csv"
    with truth_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(truth_rows[0]))
        writer.writeheader()
        writer.writerows(truth_rows)

    positive_count = 0
    covered_count = 0
    positive_mass = 0.0
    covered_mass = 0.0
    unresolved_positive = 0
    unresolved_covered = 0
    normalized_widths: list[float] = []
    contraction_values: list[float] = []
    all_unresolved_blocked = True
    no_point = True
    truth_by_target: dict[str, dict[str, float]] = defaultdict(dict)
    for row in truth_rows:
        truth_by_target[str(row["target_id"])][str(row["destination"])] = float(row["actual_count"])

    for prediction in predictions:
        remainder = float(prediction["conditional_remainder_count"])
        coordinates = prediction["coordinates"]
        if remainder > 0:
            joint_width = sum(
                float(item["interval_count"][1]) - float(item["interval_count"][0])
                for item in coordinates
            )
            evidence_only_width = len(coordinates) * remainder
            contraction_values.append(1.0 - joint_width / evidence_only_width)
        no_point = no_point and prediction["operational_point_allocation"] is None
        for coordinate in coordinates:
            name = str(coordinate["destination"])
            lower, upper = (float(value) for value in coordinate["interval_count"])
            actual = truth_by_target[str(prediction["target_id"])][name]
            covered = lower - TOLERANCE <= actual <= upper + TOLERANCE
            if name == "UNRESOLVED_DESTINATION":
                all_unresolved_blocked = (
                    all_unresolved_blocked
                    and coordinate["named_report_status"] == "blocked_unresolved_identity"
                )
            if actual > 0:
                positive_count += 1
                positive_mass += actual
                normalized_widths.append((upper - lower) / remainder if remainder > 0 else 0.0)
                if covered:
                    covered_count += 1
                    covered_mass += actual
                if name == "UNRESOLVED_DESTINATION":
                    unresolved_positive += 1
                    if covered:
                        unresolved_covered += 1

    retention_cases = 0
    retention_covered = 0
    retention_named_cases = 0
    retention_rows: list[dict[str, object]] = []
    for source in eligible_sources:
        for month in sorted(TEST_MONTHS):
            lower_total = 0.0
            upper_total = 0.0
            actual_total = 0.0
            all_named = True
            for movement_class in CLASSES:
                prediction = prediction_lookup[target_id(source, month, movement_class)]
                coord_map = {str(item["destination"]): item for item in prediction["coordinates"]}
                actual_total += aggregate.get((month, source, source), {movement_class: 0.0})[movement_class]
                if source in coord_map:
                    lower, upper = coord_map[source]["interval_count"]
                else:
                    lower, upper = coord_map["UNRESOLVED_DESTINATION"]["interval_count"]
                    lower = 0.0
                    all_named = False
                lower_total += float(lower)
                upper_total += float(upper)
            if actual_total > 0:
                retention_cases += 1
                if lower_total - TOLERANCE <= actual_total <= upper_total + TOLERANCE:
                    retention_covered += 1
                if all_named:
                    retention_named_cases += 1
            retention_rows.append(
                {
                    "source_county": source,
                    "month": f"2010-{month:02d}",
                    "actual_same_county_count": actual_total,
                    "neutral_interval_count": [lower_total, upper_total],
                    "identity_status": "named_fitted_destination" if all_named else "partly_unresolved_identity",
                }
            )

    metrics = {
        "eligible_source_count": len(eligible_sources),
        "target_source_class_month_count": len(predictions),
        "positive_withheld_compartment_count": positive_count,
        "compartment_count_coverage": covered_count / positive_count if positive_count else 0.0,
        "movement_weighted_coverage": covered_mass / positive_mass if positive_mass else 0.0,
        "positive_unresolved_compartment_count": unresolved_positive,
        "unresolved_compartment_coverage": (
            unresolved_covered / unresolved_positive if unresolved_positive else 0.0
        ),
        "positive_same_county_retention_case_count": retention_cases,
        "same_county_retention_coverage": (
            retention_covered / retention_cases if retention_cases else 0.0
        ),
        "same_county_retention_named_case_count": retention_named_cases,
        "median_positive_compartment_width_over_remainder": (
            statistics.median(normalized_widths) if normalized_widths else 1.0
        ),
        "median_total_width_contraction": (
            statistics.median(contraction_values) if contraction_values else 0.0
        ),
        "maximum_balance_violation": max_balance_violation,
        "all_unresolved_destinations_unnamed": all_unresolved_blocked,
        "no_operational_point_estimate": no_point,
        "direct_radius": radii["direct"],
        "indirect_radius": radii["indirect"],
    }
    gates = {
        "at_least_100_targets": len(predictions) >= 100,
        "at_least_200_positive_compartments": positive_count >= 200,
        "count_coverage_at_least_0_80": metrics["compartment_count_coverage"] >= 0.80,
        "movement_weighted_coverage_at_least_0_80": metrics["movement_weighted_coverage"] >= 0.80,
        "unresolved_coverage_at_least_0_80": (
            unresolved_positive > 0 and metrics["unresolved_compartment_coverage"] >= 0.80
        ),
        "same_county_retention_coverage_at_least_0_80": (
            retention_cases > 0 and metrics["same_county_retention_coverage"] >= 0.80
        ),
        "median_width_no_more_than_0_50": (
            metrics["median_positive_compartment_width_over_remainder"] <= 0.50
        ),
        "median_contraction_at_least_0_20": metrics["median_total_width_contraction"] >= 0.20,
        "balance_violation_no_more_than_1e_8": max_balance_violation <= TOLERANCE,
        "unresolved_destinations_unnamed": all_unresolved_blocked,
        "no_operational_point_estimate": no_point,
    }
    overall = "PASS" if all(gates.values()) else "FAIL"
    score_path = PACKAGE / "04_RESULTS" / "VALIDATION_SCORE_V1_0_0.json"
    score_payload = {
        "decision": overall,
        "metrics": metrics,
        "gates": gates,
        "prediction_written_before_truth": True,
        "frozen_predictions_sha256_before_unblinding": predictions_sha,
        "claim_boundary": (
            "County-to-slaughterhouse movement-count allocation with direct/indirect class margins "
            "and a current nonlocal destination anchor; not farm-scale, African or instrument-weighed validation."
        ),
    }
    write_json(score_path, score_payload)

    retention_path = PACKAGE / "04_RESULTS" / "SAME_COUNTY_RETENTION_SCORE_ROWS_V1_0_0.json"
    write_json(retention_path, retention_rows)

    manifest = {
        "dataset": {
            "publisher": "UK Rural Payments Agency",
            "title": "Cattle movements to slaughterhouses during 2010",
            "source_catalogue_url": seal["source_catalogue_url"],
            "source_csv_url": seal["source_csv_url"],
            "retrieval_date": "2026-09-12",
            "raw_rows": raw_rows,
            "eligible_rows": eligible_rows,
            "excluded_missing_count_rows": excluded_missing_count,
            "excluded_other_year_or_bad_date_rows": excluded_other_year,
            "excluded_blank_node_rows": excluded_blank_node,
        },
        "checksums": {
            "01_PROTOCOL/VALIDATION_PROTOCOL_V1_0_0.md": sha256(PROTOCOL),
            "01_PROTOCOL/PREANALYSIS_SEAL_V1_0_0.json": sha256(SEAL),
            "02_DATA/raw/cattle-movements-to-slaughterhouses-during-2010.csv": sha256(RAW),
            "02_DATA/derived/CALIBRATION_RESIDUALS_V1_0_0.csv": sha256(calibration_path),
            "02_DATA/derived/UNBLINDED_DESTINATION_TRUTH_V1_0_0.csv": sha256(truth_path),
            "03_CODE/run_validation.py": sha256(HERE),
            "04_RESULTS/FROZEN_PREDICTIONS_V1_0_0.json": sha256(predictions_path),
            "04_RESULTS/SAME_COUNTY_RETENTION_SCORE_ROWS_V1_0_0.json": sha256(retention_path),
            "04_RESULTS/VALIDATION_SCORE_V1_0_0.json": sha256(score_path),
        },
    }
    manifest_path = PACKAGE / "05_QA" / "PROVENANCE_AND_CHECKSUM_MANIFEST_V1_0_0.json"
    write_json(manifest_path, manifest)
    print(json.dumps(score_payload, indent=2, sort_keys=True))
    return 0 if overall == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
