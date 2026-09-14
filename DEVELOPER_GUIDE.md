# Maintaining TEM-FLOW source code

The maintained application uses one source tree. The Windows desktop launcher runs this source directly; the same tree can be installed as a Python package or uploaded to a repository. The initial release stays **1.0.0**.

## Find the code to change

| Area | File in this folder |
| --- | --- |
| Single release version | `src/temflow/_version.py` |
| Map, feature dialog, mouse/keyboard controls | `src/temflow/data/patterns_private_ui.html` |
| API, access control, model dispatch, catalog | `src/temflow/private_engine.py` |
| Added nodes/routes and AI proposal records | `src/temflow/curation.py` |
| Dated removal, restoration and affected-feature review | `src/temflow/feature_changes.py` |
| Evidence-resolved reconstruction | `src/temflow/evidential_resolution.py` |
| Joint compositional allocation | `src/temflow/compositional.py` |
| Core numerical constraints | `src/temflow/core.py`, `src/temflow/constraints.py` |
| CPC/exposure and monitoring layers | `src/temflow/downstream_consequence.py`, `src/temflow/exposure_scenario.py`, `src/temflow/monitoring_layers.py` |
| Immutable dated observations | `src/temflow/versioned_registry.py` |
| Desktop process and launcher | `desktop_server.py`, `desktop_launcher.py` |
| Road reconstruction | `tools/build_africa_road_geometries.py` |
| Regression tests | `tests/` |

Add a substantial independent feature in its own module and connect it through the API and interface. Keep numerical functions separate from display code. Preserve evidence provenance and the distinction between candidate links, endpoint relations, road-shaped display and observed flow. A manually added route has no verified road path until compatible geometry has been supplied; do not substitute a guessed path.

## Daily edit and test workflow

1. Make a copy or a Git branch before editing.
2. Edit the relevant source files with your preferred editor.
3. Add a test for meaningful changes to calculations, permissions, topology or saved data.
4. Run `runtime\python.exe -B tools\check.py`, or double-click **Run checks.cmd**.
5. Restart the desktop engine and inspect the changed interface. Check selection, Escape, pan/zoom and road alignment if map code changed.
6. Record what changed and what passed in `CHANGELOG.md`, then commit your changes if using Git.

The bundled runtime includes Python 3.13.15, NumPy 2.5.1 and SciPy 1.18.0 for 64-bit Windows. It covers the engine and its regression checks. Optional extended analysis scripts using pandas, scikit-learn or requests need the normal development installation below. Third-party runtime licenses and wheel metadata remain in `runtime/`.

## Using a normal Python installation

From this folder in a terminal:

```text
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[validation]"
.venv\Scripts\python tools\check.py
.venv\Scripts\python -m temflow patterns-engine --port 8780
```

On Linux/macOS use `.venv/bin/python` and forward slashes. `pyproject.toml` describes dependencies and package contents. The desktop runtime is intentionally separate from the source distribution; do not run pip directly inside the embedded runtime. Build a new runtime in a fresh copy using `python tools/build_desktop_runtime.py` after updating its explicit version/checksum pins and testing compatible wheels.

## Version changes and releases

Use **1.0.1** for a compatible repair, **1.1.0** for compatible new functionality, or **2.0.0** for an incompatible API/data-format change. These are examples for future work; no later release has been assigned now.

```text
runtime\python.exe tools\set_version.py 1.1.0
runtime\python.exe -B tools\check.py
runtime\python.exe tools\package_release.py
runtime\python.exe tools\package_release.py --desktop
```

`set_version.py` updates `_version.py`, the citation version and the interface's initial version label. Python package metadata derives its version from `_version.py`. Backups go into `.version_backups/`. Update the actual change descriptions in `CHANGELOG.md`; historical provenance and source-release identifiers must retain their original versions.

`package_release.py` reruns checks, creates a versioned ZIP in `dist/`, and includes checksums. It refuses to overwrite an existing release ZIP. The source ZIP excludes the runtime; the desktop ZIP includes it. Both omit local user records, private editor data, caches, logs and the private chemistry ledger. Do not upload the whole working desktop folder.

## Repository maintenance

Extract the **source ZIP** into the repository. Keep the desktop ZIP as a release attachment, not as a large committed runtime tree. The included GitHub Actions workflow installs dependencies and runs `tools/check.py`. Commit changes on a branch, inspect the diff, and merge after checks pass. Tag the released version (for example `v1.1.0`) and attach the generated release ZIPs. Preserve earlier releases.

TEM-FLOW is licensed under BSD-3-Clause. Add the archival DOI to `CITATION.cff` after a permanent archive record is assigned.

For a new data format, write an explicit migration that reads the old data and writes a new copy, test it on a backup, and document the change. Never overwrite users' provenance history during an upgrade.

Runtime provenance: [Python 3.13.15 release and checksums](https://www.python.org/downloads/release/python-31315/), [Python embeddable distribution documentation](https://docs.python.org/3.13/using/windows.html#the-embeddable-package), [NumPy release metadata](https://pypi.org/pypi/numpy/2.5.1/json), [SciPy release metadata](https://pypi.org/pypi/scipy/1.18.0/json). The build verifies downloaded hashes and keeps their licenses.
