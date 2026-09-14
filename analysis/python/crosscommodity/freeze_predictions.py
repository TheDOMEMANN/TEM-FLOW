"""Freeze TEM-FLOW predictions. This module has no sealed-truth dependency."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve()
RELEASE = HERE.parents[1]
LOCK_PATH = RELEASE / "01_PROTOCOL" / "ANALYSIS_LOCK_V1_0_0.json"
TEM_MODULE = (
    RELEASE.parent
    / "TEMFLOW_Patterns_general_mass_flow_v1_0_0_2026-09-01"
    / "SOFTWARE"
    / "src"
    / "temflow"
    / "tem_calculus.py"
)


def load_standalone(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


calculus = load_standalone("temflow_crosscommodity_calculus", TEM_MODULE)
IdentitySignature = calculus.IdentitySignature
RouteCertificate = calculus.RouteCertificate
certified_marginal_flow_claim = calculus.certified_marginal_flow_claim


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def signature(row: dict[str, str]) -> object:
    return IdentitySignature(
        country=row["reporter_name"],
        food_domain=row["commodity_class"],
        commodity=row["commodity"],
        product_form="frozen HS product definition",
        material="UN Comtrade reported net export weight",
        origin=row["reporter_name"],
        transient="",
        destination=row["partner_name"],
        period=row["year"],
        denominator="selected-reporter export matrix",
        unit="kg",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=RELEASE / "04_RESULTS" / "main")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    predictor_dir = RELEASE / "02_DATA" / "derived" / "predictors"
    margin_path = predictor_dir / "test_predictor_margins.csv"
    support_path = predictor_dir / "route_support_and_historical_shares.csv"
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    margins = read_csv(margin_path)
    support_rows = read_csv(support_path)
    support = {
        (r["commodity"], r["reporter_code"], r["partner_code"]): r for r in support_rows
    }

    predictions: list[dict[str, object]] = []
    mismatch_admissions = 0
    certified_count = 0
    for row in margins:
        key = (row["commodity"], row["reporter_code"], row["partner_code"])
        route_evidence = support.get(key)
        sig = signature(row)
        certificate = None
        if route_evidence is not None:
            certificate_id = "TEM-ROUTE-" + hashlib.sha256("|".join(key).encode("utf-8")).hexdigest()[:20].upper()
            evidence_years = route_evidence["positive_training_years"].replace(";", "-")
            certificate = RouteCertificate(
                certificate_id=certificate_id,
                signature=sig,
                evidence_ids=(f"UNCOMTRADE-{row['commodity']}-{evidence_years}-ROUTE",),
                boundary="Prior positive bilateral export record certifies this exact identity, not its 2024 occurrence or mass.",
            )

        reporter_total = float(row["reporter_total_kg"])
        partner_total = float(row["partner_total_selected_reporters_kg"])
        reported_total = float(row["network_total_selected_reporters_kg"])
        raw_total = max(reported_total, reporter_total, partner_total)
        effective_total = raw_total + max(1e-9, abs(raw_total) * 1e-12)
        independent_point = reporter_total * partner_total / effective_total if effective_total > 0 else 0.0
        historical_share = float(route_evidence["historical_route_share"]) if route_evidence else 0.0
        prediction: dict[str, object] = {
            "commodity": row["commodity"],
            "commodity_class": row["commodity_class"],
            "year": int(row["year"]),
            "reporter_code": row["reporter_code"],
            "reporter_name": row["reporter_name"],
            "partner_code": row["partner_code"],
            "partner_name": row["partner_name"],
            "reporter_total_kg": reporter_total,
            "partner_total_selected_reporters_kg": partner_total,
            "reported_network_total_kg": reported_total,
            "effective_network_total_kg": effective_total,
            "source_only_lower_kg": 0.0,
            "source_only_upper_kg": reporter_total,
            "independent_margins_point_kg": independent_point,
            "historical_route_share_point_kg": reporter_total * historical_share,
            "claim_status": "blocked_no_training_route_certificate",
            "tem_lower_kg": None,
            "tem_upper_kg": None,
            "tem_midpoint_kg": None,
            "certificate_id": None,
        }
        if certificate is not None:
            claim = certified_marginal_flow_claim(
                row_total=reporter_total,
                column_total=partner_total,
                network_total=effective_total,
                signature=sig,
                evidence_ids=("UNCOMTRADE-2024-HELDOUT-MARGINS",),
                route_certificate=certificate,
            )
            prediction.update(
                {
                    "claim_status": "certified_interval",
                    "tem_lower_kg": claim.lower,
                    "tem_upper_kg": claim.upper,
                    "tem_midpoint_kg": (claim.lower + claim.upper) / 2.0,
                    "certificate_id": certificate.certificate_id,
                }
            )
            certified_count += 1
            wrong = IdentitySignature(**{**sig.__dict__, "destination": sig.destination + " [mismatch]"})
            try:
                certified_marginal_flow_claim(
                    row_total=reporter_total,
                    column_total=partner_total,
                    network_total=effective_total,
                    signature=wrong,
                    evidence_ids=("GENERATED-IDENTITY-STRESS",),
                    route_certificate=certificate,
                )
                mismatch_admissions += 1
            except ValueError:
                pass
        predictions.append(prediction)

    payload = {
        "analysis_id": lock["analysis_id"],
        "model": "TEM-FLOW",
        "model_version": lock["software_version"],
        "operation": "certificate-gated two-margin closure",
        "truth_access": False,
        "candidate_count": len(predictions),
        "certified_candidate_count": certified_count,
        "identity_mismatch_admissions": mismatch_admissions,
        "dependencies": {
            str(margin_path.relative_to(RELEASE)).replace("\\", "/"): sha256(margin_path),
            str(support_path.relative_to(RELEASE)).replace("\\", "/"): sha256(support_path),
            str(LOCK_PATH.relative_to(RELEASE)).replace("\\", "/"): sha256(LOCK_PATH),
            str(TEM_MODULE.relative_to(RELEASE.parent)).replace("\\", "/"): sha256(TEM_MODULE),
        },
        "predictions": predictions,
        "claim_boundary": lock["claim_boundary"],
    }
    prediction_path = args.output_dir / "FROZEN_PREDICTIONS_V1_0_0.json"
    prediction_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "prediction_file": prediction_path.name,
        "prediction_sha256": sha256(prediction_path),
        "truth_file_read": False,
        "deterministic": True,
    }
    manifest_path = args.output_dir / "PREDICTION_FREEZE_MANIFEST_V1_0_0.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

