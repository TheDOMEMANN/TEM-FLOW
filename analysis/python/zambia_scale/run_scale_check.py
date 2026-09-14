"""Compute the limited, scale-aware check from published Zambia aggregates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve()
PACKAGE = HERE.parents[1]
INPUT = PACKAGE / "02_DATA" / "PUBLISHED_TABLE_EXTRACTION_V1_0_0.json"
OUTPUT = PACKAGE / "04_RESULTS" / "SOURCE_PROXIMITY_SCALE_CHECK_V1_0_0.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    production = data["table_6_6_household_fish_production_metric_tonnes"]
    sold = data["table_9_4_household_fish_sold_kg"]
    locations = data["table_9_2_sale_location_percent_among_selling_households"]
    households = data["table_9_1_households"]

    province_ratios = {}
    incoherent = []
    for province, production_mt in production.items():
        if province == "Zambia":
            continue
        ratio = float(sold[province]) / (1000.0 * float(production_mt))
        province_ratios[province] = ratio
        if ratio > 1.05:
            incoherent.append(province)

    selling_share = float(households["reported_percent_selling"]) / 100.0
    off_farm_share_among_sellers = (
        float(locations["within_district_not_on_farm"])
        + float(locations["outside_district"])
    ) / 100.0
    outside_district_share_among_sellers = float(locations["outside_district"]) / 100.0
    national_sold_fraction = float(sold["Zambia"]) / (1000.0 * float(production["Zambia"]))

    result = {
        "version": "1.0.0",
        "evidence_status": "independent_external_published_aggregate_not_blind",
        "national_household_fish_sold_over_produced": national_sold_fraction,
        "reported_household_share_selling": selling_share,
        "off_farm_sale_share_among_selling_households": off_farm_share_among_sellers,
        "outside_district_sale_share_among_selling_households": outside_district_share_among_sellers,
        "approximate_all_household_share_selling_off_farm": selling_share * off_farm_share_among_sellers,
        "approximate_all_household_share_selling_outside_district": selling_share * outside_district_share_among_sellers,
        "province_sold_over_produced_ratios": province_ratios,
        "province_ratios_above_1_05": incoherent,
        "decision": {
            "farm_node": "automatic approximately 100% retention is contradicted as a general default",
            "district_node": "literal 100% retention is contradicted, but retained mass is not identified",
            "mass_allocation": "sale-location household shares cannot be applied to mass; use [0,M] outward/retained unresolved bounds unless compatible local mass evidence exists",
            "required_software_rule": "node scale must be explicit; missing downstream records create an unresolved sink, not a zero-flow assertion"
        },
        "claim_boundary": (
            "The report demonstrates nonzero movement away from producing farms and districts. "
            "It does not report mass by sale location and cannot calibrate a geographic retention fraction."
        ),
        "source_input_sha256": sha256(INPUT),
        "runner_sha256": sha256(HERE)
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

