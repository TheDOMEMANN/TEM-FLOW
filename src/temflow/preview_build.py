"""Identify the exact local preview code and frozen input files."""
import hashlib
from pathlib import Path

def preview_build_id():
    package = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    files = sorted([*package.glob("*.py"), *package.glob("data/**/*.json"), *package.glob("data/**/*.geojson"), *package.glob("data/**/*.csv"), *package.glob("data/*.html")])
    for path in files:
        digest.update(path.relative_to(package).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    for path in sorted(package.parents[1].glob("desktop_*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()
