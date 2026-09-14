"""Rebuild the pinned portable runtime from official Python and PyPI files."""
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = '3.13.15'
PYTHON_SHA256 = 'd1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf'
DEPENDENCIES = {'numpy': '2.5.1', 'scipy': '1.18.0'}


def download(url, expected, folder):
    destination = folder / url.rsplit('/', 1)[-1]
    if not destination.exists():
        with urllib.request.urlopen(url, timeout=60) as response, destination.open('wb') as handle:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
        raise ValueError(f'Checksum mismatch: {destination.name}')
    return destination


def build():
    runtime = ROOT / 'runtime'
    if runtime.exists():
        raise SystemExit('runtime already exists. Build a new runtime in a fresh source copy so the working runtime is preserved.')
    cache = ROOT / 'build/runtime_downloads'
    cache.mkdir(parents=True, exist_ok=True)
    url = f'https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip'
    python_zip = download(url, PYTHON_SHA256, cache)
    with zipfile.ZipFile(python_zip) as handle:
        handle.extractall(runtime)
    records = [{'file': python_zip.name, 'url': url, 'sha256': PYTHON_SHA256}]
    for package, version in DEPENDENCIES.items():
        with urllib.request.urlopen(f'https://pypi.org/pypi/{package}/{version}/json', timeout=60) as response:
            metadata = json.load(response)
        wheel = next(item for item in metadata['urls'] if 'cp313-cp313-win_amd64.whl' in item['filename'])
        source = download(wheel['url'], wheel['digests']['sha256'], cache)
        with zipfile.ZipFile(source) as handle:
            handle.extractall(runtime / 'Lib/site-packages')
        records.append({'file': source.name, 'url': wheel['url'], 'sha256': wheel['digests']['sha256']})
    (runtime / 'python313._pth').write_text('python313.zip\n.\n..\n../src\nLib/site-packages\nimport site\n', encoding='utf-8')
    (runtime / 'RUNTIME_MANIFEST.json').write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')
    print('Portable runtime built. Run checks with runtime/python.exe tools/check.py.')


if __name__ == '__main__':
    build()
