# TEM-FLOW 1.0.0 resolved release

Date: 2026-09-13

This package retains the first-release identity **TEM-FLOW 1.0.0**. The private
review interface now displays the same 1.0.0 identity as the Python package,
backend health response, integrated-run manifest, citation metadata, and
validation gate.

## Exposure-scenario application

The optional application layer now accepts a declared combination of:

- last-known or projected consumer population;
- last-observed or modelled retained compatible mass;
- last-reported food-contaminant concentration;
- body weight, reference dose, and a declared THQ threshold.

It calculates an interval for CPC, estimated daily intake, and THQ. Each result
retains the analysis date and the declared basis of the population, mass, and
chemistry inputs.

The model run does not display an exposure animation. When the calculated THQ
interval exceeds or crosses the declared threshold, the separate **Display
exposure animation** control becomes available. A red ripple indicates an
exceedance across the interval; amber indicates that the interval crosses the
threshold. Selected connecting routes receive a directional pulse from the
scenario source. The interface states that these pulses are scenario graphics
and do not establish contaminant transport along a route.

## Verification

- 175 unit and integration tests were run in the public package: 173 passed
  and 2 provenance checks were skipped because the editor-private application
  ledger is intentionally excluded.
- All eight installed-package validation gates passed.
- The embedded browser JavaScript passed `node --check`.
- The live reviewer interface produced CPC 36.5–73.0 kg/person/year, estimated
  daily intake 0.0004–0.0008 mg/kg-body-weight/day, and THQ 4.0–8.0 for a
  deliberately entered demonstration scenario, then enabled the animation only
  after the separate display control was clicked.
- The live browser console reported no errors or warnings.

The CFF value `cff-version: 1.2.0` is the Citation File Format schema version,
not the TEM-FLOW software version. Historical analysis protocols carrying
their own 1.2.0 identifiers remain unchanged to preserve provenance.
