"""Start or reuse the exact preview build; keep older processes untouched."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--no-browser", action="store_true")
parser.add_argument("--port", type=int, default=8765)
args = parser.parse_args()
spec = importlib.util.spec_from_file_location("preview_build", root / "src/temflow/preview_build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
expected = build.preview_build_id()

def metadata(url):
    try:
        with urllib.request.urlopen(url + "api/metadata", timeout=2) as response:
            return json.load(response)
    except Exception:
        return {}

for port in range(args.port, args.port + 20):
    url = f"http://127.0.0.1:{port}/"
    running = metadata(url).get("preview_build_id") == expected
    if running:
        break
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            continue
    break
else:
    raise SystemExit("No available local preview port in the requested range.")

state = Path(os.environ.get("TEMFLOW_PREVIEW_DATA_DIR", str(root.parent / ".temflow-preview-state")))
state.mkdir(parents=True, exist_ok=True)
if not running:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["PYTHONPYCACHEPREFIX"] = str(state / "pycache")
    command = [sys.executable, "-m", "temflow", "patterns-engine", "--no-browser", "--port", str(port), "--data-dir", str(state / "user_data")]
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
    with (state / f"server-{port}.log").open("ab") as log:
        proc = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True, creationflags=flags)
    (state / f"server-{port}.pid").write_text(str(proc.pid))
    for attempt in range(60):
        if metadata(url).get("preview_build_id") == expected:
            break
        if proc.poll() is not None:
            raise SystemExit(f"Preview stopped. Check {state / f'server-{port}.log'}")
        time.sleep(.5)
    else:
        raise SystemExit(f"Preview did not start. Check {state / f'server-{port}.log'}")
(state / "active-preview.json").write_text(json.dumps({"url": url, "preview_build_id": expected}, indent=2) + "\n")
if not args.no_browser:
    webbrowser.open(url)
print("TEM-FLOW preview available at " + url)
