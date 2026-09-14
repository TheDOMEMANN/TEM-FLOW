"""Build calibration summaries from the unblinded prefix arm only."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve()
RUNNER = HERE.parent / "run_blind_raw_multistage_validation.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("temflow_dryad_runner", RUNNER)
    if spec is None or spec.loader is None:
        raise ImportError(RUNNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUN = load_runner()
GRID = tuple(round(index * 0.05, 2) for index in range(21))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prefix_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows: list[dict[str, object]] = []
    episode_count = 0
    for path in sorted(args.prefix_dir.glob("*_train-ready_all_carts.csv"), key=lambda item: item.name):
        frame = pd.read_csv(
            path,
            usecols=["date_cartID", "GPS_TOW", "raw_mass", "activity"],
            low_memory=False,
        )
        for unit_id, group in frame.groupby("date_cartID", sort=True, dropna=False):
            run = RUN.longest_pick_run(group)
            if run is None:
                continue
            times = pd.to_numeric(run["GPS_TOW"], errors="coerce").to_numpy(float)
            start = float(times[0])
            end = float(times[-1])
            episode_id = RUN.Episode(
                member=path.name,
                unit_id=str(unit_id),
                start_tow=start,
                end_tow=end,
                duration_seconds=(end - start) / 1000.0,
                rows=len(run),
                start_interval=(0.0, 0.0),
                end_interval=(0.0, 0.0),
                start_median=0.0,
                end_median=0.0,
                truth=(),
            ).episode_id
            episode_rows: list[dict[str, object]] = []
            for q in GRID:
                center = start + q * (end - start)
                values = RUN.window_values(run, center, 500.0)
                if values.size == 0:
                    episode_rows = []
                    break
                low, high = np.quantile(values, [0.025, 0.975])
                episode_rows.append(
                    {
                        "episode_id": episode_id,
                        "member": path.name,
                        "unit_id": str(unit_id),
                        "q": q,
                        "median_kg": float(np.median(values)),
                        "low_kg": float(low),
                        "high_kg": float(high),
                    }
                )
            if episode_rows:
                rows.extend(episode_rows)
                episode_count += 1
        del frame
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"calibration_episodes={episode_count}")
    print(f"calibration_rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
