# TEM-FLOW source-only route-allocation validation protocol

Version: 1.0.0  
Lock date: 2026-09-12

## Question

Can TEM-FLOW reconstruct destination-route mass from an observed source total and earlier route evidence, without using target-period destination or checkpoint margins?

## Evidence

The test uses Karg et al., *A spatio-temporal dataset on food flows for four West African cities*, DOI `10.5281/zenodo.6423382`. The data were collected independently of ED-FLOW and TEM-FLOW. The field `total_quantity` is standardized fresh-weight mass based on reported units, measured volumes and product-density conversions. It is not treated as uniformly instrument-measured mass.

The CSV was used previously for a three-margin conditional reconstruction. Therefore this new test is not analyst-blind to the dataset. The new estimand, rules and gates are locked before the new analysis. Earlier results are retained and cannot be replaced by this test.

## Eligible records

Use every record with complete city, year, season, commodity, direction, date, source, field checkpoint, destination, transport mode and positive `total_quantity`. Exclude rail, plane and boat/ferry records. Do not use the dataset's aggregate adjustment for missing locations.

Create every city-year-season-commodity-direction panel containing at least six distinct survey dates. Sort dates. Use the first 60% of dates for fitting, the next 20% for calibration and all remaining dates for testing, with at least three fit dates, one calibration date and one test date. Include every test source that occurred during fitting. No panel is selected using target performance.

## Partial-evidence reconstruction

For each fitted source, the certified route skeleton consists only of source-checkpoint-destination identities observed during fitting. Its historical share is its fit mass divided by all fit mass from that source.

On a target date, the model receives only:

- the panel identity and date;
- source identity;
- observed aggregate source mass;
- the fit-certified route skeleton and historical shares.

It must not receive target route masses, target checkpoint margins, target destination margins or target-only route identities. Target-only paths are combined into an unresolved-route sink.

For fitted route `r`, let `p_r` be its historical share. Calibration residuals are `|a_r - p_r|`, where `a_r` is the route's calibration-date share and is zero when the fitted route was inactive. The unresolved residual is the calibration share assigned to paths absent from the fitted skeleton.

Use the finite-sample 90% order statistic `ceil((n+1)*0.90)`, clipped to the largest observed rank. Estimate radii by city and direction when at least 30 residuals are available; otherwise use the global radius.

The preliminary bounds are:

`f_r / M in [max(0, p_r-rho), min(1, p_r+rho)]`

and

`f_unresolved / M in [0, u90]`.

Supply these bounds and the exact source balance `sum(f)=M` to the unchanged TEM-FLOW ERR feasible-set operator. Certified fitted routes may receive named interval claims. The unresolved route must remain explicitly unresolved. No operational point estimate is requested.

## Prediction and truth order

Write and hash all target intervals before writing target route masses or computing scores. The source total is an allowed target input. The prediction stage must not print target route outcomes.

## Frozen gates

A pass requires all of the following:

- at least 50 eligible target source-date groups;
- at least 100 positive target compartments, including unresolved sinks;
- at least 80% count coverage of positive target compartment masses;
- at least 80% mass-weighted coverage of positive target compartment masses;
- at least 80% coverage of unresolved-route target masses;
- median interval width no greater than 50% of source mass among positive target compartments;
- maximum ERR constraint violation no greater than `1e-8`;
- every unresolved-route identity remains blocked;
- no operational point estimate is produced;
- raw input, prediction, truth, score and code have checksums.

## Claim boundary

A pass supports source-total-to-route interval allocation for repeated, field-observed West African city food-flow panels. It does not prove route discovery where no prior route identity exists, full farm-to-fork continuity, complete city capture, physical weighbridge accuracy, source retention, CPC, chemistry, exposure or hazard.
