# Entering new records in TEM-FLOW

This guide is for users who work in Excel or another spreadsheet program. You do not need to write Python or JSON.

## Choose the right way to enter information

Use **Add new feature** on the map when you need to add or remove a place or a route. These changes are saved in the local `user_data` folder and appear again after restarting TEM-FLOW.

Use the **dated-record CSV** when you have new observations for existing places or routes, such as a reported mass, CPC interval, population, contaminant result, or monitoring alert. The file is used for the current browser session and current model run. It does not rewrite the original evidence ledger.

The existing JSON input remains available for advanced users. TEM-FLOW converts an uploaded CSV to this same JSON structure internally.

## Prepare the CSV file

1. Download `TEMFLOW_DATED_RECORD_INPUT_TEMPLATE.csv` from the Run workflow panel.
   You can also download `TEMFLOW_DATED_RECORD_EXAMPLE.csv` to see four synthetic rows. Do not treat its invented names or values as evidence.
2. Open it in Excel, LibreOffice Calc, or another spreadsheet program.
3. Keep the column names in the first row. You may leave columns blank when they do not apply, but do not rename or add columns.
4. Put one dated record in each later row.
5. Save the file as **CSV UTF-8 (Comma delimited)**.

Every row must contain these three fields:

- `layer`: what kind of record this is.
- `record_id`: your unique name for the record, such as `OBS-ZIWAY-2026-01`.
- `observed_at`: the observation or source date in `YYYY-MM-DD` form, such as `2026-09-15`.

Blank cells remain unknown. TEM-FLOW never changes a blank cell to zero. Enter `0` only when the source explicitly reported zero.

## Values allowed in the layer column

| `layer` value | Use it for | Main columns to complete |
|---|---|---|
| `od_evidence` | A dated source-to-destination mass or route record | `origin`, `destination`, `commodity`, `reported_mass` or `quantity`, `unit` or `mass_unit_period`, `provenance` |
| `cpc_compatibility` | A CPC interval for one exact destination and product | `identified_lower`, `identified_upper`, `measured_lower`, `measured_upper`, identity and certificate fields described below |
| `contaminant_trace` | A private contaminant observation | `node_id` or `route_id`, `value`, `unit`, `material`, `provenance` |
| `exposure_scenario` | A private exposure calculation request | `source_node_id`, retained mass interval, `consumer_population`, concentration, body weight, reference dose, and evidence-basis fields |
| `market_access` | A market-access observation or alert | `node_id` or `route_id`, `status`, `trigger`, `provenance` |
| `flow_irregularity` | A marketing or flow irregularity | `node_id` or `route_id`, `status`, `trigger`, `provenance` |
| `postharvest_loss` | A postharvest-loss observation | `node_id` or `route_id`, `value`, `unit`, `status`, `trigger`, `provenance` |
| `supply_continuity` | A supply interruption or warning | `node_id` or `route_id`, `status`, `trigger`, `provenance` |
| `price_affordability` | A price or affordability observation | `node_id`, `value`, `unit`, `status`, `trigger`, `provenance` |

A file may contain several kinds of rows. It may contain many OD, contaminant, or monitoring rows. It may contain only one `cpc_compatibility` row and one `exposure_scenario` row because each run evaluates one CPC and exposure scenario at a time.

## CPC rows and provenance

A CPC value can affect a result only when it identifies the exact claim and its evidence. Complete these columns:

- Interval: `identified_lower`, `identified_upper`, `measured_lower`, and normally `measured_upper`.
- Identity: `country`, `food_domain`, `commodity`, `product_form`, `destination`, `period`, `denominator`, and `unit`.
- Evidence: `certificate_id`, `evidence_ids`, and `claim_boundary`.

Separate more than one evidence ID with a semicolon, for example `SURVEY-12;LEDGER-7`. The claim boundary should state what the evidence authorizes, for example: `Exact lake-side destination, fish product, resident-consumer denominator and 2025 period.`

TEM-FLOW rejects an uncertified direct CPC input instead of treating it as verified. The same identity fields must describe both the CPC claim and its certificate.

## Exposure-scenario rows

Complete the following fields when they are available:

- `retained_mass_lower_kg_year` and `retained_mass_upper_kg_year`
- `consumer_population`
- `concentration_mg_per_kg_food`
- `body_weight_kg`
- `reference_dose_mg_per_kg_day`
- `declared_thq_threshold`
- `mass_basis`: normally `last_observed` or `modelled`
- `population_basis`: normally `last_known` or `projected`
- `chemistry_basis`: normally `last_reported`

Set `requested` to `yes`. Chemistry values are not supplied in the public repository; a user may enter them locally in a private file.

## OD evidence and the model boundary

An `od_evidence` row is retained in the run manifest so the record, date, and provenance remain visible. Uploading that row does not automatically turn it into an ERR equation or force unobserved routes to zero. A complete ERR problem still requires explicit variables, physical constraints, bounds, and coordinate certificates through the programmatic `/api/err/run` interface.

This boundary prevents a spreadsheet observation from being given more mathematical authority than its source supports.

## Load and run the file

1. Start TEM-FLOW and select the relevant node or route on the map by double-clicking it.
2. Open **Run workflow — include only the layers needed**.
3. Tick only the layers you want to evaluate.
4. Under **Load dated-record CSV or private-layer JSON on demand**, select your CSV.
5. Read the message below the file box. It reports the number of rows converted, or identifies the row and field that must be corrected.
6. Click **Run selected workflow**.
7. Read the run manifest and any refusal or blocked-evidence message. A refusal means that TEM-FLOW preserved an evidence boundary; it is not a software failure.

The uploaded data remain in browser memory for the session. Click **Clear loaded private data**, close the tab, or restart the local application to remove them from the active workflow. Keep the source CSV in your own controlled folder if it contains private information.

## Common corrections

- **Unknown CSV columns:** restore the original template header and move your values into the supported columns.
- **Date error:** use a real date such as `2026-09-15`, with four-digit year, two-digit month, and two-digit day.
- **Number error:** remove words and unit symbols from number cells. Put the unit in the `unit` column.
- **Lower exceeds upper:** correct the interval endpoints.
- **Unsupported layer:** copy one of the exact layer names from the table above.
- **CPC certificate error:** complete all CPC identity, evidence, and claim-boundary fields.

## JSON users

Advanced users may continue to upload `docs/PRIVATE_LAYER_INPUT_TEMPLATE.json`. Its root must be a JSON object. CSV and JSON follow the same session-only privacy rule and feed the same engine integration point.
