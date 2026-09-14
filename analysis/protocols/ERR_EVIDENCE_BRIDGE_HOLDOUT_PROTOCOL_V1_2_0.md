# TEM-FLOW Evidence Bridge analyst-blind holdout protocol

Version: 1.2.0  
Lock date: 2026-09-12  
Target files: `5-15-24_train-ready_all_carts.csv` and `5-25-24_train-ready_all_carts.csv`

## Purpose

The neutral endpoint hull in the version 1.0.0 test covered most hidden masses but failed the frozen late-stage coverage and interval-width gates. This protocol tests a strengthened evidential bridge on two raw daily files that have not been downloaded, opened or used in calibration.

## Separation of calibration and validation

Calibration is limited to the ten CRC-verified daily files in the deterministic prefix arm. It contains 217 eligible cart-day episodes. Its fixed calibration table has SHA-256 `8BED7FCBB543152FCF13F7BB728C9CDD010D23A41AD3948580D66E60B4EA9ACE`.

The two target files are wholly excluded from calibration. Before this lock, only their paths, byte offsets, compressed sizes, uncompressed sizes and ZIP CRC values were visible. No CSV row or numerical `raw_mass` value from either target had been opened.

Target central-directory records:

- 5-15-24: compressed size 175,958,628; uncompressed size 714,923,098; CRC-32 `52780cb5`;
- 5-25-24: compressed size 161,198,788; uncompressed size 637,292,616; CRC-32 `0b36a311`.

## Fixed validation units

The episode definition, longest-run selection, duration threshold and row threshold are inherited unchanged from version 1.0.0. Every eligible `date_cartID` episode in both held-out files must be included.

## Partial evidence and hidden nodes

For each episode, observed evidence anchors occur at fractional times `0.00, 0.10, ..., 1.00`. Each anchor is the 2.5th to 97.5th percentile of load-cell mass in the fixed one-second window, and its median is recorded for scaling.

The ten hidden transient nodes occur midway between anchors at `0.05, 0.15, ..., 0.95`. Their truths are the median load-cell masses in fixed one-second windows. These target truths may be opened only after predictions are written and hashed.

## Evidence Bridge constraints

For hidden midpoint `q` with adjacent anchor intervals `[La,Ua]` and `[Lb,Ub]`, define the local physical hull:

`Hq = [min(La,Lb), max(Ua,Ub)]`.

Let `B = max(|median at 0.00|, |median at 1.00|, 1 kg)`. The calibrated evidence bridge is:

`Iq = [max(0, lower(Hq) - rho_q B), upper(Hq) + rho_q B]`.

The frozen stage radii are:

| q | rho_q |
|---:|---:|
| 0.05 | 0.002143514998237819 |
| 0.15 | 0.0001886288727136061 |
| 0.25 | 0.016117370499098657 |
| 0.35 | 0.011201704490921014 |
| 0.45 | 0.029846480030695195 |
| 0.55 | 0.03214349206055058 |
| 0.65 | 0.02557431864822125 |
| 0.75 | 0.024819608624973635 |
| 0.85 | 0.025204718133751608 |
| 0.95 | 0.12306125929182522 |

Radii at `q=0.05` through `0.85` are the finite-sample 90% stage-specific calibration order statistics. The terminal-adjacent `q=0.95` radius is the predeclared 95% order statistic because the primary late-stage gate is 90%. The order-statistic index is `ceil((n+1) * coverage)` with `n=217`, clipped to the largest observed rank.

Each bridge interval is supplied as a linear bound to the unchanged TEM-FLOW ERR version 1.1 feasible-set operator. Adjacent mass differences retain certified addition and uncertified removal coordinates. Unsupported removal identities must remain latent and blocked. No operational point is requested.

This is an interval certificate, not a fitted point trajectory. It combines local measured anchors, mass balance, evidence identity and held-out calibration residuals.

## Frozen pass gates

A pass requires all of the following:

- at least 20 eligible target episodes across the two unseen files;
- both target files match their ZIP uncompressed size and CRC-32;
- neither target file or target truth entered calibration;
- at least 80% coverage across all hidden midpoint masses;
- at least 90% coverage at `q=0.95`;
- median interval width no greater than 25% of `B`;
- maximum ERR constraint violation no greater than `1e-8`;
- every unsupported removal identity remains blocked;
- no operational point is produced;
- protocol, calibration, target, prediction and score artefacts have checksums.

The earlier neutral test remains a recorded failure. This revised test cannot replace or erase it.

## Claim boundary

A pass supports a calibrated, analyst-blind, raw multi-stage reconstruction claim for within-field strawberry cart routes, including an explicit unseen-day holdout. It does not validate farm-to-market transfer, source-proximity absorption, population, CPC, chemistry, exposure, hazard or annual flow. The two target days come from the same independent external study and site as calibration; this is not cross-study or cross-country validation.
