"""Fixed retrospective reporting-packet comparison on Brazzaville survey data.

This evaluates derived archive quantities, NOT independent field measurements.
Run with --input-dir PATH_TO_DATAVERSE_FILES --output-dir OUTPUT_PATH.
The numerical mass-flow kernel is imported unchanged from production_tree.
"""
from pathlib import Path
from collections import defaultdict, Counter
import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
import platform
import numpy as np
import scipy
from scipy.optimize import linprog
from production_tree import from_payload

DOI = "https://doi.org/10.18167/DVN1/DAMXAW"
RAW_NAME = "dt_produce_flows_retail_market.csv"
RAW_SHA256 = "71b5e06c2af23ddc009df9281f33028d7dfc113578d6de02b4a4853d390287d1"
THRESHOLDS = (0.05, 0.10, 0.25, 0.50)
DESIGNS = ("seven_individual_markets", "seven_paired_market_groups")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def status(lower, upper, threshold):
    # Same 'at least' convention as the manuscript; absorb numerical roundoff.
    if lower >= threshold - 1e-10:
        return "above"
    if upper < threshold - 1e-10:
        return "below"
    return "unresolved"


def export_csv(path, rows):
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def arrangement(markets, training, design):
    ranked = sorted(range(len(markets)), key=lambda j: (-training[j], markets[j]))
    if design == DESIGNS[0]:
        nodes = ["ARCHIVED_SAMPLE_TOTAL"] + list(markets)
        edges = [(0, j + 1) for j in range(len(markets))]
        records = [{"id": "market:" + markets[j], "edge": j, "error": 0.0}
                   for j in ranked[:7]]
        groups = [[j] for j in ranked[:7]]
        terminals = list(range(1, len(markets) + 1))
    else:
        groups = [[ranked[j], ranked[-1-j]] for j in range(7)]
        nodes = ["ARCHIVED_SAMPLE_TOTAL"] + ["PAIR_" + str(i+1) for i in range(7)] + list(markets)
        edges = []
        records = []
        for i, members in enumerate(groups):
            records.append({"id": "pair:" + "|".join(markets[j] for j in members),
                            "edge": len(edges), "error": 0.0})
            edges.append((0, i+1))
            for j in members:
                edges.append((i+1, 8+j))
        terminals = list(range(8, 8 + len(markets)))
    payload = {"nodes": nodes, "edges": edges, "terminals": terminals,
               "records": records, "mass": 1.0}
    return payload, groups


def exact_bounds(reference, groups, design, lost):
    """Closed-form bounds for these two disjoint-report arrangements."""
    n = len(reference)
    lower = np.zeros(n)
    upper = np.zeros(n)
    if design == DESIGNS[0]:
        retained = [g[0] for i, g in enumerate(groups) if i != lost]
        omitted = [j for j in range(n) if j not in retained]
        lower[retained] = upper[retained] = reference[retained]
        remaining = float(sum(reference[j] for j in omitted))
        upper[omitted] = remaining
        if len(omitted) == 1:
            lower[omitted] = remaining
    else:
        # An erased pair total is recovered from the archived total and the six
        # surviving, disjoint pair totals. This is conservation, not a backup
        # independently acquired in the field.
        for group in groups:
            upper[group] = float(sum(reference[j] for j in group))
    return lower, upper


def load_public_engine(source_root=None):
    """Locate a companion editable source without depending on this computer."""
    candidates = []
    if source_root is not None:
        candidates.extend([Path(source_root)/"src", Path(source_root)])
    else:
        here = Path(__file__).resolve()
        for parent in list(here.parents)[:5]:
            candidates.extend(parent/part for part in
                              ("src", "Editable_Source/src", "Source/src", "Desktop/src",
                               "User_package/Editable_Source/src"))
    for candidate in candidates:
        if (candidate/"temflow"/"structural.py").is_file():
            sys.path.insert(0, str(candidate))
            from temflow.structural import run_structural_payload
            import temflow.structural as module
            return run_structural_payload, Path(module.__file__)
    raise FileNotFoundError("Companion TEM-FLOW source not found; supply --source-root PATH_TO_EDITABLE_SOURCE")


def run(output_dir, input_dir, source_root=None):
    out = Path(output_dir)
    inputs = Path(input_dir)
    out.mkdir(parents=True, exist_ok=True)
    code_dir = Path(__file__).resolve().parent
    protocol = code_dir / "BRAZZAVILLE_REPORTING_PROTOCOL.txt"
    if not protocol.exists():
        protocol = code_dir / "PROTOCOL.txt"
    lock = code_dir / "BRAZZAVILLE_PROTOCOL_LOCK.json"
    protocol_hash = sha256(protocol)
    if lock.exists():
        assert json.loads(lock.read_text(encoding="utf-8"))["protocol_sha256"] == protocol_hash
    raw = inputs / RAW_NAME
    assert sha256(raw) == RAW_SHA256, "Unexpected source data; fixed analysis requires source version 1"
    public_engine, public_engine_path = load_public_engine(source_root)
    totals = defaultdict(float)
    counts = Counter()
    exclusions = []
    markets = set()
    products = set()
    raw_count = 0
    # The supplied CSV has Windows-1252 text bytes (including a ligature in an
    # origin label); use the actual source encoding rather than replacing text.
    with raw.open(encoding="cp1252", newline="") as fh:
        for row_number, row in enumerate(csv.DictReader(fh), start=2):
            raw_count += 1
            try:
                value = float(row["volume_kg"])
                assert math.isfinite(value) and value >= 0
                assert row["season"] in {"Rainy", "Dry"}
                assert row["nom_marche"] and row["type_produit"]
            except (ValueError, AssertionError, KeyError):
                exclusions.append({"row": row_number, "reason": "invalid quantity, season, market or product"})
                continue
            s, p, m = row["season"], row["type_produit"], row["nom_marche"]
            totals[s, p, m] += value
            counts[s, p, m] += 1
            markets.add(m)
            products.add(p)
    markets = sorted(markets)
    products = sorted(products)
    assert raw_count == 8208 and len(markets) == 14 and len(products) == 16
    references = []
    scenarios = []
    bounds_rows = []
    product_rows = []
    threshold_rows = []
    prospective_rows = []
    payloads = []
    max_lp_gap = 0.0
    lp_solves = 0
    consistency_count = 0
    prospective_checks = 0
    public_engine_calls = 0
    public_endpoint_checks = 0
    public_prospective_checks = 0
    max_public_gap = 0.0
    excluded_products = []
    for product in products:
        training = np.array([totals["Rainy", product, m] for m in markets])
        dry_kg = np.array([totals["Dry", product, m] for m in markets])
        dry_total = float(sum(dry_kg))
        if sum(training) <= 0 or dry_total <= 0:
            excluded_products.append(product)
            continue
        reference = dry_kg / dry_total
        for j, market in enumerate(markets):
            references.append({"product": product, "market": market,
                               "rainy_kg": float(training[j]), "dry_kg": float(dry_kg[j]),
                               "dry_share": float(reference[j]),
                               "rainy_rows": counts["Rainy", product, market],
                               "dry_rows": counts["Dry", product, market]})
        for design in DESIGNS:
            payload, groups = arrangement(markets, training, design)
            ledger = from_payload(payload)
            H = np.array(ledger.measurement_matrix(), dtype=float)
            readings = H @ reference
            prospective = ledger.profiles(1)["widths"]
            payloads.append({"product": product, "design": design,
                             "training_season": "Rainy", "evaluation_season": "Dry",
                             "dry_total_kg": dry_total, "payload": payload,
                             "source_data_reference_shares": reference.tolist(),
                             "derived_report_readings": readings.tolist()})
            for j, v in enumerate(payload["terminals"]):
                prospective_rows.append({"product": product, "design": design,
                                         "market": markets[j], "no_loss_width_share": prospective[v][0],
                                         "one_loss_width_share": prospective[v][1]})
            scenario_widths = []
            all_lower = []
            all_upper = []
            for lost in [None] + list(range(7)):
                keep = [i for i in range(7) if i != lost]
                A_eq = np.vstack([np.ones(len(markets)), H[keep]])
                b_eq = np.r_[1.0, readings[keep]]
                lower, upper = exact_bounds(reference, groups, design, lost)
                public_payload = {
                    "schema": "temflow.aggregate.v1", "total_mass": 1.0,
                    "destinations": markets,
                    "missing_record_budget": 1 if lost is None else 0,
                    "known_missing_record_ids": [] if lost is None else [payload["records"][lost]["id"]],
                    "context": {
                        "source": "Brazzaville retail survey sample; accounting total, not a physical origin",
                        "commodity": product, "mass_unit": "share of published Dry sample total",
                        "period_start": "2022-08-01", "period_end": "2022-08-31"},
                    "records": [
                        {"id": payload["records"][i]["id"],
                         "destinations": [markets[j] for j in group], "error": 0.0,
                         "value": float(readings[i]),
                         "provenance": "Derived archive packet from shared survey estimates; not independently acquired backup data; " + DOI}
                        for i, group in enumerate(groups)]}
                actual = public_engine(public_payload)
                assert actual["status"] == "ok" and actual["conditional"]["status"] == "ok"
                assert actual["engine_version"] == "1.0.0"
                public_engine_calls += 1
                for j, market in enumerate(markets):
                    bound = actual["conditional"]["bounds"][market]
                    gap = max(abs(bound["lower"]-lower[j]), abs(bound["upper"]-upper[j]))
                    max_public_gap = max(max_public_gap, gap)
                    assert gap < 1e-8, ("public conditional", product, design, lost, market, gap)
                    public_endpoint_checks += 2
                    if lost is None:
                        expected = prospective[payload["terminals"][j]]
                        obtained = actual["prospective"]["widths"][market]
                        assert max(abs(a-b) for a,b in zip(expected, obtained)) < 1e-8
                        public_prospective_checks += 2
                if lost is None:
                    payloads[-1]["public_engine_payload"] = public_payload
                all_lower.append(lower)
                all_upper.append(upper)
                loss_label = "none" if lost is None else payload["records"][lost]["id"]
                for j in range(len(markets)):
                    objective = np.zeros(len(markets))
                    objective[j] = 1.0
                    lo = linprog(objective, A_eq=A_eq, b_eq=b_eq, bounds=(0, None), method="highs")
                    hi = linprog(-objective, A_eq=A_eq, b_eq=b_eq, bounds=(0, None), method="highs")
                    assert lo.success and hi.success, (product, design, lost, j)
                    gap = max(abs(lo.fun-lower[j]), abs(-hi.fun-upper[j]))
                    max_lp_gap = max(max_lp_gap, gap)
                    assert gap < 1e-8, (product, design, lost, j, gap)
                    lp_solves += 2
                    assert lower[j]-1e-8 <= reference[j] <= upper[j]+1e-8
                    consistency_count += 1
                    budget = int(lost is not None)
                    assert upper[j]-lower[j] <= prospective[payload["terminals"][j]][budget]+1e-8
                    prospective_checks += 1
                    row = {"product": product, "design": design, "lost_report": loss_label,
                           "market": markets[j], "lower_share": float(lower[j]),
                           "upper_share": float(upper[j]), "reference_share": float(reference[j]),
                           "lower_kg": float(lower[j]*dry_total), "upper_kg": float(upper[j]*dry_total)}
                    for threshold in THRESHOLDS:
                        row["status_" + str(int(100*threshold)) + "pct"] = status(lower[j], upper[j], threshold)
                    bounds_rows.append(row)
                mean_width = float(np.mean(upper-lower))
                scenario_widths.append(mean_width)
                scenarios.append({"product": product, "design": design, "lost_report": loss_label,
                                  "mean_width_share_of_total": mean_width})
            product_rows.append({"product": product, "design": design,
                                 "dry_total_kg": dry_total,
                                 "no_loss_mean_width_share": scenario_widths[0],
                                 "worst_single_loss_mean_width_share": max(scenario_widths[1:]),
                                 "mean_single_loss_mean_width_share": statistics.mean(scenario_widths[1:])})
            for threshold in THRESHOLDS:
                statuses = [[status(lo[j], hi[j], threshold) for j in range(len(markets))]
                            for lo, hi in zip(all_lower, all_upper)]
                none_counts = Counter(statuses[0])
                loss_counts = Counter(s for row in statuses[1:] for s in row)
                robust = []
                for j in range(len(markets)):
                    unique = {row[j] for row in statuses}
                    robust.append(next(iter(unique)) if len(unique) == 1 and "unresolved" not in unique else "unresolved")
                robust_counts = Counter(robust)
                threshold_rows.append({"product": product, "design": design, "threshold_share": threshold,
                                       "no_loss_above": none_counts["above"], "no_loss_below": none_counts["below"],
                                       "one_loss_above": loss_counts["above"], "one_loss_below": loss_counts["below"],
                                       "robust_above": robust_counts["above"], "robust_below": robust_counts["below"],
                                       "markets": len(markets), "single_loss_market_scenarios": 7*len(markets)})
        print("Completed Brazzaville:", product, flush=True)
    summary = []
    threshold_summary = []
    for design in DESIGNS:
        subset = [row for row in product_rows if row["design"] == design]
        summary.append({"design": design, "products": len(subset),
                        **{metric + "_median": statistics.median(row[metric] for row in subset)
                           for metric in ("no_loss_mean_width_share", "worst_single_loss_mean_width_share", "mean_single_loss_mean_width_share")},
                        "worst_single_loss_min": min(row["worst_single_loss_mean_width_share"] for row in subset),
                        "worst_single_loss_max": max(row["worst_single_loss_mean_width_share"] for row in subset)})
        for threshold in THRESHOLDS:
            subset = [row for row in threshold_rows if row["design"] == design and row["threshold_share"] == threshold]
            counts_sum = {k: sum(row[k] for row in subset) for k in
                          ("no_loss_above", "no_loss_below", "one_loss_above", "one_loss_below",
                           "robust_above", "robust_below", "markets", "single_loss_market_scenarios")}
            counts_sum["no_loss_resolved_fraction"] = (counts_sum["no_loss_above"]+counts_sum["no_loss_below"])/counts_sum["markets"]
            counts_sum["one_loss_resolved_fraction"] = (counts_sum["one_loss_above"]+counts_sum["one_loss_below"])/counts_sum["single_loss_market_scenarios"]
            counts_sum["robust_resolved_fraction"] = (counts_sum["robust_above"]+counts_sum["robust_below"])/counts_sum["markets"]
            threshold_summary.append({"design": design, "threshold_share": threshold, **counts_sum})
    paired = Counter()
    comparisons = []
    for product in products:
        row = {d: next((r for r in product_rows if r["product"] == product and r["design"] == d), None) for d in DESIGNS}
        if any(v is None for v in row.values()):
            continue
        a, b = [row[d]["worst_single_loss_mean_width_share"] for d in DESIGNS]
        winner = "tie" if abs(a-b) < 1e-10 else DESIGNS[int(b < a)]
        paired[winner] += 1
        comparisons.append({"product": product, "individual_worst_width_share": a,
                            "paired_worst_width_share": b, "paired_minus_individual": b-a,
                            "smaller_worst_width": winner})
    result = {
        "title": "Retrospective resilience of equal-size reports on Brazzaville survey quantities",
        "status": "Retrospective scenario evaluation; not independent field validation",
        "dataset_doi": DOI, "dataset_version": "1", "dataset_licence": "CC BY-NC 4.0",
        "input_encoding": "Windows-1252",
        "raw_rows": raw_count, "valid_rows": raw_count-len(exclusions), "excluded_rows": exclusions,
        "excluded_products": excluded_products, "markets": markets, "products": products,
        "protocol_sha256": protocol_hash, "raw_sha256": RAW_SHA256,
        "software_version": "1.0.0", "kernel_sha256": sha256(Path(sys.modules["production_tree"].__file__)),
        "public_engine_structural_sha256": sha256(public_engine_path),
        "summary": summary, "threshold_summary": threshold_summary,
        "paired_product_winners": dict(paired),
        "algebraic_interpretation": "Paired-report mean width equals 2/14=1/7 by conservation for these two-member groups; it is not an empirical discovery. Empirical contrasts concern individual-report widths and threshold resolutions.",
        "validation": {"lp_solves": lp_solves, "maximum_lp_absolute_gap_share": max_lp_gap,
                       "public_engine_calls": public_engine_calls,
                       "public_conditional_endpoint_checks": public_endpoint_checks,
                       "public_prospective_value_checks": public_prospective_checks,
                       "maximum_public_engine_gap_share": max_public_gap,
                       "validation_extension": "After the fixed analysis, all cases were rerun through the unchanged public engine entry point; no design, threshold, eligibility, or outcome rule changed.",
                       "reference_containment_checks": consistency_count,
                       "conditional_within_prospective_checks": prospective_checks,
                       "containment_interpretation": "Expected by construction; not empirical coverage",
                       "all_one_loss_prospective_widths_equal_full_total":
                           all(abs(r["one_loss_width_share"]-1) < 1e-10 for r in prospective_rows)},
        "limitations": [
            "All totals and reports derive from the same survey quantities; none is an independent replicate.",
            "The exact archived sample total is retained under every simulated packet-loss state.",
            "Zero numerical error allowance treats archived estimates as exact numbers, not error-free physical measurements.",
            "Retail quantities derive partly from expenditure divided by average unit price; conversion bias is shared.",
            "Two seasonal snapshots and sampled markets do not establish generalization to other places, seasons or actual loss patterns.",
            "Equal scalar report count does not establish equal measurement effort, transport burden or survey cost.",
            "Thresholds are illustrative fractions, not validated policy or health decision thresholds.",
            "Empty recorded cells are zero quantities in this sample, not proof of absent physical commodity flows.",
            "The structured metadata mislabels the country and covered year; the source title, README and collection dates support Brazzaville, Republic of Congo, 2022.",
            "The source README's listed retail markets differ from CSV labels; analysis retains unmodified CSV labels."
        ],
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "numpy": np.__version__, "scipy": scipy.__version__},
    }
    for filename, rows in [("reference_market_totals.csv", references), ("conditional_bounds.csv", bounds_rows),
                           ("scenario_widths.csv", scenarios), ("product_outcomes.csv", product_rows),
                           ("product_thresholds.csv", threshold_rows), ("prospective_widths.csv", prospective_rows),
                           ("paired_comparison.csv", comparisons), ("threshold_summary.csv", threshold_summary)]:
        export_csv(out/filename, rows)
    (out/"REPORTING_PAYLOADS.json").write_text(json.dumps(payloads, indent=2), encoding="utf-8")
    (out/"RESULTS.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out/"ATTRIBUTION_AND_LICENCE.txt").write_text(
        "Derived from: Ameller, Joaquin; Moustier, Paule; Maba Ngouloubi, Prince Loique; Ofoueme-Berton, Yolande (2026).\n"
        "Dataset of produce supply flows in Brazzaville: A survey of traders in 2022. CIRAD Dataverse, version 1.\n"
        + DOI + "\nSource and derived survey summaries: CC BY-NC 4.0, https://creativecommons.org/licenses/by-nc/4.0/.\n"
        "Changes: market-product aggregation, normalization, simulated report loss, and calculation of bounds and summaries.\n"
        "This licence is distinct from the licence applying to TEM-FLOW program code.\n", encoding="utf-8")
    files = {p.name: sha256(p) for p in sorted(out.iterdir()) if p.is_file() and p.name != "OUTPUT_MANIFEST.json"}
    (out/"OUTPUT_MANIFEST.json").write_text(json.dumps(files, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=root/"inputs"/"brazzaville")
    parser.add_argument("--output-dir", type=Path, default=root/"results"/"african_reporting")
    parser.add_argument("--source-root", type=Path, default=None,
                        help="TEM-FLOW source root containing src/temflow; autodetected in standard bundles")
    args = parser.parse_args()
    results = run(args.output_dir, args.input_dir, args.source_root)
    print(json.dumps({k: results[k] for k in ("summary", "paired_product_winners", "validation")}, indent=2))
