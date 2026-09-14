"""Independently recompute the frozen UK RPA validation score."""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path


HERE = Path(__file__).resolve()
PACKAGE = HERE.parents[1]
PREDICTIONS = PACKAGE / "04_RESULTS" / "FROZEN_PREDICTIONS_V1_0_0.json"
TRUTH = PACKAGE / "02_DATA" / "derived" / "UNBLINDED_DESTINATION_TRUTH_V1_0_0.csv"
RETENTION = PACKAGE / "04_RESULTS" / "SAME_COUNTY_RETENTION_SCORE_ROWS_V1_0_0.json"
SCORE = PACKAGE / "04_RESULTS" / "VALIDATION_SCORE_V1_0_0.json"
MANIFEST = PACKAGE / "05_QA" / "PROVENANCE_AND_CHECKSUM_MANIFEST_V1_0_0.json"
RAW = PACKAGE / "02_DATA" / "raw" / "cattle-movements-to-slaughterhouses-during-2010.csv"
TOL = 1e-8


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def close(left: float, right: float, tolerance: float = 1e-12) -> bool:
    return abs(left - right) <= tolerance * max(1.0, abs(left), abs(right))


def main() -> int:
    prediction_payload = json.loads(PREDICTIONS.read_text(encoding="utf-8"))
    score_payload = json.loads(SCORE.read_text(encoding="utf-8"))
    retention_rows = json.loads(RETENTION.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    checksum_results = {}
    for relative, expected in manifest["checksums"].items():
        path = PACKAGE / relative
        checksum_results[relative] = {
            "expected": expected,
            "observed": sha256(path),
            "match": sha256(path) == expected,
        }

    truth: dict[str, dict[str, float]] = defaultdict(dict)
    with TRUTH.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            truth[row["target_id"]][row["destination"]] = float(row["actual_count"])

    positive_count = covered_count = 0
    positive_weight = covered_weight = 0.0
    unresolved_positive = unresolved_covered = 0
    widths: list[float] = []
    contractions: list[float] = []
    max_violation = 0.0
    unresolved_unnamed = True
    no_point = True
    for prediction in prediction_payload["predictions"]:
        remainder = float(prediction["conditional_remainder_count"])
        coordinates = prediction["coordinates"]
        lowers = [float(item["interval_count"][0]) for item in coordinates]
        uppers = [float(item["interval_count"][1]) for item in coordinates]
        max_violation = max(
            max_violation,
            max(0.0, sum(lowers) - remainder, remainder - sum(uppers)),
        )
        if remainder > 0:
            contractions.append(
                1.0 - sum(upper - lower for lower, upper in zip(lowers, uppers))
                / (len(coordinates) * remainder)
            )
        no_point = no_point and prediction["operational_point_allocation"] is None
        for item, lower, upper in zip(coordinates, lowers, uppers):
            destination = item["destination"]
            actual = truth[prediction["target_id"]][destination]
            covered = lower - TOL <= actual <= upper + TOL
            if destination == "UNRESOLVED_DESTINATION":
                unresolved_unnamed = (
                    unresolved_unnamed
                    and item["named_report_status"] == "blocked_unresolved_identity"
                )
            if actual > 0:
                positive_count += 1
                positive_weight += actual
                widths.append((upper - lower) / remainder if remainder > 0 else 0.0)
                if covered:
                    covered_count += 1
                    covered_weight += actual
                if destination == "UNRESOLVED_DESTINATION":
                    unresolved_positive += 1
                    if covered:
                        unresolved_covered += 1

    raw_same_county: dict[tuple[str, int], float] = defaultdict(float)
    with RAW.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            source = row["From County"].strip().upper()
            destination = row["To County"].strip().upper()
            try:
                date = datetime.strptime(row["Month & Year of Movement"].strip(), "%b-%y")
                direct = float(row["Direct Movements"].replace(",", ""))
                indirect = float(row["Indirect Movements"].replace(",", ""))
            except (ValueError, TypeError):
                continue
            if date.year == 2010 and date.month >= 9 and source and source == destination:
                raw_same_county[(source, date.month)] += direct + indirect

    retention_positive = retention_covered = retention_named = retention_named_covered = 0
    retention_actual_matches_raw = True
    for row in retention_rows:
        source = row["source_county"]
        month = int(row["month"][-2:])
        actual = float(row["actual_same_county_count"])
        lower, upper = (float(value) for value in row["neutral_interval_count"])
        retention_actual_matches_raw = retention_actual_matches_raw and close(
            actual, raw_same_county.get((source, month), 0.0)
        )
        if actual > 0:
            retention_positive += 1
            covered = lower - TOL <= actual <= upper + TOL
            if covered:
                retention_covered += 1
            if row["identity_status"] == "named_fitted_destination":
                retention_named += 1
                if covered:
                    retention_named_covered += 1

    recomputed = {
        "target_source_class_month_count": len(prediction_payload["predictions"]),
        "positive_withheld_compartment_count": positive_count,
        "compartment_count_coverage": covered_count / positive_count,
        "movement_weighted_coverage": covered_weight / positive_weight,
        "positive_unresolved_compartment_count": unresolved_positive,
        "unresolved_compartment_coverage": unresolved_covered / unresolved_positive,
        "positive_same_county_retention_case_count": retention_positive,
        "same_county_retention_coverage": retention_covered / retention_positive,
        "same_county_retention_named_case_count": retention_named,
        "same_county_retention_named_coverage": retention_named_covered / retention_named,
        "median_positive_compartment_width_over_remainder": statistics.median(widths),
        "median_total_width_contraction": statistics.median(contractions),
        "maximum_balance_violation": max_violation,
        "all_unresolved_destinations_unnamed": unresolved_unnamed,
        "no_operational_point_estimate": no_point,
    }
    metric_matches = {}
    for key, value in recomputed.items():
        if key == "same_county_retention_named_coverage":
            continue
        reported = score_payload["metrics"][key]
        metric_matches[key] = (
            value == reported if isinstance(value, (bool, int)) else close(float(value), float(reported))
        )

    result = {
        "status": "PASS" if (
            all(item["match"] for item in checksum_results.values())
            and all(metric_matches.values())
            and retention_actual_matches_raw
            and sha256(PREDICTIONS) == score_payload["frozen_predictions_sha256_before_unblinding"]
        ) else "FAIL",
        "all_manifest_checksums_match": all(item["match"] for item in checksum_results.values()),
        "frozen_prediction_hash_matches_score": (
            sha256(PREDICTIONS) == score_payload["frozen_predictions_sha256_before_unblinding"]
        ),
        "reported_metrics_match": all(metric_matches.values()),
        "retention_truth_matches_raw_csv": retention_actual_matches_raw,
        "recomputed_metrics": recomputed,
        "checksum_results": checksum_results,
    }
    output = PACKAGE / "05_QA" / "INDEPENDENT_RECOMPUTE_V1_0_0.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
