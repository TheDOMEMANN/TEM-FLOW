> For the editable Windows desktop build, start with [DESKTOP_START_HERE.md](DESKTOP_START_HERE.md). For source changes, version upgrades and repository releases, read [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md). The current feature manager adds, removes and restores nodes/routes with curator access.

# TEM-FLOW 1.0.0

TEM-FLOW reconstructs source–transient–destination mass-flow intervals when
route evidence is incomplete, dated differently, or collected by separate
institutions. It preserves mass balance and the identity of the material while
distinguishing observed, source-reported, transparently derived, and
model-derived quantities.

TEM-FLOW does not force a single allocation when several networks satisfy the
evidence. Its main outputs are feasible intervals, supporting solutions,
evidence links, sufficiency measures, and explicit refusal states. A point
allocation is optional and is always labelled as a prior-dependent working
value.

## What version 1.0.0 contains

- Evidence-Resolved Reconstruction (ERR) for exact bounds over a physical
  feasible set and its least-unresolved subset.
- A joint destination-share set on the simplex, calibrated with total-variation
  residuals, for evidence states that contain earlier route shares and a
  compatible current downstream anchor.
- Typed identities, transformation certificates, dated-evidence matching, and
  an unresolved-destination compartment.
- The inherited ED-FLOW-style reviewer interface with the TEM-FLOW computation
  and reporting rules underneath it.
- Optional downstream CPC and chemistry consumers. These are applications of a
  compatible mass interval, not part of the method's novelty claim.
- Explicit include/exclude switches for ERR, CPC compatibility, contaminant
  tracing, exposure/ED/THQ, market access, flow irregularity, postharvest loss,
  supply continuity, and price/affordability monitoring.
- An explicit exposure-scenario consumer can combine a declared last-known or
  projected consumer population, last-observed or modelled retained mass, and
  last-reported food concentration to calculate CPC, estimated daily intake,
  and THQ. The result records every input basis and its analysis date. A red
  node ripple and route pulse is available only after a declared THQ
  exceedance and only when the reviewer clicks **Display exposure animation**.
  An interval that only crosses the threshold uses amber. Running the model
  never displays the animation automatically, and route pulses do not assert
  that contaminated product travelled along the displayed route.

The public Patterns package contains the computational slots and a local CSV or
JSON file loader, but no contaminant-chemistry application ledger. A dated CSV
uses one observation per row and is validated and converted internally to the
engine's JSON contract. Sensitive application records can be supplied on
demand and remain in browser memory for the active session. See the
[plain-language input guide](docs/INPUT_GUIDE_FOR_ORDINARY_USERS.md) and the
[blank CSV template](docs/TEMFLOW_DATED_RECORD_INPUT_TEMPLATE.csv). A
[filled synthetic example](docs/TEMFLOW_DATED_RECORD_EXAMPLE.csv) shows four
record types without disclosing application data. The
editor-private package retains the frozen evidence ledger for confidential
testing.

Map coordinates are drawn from the audited predecessor coordinate registers
where an exact or documented same-feature match exists. Commodity-state child
nodes inherit their physical parent's audited coordinate. Unresolved registry
nodes remain available to the model and lists, but their display-only layout
proxies are hidden by default and can be shown explicitly. Double-click selects
a map feature; left-drag pans; right-drag up/down zooms; Escape clears floating
messages, map selection, and exposure animation.

Source mass alone is not treated as enough evidence for useful destination
allocation. The Karg validation returned a median interval width equal to
98.32% of source mass. Likewise, a missing downstream record does not imply
100% source retention. Both conditions return broad intervals or refusal until
compatible evidence is supplied.

## Install and check

```powershell
python -m pip install .
python -m temflow validate
python -m unittest discover -s tests -v
python analysis/python/reproduce_all.py --output analysis/results/REPRODUCTION_REPORT_V1_0_0.json
```

The last command distinguishes raw-to-result reproduction from independent
rescoring when raw evidence is too large, externally hosted, or restricted.
See `analysis/README.md` for the case-by-case data boundary.

Run the local reviewer interface:

```powershell
python -m temflow patterns-engine --host 127.0.0.1 --port 8765 --data-dir .\user_data_temflow
```

Core HTTP operations are `POST /api/err/run` and
`POST /api/compositional/run`. The integrated `POST /api/model/run` retains the
same map and evidence-selection architecture.

## Repository layout

- `src/temflow/`: installable software and reviewer interface.
- `tests/`: source tests.
- `FORMULATION/`: method definitions and proof obligations.
- `ledger/`: append-only evidence and transformation ledgers.
- `analysis/data/`: isolated CSV inputs used by the reported analyses.
- `analysis/python/`: Python analysis and independent-check scripts.
- `analysis/R/`: an independent base-R check of the paper's result table.
- `analysis/results/`: frozen scores and checksums.
- `analysis/protocols/`: pre-analysis protocols, seals, and amendments.

Downloaded working archives, partial range downloads, build directories,
rendered pages, caches, and superseded outputs are deliberately excluded.

## Validation boundary

The strongest branching test used independently collected UK cattle-movement
records. Under a sealed split, 99.53% of positive withheld compartments were
inside the intervals, median total width contracted by 50.70%, and 99.12% of
positive same-county retention cases were covered. These are administrative
movement counts at county scale, not instrument-weighed mass or farm-scale
retention.

An analyst-blind Dryad test covered 88.64% of 440 hidden transient mass states.
The source-only Karg test failed the informativeness and unresolved-coverage
gates. NASS and Zambia evidence reject a general no-route-means-100%-retention
rule. These negative results are part of the release.

## Public release identifiers

TEM-FLOW is released under the BSD 3-Clause License. The maintained source and
versioned releases are available at
[github.com/TheDOMEMANN/TEM-FLOW](https://github.com/TheDOMEMANN/TEM-FLOW).
Add the archival DOI to `CITATION.cff` after an archival record is deposited.
