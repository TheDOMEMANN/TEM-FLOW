"""Validate TEM-FLOW route intervals using source totals without target margins."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import statistics
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix


HERE = Path(__file__).resolve()
PACKAGE = HERE.parents[1]
OUTPUTS = HERE.parents[2]
RAW = (
    OUTPUTS
    / "TEMFLOW_Patterns_70pct_readiness_protocol_v1_0_0_2026-09-08"
    / "01_PROTOCOL"
    / "data"
    / "karg_west_africa_food_flows"
    / "Food_flow_data_v1.csv"
)
ERR_SOURCE = (
    OUTPUTS
    / "TEMFLOW_Patterns_evidence_resolved_v1_1_0_2026-09-01"
    / "SOFTWARE"
    / "src"
    / "temflow"
    / "evidential_resolution.py"
)
EXPECTED_RAW_SHA256 = "e2ca52be88ee0efe2b5e1b2ccd1a5b30a360751b9ecc99e8729c4200adaece41"
EXPECTED_ERR_SHA256 = "fcd1b1e836ea9ceeacbcbc5fa4cf8456e2fac174b89ad1635acab2bf97ef7bb0"
EXCLUDED_MODES = {"Rail", "Plane", "Boat/ferry"}


def load_err():
    spec = importlib.util.spec_from_file_location("temflow_err_karg", ERR_SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load ERR source")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ERR = load_err()


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
        raise RuntimeError("empty calibration residual set")
    ordered = sorted(float(value) for value in values)
    rank = min(len(ordered), max(1, math.ceil((len(ordered) + 1) * coverage)))
    return ordered[rank - 1]


def panel_id(key: tuple[object, ...]) -> str:
    return hashlib.sha256("|".join(map(str, key)).encode("utf-8")).hexdigest()[:16].upper()


def main() -> int:
    if sha256(RAW) != EXPECTED_RAW_SHA256:
        raise RuntimeError("Karg raw file hash differs from the frozen source")
    if sha256(ERR_SOURCE) != EXPECTED_ERR_SHA256:
        raise RuntimeError("ERR source hash differs from the frozen source")

    frame = pd.read_csv(RAW, sep=";", encoding="cp1252", low_memory=False)
    frame["survey_date"] = pd.to_datetime(frame["date"], errors="coerce", dayfirst=True)
    frame["mass_kg"] = pd.to_numeric(frame["total_quantity"], errors="coerce")
    required = [
        "city",
        "year",
        "season",
        "commodity_name_gen",
        "direction",
        "survey_date",
        "source_name",
        "data_collection_name",
        "destination_name",
        "means_of_transport",
        "mass_kg",
    ]
    eligible = frame.dropna(subset=required).copy()
    eligible = eligible[
        (eligible["mass_kg"] > 0)
        & (~eligible["means_of_transport"].isin(EXCLUDED_MODES))
    ]

    group_fields = ["city", "year", "season", "commodity_name_gen", "direction"]
    models: list[dict[str, object]] = []
    calibration_rows: list[dict[str, object]] = []
    target_inputs: list[dict[str, object]] = []
    target_lookup: dict[tuple[str, str, str], pd.DataFrame] = {}

    for key, panel in eligible.groupby(group_fields, sort=True):
        dates = sorted(pd.Timestamp(value) for value in panel["survey_date"].unique())
        if len(dates) < 6:
            continue
        n_fit = max(3, int(math.floor(0.60 * len(dates))))
        n_cal = max(1, int(math.floor(0.20 * len(dates))))
        if n_fit + n_cal >= len(dates):
            n_cal = 1
            n_fit = len(dates) - 2
        fit_dates = dates[:n_fit]
        calibration_dates = dates[n_fit : n_fit + n_cal]
        target_dates = dates[n_fit + n_cal :]
        fit_panel = panel[panel["survey_date"].isin(fit_dates)]
        calibration_panel = panel[panel["survey_date"].isin(calibration_dates)]
        target_panel = panel[panel["survey_date"].isin(target_dates)]
        pid = panel_id(tuple(key))

        for source in sorted(str(value) for value in fit_panel["source_name"].unique()):
            fit_source = fit_panel[fit_panel["source_name"].astype(str) == source]
            grouped_fit = (
                fit_source.groupby(["data_collection_name", "destination_name"])["mass_kg"]
                .sum()
                .sort_index()
            )
            fit_total = float(grouped_fit.sum())
            if fit_total <= 0:
                continue
            support = [(str(a), str(b)) for a, b in grouped_fit.index]
            historical = {
                f"{a}|{b}": float(grouped_fit.loc[(a, b)] / fit_total)
                for a, b in support
            }
            bucket = f"{key[0]}|{key[4]}"
            model = {
                "panel_id": pid,
                "panel_key": tuple(key),
                "source": source,
                "fit_dates": fit_dates,
                "calibration_dates": calibration_dates,
                "target_dates": target_dates,
                "support": support,
                "historical": historical,
                "bucket": bucket,
            }
            models.append(model)

            for date in calibration_dates:
                sample = calibration_panel[
                    (calibration_panel["survey_date"] == date)
                    & (calibration_panel["source_name"].astype(str) == source)
                ]
                source_total = float(sample["mass_kg"].sum())
                if source_total <= 0:
                    continue
                actual = sample.groupby(["data_collection_name", "destination_name"])["mass_kg"].sum()
                support_set = set(support)
                for route in support:
                    actual_share = float(actual.get(route, 0.0) / source_total)
                    expected_share = historical[f"{route[0]}|{route[1]}"]
                    calibration_rows.append(
                        {
                            "panel_id": pid,
                            "bucket": bucket,
                            "date": date.date().isoformat(),
                            "source": source,
                            "kind": "known_route",
                            "route": f"{route[0]}|{route[1]}",
                            "residual": abs(actual_share - expected_share),
                        }
                    )
                unresolved_share = float(
                    sum(float(value) for route, value in actual.items() if route not in support_set)
                    / source_total
                )
                calibration_rows.append(
                    {
                        "panel_id": pid,
                        "bucket": bucket,
                        "date": date.date().isoformat(),
                        "source": source,
                        "kind": "unresolved_route",
                        "route": "UNRESOLVED",
                        "residual": unresolved_share,
                    }
                )

            for date in target_dates:
                sample = target_panel[
                    (target_panel["survey_date"] == date)
                    & (target_panel["source_name"].astype(str) == source)
                ]
                source_total = float(sample["mass_kg"].sum())
                if source_total <= 0:
                    continue
                target_id = f"{pid}|{date.date().isoformat()}|{source}"
                target_inputs.append(
                    {
                        "target_id": target_id,
                        "panel_id": pid,
                        "date": date.date().isoformat(),
                        "source": source,
                        "source_total_kg": source_total,
                    }
                )
                target_lookup[(pid, date.date().isoformat(), source)] = sample

    if not calibration_rows:
        raise RuntimeError("no calibration residuals")
    global_known = [float(row["residual"]) for row in calibration_rows if row["kind"] == "known_route"]
    global_unresolved = [float(row["residual"]) for row in calibration_rows if row["kind"] == "unresolved_route"]
    bucket_radii: dict[str, dict[str, object]] = {}
    for bucket in sorted({str(model["bucket"]) for model in models}):
        known = [
            float(row["residual"])
            for row in calibration_rows
            if row["bucket"] == bucket and row["kind"] == "known_route"
        ]
        unresolved = [
            float(row["residual"])
            for row in calibration_rows
            if row["bucket"] == bucket and row["kind"] == "unresolved_route"
        ]
        selected_known = known if len(known) >= 30 else global_known
        selected_unresolved = unresolved if len(unresolved) >= 30 else global_unresolved
        bucket_radii[bucket] = {
            "known_route_radius": finite_quantile(selected_known, 0.90),
            "unresolved_upper_share": finite_quantile(selected_unresolved, 0.90),
            "known_residual_count": len(selected_known),
            "unresolved_residual_count": len(selected_unresolved),
            "known_scope": "city_direction" if len(known) >= 30 else "global",
            "unresolved_scope": "city_direction" if len(unresolved) >= 30 else "global",
        }

    calibration_path = PACKAGE / "02_DATA" / "derived" / "CALIBRATION_RESIDUALS_V1_0_0.csv"
    with calibration_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(calibration_rows[0]))
        writer.writeheader()
        writer.writerows(calibration_rows)

    models_by_key = {(str(model["panel_id"]), str(model["source"])): model for model in models}
    predictions: list[dict[str, object]] = []
    max_violation = 0.0
    all_unresolved_blocked = True
    no_operational_point = True
    for target in target_inputs:
        model = models_by_key[(str(target["panel_id"]), str(target["source"]))]
        support = list(model["support"])
        historical = dict(model["historical"])
        radius = bucket_radii[str(model["bucket"])]
        total = float(target["source_total_kg"])
        names = tuple([f"route_{index:04d}" for index in range(len(support))] + ["unresolved_route"])
        lower_share = [
            max(0.0, float(historical[f"{route[0]}|{route[1]}"]) - float(radius["known_route_radius"]))
            for route in support
        ] + [0.0]
        upper_share = [
            min(1.0, float(historical[f"{route[0]}|{route[1]}"]) + float(radius["known_route_radius"]))
            for route in support
        ] + [min(1.0, float(radius["unresolved_upper_share"]))]
        polytope = ERR.FlowPolytope(
            variable_names=names,
            prior=None,
            lower=np.asarray(lower_share, dtype=float) * total,
            upper=np.asarray(upper_share, dtype=float) * total,
            A_eq=csr_matrix(np.ones((1, len(names)), dtype=float)),
            b_eq=np.asarray([total], dtype=float),
            A_ub=csr_matrix((0, len(names))),
            b_ub=np.asarray([], dtype=float),
            equality_names=("source mass balance",),
        )
        certificates = {
            name: (f"KARG-FIT-PATH-{target['panel_id']}-{index:04d}",)
            for index, name in enumerate(names[:-1])
        }
        result = ERR.evidence_resolved_reconstruction(
            polytope,
            certified_mask=tuple([True] * len(support) + [False]),
            evidence_ids=(f"KARG-SOURCE-TOTAL-{target['target_id']}", "KARG-FIT-ROUTE-SKELETON"),
            certificate_ids_by_coordinate=certificates,
            unresolved_weights=tuple([0.0] * len(support) + [1.0]),
            require_operational_table=False,
            tolerance=1e-8,
        )
        payload = result.to_dict()
        coordinates = {item["variable"]: item for item in payload["coordinates"]}
        route_predictions = []
        for index, route in enumerate(support):
            coordinate = coordinates[names[index]]
            route_predictions.append(
                {
                    "checkpoint": route[0],
                    "destination": route[1],
                    "historical_share": historical[f"{route[0]}|{route[1]}"],
                    "neutral_interval_kg": coordinate["neutral_interval"],
                    "named_report_status": coordinate["named_report_status"],
                }
            )
        unresolved_claim = result.claim("unresolved_route")
        solver_violation = float(payload["solver_certificate"]["maximum_constraint_violation"])
        max_violation = max(max_violation, solver_violation)
        all_unresolved_blocked = (
            all_unresolved_blocked
            and unresolved_claim["status"] == "blocked_unresolved_identity"
        )
        no_operational_point = no_operational_point and result.operational_allocation is None
        predictions.append(
            {
                **target,
                "bucket": model["bucket"],
                "calibration_radius": radius,
                "known_routes": route_predictions,
                "unresolved_interval_kg": coordinates["unresolved_route"]["neutral_interval"],
                "unresolved_named_report_status": unresolved_claim["status"],
                "maximum_constraint_violation": solver_violation,
                "operational_point": None,
            }
        )

    prediction_payload = {
        "version": "1.0.0",
        "algorithm": "TEM-FLOW source-only Evidence Bridge through ERR",
        "target_route_masses_used_for_prediction": False,
        "target_checkpoint_margins_used": False,
        "target_destination_margins_used": False,
        "calibration_radii": bucket_radii,
        "predictions": predictions,
    }
    prediction_path = PACKAGE / "04_RESULTS" / "FROZEN_PREDICTIONS_V1_0_0.json"
    write_json(prediction_path, prediction_payload)
    prediction_hash = sha256(prediction_path)

    truth_rows: list[dict[str, object]] = []
    for prediction in predictions:
        sample = target_lookup[(str(prediction["panel_id"]), str(prediction["date"]), str(prediction["source"]))]
        actual = sample.groupby(["data_collection_name", "destination_name"])["mass_kg"].sum()
        known_set = {
            (str(route["checkpoint"]), str(route["destination"]))
            for route in prediction["known_routes"]
        }
        for route in prediction["known_routes"]:
            identity = (str(route["checkpoint"]), str(route["destination"]))
            observed = float(actual.get(identity, 0.0))
            low, high = map(float, route["neutral_interval_kg"])
            truth_rows.append(
                {
                    "target_id": prediction["target_id"],
                    "kind": "known_route",
                    "checkpoint": identity[0],
                    "destination": identity[1],
                    "source_total_kg": prediction["source_total_kg"],
                    "observed_kg": observed,
                    "lower_kg": low,
                    "upper_kg": high,
                    "covered": low - 1e-9 <= observed <= high + 1e-9,
                    "width_over_source": (high - low) / float(prediction["source_total_kg"]),
                }
            )
        unresolved_observed = float(sum(float(value) for route, value in actual.items() if route not in known_set))
        low, high = map(float, prediction["unresolved_interval_kg"])
        truth_rows.append(
            {
                "target_id": prediction["target_id"],
                "kind": "unresolved_route",
                "checkpoint": "",
                "destination": "UNRESOLVED",
                "source_total_kg": prediction["source_total_kg"],
                "observed_kg": unresolved_observed,
                "lower_kg": low,
                "upper_kg": high,
                "covered": low - 1e-9 <= unresolved_observed <= high + 1e-9,
                "width_over_source": (high - low) / float(prediction["source_total_kg"]),
            }
        )

    truth_path = PACKAGE / "02_DATA" / "derived" / "UNBLINDED_ROUTE_TRUTH_V1_0_0.csv"
    with truth_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(truth_rows[0]))
        writer.writeheader()
        writer.writerows(truth_rows)

    positive = [row for row in truth_rows if float(row["observed_kg"]) > 0]
    unresolved = [row for row in truth_rows if row["kind"] == "unresolved_route"]
    count_coverage = statistics.fmean(bool(row["covered"]) for row in positive) if positive else 0.0
    total_positive_mass = sum(float(row["observed_kg"]) for row in positive)
    mass_coverage = (
        sum(float(row["observed_kg"]) for row in positive if bool(row["covered"])) / total_positive_mass
        if total_positive_mass > 0
        else 0.0
    )
    unresolved_coverage = statistics.fmean(bool(row["covered"]) for row in unresolved) if unresolved else 0.0
    widths = [float(row["width_over_source"]) for row in positive]
    resolved_mass = sum(
        float(row["observed_kg"]) for row in positive if row["kind"] == "known_route"
    )
    total_source_mass = sum(float(item["source_total_kg"]) for item in predictions)
    gates = {
        "minimum_50_target_source_dates": len(predictions) >= 50,
        "minimum_100_positive_compartments": len(positive) >= 100,
        "positive_count_coverage_at_least_0_80": count_coverage >= 0.80,
        "positive_mass_coverage_at_least_0_80": mass_coverage >= 0.80,
        "unresolved_coverage_at_least_0_80": unresolved_coverage >= 0.80,
        "median_width_over_source_at_most_0_50": bool(widths) and statistics.median(widths) <= 0.50,
        "solver_violation_at_most_1e_8": max_violation <= 1e-8,
        "unresolved_identity_blocked": all_unresolved_blocked,
        "no_operational_point": no_operational_point,
    }
    score = {
        "status": "pass" if all(gates.values()) else "fail",
        "prediction_sha256_before_truth_write": prediction_hash,
        "eligible_target_source_dates": len(predictions),
        "positive_target_compartments": len(positive),
        "positive_count_coverage": count_coverage,
        "positive_mass_weighted_coverage": mass_coverage,
        "unresolved_route_coverage": unresolved_coverage,
        "median_interval_width_over_source": statistics.median(widths) if widths else None,
        "known_path_share_of_target_mass": resolved_mass / total_source_mass if total_source_mass else None,
        "maximum_solver_constraint_violation": max_violation,
        "gates": gates,
        "claim_boundary": (
            "Retrospective, temporally separated source-total-to-route interval validation on "
            "field-standardized West African city food flows. No target checkpoint or destination "
            "margins were supplied. This is not full farm-to-fork or source-retention validation."
        ),
    }
    score_path = PACKAGE / "04_RESULTS" / "SOURCE_ONLY_ALLOCATION_SCORE_V1_0_0.json"
    write_json(score_path, score)
    audit = {
        "raw_sha256": sha256(RAW),
        "err_source_sha256": sha256(ERR_SOURCE),
        "script_sha256": sha256(HERE),
        "calibration_sha256": sha256(calibration_path),
        "prediction_sha256": sha256(prediction_path),
        "truth_sha256": sha256(truth_path),
        "score_sha256": sha256(score_path),
        "prediction_hashed_before_truth_write": True,
    }
    write_json(PACKAGE / "06_QA" / "EXECUTION_AUDIT_V1_0_0.json", audit)
    print(json.dumps({key: value for key, value in score.items() if key != "gates"}, indent=2))
    print(json.dumps(gates, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
