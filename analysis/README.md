# Analysis files

This directory separates manuscript analyses from the installable TEM-FLOW
package. CSV files are under `data`, executable scripts under `python` and `R`,
frozen scores under `results`, and sealed decisions under `protocols`.

The UK RPA raw CSV is included because the source states that it is public under
the UK Open Government Licence. Large Dryad working archives and restricted
NASS microdata are not redistributed. Their public download or access route,
checksums, and derived outputs remain documented by the original protocols.

Run the complete public validation reproduction from the repository root:

```powershell
python analysis\python\reproduce_all.py --output analysis\results\REPRODUCTION_REPORT_V1_0_0.json
```

This command reruns the sealed UK RPA validation from the included public raw
CSV, independently rescores the Karg, Dryad and cross-commodity frozen
predictions against their unblinded truth, rescores the public NASS derived
truth, and recalculates the Zambia scale evidence. It reports the reproduction
level for every case. A copied summary-table check is identified only as an
integrity check.

The reproducibility boundaries are deliberate and visible:

| Validation | Public reproduction level | Data boundary |
|---|---|---|
| UK RPA branching | Raw data to final score | Public OGL CSV included |
| Karg source-only | Frozen prediction rescore | Prediction, truth and calibration data included |
| Dryad transient | Frozen prediction rescore | The approximately 1.7 GB raw holdout remains at its public archive; acquisition manifest included |
| Cross-commodity trade | Frozen prediction rescore | Prediction and scored holdout cells included |
| NASS retention | Derived-truth rescore | Raw microdata are restricted; negative result retained |
| Zambia scale | Published-table recalculation | Extracted official table values included |

The original case scripts remain under `python` as protocol-preserving source
records. Some retain the directory names of their sealed analysis packages;
`reproduce_all.py` is the supported repository entry point and constructs an
isolated compatible layout where a raw rerun is possible.

The optional base-R integrity check remains available:

```powershell
Rscript analysis\R\reproduce_validation_summary.R
```
