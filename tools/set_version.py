"""Update the single version source and generated citation/UI release labels."""
import argparse
from datetime import datetime
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]

def set_version(version):
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise ValueError('Use a semantic version such as 1.0.1, 1.1.0 or 2.0.0.')
    files = [ROOT / 'src/temflow/_version.py', ROOT / 'CITATION.cff', ROOT / 'src/temflow/data/patterns_private_ui.html']
    backup = ROOT / '.version_backups' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    for path in files:
        target = backup / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    files[0].write_text(f'"""Single source of truth for the editable TEM-FLOW release version."""\nVERSION = "{version}"\n', encoding='utf-8')
    citation = re.sub(r'^version:.*$', f'version: {version}', files[1].read_text(encoding='utf-8'), flags=re.MULTILINE)
    files[1].write_text(citation, encoding='utf-8')
    ui = re.sub(r'>v[0-9]+\.[0-9]+\.[0-9]+</span>', f'>v{version}</span>', files[2].read_text(encoding='utf-8'), count=1)
    files[2].write_text(ui, encoding='utf-8')
    print(f'Version set to {version}. Backups: {backup}\nRun tools/check.py and record the changes in CHANGELOG.md before releasing.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('version')
    set_version(parser.parse_args().version)
