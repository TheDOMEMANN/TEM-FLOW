"""Launch the editable local application with its bundled Python runtime."""
import argparse
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import traceback
from urllib.request import Request, urlopen
from urllib.parse import quote
import webbrowser

ROOT = Path(__file__).resolve().parent


def request_json(url, payload=None, token=None):
    headers = {} if token is None else {'X-TEMFLOW-Desktop': token}
    request = Request(url, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
    with urlopen(request, timeout=3) as response:
        return json.load(response)


def healthy(info):
    # The health endpoint remains accessible even when optional view tokens are set.
    try:
        return request_json(info['url'] + 'api/health').get('status') == 'ok'
    except Exception:
        return False


def stop(info):
    request_json(info['url'] + 'api/desktop/stop', {}, info['stop_capability'])
    for _ in range(40):
        if not healthy(info):
            return
        time.sleep(.1)
    raise RuntimeError('The previous desktop process has not stopped. Retry after it finishes active requests.')


def open_window(url, data_dir):
    settings = json.loads((data_dir / 'desktop_settings.json').read_text(encoding='utf-8'))
    url += '#curator=' + quote(settings['curator_token'], safe='')
    # Edge app mode gives the local browser interface its own desktop window.
    roots = [os.environ.get('ProgramFiles(x86)', ''), os.environ.get('ProgramFiles', '')]
    edge = next((Path(base) / 'Microsoft/Edge/Application/msedge.exe' for base in roots
                 if base and (Path(base) / 'Microsoft/Edge/Application/msedge.exe').is_file()), None)
    if edge:
        subprocess.Popen([str(edge), '--app=' + url, '--user-data-dir=' + str(data_dir / 'browser_profile')],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(url)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--restart', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=8780)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'user_data')
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    state_path = data_dir / 'desktop_state.json'
    info = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else None
    spec = importlib.util.spec_from_file_location('temflow_preview_build', ROOT / 'src/temflow/preview_build.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected = module.preview_build_id()
    if info and healthy(info):
        if args.stop or args.restart or info.get('build_id') != expected or info.get('source_root') != str(ROOT):
            stop(info)
            info = None
        else:
            if not args.no_browser:
                open_window(info['url'], data_dir)
            if sys.stdout:
                print(info['url'])
            return 0
    if args.stop:
        return 0
    for port in range(args.port, args.port + 30):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
                break
            except OSError:
                continue
    else:
        raise RuntimeError('No local desktop port is available.')
    runtime = ROOT / 'runtime/pythonw.exe'
    executable = str(runtime) if runtime.exists() else sys.executable
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    with (data_dir / 'desktop-server.log').open('ab') as log:
        process = subprocess.Popen([executable, '-B', str(ROOT / 'desktop_server.py'), '--port', str(port), '--data-dir', str(data_dir)],
                                   cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   creationflags=flags, close_fds=True)
    for _ in range(100):
        if state_path.exists():
            info = json.loads(state_path.read_text(encoding='utf-8'))
            if info.get('build_id') == expected and info.get('source_root') == str(ROOT) and healthy(info):
                break
        if process.poll() is not None:
            raise RuntimeError('The engine could not start. See user_data/desktop-server.log.')
        time.sleep(.2)
    else:
        raise RuntimeError('The engine did not become ready. See user_data/desktop-server.log.')
    if not args.no_browser:
        open_window(info['url'], data_dir)
    if sys.stdout:
        print(info['url'])
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        (ROOT / 'desktop-launch-error.log').write_text(traceback.format_exc(), encoding='utf-8')
        if os.name == 'nt' and '--no-browser' not in sys.argv:
            ctypes.windll.user32.MessageBoxW(None, str(error) + '\nSee desktop-launch-error.log for details.', 'TEM-FLOW could not launch', 0x10)
        else:
            raise
