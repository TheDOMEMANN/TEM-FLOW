# Outcome-blind implementation amendment

Version: 1.2.1  
Date: 2026-09-12

## Why the sealed 1.2.0 execution aborted

The target reader completed and wrote the observed-anchor predictor file, but the first prediction run stopped before writing a prediction, hidden-truth or score file. The ERR validator rejected at least one bridge interval because the raw load-cell offset made its calculated upper endpoint negative. ERR correctly requires physical mass bounds to satisfy `0 <= lower <= upper`.

The failed runner had SHA-256 `9139BD85C8C01F71671DAD6A22F45B8898F9CB09BD6D4F97A5EE00C847DAE8AD`. The anchor-only predictor written by that failed run had SHA-256 `91094921D85F15B42463245FDC8E54800053C76E1EC3510A9D2C327AA075A92A`.

## Fixed amendment

The locked bridge formula already imposed `max(0, ...)` on its lower endpoint and ERR's domain is nonnegative physical mass. Version 1.2.1 applies the same nonnegative intersection to the upper endpoint:

`Iq = [max(0, lower(Hq) - rho_q B), max(0, upper(Hq) + rho_q B)]`.

No radius, target, episode rule, anchor rule, hidden time, gate or ERR setting is changed.

## Blindness boundary

This is a post-access implementation amendment, not a fully pre-access preregistration. Target CSVs were read by the failed program before this amendment, but no hidden target value was printed or written for analyst inspection, no prediction file existed, and no score was calculated. The amended run is therefore described as outcome-blind and calibration-withheld, with this deviation reported. It must not be described as a clean preregistered holdout.

The original 1.2.0 abort and the earlier neutral-model failure remain retained.
