"""Prepare training evidence, test margins and sealed truth from archived responses."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path


HERE = Path(__file__).resolve()
RELEASE = HERE.parents[1]
LOCK_PATH = RELEASE / "01_PROTOCOL" / "ANALYSIS_LOCK_V1_0_0.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def number(value: float) -> str:
    return format(value, ".15g")


def main() -> int:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    raw_dir = RELEASE / "02_DATA" / "raw" / "uncomtrade"
    derived = RELEASE / "02_DATA" / "derived"
    predictor_dir = derived / "predictors"
    truth_dir = derived / "sealed_truth"
    predictor_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)

    acquisition_path = raw_dir / "ACQUISITION_MANIFEST_V1_0_0.json"
    acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
    entry_lookup = {(e["commodity"], int(e["year"])): e for e in acquisition["entries"]}

    matrix: dict[tuple[str, int, str, str], float] = defaultdict(float)
    partner_names: dict[tuple[str, str], str] = {}
    audit_rows: list[dict[str, object]] = []

    for commodity, spec in lock["commodity_groups"].items():
        allowed_reporters = set(spec["reporters"])
        allowed_codes = set(spec["hs_codes"])
        for year in [*lock["training_years"], lock["test_year"]]:
            entry = entry_lookup[(commodity, year)]
            source_path = raw_dir / entry["file"]
            if sha256(source_path) != entry["sha256"]:
                raise ValueError(f"raw checksum mismatch: {source_path.name}")
            payload = json.loads(source_path.read_text(encoding="utf-8-sig"))
            records = payload.get("data", [])
            kept = 0
            excluded_world = 0
            excluded_estimated = 0
            excluded_missing_or_nonpositive = 0
            excluded_out_of_scope = 0
            for record in records:
                reporter = str(record.get("reporterCode", ""))
                partner = str(record.get("partnerCode", ""))
                command = str(record.get("cmdCode", ""))
                if reporter not in allowed_reporters or command not in allowed_codes:
                    excluded_out_of_scope += 1
                    continue
                if partner == str(lock["exclude_world_partner_code"]):
                    excluded_world += 1
                    continue
                if bool(record.get("isNetWgtEstimated", False)):
                    excluded_estimated += 1
                    continue
                net_weight = record.get("netWgt")
                try:
                    mass = float(net_weight)
                except (TypeError, ValueError):
                    excluded_missing_or_nonpositive += 1
                    continue
                if mass <= 0:
                    excluded_missing_or_nonpositive += 1
                    continue
                matrix[(commodity, year, reporter, partner)] += mass
                partner_names[(commodity, partner)] = str(record.get("partnerDesc") or partner)
                kept += 1
            audit_rows.append(
                {
                    "commodity": commodity,
                    "year": year,
                    "raw_record_count": len(records),
                    "kept_component_record_count": kept,
                    "excluded_world": excluded_world,
                    "excluded_estimated_net_weight": excluded_estimated,
                    "excluded_missing_or_nonpositive_net_weight": excluded_missing_or_nonpositive,
                    "excluded_out_of_scope": excluded_out_of_scope,
                    "raw_file": source_path.name,
                    "raw_sha256": sha256(source_path),
                }
            )

    training_rows: list[dict[str, object]] = []
    support: dict[tuple[str, str, str], dict[str, object]] = {}
    for commodity, spec in lock["commodity_groups"].items():
        for reporter, reporter_name in spec["reporters"].items():
            reporter_totals = {
                year: sum(
                    mass
                    for (com, yr, rep, _partner), mass in matrix.items()
                    if com == commodity and yr == year and rep == reporter
                )
                for year in lock["training_years"]
            }
            partners = sorted(
                {
                    partner
                    for (com, year, rep, partner), mass in matrix.items()
                    if com == commodity and year in lock["training_years"] and rep == reporter and mass > 0
                },
                key=lambda value: int(value),
            )
            for partner in partners:
                yearly = {
                    year: matrix.get((commodity, year, reporter, partner), 0.0)
                    for year in lock["training_years"]
                }
                total_cell = sum(yearly.values())
                total_reporter = sum(reporter_totals.values())
                if total_cell <= 0:
                    continue
                key = (commodity, reporter, partner)
                support[key] = {
                    "training_cell_mass_kg": total_cell,
                    "training_reporter_mass_kg": total_reporter,
                    "positive_training_years": ";".join(str(y) for y, mass in yearly.items() if mass > 0),
                }
                for year, mass in yearly.items():
                    if mass > 0:
                        training_rows.append(
                            {
                                "commodity": commodity,
                                "commodity_class": spec["class"],
                                "year": year,
                                "reporter_code": reporter,
                                "reporter_name": reporter_name,
                                "partner_code": partner,
                                "partner_name": partner_names.get((commodity, partner), partner),
                                "net_weight_kg": number(mass),
                                "evidence_role": "source_reported_route_certificate_evidence",
                            }
                        )

    support_rows: list[dict[str, object]] = []
    for (commodity, reporter, partner), values in sorted(support.items()):
        spec = lock["commodity_groups"][commodity]
        support_rows.append(
            {
                "commodity": commodity,
                "commodity_class": spec["class"],
                "reporter_code": reporter,
                "reporter_name": spec["reporters"][reporter],
                "partner_code": partner,
                "partner_name": partner_names.get((commodity, partner), partner),
                "positive_training_years": values["positive_training_years"],
                "training_cell_mass_kg": number(float(values["training_cell_mass_kg"])),
                "training_reporter_mass_kg": number(float(values["training_reporter_mass_kg"])),
                "historical_route_share": number(
                    float(values["training_cell_mass_kg"]) / float(values["training_reporter_mass_kg"])
                    if float(values["training_reporter_mass_kg"]) > 0
                    else 0.0
                ),
            }
        )

    predictor_rows: list[dict[str, object]] = []
    truth_rows: list[dict[str, object]] = []
    test_year = int(lock["test_year"])
    for commodity, spec in lock["commodity_groups"].items():
        reporters = list(spec["reporters"])
        partners = sorted(
            {
                partner
                for (com, year, _reporter, partner), mass in matrix.items()
                if com == commodity and year == test_year and mass > 0
            },
            key=lambda value: int(value),
        )
        row_totals = {
            reporter: sum(matrix.get((commodity, test_year, reporter, partner), 0.0) for partner in partners)
            for reporter in reporters
        }
        column_totals = {
            partner: sum(matrix.get((commodity, test_year, reporter, partner), 0.0) for reporter in reporters)
            for partner in partners
        }
        network_total = sum(row_totals.values())
        for reporter in reporters:
            for partner in partners:
                common = {
                    "commodity": commodity,
                    "commodity_class": spec["class"],
                    "year": test_year,
                    "reporter_code": reporter,
                    "reporter_name": spec["reporters"][reporter],
                    "partner_code": partner,
                    "partner_name": partner_names.get((commodity, partner), partner),
                }
                predictor_rows.append(
                    {
                        **common,
                        "reporter_total_kg": number(row_totals[reporter]),
                        "partner_total_selected_reporters_kg": number(column_totals[partner]),
                        "network_total_selected_reporters_kg": number(network_total),
                        "route_certificate_available": str((commodity, reporter, partner) in support).lower(),
                    }
                )
                truth_rows.append(
                    {
                        **common,
                        "heldout_bilateral_net_weight_kg": number(
                            matrix.get((commodity, test_year, reporter, partner), 0.0)
                        ),
                        "evidence_role": "sealed_source_reported_holdout_truth",
                    }
                )

    training_rows.sort(key=lambda r: (r["commodity"], int(r["year"]), int(r["reporter_code"]), int(r["partner_code"])))
    predictor_rows.sort(key=lambda r: (r["commodity"], int(r["reporter_code"]), int(r["partner_code"])))
    truth_rows.sort(key=lambda r: (r["commodity"], int(r["reporter_code"]), int(r["partner_code"])))

    outputs = {
        "training_route_records.csv": (
            ["commodity", "commodity_class", "year", "reporter_code", "reporter_name", "partner_code", "partner_name", "net_weight_kg", "evidence_role"],
            training_rows,
            predictor_dir,
        ),
        "route_support_and_historical_shares.csv": (
            ["commodity", "commodity_class", "reporter_code", "reporter_name", "partner_code", "partner_name", "positive_training_years", "training_cell_mass_kg", "training_reporter_mass_kg", "historical_route_share"],
            support_rows,
            predictor_dir,
        ),
        "test_predictor_margins.csv": (
            ["commodity", "commodity_class", "year", "reporter_code", "reporter_name", "partner_code", "partner_name", "reporter_total_kg", "partner_total_selected_reporters_kg", "network_total_selected_reporters_kg", "route_certificate_available"],
            predictor_rows,
            predictor_dir,
        ),
        "SEALED_test_bilateral_truth.csv": (
            ["commodity", "commodity_class", "year", "reporter_code", "reporter_name", "partner_code", "partner_name", "heldout_bilateral_net_weight_kg", "evidence_role"],
            truth_rows,
            truth_dir,
        ),
        "extraction_audit.csv": (
            ["commodity", "year", "raw_record_count", "kept_component_record_count", "excluded_world", "excluded_estimated_net_weight", "excluded_missing_or_nonpositive_net_weight", "excluded_out_of_scope", "raw_file", "raw_sha256"],
            audit_rows,
            derived,
        ),
    }
    written: list[dict[str, object]] = []
    for name, (fields, rows, directory) in outputs.items():
        path = directory / name
        write_csv(path, fields, rows)
        written.append({"file": str(path.relative_to(RELEASE)).replace("\\", "/"), "sha256": sha256(path), "row_count": len(rows)})

    seal = {
        "analysis_id": lock["analysis_id"],
        "lock_sha256": sha256(LOCK_PATH),
        "acquisition_manifest_sha256": sha256(acquisition_path),
        "files": written,
        "truth_file_isolated_from_prediction": True,
        "test_cell_values_printed": False,
    }
    seal_path = derived / "DATA_SEAL_MANIFEST_V1_0_0.json"
    seal_path.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"file_count": len(written), "seal_sha256": sha256(seal_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

