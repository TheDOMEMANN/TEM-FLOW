"""Independent lightweight check of the manuscript validation summary."""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "validation_summary.csv"


def main() -> int:
    with DATA.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 18:
        raise AssertionError(f"expected 18 summary rows, found {len(rows)}")
    lookup = {(row["validation"], row["metric"]): float(row["value"]) for row in rows}
    expected = {
        ("Dryad transient", "overall hidden-state coverage"): 0.8864,
        ("Karg source-only", "median relative interval width"): 0.9832,
        ("UK RPA branching", "positive-compartment coverage"): 0.995334,
        ("UK RPA branching", "same-county retention coverage"): 0.991189,
        ("UK RPA branching", "median total-width contraction"): 0.506950,
    }
    for key, value in expected.items():
        if abs(lookup[key] - value) > 1e-12:
            raise AssertionError(f"summary value mismatch for {key}")
    print(f"PASS: {len(rows)} validation-summary rows checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
