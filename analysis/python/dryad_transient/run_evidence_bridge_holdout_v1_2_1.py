"""Run the outcome-blind Evidence Bridge amendment on two raw holdout days."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix


HERE = Path(__file__).resolve()
PACKAGE = HERE.parents[1]
OUTPUTS = HERE.parents[2]
HOLDOUT_DIR = PACKAGE / "02_DATA" / "derived" / "holdout_raw"
ACQUISITION = PACKAGE / "02_DATA" / "derived" / "HOLDOUT_ACQUISITION_MANIFEST_V1_2_0.json"
CALIBRATION = PACKAGE / "02_DATA" / "derived" / "BRIDGE_CALIBRATION_PREFIX_V1_2_0.csv"
ERR_SOURCE = (
    OUTPUTS
    / "TEMFLOW_Patterns_evidence_resolved_v1_1_0_2026-09-01"
    / "SOFTWARE"
    / "src"
    / "temflow"
    / "evidential_resolution.py"
)
EXPECTED_CALIBRATION_SHA256 = "8bed7fcbb543152fcf13f7bb728c9cdd010d23a41ad3948580d66e60b4ea9ace"
EXPECTED_ERR_SHA256 = "fcd1b1e836ea9ceeacbcbc5fa4cf8456e2fac174b89ad1635acab2bf97ef7bb0"
ANCHOR_Q = tuple(round(index * 0.1, 2) for index in range(11))
HIDDEN_Q = tuple(round(0.05 + index * 0.1, 2) for index in range(10))
GRID_Q = tuple(round(index * 0.05, 2) for index in range(21))
RADII = {
    0.05: 0.002143514998237819,
    0.15: 0.0001886288727136061,
    0.25: 0.016117370499098657,
    0.35: 0.011201704490921014,
    0.45: 0.029846480030695195,
    0.55: 0.03214349206055058,
    0.65: 0.02557431864822125,
    0.75: 0.024819608624973635,
    0.85: 0.025204718133751608,
    0.95: 0.12306125929182522,
}


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("temflow_err_evidence_bridge", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ERR = load_module(ERR_SOURCE)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@dataclass
class HoldoutEpisode:
    episode_id: str
    member: str
    unit_id: str
    start_tow: float
    end_tow: float
    duration_seconds: float
    rows: int
    anchors: dict[float, tuple[float, float, float]]
    truths: dict[float, float]


def longest_pick_run(group: pd.DataFrame) -> pd.DataFrame | None:
    group = group.sort_values("GPS_TOW", kind="stable").reset_index(drop=True)
    times = pd.to_numeric(group["GPS_TOW"], errors="coerce").to_numpy(float)
    picks = group["activity"].astype(str).str.strip().eq("Pick").to_numpy(bool, copy=True)
    picks &= np.isfinite(times)
    starts = picks & np.r_[True, (~picks[:-1]) | ((times[1:] - times[:-1]) > 500.0)]
    run_ids = np.cumsum(starts)
    candidates = []
    for run_id in np.unique(run_ids[picks]):
        idx = np.flatnonzero(picks & (run_ids == run_id))
        if idx.size:
            duration = (times[idx[-1]] - times[idx[0]]) / 1000.0
            candidates.append((duration, times[idx[0]], int(idx.size), idx))
    if not candidates:
        return None
    duration, _, count, idx = sorted(candidates, key=lambda item: (-item[0], item[1]))[0]
    if duration < 60.0 or count < 500:
        return None
    return group.iloc[idx].copy()


def values_at(run: pd.DataFrame, center: float) -> np.ndarray:
    times = pd.to_numeric(run["GPS_TOW"], errors="coerce").to_numpy(float)
    masses = pd.to_numeric(run["raw_mass"], errors="coerce").to_numpy(float)
    values = masses[np.isfinite(masses) & (np.abs(times - center) <= 500.0)]
    if values.size == 0:
        nearest = np.nanargmin(np.abs(times - center))
        values = masses[[nearest]]
    return values[np.isfinite(values)]


def extract_holdout() -> tuple[list[HoldoutEpisode], list[dict[str, object]]]:
    episodes = []
    inventory = []
    expected = json.loads(ACQUISITION.read_text(encoding="utf-8"))["targets"]
    expected_by_name = {item["name"]: item for item in expected}
    paths = sorted(HOLDOUT_DIR.glob("*_train-ready_all_carts.csv"), key=lambda item: item.name)
    if {path.name for path in paths} != set(expected_by_name):
        raise RuntimeError("holdout target set mismatch")
    for path in paths:
        record = expected_by_name[path.name]
        if sha256(path) != record["uncompressed_sha256"]:
            raise RuntimeError(f"holdout SHA-256 mismatch: {path.name}")
        frame = pd.read_csv(
            path,
            usecols=["date_cartID", "GPS_TOW", "raw_mass", "activity"],
            low_memory=False,
        )
        inventory.append({"member": path.name, "rows": int(len(frame)), "sha256": sha256(path)})
        for unit_id, group in frame.groupby("date_cartID", sort=True, dropna=False):
            run = longest_pick_run(group)
            if run is None:
                continue
            times = pd.to_numeric(run["GPS_TOW"], errors="coerce").to_numpy(float)
            start = float(times[0])
            end = float(times[-1])
            grid = {}
            for q in GRID_Q:
                values = values_at(run, start + q * (end - start))
                if values.size == 0:
                    grid = {}
                    break
                low, high = np.quantile(values, [0.025, 0.975])
                grid[q] = (float(low), float(high), float(np.median(values)))
            if not grid:
                continue
            raw_id = f"{path.name}|{unit_id}|{start:.6f}|{end:.6f}"
            episode_id = hashlib.sha256(raw_id.encode()).hexdigest()[:24]
            episodes.append(
                HoldoutEpisode(
                    episode_id=episode_id,
                    member=path.name,
                    unit_id=str(unit_id),
                    start_tow=start,
                    end_tow=end,
                    duration_seconds=(end - start) / 1000.0,
                    rows=int(len(run)),
                    anchors={q: grid[q] for q in ANCHOR_Q},
                    truths={q: grid[q][2] for q in HIDDEN_Q},
                )
            )
        del frame
    return episodes, inventory


def bridge_bounds(episode: HoldoutEpisode) -> tuple[dict[float, tuple[float, float]], float]:
    scale = max(abs(episode.anchors[0.0][2]), abs(episode.anchors[1.0][2]), 1.0)
    bounds = {}
    for q in HIDDEN_Q:
        left_q = round(q - 0.05, 2)
        right_q = round(q + 0.05, 2)
        left = episode.anchors[left_q]
        right = episode.anchors[right_q]
        radius = RADII[q] * scale
        bounds[q] = (
            max(0.0, min(left[0], right[0]) - radius),
            max(0.0, max(left[1], right[1]) + radius),
        )
    return bounds, scale


def predict(episode: HoldoutEpisode) -> dict[str, object]:
    hidden_bounds, scale = bridge_bounds(episode)
    state_names = tuple(f"cart_mass_q{index:02d}_kg" for index in range(21))
    addition_names = tuple(f"certified_pick_addition_t{index:02d}_kg" for index in range(1, 21))
    removal_names = tuple(f"latent_removal_t{index:02d}_kg" for index in range(1, 21))
    names = state_names + addition_names + removal_names
    state_lower = []
    state_upper = []
    for index, q in enumerate(GRID_Q):
        if index % 2 == 0:
            low, high, _ = episode.anchors[q]
            state_lower.append(max(0.0, low))
            state_upper.append(max(0.0, high))
        else:
            low, high = hidden_bounds[q]
            state_lower.append(low)
            state_upper.append(high)
    delta = max(max(state_upper) - min(state_lower), 1e-9)
    lower = np.r_[np.asarray(state_lower), np.zeros(40)]
    upper = np.r_[np.asarray(state_upper), np.full(40, delta)]
    a_eq = np.zeros((20, len(names)))
    for transition in range(20):
        a_eq[transition, transition] = -1.0
        a_eq[transition, transition + 1] = 1.0
        a_eq[transition, 21 + transition] = -1.0
        a_eq[transition, 41 + transition] = 1.0
    polytope = ERR.FlowPolytope(
        variable_names=names,
        prior=None,
        lower=lower,
        upper=upper,
        A_eq=csr_matrix(a_eq),
        b_eq=np.zeros(20),
        A_ub=csr_matrix((0, len(names))),
        b_ub=np.asarray([], dtype=float),
        equality_names=tuple(f"mass balance transition {index}" for index in range(1, 21)),
    )
    certificates = {
        **{name: ("TEM-CERT-DRYAD-EVIDENCE-BRIDGE-STATE-V1",) for name in state_names},
        **{name: ("TEM-CERT-DRYAD-PICK-ACTIVITY-V1",) for name in addition_names},
    }
    result = ERR.evidence_resolved_reconstruction(
        polytope,
        certified_mask=tuple([True] * 41 + [False] * 20),
        evidence_ids=(
            f"DRYAD-HOLDOUT-{episode.episode_id}-ANCHORS",
            "DRYAD-PREFIX-CALIBRATION-RADII-V1_2_0",
        ),
        certificate_ids_by_coordinate=certificates,
        unresolved_weights=tuple([0.0] * 41 + [1.0] * 20),
        require_operational_table=False,
        tolerance=1e-8,
    )
    payload = result.to_dict()
    coordinates = {item["variable"]: item for item in payload["coordinates"]}
    hidden = []
    for index, q in enumerate(HIDDEN_Q):
        coordinate = coordinates[f"cart_mass_q{2 * index + 1:02d}_kg"]
        hidden.append(
            {
                "q": q,
                "rho": RADII[q],
                "neutral_interval_kg": coordinate["neutral_interval"],
                "named_report_status": coordinate["named_report_status"],
            }
        )
    removal_claims = [result.claim(name) for name in removal_names]
    return {
        "episode_id": episode.episode_id,
        "member": episode.member,
        "unit_id": episode.unit_id,
        "duration_seconds": episode.duration_seconds,
        "rows": episode.rows,
        "scale_B_kg": scale,
        "hidden_intervals": hidden,
        "solver_certificate": payload["solver_certificate"],
        "operational_projection": payload["operational_projection"],
        "all_removal_claims_blocked": all(
            claim["status"] == "blocked_unresolved_identity" for claim in removal_claims
        ),
    }


def main() -> int:
    if sha256(CALIBRATION) != EXPECTED_CALIBRATION_SHA256:
        raise RuntimeError("calibration hash changed after lock")
    if sha256(ERR_SOURCE) != EXPECTED_ERR_SHA256:
        raise RuntimeError("ERR source hash changed after lock")
    episodes, inventory = extract_holdout()

    predictor = {
        "version": "1.2.1",
        "implementation_amendment": "nonnegative intersection applied to both interval endpoints",
        "target_excluded_from_calibration": True,
        "target_raw_mass_printed_before_prediction": False,
        "calibration_sha256": EXPECTED_CALIBRATION_SHA256,
        "eligible_episode_count": len(episodes),
        "target_inventory": inventory,
        "episodes": [
            {
                "episode_id": episode.episode_id,
                "member": episode.member,
                "unit_id": episode.unit_id,
                "start_tow": episode.start_tow,
                "end_tow": episode.end_tow,
                "duration_seconds": episode.duration_seconds,
                "rows": episode.rows,
                "anchors": {
                    f"{q:.2f}": {
                        "low_kg": episode.anchors[q][0],
                        "high_kg": episode.anchors[q][1],
                        "median_kg": episode.anchors[q][2],
                    }
                    for q in ANCHOR_Q
                },
            }
            for episode in episodes
        ],
    }
    predictor_path = PACKAGE / "02_DATA" / "derived" / "EVIDENCE_BRIDGE_BLIND_PREDICTOR_V1_2_1.json"
    write_json(predictor_path, predictor)

    predictions = {
        "algorithm": "TEM-FLOW Evidence Bridge through ERR",
        "version": "1.2.1",
        "implementation_amendment": "nonnegative intersection applied to both interval endpoints",
        "truth_access_during_prediction": False,
        "target_used_for_calibration": False,
        "radii": {f"{q:.2f}": value for q, value in RADII.items()},
        "episodes": [predict(episode) for episode in episodes],
    }
    prediction_path = PACKAGE / "04_RESULTS" / "EVIDENCE_BRIDGE_FROZEN_PREDICTIONS_V1_2_1.json"
    write_json(prediction_path, predictions)
    prediction_hash = sha256(prediction_path)

    truth_rows = []
    for episode, prediction in zip(episodes, predictions["episodes"], strict=True):
        for q, interval in zip(HIDDEN_Q, prediction["hidden_intervals"], strict=True):
            truth = episode.truths[q]
            low, high = interval["neutral_interval_kg"]
            truth_rows.append(
                {
                    "episode_id": episode.episode_id,
                    "member": episode.member,
                    "unit_id": episode.unit_id,
                    "q": q,
                    "truth_kg": truth,
                    "lower_kg": low,
                    "upper_kg": high,
                    "covered": low <= truth <= high,
                    "width_kg": high - low,
                    "scale_B_kg": prediction["scale_B_kg"],
                    "width_over_B": (high - low) / prediction["scale_B_kg"],
                }
            )
    truth_path = PACKAGE / "02_DATA" / "derived" / "EVIDENCE_BRIDGE_UNBLINDED_TRUTH_V1_2_1.csv"
    with truth_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(truth_rows[0]) if truth_rows else ["episode_id"])
        writer.writeheader()
        writer.writerows(truth_rows)

    coverage = statistics.fmean(bool(row["covered"]) for row in truth_rows) if truth_rows else 0.0
    q95 = [row for row in truth_rows if math.isclose(float(row["q"]), 0.95)]
    q95_coverage = statistics.fmean(bool(row["covered"]) for row in q95) if q95 else 0.0
    widths = [float(row["width_over_B"]) for row in truth_rows]
    max_violation = max(
        float(item["solver_certificate"]["maximum_constraint_violation"])
        for item in predictions["episodes"]
    ) if predictions["episodes"] else math.inf
    gates = {
        "minimum_20_target_episodes": len(episodes) >= 20,
        "target_files_crc_and_sha_verified": True,
        "target_excluded_from_calibration": True,
        "all_hidden_coverage_at_least_0_80": coverage >= 0.8,
        "q95_coverage_at_least_0_90": q95_coverage >= 0.9,
        "median_width_over_B_at_most_0_25": bool(widths) and statistics.median(widths) <= 0.25,
        "solver_violation_at_most_1e_8": max_violation <= 1e-8,
        "unsupported_removals_blocked": all(
            bool(item["all_removal_claims_blocked"]) for item in predictions["episodes"]
        ),
        "no_operational_point": all(
            item["operational_projection"]["status"] == "not_requested"
            for item in predictions["episodes"]
        ),
    }
    score = {
        "status": "pass" if all(gates.values()) else ("ineligible" if not gates["minimum_20_target_episodes"] else "fail"),
        "prediction_sha256_before_unblinding": prediction_hash,
        "eligible_target_episodes": len(episodes),
        "hidden_target_measurements": len(truth_rows),
        "all_hidden_coverage": coverage,
        "q95_coverage": q95_coverage,
        "median_width_over_B": statistics.median(widths) if widths else None,
        "maximum_solver_constraint_violation": max_violation,
        "gates": gates,
        "claim_boundary": (
            "Analyst-blind unseen-day validation of calibrated transient cart-mass intervals "
            "within one external strawberry field dataset. It is not farm-to-market, cross-study, "
            "population, CPC, chemistry, exposure or hazard validation."
        ),
    }
    score_path = PACKAGE / "04_RESULTS" / "EVIDENCE_BRIDGE_HOLDOUT_SCORE_V1_2_1.json"
    write_json(score_path, score)
    audit = {
        "calibration_sha256": sha256(CALIBRATION),
        "acquisition_manifest_sha256": sha256(ACQUISITION),
        "err_source_sha256": sha256(ERR_SOURCE),
        "predictor_sha256": sha256(predictor_path),
        "prediction_sha256": sha256(prediction_path),
        "truth_sha256": sha256(truth_path),
        "score_sha256": sha256(score_path),
        "prediction_was_hashed_before_truth_write": True,
    }
    write_json(PACKAGE / "06_QA" / "EVIDENCE_BRIDGE_HOLDOUT_AUDIT_V1_2_1.json", audit)
    print(json.dumps({key: value for key, value in score.items() if key != "gates"}, indent=2))
    print(json.dumps(gates, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
