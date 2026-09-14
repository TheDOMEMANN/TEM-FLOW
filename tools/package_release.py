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
SOURCE_DIRS = {'src', 'tests', 'tools', 'analysis', '.github', 'docs', 'ledger'}
SOURCE_FILES = {
    '.gitignore', 'CHANGELOG.md', 'CITATION.cff', 'DEVELOPER_GUIDE.md',
    'DESKTOP_START_HERE.md', 'LICENSE', 'PUBLIC_DATA_BOUNDARY.md', 'README.md',
    'RELEASE_NOTES_1.0.0.md', 'desktop_launcher.py', 'desktop_server.py',
    'pyproject.toml', 'requirements-desktop.txt', 'requirements-lock.txt',
    'start_preview.py',
}
DESKTOP_ONLY_FILES = {
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
        elif len(relative.parts) == 1 and (path.name in SOURCE_FILES or (desktop and path.name in DESKTOP_ONLY_FILES)):
            result.append(path)
    return sorted(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--desktop', action='store_true')
    parser.add_argument('--skip-checks', action='store_true', help='Use only if the identical source/runtime has already passed tools/check.py.')
    args = parser.parse_args()
    if args.desktop and not (ROOT / 'runtime/python.exe').exists():
        raise SystemExit('Desktop runtime missing. Run tools/build_desktop_runtime.py from a full Python installation.')
    if not args.skip_checks:
        subprocess.run([sys.executable, '-B', str(ROOT / 'tools/check.py')], cwd=ROOT, check=True)
    spec = importlib.util.spec_from_file_location('release_version', ROOT / 'src/temflow/_version.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    version = module.VERSION
    destination = ROOT / 'dist'
    destination.mkdir(exist_ok=True)
    archive = destination / f'TEM-FLOW-{version}-{"Windows-desktop" if args.desktop else "source"}.zip'
    if archive.exists():
        raise SystemExit(f'{archive.name} already exists. Preserve that release and choose a new version before building another.')
    files = release_files(args.desktop)
    manifest = {'version': version, 'kind': 'Windows-desktop' if args.desktop else 'source',
                'files': [{'path': path.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in files]}
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as handle:
        for path in files:
            handle.write(path, path.relative_to(ROOT))
        handle.writestr('RELEASE_MANIFEST.json', json.dumps(manifest, indent=2) + '\n')
    print(archive)
    print('SHA256 ' + hashlib.sha256(archive.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
