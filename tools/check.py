"""Check this source and reproduce saved results without replacing them."""
from pathlib import Path
import argparse
import datetime
import json
import os
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    out = args.output_dir or ROOT / 'user_data/checks' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if out == ROOT / 'analysis' or ROOT / 'analysis' in out.parents:
        raise ValueError('Choose an output directory outside the saved analysis tree.')
    import temflow
    assert Path(temflow.__file__).resolve().parent == ROOT / 'src/temflow', 'Wrong source imported'
    report = {'source_root': str(ROOT), 'version': temflow.__version__,
              'checked_at': datetime.datetime.now().isoformat(), 'python': sys.version,
              'stages': {}, 'status': 'running'}

    def save():
        (out / 'CHECK_SUMMARY.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    try:
        with (out / 'unit-tests.log').open('w', encoding='utf-8') as log:
            suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
        report['stages']['unit_tests'] = {'run': result.testsRun, 'skipped': len(result.skipped),
            'failures': len(result.failures), 'errors': len(result.errors), 'passed': result.wasSuccessful()}
        print('Unit tests:', report['stages']['unit_tests'], flush=True)
        if not result.wasSuccessful():
            raise RuntimeError('Unit tests failed; see unit-tests.log')
        from contextlib import redirect_stdout, redirect_stderr
        from temflow.validation import run_packaged_validation
        with (out / 'installed-checks.log').open('w', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
            status = run_packaged_validation()
        report['stages']['packaged_validation'] = {'exit_code': status}
        if status:
            raise RuntimeError('Packaged validation failed')
        commands = {
            'legacy-reproduction': [str(ROOT / 'analysis/python/reproduce_all.py'), '--output', str(out / 'legacy.json')],
            'structural-independent': [str(ROOT / 'analysis/structural/validate.py'), '--output-dir', str(out / 'structural')],
            'structural-expansion': [str(ROOT / 'analysis/structural/validate_structural_comparison.py'), '--output-dir', str(out / 'structural')],
            'cli-example': [str(ROOT / 'tools/source_cli.py'), 'structural', str(ROOT / 'docs/AGGREGATE_RECORD_EXAMPLE.csv'), '--output', str(out / 'structural/cli_example.json')],
            'saved-result-comparison': [str(ROOT / 'tools/compare_saved_results.py'), str(out)],
        }
        environment = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONDONTWRITEBYTECODE='1')
        for name, command in commands.items():
            with (out / (name + '.log')).open('w', encoding='utf-8') as log:
                checked = subprocess.run([sys.executable, '-B', *command], cwd=ROOT, env=environment,
                                         stdout=log, stderr=subprocess.STDOUT)
            report['stages'][name] = {'exit_code': checked.returncode}
            print(name, 'PASS' if checked.returncode == 0 else 'FAIL', flush=True)
            save()
            if checked.returncode:
                raise RuntimeError(name + ' failed; see its log')
        report['status'] = 'pass'
        print('All checks passed. Report:', out, flush=True)
        return 0
    except Exception as error:
        report['status'] = 'fail'
        report['error'] = str(error)
        print('Check failed:', error, '\nReport:', out, flush=True)
        return 1
    finally:
        save()


if __name__ == '__main__':
    raise SystemExit(main())
