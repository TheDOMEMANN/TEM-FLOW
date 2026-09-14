"""Test and replace automatic source-proximity retention using NASS 2023."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve()
PACKAGE = HERE.parents[1]
RAW = Path(
    r"C:\Users\hp\Desktop\Exposure_Africa\data\raw\restricted\fishery_observation_extraction"
    r"\2026-08-16\nigeria_nass\NASS_anonymized_dataset.zip"
)
ACQUISITION = PACKAGE / "02_DATA" / "raw" / "NASS_ACQUISITION_MANIFEST_V1_0_0.json"
RESTRICTED_OBSERVATIONS = RAW.parent / "restricted_observations"
CONFIGS = {
    "fish_farming": {
        "member": "17_fish_farming",
        "source_file": "17_Fish_Farming.dta",
        "archive_crc32": "c707e68f",
        "source": "s05a_q04a",
        "sold": "s05a_q07a",
        "sale_flag": "s05a_q06",
        "product": "s05a_product__id",
        "primary": True,
    },
    "fish_capture": {
        "member": "18_fish_capture",
        "source_file": "18_Fish_Capture.dta",
        "archive_crc32": "d8fb5958",
        "source": "s06a_q11a",
        "sold": "s06a_q14a",
        "sale_flag": "s06a_q13",
        "product": "s06a_product__id",
        "primary": True,
    },
}


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
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise RuntimeError("empty calibration fraction set")
    rank = min(len(ordered), max(1, math.ceil((len(ordered) + 1) * coverage)))
    return ordered[rank - 1]


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    good = values.notna() & weights.notna() & (weights > 0)
    if not good.any():
        return math.nan
    return float((values[good] * weights[good]).sum() / weights[good].sum())


def column(frame: pd.DataFrame, expected: str) -> str:
    mapping = {str(name).casefold(): str(name) for name in frame.columns}
    key = expected.casefold()
    if key not in mapping:
        raise KeyError(f"missing expected column {expected!r}; available={list(frame.columns)}")
    return mapping[key]


def anonymous_id(domain: str, row: pd.Series, index: object, hhid: str, product: str) -> str:
    payload = "|".join((domain, str(row.get(hhid, "")), str(row.get(product, "")), str(index)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20].upper()


def main() -> int:
    manifest = json.loads(ACQUISITION.read_text(encoding="utf-8"))
    if sha256(RAW) != str(manifest["sha256"]):
        raise RuntimeError("NASS archive hash differs from acquisition manifest")
    member_inventory: list[dict[str, object]] = []
    selected: dict[str, Path] = {}
    for domain, config in CONFIGS.items():
        source_path = RESTRICTED_OBSERVATIONS / str(config["source_file"])
        if not source_path.is_file():
            raise RuntimeError(f"missing restricted source member for {domain}: {source_path}")
        selected[domain] = source_path
        member_inventory.append(
            {
                "domain": domain,
                "archive_member": str(config["source_file"]),
                "bytes": source_path.stat().st_size,
                "crc32": str(config["archive_crc32"]),
                "sha256": sha256(source_path),
                "source_storage": "referenced_in_place_from_restricted_workspace_area",
            }
        )

    prepared: dict[str, pd.DataFrame] = {}
    domain_summaries: dict[str, dict[str, object]] = {}
    predictions: list[dict[str, object]] = []
    truths: list[dict[str, object]] = []
    calibration_bounds: dict[str, dict[str, object]] = {}

    for domain, config in CONFIGS.items():
        raw = pd.read_stata(selected[domain], convert_categoricals=False)
        source_col = column(raw, str(config["source"]))
        sold_col = column(raw, str(config["sold"]))
        sale_flag_col = column(raw, str(config["sale_flag"]))
        zone_col = column(raw, "zone_id")
        sector_col = column(raw, "sector")
        weight_col = column(raw, "final_weight")
        product_col = column(raw, str(config["product"]))
        hhid_col = column(raw, "hhid")
        sold_mass = pd.to_numeric(raw[sold_col], errors="coerce")
        sale_flag = pd.to_numeric(raw[sale_flag_col], errors="coerce")
        sold_mass = sold_mass.mask((sale_flag == 2) & sold_mass.isna(), 0.0)
        frame = pd.DataFrame(
            {
                "source_mass_kg": pd.to_numeric(raw[source_col], errors="coerce"),
                "sold_mass_kg": sold_mass,
                "sale_flag": sale_flag,
                "zone": pd.to_numeric(raw[zone_col], errors="coerce"),
                "sector": raw[sector_col].astype(str),
                "weight": pd.to_numeric(raw[weight_col], errors="coerce"),
                "product": raw[product_col].astype(str),
                "hhid": raw[hhid_col].astype(str),
            },
            index=raw.index,
        )
        frame = frame[
            (frame["source_mass_kg"] > 0)
            & frame["sale_flag"].isin([1, 2])
            & (frame["sold_mass_kg"] >= 0)
        ].copy()
        frame["sold_fraction"] = frame["sold_mass_kg"] / frame["source_mass_kg"]
        frame["literal_zero_outward"] = frame["sold_mass_kg"] <= 1e-12
        frame["approximately_full_retention"] = frame["sold_fraction"] <= 0.05
        frame["balance_coherent"] = frame["sold_mass_kg"] <= 1.05 * frame["source_mass_kg"]
        frame["record_id"] = [
            anonymous_id(domain, raw.loc[index], index, hhid_col, product_col)
            for index in frame.index
        ]
        prepared[domain] = frame
        near_share = float(frame["approximately_full_retention"].mean()) if len(frame) else 0.0
        literal_share = float(frame["literal_zero_outward"].mean()) if len(frame) else 0.0
        domain_summaries[domain] = {
            "raw_rows": len(raw),
            "eligible_rows": len(frame),
            "confirmed_non_seller_rows": int((frame["sale_flag"] == 2).sum()),
            "balance_incoherent_rows": int((~frame["balance_coherent"]).sum()),
            "literal_zero_outward_share": literal_share,
            "approximately_full_retention_share": near_share,
            "weighted_approximately_full_retention_share": weighted_mean(
                frame["approximately_full_retention"].astype(float), frame["weight"]
            ) if len(frame) else None,
            "hard_rule_supported": near_share >= 0.95,
            "primary_fish_domain": bool(config["primary"]),
        }

    for domain in ("fish_farming", "fish_capture"):
        frame = prepared[domain]
        coherent = frame[frame["balance_coherent"] & frame["zone"].notna()].copy()
        coherent["sold_fraction_capped"] = coherent["sold_fraction"].clip(lower=0, upper=1)
        fit = coherent[coherent["zone"].isin([1, 2, 3, 4])]
        holdout = coherent[coherent["zone"].isin([5, 6])]
        if fit.empty:
            raise RuntimeError(f"no zone 1-4 calibration records for {domain}")
        domain_upper = finite_quantile(fit["sold_fraction_capped"].tolist(), 0.95)
        sector_bounds: dict[str, dict[str, object]] = {}
        for sector, group in fit.groupby("sector", sort=True):
            sector_bounds[str(sector)] = {
                "upper_fraction": finite_quantile(group["sold_fraction_capped"].tolist(), 0.95)
                if len(group) >= 100
                else domain_upper,
                "calibration_n": len(group) if len(group) >= 100 else len(fit),
                "scope": "domain_sector" if len(group) >= 100 else "domain",
            }
        calibration_bounds[domain] = {
            "domain_upper_fraction": domain_upper,
            "domain_calibration_n": len(fit),
            "sector_bounds": sector_bounds,
        }
        for index, row in holdout.iterrows():
            bound_record = sector_bounds.get(
                str(row["sector"]),
                {"upper_fraction": domain_upper, "scope": "domain", "calibration_n": len(fit)},
            )
            upper_fraction = float(bound_record["upper_fraction"])
            source_mass = float(row["source_mass_kg"])
            predictions.append(
                {
                    "record_id": row["record_id"],
                    "domain": domain,
                    "zone": int(row["zone"]),
                    "sector": str(row["sector"]),
                    "source_mass_kg": source_mass,
                    "outward_mass_interval_kg": [0.0, upper_fraction * source_mass],
                    "retained_or_unresolved_mass_interval_kg": [
                        max(0.0, (1.0 - upper_fraction) * source_mass),
                        source_mass,
                    ],
                    "upper_fraction": upper_fraction,
                    "calibration_scope": bound_record["scope"],
                }
            )

    prediction_payload = {
        "version": "1.0.0",
        "hard_rule_prediction": "approximately 100% retention when no destination record",
        "replacement": "calibrated upper outward fraction with unresolved retention interval",
        "calibration_zones": [1, 2, 3, 4],
        "holdout_zones": [5, 6],
        "calibration_bounds": calibration_bounds,
        "predictions": predictions,
    }
    prediction_path = PACKAGE / "04_RESULTS" / "FROZEN_RETENTION_PREDICTIONS_V1_0_0.json"
    write_json(prediction_path, prediction_payload)
    prediction_hash = sha256(prediction_path)

    truth_by_id = {
        str(row["record_id"]): row
        for domain in ("fish_farming", "fish_capture")
        for _, row in prepared[domain][
            prepared[domain]["balance_coherent"] & prepared[domain]["zone"].isin([5, 6])
        ].iterrows()
    }
    for prediction in predictions:
        row = truth_by_id[str(prediction["record_id"])]
        observed = float(row["sold_mass_kg"])
        low, high = map(float, prediction["outward_mass_interval_kg"])
        truths.append(
            {
                "record_id": prediction["record_id"],
                "domain": prediction["domain"],
                "zone": prediction["zone"],
                "sector": prediction["sector"],
                "source_mass_kg": prediction["source_mass_kg"],
                "sold_mass_kg": observed,
                "sold_fraction": float(row["sold_fraction"]),
                "survey_weight": float(row["weight"]),
                "upper_fraction": prediction["upper_fraction"],
                "covered": low - 1e-9 <= observed <= high + 1e-9,
            }
        )

    truth_path = PACKAGE / "02_DATA" / "derived" / "UNBLINDED_RETENTION_TRUTH_V1_0_0.csv"
    with truth_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(truths[0]))
        writer.writeheader()
        writer.writerows(truths)

    alternative: dict[str, dict[str, object]] = {}
    for domain in ("fish_farming", "fish_capture"):
        rows = [row for row in truths if row["domain"] == domain]
        coverage = statistics.fmean(bool(row["covered"]) for row in rows) if rows else 0.0
        weighted_coverage = (
            sum(float(row["survey_weight"]) for row in rows if bool(row["covered"]))
            / sum(float(row["survey_weight"]) for row in rows)
            if rows and sum(float(row["survey_weight"]) for row in rows) > 0
            else None
        )
        upper_values = [float(row["upper_fraction"]) for row in rows]
        alternative[domain] = {
            "holdout_records": len(rows),
            "holdout_coverage": coverage,
            "weighted_holdout_coverage": weighted_coverage,
            "median_upper_fraction": statistics.median(upper_values) if upper_values else None,
        }

    hard_rule_rejected = any(
        not bool(domain_summaries[domain]["hard_rule_supported"])
        for domain in ("fish_farming", "fish_capture")
    )
    gates = {
        "minimum_100_fish_farming_holdout": alternative["fish_farming"]["holdout_records"] >= 100,
        "minimum_200_fish_capture_holdout": alternative["fish_capture"]["holdout_records"] >= 200,
        "fish_farming_coverage_at_least_0_90": alternative["fish_farming"]["holdout_coverage"] >= 0.90,
        "fish_capture_coverage_at_least_0_90": alternative["fish_capture"]["holdout_coverage"] >= 0.90,
        "fish_farming_upper_below_0_95": (
            alternative["fish_farming"]["median_upper_fraction"] is not None
            and alternative["fish_farming"]["median_upper_fraction"] < 0.95
        ),
        "fish_capture_upper_below_0_95": (
            alternative["fish_capture"]["median_upper_fraction"] is not None
            and alternative["fish_capture"]["median_upper_fraction"] < 0.95
        ),
        "calibration_holdout_zones_disjoint": True,
    }
    alternative_pass = all(gates.values())
    score = {
        "version": "1.0.0",
        "hard_100_percent_rule_status": "rejected" if hard_rule_rejected else "not_rejected",
        "calibrated_alternative_status": "pass" if alternative_pass else "fail_use_logical_unresolved_interval",
        "secondary_crop_extension_status": (
            "not_computable: public-use archive omits the catalogued computed harvest_QTY source field"
        ),
        "prediction_sha256_before_truth_write": prediction_hash,
        "domain_summaries": domain_summaries,
        "geographic_holdout": alternative,
        "gates": gates,
        "claim_boundary": (
            "Independent respondent-reported production and sales data test whether absence of a "
            "destination record can justify full source retention. Exact local absorption, losses, "
            "stock change and destinations are not measured by this test."
        ),
    }
    score_path = PACKAGE / "04_RESULTS" / "SOURCE_RETENTION_SCORE_V1_0_0.json"
    write_json(score_path, score)
    inventory_path = PACKAGE / "02_DATA" / "derived" / "EXTRACTED_MEMBER_INVENTORY_V1_0_0.json"
    write_json(inventory_path, member_inventory)
    audit = {
        "archive_sha256": sha256(RAW),
        "acquisition_manifest_sha256": sha256(ACQUISITION),
        "script_sha256": sha256(HERE),
        "prediction_sha256": sha256(prediction_path),
        "truth_sha256": sha256(truth_path),
        "score_sha256": sha256(score_path),
        "member_inventory_sha256": sha256(inventory_path),
        "prediction_hashed_before_truth_write": True,
    }
    write_json(PACKAGE / "06_QA" / "EXECUTION_AUDIT_V1_0_0.json", audit)
    print(json.dumps({key: value for key, value in score.items() if key not in {"domain_summaries", "gates"}}, indent=2))
    print(json.dumps(domain_summaries, indent=2))
    print(json.dumps(alternative, indent=2))
    print(json.dumps(gates, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
