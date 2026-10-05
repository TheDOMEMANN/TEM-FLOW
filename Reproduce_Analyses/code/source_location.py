"""Locate a companion TEM-FLOW source in supported distribution layouts."""
from pathlib import Path
import os


def locate_source(anchor, requested=None):
    requested = requested or os.environ.get('TEMFLOW_SOURCE_ROOT')
    if requested:
        candidates = [Path(requested)]
    else:
        here = Path(anchor).resolve()
        here = here.parent if here.is_file() else here
        candidates = []
        for parent in [here, *list(here.parents)[:4]]:
            candidates.extend([parent/'Editable_Source', parent/'Source', parent,
                               parent/'User_package/Editable_Source'])
    for candidate in candidates:
        if (candidate/'src/temflow/structural.py').is_file() and (candidate/'src/temflow/_version.py').is_file():
            return candidate.resolve()
    raise FileNotFoundError('Keep Editable_Source or Source beside the analyses, or use the repository root '
                           'containing src/temflow. Otherwise pass --source-root PATH or set TEMFLOW_SOURCE_ROOT.')
