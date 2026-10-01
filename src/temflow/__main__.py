from __future__ import annotations

import argparse

from .dashboard import dashboard_parser, serve
from .private_engine import private_engine_parser, serve_private_engine
from .validation import run_packaged_validation


def main() -> int:
    parser = argparse.ArgumentParser(prog="temflow", description="TEM-FLOW typed evidential measure-flow engine")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="run installed-package validation checks")
    dashboard_parser(subparsers)
    private_engine_parser(subparsers)
    structural = subparsers.add_parser("structural", help="calculate ranges and missing-record uncertainty from aggregate CSV or JSON")
    structural.add_argument("input")
    structural.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "structural":
        import json
        from pathlib import Path
        from .structural import load_structural_file, run_structural_payload
        try:
            result = run_structural_payload(load_structural_file(args.input))
            Path(args.output).write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
        return 0
    if args.command == "validate":
        return run_packaged_validation()
    if args.command == "dashboard":
        return serve(args.host, args.port, not args.no_browser)
    if args.command == "patterns-engine":
        return serve_private_engine(args.host, args.port, args.data_dir, open_browser=not args.no_browser)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

