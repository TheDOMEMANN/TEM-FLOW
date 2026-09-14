# TEM-FLOW independent branching and source-proximity validation protocol

Version: 1.0.0  
Lock date: 2026-09-12

## Fixed method framing

TEM-FLOW is a multi-domain method for reconstructing source–transient–destination mass-flow states from incomplete, dated and differently sourced evidence. It returns feasible intervals, provenance links, evidence-sufficiency diagnostics and explicit refusal states. CPC, chemistry, exposure and health-risk calculations are downstream applications and are not the identity of this validation.

## Question

Can TEM-FLOW reconstruct withheld destination allocations and same-county retention when it receives a source total, a current direct/indirect movement margin, one current destination anchor selected without target outcomes, and earlier route evidence?

This does not test prediction from source mass alone. The earlier Karg source-only test already showed that such allocation is usually not informative.

## Independent evidence

Use the UK Rural Payments Agency dataset *Cattle movements to slaughterhouses during 2010*, distributed by the UK National Data Library under the Open Government Licence. The catalogue states that direct movements go from one premises to another and indirect movements pass through a transit location such as a market.

Before this protocol was sealed, only the public catalogue metadata and its four-row preview were inspected. The full CSV had not been downloaded, parsed or scored. The source is independent of ED-FLOW and TEM-FLOW and has not been used in the project.

The fields `Direct Movements` and `Indirect Movements` will be treated as reported nonnegative movement counts in a conserved count unit. They will not be described as instrument-weighed mass or as individual-animal identifiers unless the source documentation establishes that meaning. The indirect field identifies a transit class but not the transit location.

## Frozen split and eligibility

- Parse `Month & Year of Movement` as a monthly date and retain 2010 records with nonblank source and destination counties.
- Treat missing or nonnumeric direct/indirect values as missing, not zero. Retain nonnegative observed counts.
- Aggregate duplicate source–destination–month rows by summing within direct and indirect classes.
- Use January–May for fitting, June–August for calibration and September–December for testing.
- Retain a source county only when it has positive movement in every split and at least one fitted nonlocal destination.
- The fitted route support contains only destinations observed during fitting. A destination first observed later is represented by one unresolved-destination compartment.

## Target evidence and withheld truth

For each eligible source county, select one nonlocal anchor destination using fitting data only: the destination with the largest fitted count across direct and indirect classes, with lexical order as the tie-breaker.

For each source–month in the test period, TEM-FLOW receives:

- the total reported movement count from the source;
- the current direct and indirect class totals;
- the current direct and indirect count to the preselected anchor destination;
- fitted destination identities and fitted conditional shares.

The remaining destination-by-class counts are withheld until intervals are written and hashed. Counts to target-only destinations are combined into the unresolved-destination truth. The same-county destination is never selected as the anchor and remains withheld, so it can test geographic source-proximity retention at county scale.

## Joint compositional ambiguity set

For source `s`, movement class `c` and month `t`, subtract the observed anchor count from the class total. Let the remaining count be `R_sct`. Let `p_sc` be the fitted share vector over non-anchor fitted destinations plus one unresolved component, with fitted unresolved share fixed at zero.

For every eligible calibration month with `R_sct > 0`, form the observed share vector `a_sct`; all destinations outside the fitted support enter the unresolved component. Its total-variation residual is

`d_sct = 0.5 * sum_j |a_sctj - p_scj|`.

Use the finite-sample 90% order statistic `ceil((n+1)*0.90)`, clipped to the largest observed rank. Estimate a radius separately for direct and indirect classes when at least 30 calibration residuals are available; otherwise pool both classes. No target observation may change the radius.

The target feasible share set is

`Q_sct = {q: q >= 0, sum(q)=1, 0.5*||q-p_sc||_1 <= epsilon_c}`.

If `R_sct = 0`, all remaining allocations are exactly zero. Otherwise the sharp coordinate bounds under this set are

`q_j in [max(0,p_scj-epsilon_c), min(1,p_scj+epsilon_c)]`.

Multiply these bounds by `R_sct`; retain the exact anchor and class margins as equality evidence. The unresolved coordinate cannot receive a named destination. No operational point allocation is requested.

This joint set replaces independent route-by-route residual bands. It preserves the compositional dependence between branches, but it cannot create information absent from the evidence.

## Evidence-only comparator and sufficiency

The evidence-only interval for every unobserved coordinate is `[0,R_sct]`. Report contraction as one minus the total width under the joint set divided by total width under the evidence-only set. The model is decision-sufficient only when both coverage and width gates pass; otherwise it must return intervals or abstain.

## Frozen gates

A pass requires all of the following:

- at least 100 eligible source–class–month targets;
- at least 200 positive withheld compartments;
- at least 80% compartment-count coverage;
- at least 80% movement-weighted coverage;
- at least 80% coverage for unresolved-destination compartments with positive truth;
- at least 80% coverage of withheld same-county retention counts;
- median positive-compartment width no greater than 50% of its class residual total;
- median total-width contraction of at least 20% relative to the evidence-only set;
- maximum source/class balance violation no greater than `1e-8`;
- every unresolved destination remains unnamed;
- no operational point estimate is emitted;
- protocol, raw input, frozen predictions, unblinded truth, score and executable code have SHA-256 checksums.

## Claim boundary

A pass supports evidence-conditioned interval reconstruction of county-to-slaughterhouse branching and same-county retention in an independent administrative cattle-movement dataset. It also tests a direct/indirect transit-class margin. It does not establish farm-scale retention, identify the unnamed transit market, validate African food flows, prove physical weighbridge accuracy, or validate CPC, chemistry, exposure or hazard calculations.
