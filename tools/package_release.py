"""Build a checked source or Windows archive without local or private records."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = {'src', 'tests', 'tools', 'analysis', '.github', 'docs', 'ledger', 'FORMULATION', 'Reproduce_Analyses'}
SOURCE_FILES = {
    '.gitignore', '.gitattributes', 'GEOGRAPHIC_COVERAGE.csv', 'CHANGELOG.md', 'CITATION.cff',
    'DEVELOPER_GUIDE.md', 'DESKTOP_START_HERE.md', 'LICENSE', 'PUBLIC_DATA_BOUNDARY.md', 'README.md',
    'RELEASE_NOTES_1.0.0.md', 'desktop_launcher.py', 'desktop_server.py', 'pyproject.toml',
    'requirements-desktop.txt', 'requirements-lock.txt', 'start_preview.py', 'STRUCTURAL_REVISION.json',
    'CURRENT_REVISION.json', 'CURRENT_REVISION.txt', 'SOURCE_MANIFEST.json', 'DISTRIBUTION_MANIFEST.json',
    'EDITABLE_SOURCE_START_HERE.html', 'EDITABLE_SOURCE_START_HERE.txt', 'Launch editable source.cmd',
    'Restart editable source.cmd', 'Stop editable source.cmd', 'Check editable source.cmd',
}
LAUNCHER_FILES = {
    'Create desktop shortcut.vbs', 'Edit source.cmd', 'Launch TEM-FLOW.cmd', 'Launch TEM-FLOW.vbs',
    'Restart TEM-FLOW.cmd', 'Run checks.cmd', 'Stop TEM-FLOW.cmd',
}
EXCLUDED_PARTS = {
    '__pycache__', '.git', '.venv', 'node_modules', 'private_editor_data', 'private_review',
    '.version_backups', 'dist', 'build', 'fresh_runs', 'rollback', 'history', 'credentials',
}
ANALYSIS_DIRS = {'code', 'inputs', 'recorded_results', 'generated_figures'}
ANALYSIS_FILES = {
    'INPUT_HASHES.json', 'MANIFEST.json', 'PROTOCOL.json', 'PROTOCOL_AMENDMENT.txt', 'README.txt',
    'Repeat analyses.cmd', 'repeat_analyses.py', 'requirements-figures.txt',
    'requirements-recorded.txt', 'requirements.txt',
}
GENERATED_MANIFESTS = {'SOURCE_MANIFEST.json', 'DISTRIBUTION_MANIFEST.json', 'RELEASE_MANIFEST.json'}


def safe_file(path, relative):
    parts = [part.lower() for part in relative.parts]
    return (not path.is_symlink()
            and not any(p in EXCLUDED_PARTS or p.startswith('user_data') or p.endswith('.egg-info') for p in parts)
            and path.suffix.lower() not in {'.pyc', '.log', '.lnk'}
            and path.name.lower() not in {'atlas_evidence_ledger.csv', '.env'})


def analysis_allowed(relative):
    return relative.parts[0] in ANALYSIS_DIRS or (len(relative.parts) == 1 and relative.name in ANALYSIS_FILES)


def release_files(desktop=False):
    """Return eligible files contained in the source root (legacy public API)."""
    result = []
    for path in ROOT.rglob('*'):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if not safe_file(path, relative):
            continue
        first = relative.parts[0]
        if first == 'Reproduce_Analyses' and not analysis_allowed(Path(*relative.parts[1:])):
            continue
        if first in SOURCE_DIRS or (desktop and first == 'runtime'):
            result.append(path)
        elif len(relative.parts) == 1 and (path.name in SOURCE_FILES or path.name in LAUNCHER_FILES):
            result.append(path)
    return sorted(result)


def release_entries(desktop=False):
    """Also support the user/journal layout with analyses beside the source."""
    entries = {p.relative_to(ROOT).as_posix(): p for p in release_files(desktop)}
    if not (ROOT / 'Reproduce_Analyses').is_dir():
        for candidate in [ROOT.parent / 'Reproduce_Analyses', ROOT.parent / 'Analyses']:
            if not candidate.is_dir():
                continue
            for path in candidate.rglob('*'):
                if not path.is_file():
                    continue
                relative = path.relative_to(candidate)
                if safe_file(path, relative) and analysis_allowed(relative):
                    entries['Reproduce_Analyses/' + relative.as_posix()] = path
            break
    return dict(sorted(entries.items()))


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', default='', help='Dated archive label; the software version is unchanged.')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    parser.add_argument('--desktop', action='store_true')
    parser.add_argument('--skip-checks', action='store_true', help='Only for identical source/runtime already checked with tools/check.py.')
    args = parser.parse_args()
    if args.revision and not all(c.isascii() and (c.isalnum() or c in '-_') for c in args.revision):
        parser.error('Use letters, numbers, hyphens or underscores in the revision label.')
    if args.desktop and not (ROOT / 'runtime/python.exe').is_file():
        raise SystemExit('Desktop runtime missing. Run tools/build_desktop_runtime.py first.')
    if not args.skip_checks:
        subprocess.run([sys.executable, '-B', str(ROOT / 'tools/check.py')], cwd=ROOT, check=True)
    spec = importlib.util.spec_from_file_location('release_version', ROOT / 'src/temflow/_version.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    version = module.VERSION
    args.output_dir.mkdir(parents=True, exist_ok=True)
    suffix = '-' + args.revision if args.revision else ''
    archive = args.output_dir / f'TEM-FLOW-{version}-{"Windows-desktop" if args.desktop else "source"}{suffix}.zip'
    if archive.exists():
        raise SystemExit('Archive exists; choose another revision or output directory. Existing archives are preserved.')
    entries = release_entries(args.desktop)
    # Generate current manifests from exact delivered bytes. A missing old
    # distribution manifest is not an error, and historical manifests are not
    # silently promoted to current evidence.
    payload = {name: path.read_bytes() for name, path in entries.items() if name not in GENERATED_MANIFESTS}
    source_hashes = {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()
                     if not name.startswith('runtime/')}
    payload['SOURCE_MANIFEST.json'] = json_bytes({'version': version, 'revision': args.revision,
        'scope': 'All source and analysis files; generated distribution/release manifests and runtime excluded.',
        'files': source_hashes})
    rows = [{'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            for name, data in sorted(payload.items()) if not name.startswith('runtime/')]
    payload['DISTRIBUTION_MANIFEST.json'] = json_bytes({'version': version, 'revision': args.revision,
        'file_count': len(rows), 'files': rows})
    release = {'version': version, 'kind': 'Windows-desktop' if args.desktop else 'source',
        'revision': args.revision,
        'files': [{'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                  for name, data in sorted(payload.items())]}
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as handle:
        for name, data in sorted(payload.items()):
            handle.writestr(name, data)
        handle.writestr('RELEASE_MANIFEST.json', json_bytes(release))
    print(archive)
    print('SHA256 ' + hashlib.sha256(archive.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
