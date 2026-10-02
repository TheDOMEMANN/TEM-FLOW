"""Compare a fresh check run with saved results; report every numerical change."""
from pathlib import Path
import argparse
import json
import math

ROOT = Path(__file__).resolve().parents[1]
METADATA = {'seconds', 'tree_seconds', 'prototype_seconds', 'python', 'numpy', 'scipy', 'date'}


def compare(expected, actual, path='', changes=None):
    changes = [] if changes is None else changes
    if isinstance(expected, dict) and isinstance(actual, dict):
        a, b = set(expected) - METADATA, set(actual) - METADATA
        if a != b:
            changes.append(path + ': fields differ')
        for key in sorted(a & b):
            compare(expected[key], actual[key], path + '/' + key, changes)
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            changes.append(path + ': lengths differ')
        for i, (a, b) in enumerate(zip(expected, actual)):
            compare(a, b, path + '/' + str(i), changes)
    elif isinstance(expected, (float, int)) and not isinstance(expected, bool) and isinstance(actual, (float, int)) and not isinstance(actual, bool):
        if not math.isclose(expected, actual, rel_tol=1e-10, abs_tol=1e-10):
            changes.append(f'{path}: {expected!r} != {actual!r}')
    elif expected != actual:
        changes.append(f'{path}: values differ')
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_directory', type=Path)
    args = parser.parse_args()
    pairs = [(ROOT / 'analysis/results/REPRODUCTION_REPORT_STRUCTURAL_REVISION.json', args.run_directory / 'legacy.json')]
    pairs += [(p, args.run_directory / 'structural' / p.name) for p in sorted((ROOT / 'analysis/structural/results').glob('*.json'))]
    report = {'status': 'pass', 'absolute_tolerance': 1e-10, 'relative_tolerance': 1e-10,
              'excluded_metadata_fields': sorted(METADATA), 'files': []}
    for saved, fresh in pairs:
        row = {'saved': saved.relative_to(ROOT).as_posix(), 'new': str(fresh)}
        if not fresh.exists():
            row['changes'] = ['New result file missing']
        else:
            left = json.loads(saved.read_text(encoding='utf-8'))
            right = json.loads(fresh.read_text(encoding='utf-8'))
            row['changes'] = compare(left, right)
            row['exact_json_match'] = left == right
        if row['changes']:
            report['status'] = 'fail'
        report['files'].append(row)
    (args.run_directory / 'SAVED_RESULT_COMPARISON.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
