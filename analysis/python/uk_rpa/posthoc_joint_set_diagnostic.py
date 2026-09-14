"""Post-hoc diagnostic of simultaneous membership in each frozen TV set.

This diagnostic was not a frozen pass gate and cannot change the main decision.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


HERE = Path(__file__).resolve()
PACKAGE = HERE.parents[1]
PREDICTIONS = PACKAGE / "04_RESULTS" / "FROZEN_PREDICTIONS_V1_0_0.json"
TRUTH = PACKAGE / "02_DATA" / "derived" / "UNBLINDED_DESTINATION_TRUTH_V1_0_0.csv"


def main() -> int:
    predictions = json.loads(PREDICTIONS.read_text(encoding="utf-8"))["predictions"]
    truth: dict[str, dict[str, float]] = defaultdict(dict)
    with TRUTH.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            truth[row["target_id"]][row["destination"]] = float(row["actual_count"])

    rows = []
    for prediction in predictions:
        remainder = float(prediction["conditional_remainder_count"])
        if remainder <= 0:
            continue
        tv = 0.5 * sum(
            abs(
                truth[prediction["target_id"]][coordinate["destination"]] / remainder
                - float(coordinate["historical_conditional_share"])
            )
            for coordinate in prediction["coordinates"]
        )
        epsilon = float(prediction["epsilon"])
        rows.append(
            {
                "movement_class": prediction["movement_class"],
                "remainder": remainder,
                "total_variation": tv,
                "epsilon": epsilon,
                "inside_joint_set": tv <= epsilon + 1e-12,
            }
        )

    by_class = {}
    for movement_class in ("direct", "indirect"):
        selected = [row for row in rows if row["movement_class"] == movement_class]
        by_class[movement_class] = {
            "target_count": len(selected),
            "simultaneous_joint_set_coverage": sum(row["inside_joint_set"] for row in selected)
            / len(selected),
            "remainder_weighted_joint_set_coverage": sum(
                row["remainder"] for row in selected if row["inside_joint_set"]
            )
            / sum(row["remainder"] for row in selected),
            "median_total_variation": statistics.median(row["total_variation"] for row in selected),
        }
    result = {
        "status": "post_hoc_diagnostic_not_a_frozen_gate",
        "all_classes": {
            "target_count": len(rows),
            "simultaneous_joint_set_coverage": sum(row["inside_joint_set"] for row in rows)
            / len(rows),
            "remainder_weighted_joint_set_coverage": sum(
                row["remainder"] for row in rows if row["inside_joint_set"]
            )
            / sum(row["remainder"] for row in rows),
            "median_total_variation": statistics.median(row["total_variation"] for row in rows),
        },
        "by_class": by_class,
        "interpretation": (
            "Simultaneous coverage tests whether the whole withheld destination vector, not merely each "
            "coordinate, lies inside the frozen joint total-variation set."
        ),
    }
    output = PACKAGE / "05_QA" / "POSTHOC_JOINT_SET_DIAGNOSTIC_V1_0_0.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
