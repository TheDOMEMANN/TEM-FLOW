"""Build a clean source or Windows desktop ZIP without local user records."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = {'src', 'tests', 'tools', 'analysis', '.github', 'docs', 'ledger', 'FORMULATION'}
SOURCE_FILES = {
    '.gitignore', '.gitattributes', 'GEOGRAPHIC_COVERAGE.csv', 'CHANGELOG.md', 'CITATION.cff', 'DEVELOPER_GUIDE.md',
    'DESKTOP_START_HERE.md', 'LICENSE', 'PUBLIC_DATA_BOUNDARY.md', 'README.md',
    'RELEASE_NOTES_1.0.0.md', 'desktop_launcher.py', 'desktop_server.py',
    'pyproject.toml', 'requirements-desktop.txt', 'requirements-lock.txt',
    'start_preview.py', 'STRUCTURAL_REVISION.json', 'DISTRIBUTION_MANIFEST.json',
    'EDITABLE_SOURCE_START_HERE.html', 'EDITABLE_SOURCE_START_HERE.txt',
    'Launch editable source.cmd', 'Restart editable source.cmd',
    'Stop editable source.cmd', 'Check editable source.cmd',
}
LAUNCHER_FILES = {
    'Create desktop shortcut.vbs', 'Edit source.cmd', 'Launch TEM-FLOW.cmd',
    'Launch TEM-FLOW.vbs', 'Restart TEM-FLOW.cmd', 'Run checks.cmd',
    'Stop TEM-FLOW.cmd',
}
EXCLUDED_PARTS = {'__pycache__', '.git', 'user_data', 'PRIVATE_EDITOR_DATA', '.version_backups', 'dist', 'build'}


def release_files(desktop=False):
    result = []
    for path in ROOT.rglob('*'):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_PARTS or part.startswith('user_data') or part.endswith('.egg-info') for part in relative.parts):
            continue
        if path.suffix in {'.pyc', '.log', '.lnk'} or path.name == 'atlas_evidence_ledger.csv':
            continue
        if relative.parts[0] in SOURCE_DIRS or (desktop and relative.parts[0] == 'runtime'):
            result.append(path)
        elif len(relative.parts) == 1 and (path.name in SOURCE_FILES or path.name in LAUNCHER_FILES):
            result.append(path)
    return sorted(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--revision', default='', help='Optional archive label; does not change the software version.')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    parser.add_argument('--desktop', action='store_true')
    parser.add_argument('--skip-checks', action='store_true', help='Use only if the identical source/runtime has already passed tools/check.py.')
    args = parser.parse_args()
    if args.revision and not all(c.isascii() and (c.isalnum() or c in '-_') for c in args.revision):
        parser.error('Use letters, numbers, hyphens or underscores for the revision label.')
    if args.desktop and not (ROOT / 'runtime/python.exe').exists():
        raise SystemExit('Desktop runtime missing. Run tools/build_desktop_runtime.py from a full Python installation.')
    if not args.skip_checks:
        subprocess.run([sys.executable, '-B', str(ROOT / 'tools/check.py')], cwd=ROOT, check=True)
    spec = importlib.util.spec_from_file_location('release_version', ROOT / 'src/temflow/_version.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    version = module.VERSION
    destination = args.output_dir
    destination.mkdir(parents=True, exist_ok=True)
    suffix = '-' + args.revision if args.revision else ''
    archive = destination / f'TEM-FLOW-{version}-{"Windows-desktop" if args.desktop else "source"}{suffix}.zip'
    if archive.exists():
        raise SystemExit(f'{archive.name} already exists. Preserve that archive; use a distinct --revision label or --output-dir for another build.')
    files = release_files(args.desktop)
    # Recompute source checksums for the files being released after user edits.
    # Preserve the old manifest on disk as evidence of the downloaded revision.
    distribution = json.loads((ROOT / 'DISTRIBUTION_MANIFEST.json').read_text(encoding='utf-8'))
    distribution['files'] = [{'path': p.relative_to(ROOT).as_posix(), 'bytes': p.stat().st_size,
                              'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                             for p in files if p.name != 'DISTRIBUTION_MANIFEST.json'
                             and p.relative_to(ROOT).parts[0] != 'runtime']
    distribution['file_count'] = len(distribution['files'])
    distribution_bytes = (json.dumps(distribution, indent=2) + '\n').encode('utf-8')
    manifest = {'version': version, 'kind': 'Windows-desktop' if args.desktop else 'source',
                'revision': args.revision,
                'files': [{'path': path.relative_to(ROOT).as_posix(),
                           'sha256': hashlib.sha256(distribution_bytes if path.name == 'DISTRIBUTION_MANIFEST.json' else path.read_bytes()).hexdigest()} for path in files]}
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as handle:
        for path in files:
            if path.name == 'DISTRIBUTION_MANIFEST.json':
                handle.writestr('DISTRIBUTION_MANIFEST.json', distribution_bytes)
            else:
                handle.write(path, path.relative_to(ROOT))
        handle.writestr('RELEASE_MANIFEST.json', json.dumps(manifest, indent=2) + '\n')
    print(archive)
    print('SHA256 ' + hashlib.sha256(archive.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
