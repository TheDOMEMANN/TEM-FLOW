# TEM-FLOW 1.0.0 reproducibility guide

From a source checkout with Python 3.10 or later:

```text
python -m pip install -r requirements-lock.txt
python -m pip install --no-deps -e .
python -B tools/check.py
```

`tools/check.py` runs the computational test suite, eight installed-package
validation gates, and `analysis/python/reproduce_all.py`. The public release is
acceptable only when this command succeeds from a clean extraction of the
release archive.

The engine tests exercise numerical conservation, feasible intervals, sharp
bounds, infeasibility, temporal matching, identity certificates, refusal
states, the map registry and the reviewer interface. The analysis runner then
checks the manuscript-facing validation evidence at the strongest public level
available for each dataset.

The public package excludes the CPC/contaminant application ledger. Those data
are not needed for the core TEM-FLOW tests or the validation summary. The NASS
raw microdata are also restricted. These absences are reported as data-access
boundaries and are never converted into successful raw-data reproduction
claims.
