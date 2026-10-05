REPEAT THE ARRAY ANALYSES — 5 OCTOBER 2026
Software version: TEM-FLOW 1.0.0

START HERE
Windows user package: double-click Repeat analyses.cmd. Keep Desktop,
Editable_Source and Reproduce_Analyses together. The included Python runtime
already contains the numerical libraries needed for the calculation.

Repository source or journal code package: use Python 3.12 or later, open this
analysis folder in a terminal, then run:
  python -m pip install -r requirements.txt
  python repeat_analyses.py

Supported layouts are Reproduce_Analyses inside the repository root, or an
analysis folder beside Editable_Source (user package) or Source (journal
package). If source is elsewhere, run:
  python repeat_analyses.py --source-root "PATH_TO_SOURCE"
The source path must contain src/temflow. The same path can be supplied through
the environment variable TEMFLOW_SOURCE_ROOT. No internet service or account
is needed after the package and numerical libraries are installed.

Each run makes a new fresh_runs folder. Open REPORT.html there to see whether
every check passed. REPORT.json records individual checks; logs identify any
failure. Supplied results are never overwritten. A custom output directory
must be new:
  python repeat_analyses.py --output "PATH_TO_NEW_OUTPUT"

NEW AFRICAN RETROSPECTIVE EVALUATION
The package now repeats the Brazzaville, Republic of the Congo, 2022 reporting
comparison from all 8,208 published retail survey rows, covering 14 market
labels and 16 vegetables. Rainy-season quantities determine two arrangements
of seven reports. The dry-season quantities provide the retained sample total
and reference for no loss and each possible single-report loss.

The comparison evaluates individual-market and paired-market reports. All
256 product/design/loss cases are run through the actual TEM-FLOW public
engine. The repeat checks all 7,168 conditional endpoints, 896 prospective
values, and 7,168 independent linear-programming optimizations. Every saved
African CSV, the full public-engine inputs, and all scientific result fields
are compared. Only software-environment metadata is allowed to vary in the
African results. Numerical tolerance is 1e-7 absolute and 1e-9 relative.

This is retrospective evaluation using African field-derived quantities,
with simulated loss after aggregation. Reports and the retained total derive
from the same survey quantities. They are not independent measurements or
backup acquisitions. The public survey volumes partly rely on price and unit
conversions; exact arithmetic does not make them error-free physical weights.
Neither design is asserted to be optimal or equally costly to acquire.

The paired reports have narrower worst-loss conditional bounds for all 16
vegetables, but individual reports have a narrower median without loss and
resolve more scenarios at the 5% threshold. Both designs have full-total
prospective one-loss widths. Preserve these qualifications: the prospective
criterion did not rank the two designs, and neither design preserved an
above-threshold conclusion across every loss state.

The locked method is code/BRAZZAVILLE_REPORTING_PROTOCOL.txt; its hash and
prescoring amendment are in code/BRAZZAVILLE_PROTOCOL_LOCK.json. These files
retain the protocol fixed before the comparison outcomes were calculated.
The subsequent public-engine check did not change the analysis rules.

AFRICAN SOURCE AND LICENCE
Ameller, J.; Moustier, P.; Maba Ngouloubi, P.L.; Ofoueme-Berton, Y. (2026).
Dataset of produce supply flows in Brazzaville: A survey of traders in 2022.
CIRAD Dataverse, version 1: https://doi.org/10.18167/DVN1/DAMXAW
Data and derived survey summaries: CC BY-NC 4.0.
https://creativecommons.org/licenses/by-nc/4.0/
This data licence is separate from the BSD 3-Clause software licence.

The original source files and metadata are in inputs/brazzaville. Only
dt_produce_flows_retail_market.csv is scored; the 102-row wholesale file is
preserved for provenance and is not treated as matched receipt validation.
Raw CSV text uses Windows-1252. The source retail SHA-256 is:
71b5e06c2af23ddc009df9281f33028d7dfc113578d6de02b4a4853d390287d1
Country/year and market-name discrepancies in the source metadata are recorded
in the protocol and result limitations; original data are not silently edited.

OTHER REPEATED ANALYSES
The runner repeats the 21-case structure-aware comparison, 60 edge checks,
UK interval/threshold analysis and constructed reporting example. It compares
all 57,488 structural profile values and every value in the output tables.
Timing is measured again, but the earlier speed ordering is not a pass rule.

The earlier empirical check repeats UK from raw data; rescores Karg, Dryad
and Comtrade frozen predictions; rescores Nigeria public derived truth because
raw microdata are restricted; and recalculates Zambia published tables.
The Karg African source-only negative result is retained.

The historical general-solver benchmark can be repeated separately using
analysis/efficiency in the companion source. It enumerates record-loss
combinations and is not a structure-aware baseline. Its earlier figure/table
numbers do not identify the current manuscript's figures or tables.

DATA INTERPRETATION
UK input: Rural Payments Agency 2010 cattle counts, Open Government Licence.
https://www.data.gov.uk/dataset/28d5ad2b-bff8-48ef-bb1d-07d86c07c77a/cattle-movements-to-slaughterhouses-during-2010
Structural inputs and the four-destination reporting example are constructed.
UK INTERVALS.csv has one method/source-month/group/compartment row; quantities
are cattle counts. UNRESOLVED_DESTINATION is an aggregate unnamed remainder.
DECISIONS.csv reports all four illustrative thresholds and specified subsets.
The source label 0 has no assigned geography. Full-set coverage differs from
joint coverage of individual intervals. No private chemistry or restricted
Nigeria microdata is included.

The methods implement established mathematics. The comparison code was written
within this project, not by an independent research team. Computational checks
are not proof of novelty or independent validation of field acquisition.

ENVIRONMENT
The 4 October analyses were recorded with Python 3.12.14, NumPy 2.5.3 and
SciPy 1.18.1 on Windows 11. requirements-recorded.txt preserves those versions.
The African analysis used the Windows application runtime: Python 3.13.15,
NumPy 2.5.1 and SciPy 1.18.0. Numerical equivalence is checked, not assumed.

REGENERATE FIGURES
Install the optional plotting requirements and run from this folder:
  python -m pip install -r requirements-figures.txt
  python code/make_figures.py
  python code/make_atlas.py
The atlas accepts --source-root "PATH_TO_SOURCE" in nonstandard layouts.
Outputs go to generated_figures. Charts use recorded medians and full ranges;
fresh timing plots would differ with machine load. The atlas uses included
public geographic inputs; displayed paths are geographic context, not measured
commodity movements. Matplotlib is not required for numerical reproduction.
