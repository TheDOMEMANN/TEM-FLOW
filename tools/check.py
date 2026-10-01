"""Run the editable source tests and package gates with the current Python."""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    from temflow.validation import run_packaged_validation
    validation_status = run_packaged_validation()
    if validation_status:
        raise SystemExit(validation_status)
    reproduction = subprocess.run(
        [sys.executable, '-B', str(ROOT / 'analysis/python/reproduce_all.py')],
        cwd=ROOT,
        check=False,
    )
    if reproduction.returncode:
        raise SystemExit(reproduction.returncode)
    for script in ("validate.py", "validate_structural_comparison.py"):
        import os
        environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        checked = subprocess.run([sys.executable, "-B", str(ROOT / "analysis/structural" / script)], cwd=ROOT, env=environment)
        if checked.returncode:
            raise SystemExit(checked.returncode)
    raise SystemExit(0)
