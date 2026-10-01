# Calculate evidence limits from aggregate records

TEM-FLOW 1.0.0, structural formulation revision of 1 October 2026.

Open **Evidence limits and missing records** in the desktop window. Click **Load example**, then **Calculate evidence limits**. The example is synthetic and contains no contaminant measurements. It has 100 kg in total and a measured combined mass of 40 kg for destinations A and B. The resulting range for A is 0–40 kg. The mass at the unnamed destination is 60 kg.

The second result asks a different question: how uncertain could the allocation be over all possible readings, including when records become unavailable? It reports range widths. It does not describe the probability of missing records, provide a confidence interval, or replace the ranges for your actual readings.

## Prepare your own table

Download the blank aggregate CSV template. Open it in a spreadsheet application, keep every column heading, and save as CSV with comma separators and UTF-8 encoding. Each row represents one independently acquired aggregate measurement. The existing dated-record CSV template remains available for CPC, OD and other workflow data; use this separate aggregate template for the structural calculation.

| Column | What to enter |
| --- | --- |
| total_mass | Exact total mass available for allocation; repeat on every row. |
| destinations | Every destination, separated by a vertical bar, such as A\|B\|Unallocated. Include an unnamed remainder whenever the named destinations are not exhaustive. |
| missing_record_budget | Largest number of additional records to test as unavailable; use 0 for none. |
| source | Source name; the same on every row. |
| commodity | Product in a single compatible form; the same on every row. |
| mass_unit | A common mass or count unit, for example kg. No automatic conversion is performed. |
| period_start, period_end | Accounting period, in YYYY-MM-DD format; the same on every row. |
| record_id | A unique name for an independently acquired measurement. Copying the same report twice does not supply two independent records. |
| group_destinations | Destinations included in this measurement, separated by a vertical bar. |
| error | Absolute error allowance in the same unit as total_mass. Use 0 only for an exact measurement. |
| value | Measured group total. A blank value permits prospective analysis but prevents calculation of current ranges until all available readings are supplied. |
| observed_on | Date of the observation, in YYYY-MM-DD format, if known. The user must verify that it describes the declared accounting period. |
| provenance | Report, survey or other source supporting the measurement and its error allowance. |

Use **Open an aggregate CSV or JSON file**, or paste the CSV rows into the box. You can edit these rows directly and recalculate. Use **Save results** to retain the complete calculation, assumptions, source context and software formulation identifier. Loading a file does not modify the geographic ledger or add map routes.

For several sources, products or periods, prepare separate files and calculate them separately. Do not combine incompatible units or dates into one accounting problem. Observations with uncertain totals, losses, conversion constraints or reference-share restrictions require the general reconstruction workflow, which is retained.

## How groups are interpreted

Groups are nested when any two groups are either separate or one is entirely inside the other. For example, A and the combined group A+B are nested. A+B and A+C overlap without nesting. TEM-FLOW checks this condition. It uses the structural theorem for nested groups and a general linear calculation for overlapping groups. The group hierarchy is an accounting structure; it is unrelated to the shape of roads on the map.

The exact source total is assumed to remain known when other records are missing. Errors have separate absolute bounds. Missing record identities are known. Hidden incorrect readings, joint error correlations, and simultaneous loss of a whole reporting institution are different problems and are not represented by this calculation.

JSON permits `known_missing_record_ids` to list records already unavailable. The additional budget then applies to the remaining records. The CSV template describes records currently available. Remove unavailable rows and adjust the budget if using CSV. JSON can also request `include_witnesses: true` to obtain allocations that attain the prospective widths in nested systems. Their destination and record order are explicitly included in the result.

If entered values contradict the exact total and error allowances, TEM-FLOW reports that the current records are incompatible. A separately reported prospective profile does not make those values valid. Different destinations may attain their worst uncertainty under different missing-record sets and readings.

## Calculation limits and reproducibility

The interactive reader accepts at most 10,000 destinations and 50,000 records, subject to a budget-dependent workload check. Conditional linear calculations are limited to 500 destinations. The overlapping-group prospective calculation is limited to 200 destinations and 20,000 destination/set calculations. A limit is reported explicitly; it is never replaced by a claimed exact answer. Input group checking and dense linear programs have their own cost; the theorem's complexity bound describes the already constructed tree calculation.

After installing the package, the same calculation can be run without the map:

```text
python -m temflow structural docs/AGGREGATE_RECORD_EXAMPLE.csv --output evidence-limits.json
```

The Python function is `temflow.run_structural_payload`. The local web endpoint is `/api/structural/run`. A complete selected workflow accepts the same object as `structural_problem` when the reconstruction layer is enabled. It never invents an accounting hierarchy from geographic proximity.

No contaminant-chemistry values are distributed with these inputs. Public CPC and OD functionality remains available.
