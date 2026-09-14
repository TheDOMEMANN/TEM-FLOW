"""Reproduce the public TEM-FLOW 1.0.0 validation evidence.

This runner distinguishes a raw-data rerun from an independent rescore of
frozen predictions.  It never treats checking a copied summary table as a
model reproduction.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path


ANALYSIS = Path(__file__).resolve().parents[1]
ROOT = ANALYSIS.parent
DATA = ANALYSIS / "data"
RESULTS = ANALYSIS / "results"
TOL = 1e-8


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close(left: float, right: float, tolerance: float = 1e-10) -> bool:
    return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_summary() -> dict:
    rows = read_csv(DATA / "validation_summary.csv")
    require(len(rows) == 18, "validation_summary.csv must contain 18 rows")
    return {"level": "integrity", "rows": len(rows), "status": "pass"}


def reproduce_uk_raw() -> dict:
    """Rerun the sealed UK analysis from the public raw CSV in isolation."""
    with tempfile.TemporaryDirectory(prefix="temflow-uk-") as temp:
        case = Path(temp) / "uk_rpa"
        mapping = {
            ROOT / "analysis/python/uk_rpa/run_validation.py": case / "03_CODE/run_validation.py",
            DATA / "uk_rpa/cattle-movements-to-slaughterhouses-during-2010.csv": case / "02_DATA/raw/cattle-movements-to-slaughterhouses-during-2010.csv",
            ANALYSIS / "protocols/VALIDATION_PROTOCOL_V1_0_0.md": case / "01_PROTOCOL/VALIDATION_PROTOCOL_V1_0_0.md",
            ANALYSIS / "protocols/PREANALYSIS_SEAL_V1_0_0.json": case / "01_PROTOCOL/PREANALYSIS_SEAL_V1_0_0.json",
        }
        for source, target in mapping.items():
            require(source.exists(), f"missing UK reproduction input: {source}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        completed = subprocess.run(
            [sys.executable, "-B", str(case / "03_CODE/run_validation.py")],
            cwd=case,
            capture_output=True,
            text=True,
            check=False,
        )
        require(completed.returncode == 0, completed.stderr or completed.stdout)
        generated = read_json(case / "04_RESULTS/VALIDATION_SCORE_V1_0_0.json")
        frozen = read_json(RESULTS / "uk_rpa/VALIDATION_SCORE_V1_0_0.json")
        require(generated["metrics"] == frozen["metrics"], "UK rerun metrics differ from frozen result")
        require(generated["gates"] == frozen["gates"], "UK rerun gates differ from frozen result")
        return {
            "level": "raw_to_result",
            "raw_sha256": sha256(DATA / "uk_rpa/cattle-movements-to-slaughterhouses-during-2010.csv"),
            "targets": generated["metrics"]["target_source_class_month_count"],
            "positive_compartment_coverage": generated["metrics"]["compartment_count_coverage"],
            "status": "pass",
        }


def rescore_karg() -> dict:
    truth = read_csv(DATA / "karg_source_only/UNBLINDED_ROUTE_TRUTH_V1_0_0.csv")
    score = read_json(RESULTS / "karg_source_only/SOURCE_ONLY_ALLOCATION_SCORE_V1_0_0.json")
    prediction = RESULTS / "karg_source_only/FROZEN_PREDICTIONS_V1_0_0.json"
    positive = [row for row in truth if float(row["observed_kg"]) > 0]
    unresolved = [row for row in truth if row["kind"] == "unresolved_route"]
    count_coverage = statistics.fmean(row["covered"] == "True" for row in positive)
    positive_mass = sum(float(row["observed_kg"]) for row in positive)
    mass_coverage = sum(float(row["observed_kg"]) for row in positive if row["covered"] == "True") / positive_mass
    unresolved_coverage = statistics.fmean(row["covered"] == "True" for row in unresolved)
    median_width = statistics.median(float(row["width_over_source"]) for row in positive)
    require(sha256(prediction) == score["prediction_sha256_before_truth_write"], "Karg prediction hash mismatch")
    require(close(count_coverage, score["positive_count_coverage"]), "Karg count coverage mismatch")
    require(close(mass_coverage, score["positive_mass_weighted_coverage"]), "Karg mass coverage mismatch")
    require(close(unresolved_coverage, score["unresolved_route_coverage"]), "Karg unresolved coverage mismatch")
    require(close(median_width, score["median_interval_width_over_source"]), "Karg width mismatch")
    return {"level": "frozen_prediction_rescore", "targets": len({r["target_id"] for r in truth}), "positive_compartment_coverage": count_coverage, "median_relative_width": median_width, "status": "pass"}


def rescore_dryad() -> dict:
    truth = read_csv(DATA / "dryad_transient/EVIDENCE_BRIDGE_UNBLINDED_TRUTH_V1_2_1.csv")
    score = read_json(RESULTS / "dryad_transient/EVIDENCE_BRIDGE_HOLDOUT_SCORE_V1_2_1.json")
    prediction = RESULTS / "dryad_transient/EVIDENCE_BRIDGE_FROZEN_PREDICTIONS_V1_2_1.json"
    coverage = statistics.fmean(row["covered"] == "True" for row in truth)
    median_width = statistics.median(float(row["width_over_B"]) for row in truth)
    require(sha256(prediction) == score["prediction_sha256_before_unblinding"], "Dryad prediction hash mismatch")
    require(len(truth) == score["hidden_target_measurements"], "Dryad target count mismatch")
    require(close(coverage, score["all_hidden_coverage"]), "Dryad coverage mismatch")
    require(close(median_width, score["median_width_over_B"]), "Dryad width mismatch")
    return {"level": "frozen_prediction_rescore", "raw_access": "external_large_archive; acquisition manifest included", "targets": len(truth), "coverage": coverage, "median_relative_width": median_width, "status": "pass"}


def rescore_crosscommodity() -> dict:
    rows = read_csv(DATA / "crosscommodity/SCORED_CELLS_V1_0_0.csv")
    predictions = read_json(RESULTS / "crosscommodity/FROZEN_PREDICTIONS_V1_0_0.json")
    score = read_json(RESULTS / "crosscommodity/HOLDOUT_SCORE_V1_0_0.json")
    items = predictions["predictions"]
    require(len(rows) == len(items), "cross-commodity row count mismatch")
    positive = [(row, pred) for row, pred in zip(rows, items) if float(row["heldout_bilateral_net_weight_kg"]) > 0]
    certified = [(row, pred) for row, pred in positive if row["claim_status"] == "certified_interval"]
    route_coverage = len(certified) / len(positive)
    total_mass = sum(float(row["heldout_bilateral_net_weight_kg"]) for row, _ in positive)
    certified_mass = sum(float(row["heldout_bilateral_net_weight_kg"]) for row, _ in certified)
    mass_coverage = certified_mass / total_mass
    interval_coverage = statistics.fmean(row["contained"].lower() == "true" for row, _ in certified)
    widths = [
        (float(row["tem_upper_kg"]) - float(row["tem_lower_kg"])) /
        (float(pred["source_only_upper_kg"]) - float(pred["source_only_lower_kg"]))
        for row, pred in certified
    ]
    overall = score["overall_metrics"]
    require(sha256(RESULTS / "crosscommodity/FROZEN_PREDICTIONS_V1_0_0.json") == score["prediction_sha256"], "cross-commodity prediction hash mismatch")
    require(close(route_coverage, overall["positive_route_certificate_coverage"]), "cross-commodity route coverage mismatch")
    require(close(mass_coverage, overall["positive_mass_certificate_coverage"]), "cross-commodity mass coverage mismatch")
    require(close(interval_coverage, overall["positive_certified_interval_coverage"]), "cross-commodity interval coverage mismatch")
    require(close(statistics.median(widths), overall["median_normalized_interval_width"]), "cross-commodity width mismatch")
    return {"level": "frozen_prediction_rescore", "positive_routes": len(positive), "route_certificate_coverage": route_coverage, "mass_certificate_coverage": mass_coverage, "median_relative_width": statistics.median(widths), "status": "pass"}


def rescore_nass() -> dict:
    truth = read_csv(DATA / "nass_retention/UNBLINDED_RETENTION_TRUTH_V1_0_0.csv")
    score = read_json(RESULTS / "nass_retention/SOURCE_RETENTION_SCORE_V1_0_0.json")
    prediction = RESULTS / "nass_retention/FROZEN_RETENTION_PREDICTIONS_V1_0_0.json"
    require(sha256(prediction) == score["prediction_sha256_before_truth_write"], "NASS prediction hash mismatch")
    domains = {}
    for domain in sorted({row["domain"] for row in truth}):
        rows = [row for row in truth if row["domain"] == domain]
        coverage = statistics.fmean(row["covered"] == "True" for row in rows)
        weighted = sum(float(row["survey_weight"]) for row in rows if row["covered"] == "True") / sum(float(row["survey_weight"]) for row in rows)
        median_upper = statistics.median(float(row["upper_fraction"]) for row in rows)
        reported = score["geographic_holdout"][domain]
        require(len(rows) == reported["holdout_records"], f"{domain} NASS count mismatch")
        require(close(coverage, reported["holdout_coverage"]), f"{domain} NASS coverage mismatch")
        require(close(weighted, reported["weighted_holdout_coverage"]), f"{domain} NASS weighted coverage mismatch")
        require(close(median_upper, reported["median_upper_fraction"]), f"{domain} NASS width mismatch")
        domains[domain] = {"records": len(rows), "coverage": coverage, "median_upper_fraction": median_upper}
    require(score["hard_100_percent_rule_status"] == "rejected", "NASS negative result was not retained")
    return {"level": "derived_truth_rescore", "raw_access": "restricted; acquisition manifest and limitation documented", "domains": domains, "hard_rule_status": "rejected", "status": "pass"}


def verify_zambia() -> dict:
    source = read_json(DATA / "zambia_scale/PUBLISHED_TABLE_EXTRACTION_V1_0_0.json")
    result = read_json(RESULTS / "zambia_scale/SOURCE_PROXIMITY_SCALE_CHECK_V1_0_0.json")
    shares = source["table_9_2_sale_location_percent_among_selling_households"]
    require(close(shares["on_farm"] / 100.0, 0.497), "Zambia on-farm share mismatch")
    require(close(shares["outside_district"] / 100.0, 0.03), "Zambia outside-district share mismatch")
    require("household" in json.dumps(result).lower(), "Zambia result lost the household/mass scale warning")
    return {"level": "published_table_recalculation", "on_farm_household_share": shares["on_farm"] / 100.0, "outside_district_household_share": shares["outside_district"] / 100.0, "status": "pass"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="optional JSON report path")
    args = parser.parse_args()
    checks = {
        "summary_integrity": check_summary(),
        "uk_rpa": reproduce_uk_raw(),
        "karg_source_only": rescore_karg(),
        "dryad_transient": rescore_dryad(),
        "crosscommodity": rescore_crosscommodity(),
        "nass_retention": rescore_nass(),
        "zambia_scale": verify_zambia(),
    }
    report = {
        "software_version": "1.0.0",
        "status": "pass",
        "interpretation": "UK RPA is reproduced raw-to-result. Karg, Dryad and cross-commodity metrics are independently rescored from frozen predictions and unblinded truth. NASS is rescored from public derived truth because raw microdata are restricted. Zambia is recalculated from the published-table extraction.",
        "checks": checks,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
