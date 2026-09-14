"""Run the archived-data analysis in two Python runtimes and compare artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve()
RELEASE = HERE.parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=RELEASE, text=True, capture_output=True)
    if completed.returncode:
        raise RuntimeError(f"command failed: {command}\n{completed.stdout}\n{completed.stderr}")


def version(executable: str) -> str:
    completed = subprocess.run([executable, "--version"], text=True, capture_output=True, check=True)
    return (completed.stdout or completed.stderr).strip()


def derived_hashes() -> dict[str, str]:
    derived = RELEASE / "02_DATA" / "derived"
    return {
        str(path.relative_to(derived)).replace("\\", "/"): sha256(path)
        for path in sorted(derived.rglob("*"))
        if path.is_file()
    }


def one_runtime(executable: str, label: str) -> dict[str, object]:
    output = RELEASE / "05_QA" / "reproduction" / label
    output.mkdir(parents=True, exist_ok=True)
    run([executable, str(RELEASE / "03_CODE" / "prepare_sealed_panel.py")])
    prepared = derived_hashes()
    run([executable, str(RELEASE / "03_CODE" / "freeze_predictions.py"), "--output-dir", str(output)])
    run([
        executable,
        str(RELEASE / "03_CODE" / "score_holdout.py"),
        "--prediction-dir",
        str(output),
        "--output-dir",
        str(output),
    ])
    files = {
        name: sha256(output / name)
        for name in (
            "FROZEN_PREDICTIONS_V1_0_0.json",
            "PREDICTION_FREEZE_MANIFEST_V1_0_0.json",
            "HOLDOUT_SCORE_V1_0_0.json",
            "SCORED_CELLS_V1_0_0.csv",
        )
    }
    return {
        "executable": executable,
        "python_version": version(executable),
        "derived_file_hashes": prepared,
        "result_file_hashes": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-a", required=True)
    parser.add_argument("--python-b", required=True)
    args = parser.parse_args()
    first = one_runtime(args.python_a, "runtime_a")
    second = one_runtime(args.python_b, "runtime_b")
    derived_match = first["derived_file_hashes"] == second["derived_file_hashes"]
    results_match = first["result_file_hashes"] == second["result_file_hashes"]
    distinct_executables = Path(args.python_a).resolve() != Path(args.python_b).resolve()
    report = {
        "runtime_a": first,
        "runtime_b": second,
        "distinct_executables": distinct_executables,
        "derived_files_byte_identical": derived_match,
        "result_files_byte_identical": results_match,
        "matching_runtime_count": 2 if distinct_executables and derived_match and results_match else 0,
        "reproduction_gate_pass": distinct_executables and derived_match and results_match,
    }
    output = RELEASE / "05_QA" / "REPRODUCTION_REPORT_V1_0_0.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"reproduction_gate_pass": report["reproduction_gate_pass"], "matching_runtime_count": report["matching_runtime_count"]}, sort_keys=True))
    return 0 if report["reproduction_gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

