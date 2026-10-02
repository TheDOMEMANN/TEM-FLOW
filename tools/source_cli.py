"""Run the CLI from this editable source, even with a borrowed embedded Python."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

if __name__ == '__main__':
    from temflow.__main__ import main
    raise SystemExit(main())
