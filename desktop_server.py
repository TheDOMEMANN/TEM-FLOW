"""Local desktop process, with a capability-protected graceful stop endpoint."""
import argparse
import json
from pathlib import Path
import secrets
import sys
import threading

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from temflow.private_engine import EngineHandler, EngineServer, PREVIEW_BUILD_ID, VERSION


class DesktopHandler(EngineHandler):
    def do_POST(self):
        if self.path == '/api/desktop/stop':
            provided = self.headers.get('X-TEMFLOW-Desktop', '')
            if not secrets.compare_digest(provided, self.server.desktop_secret):
                self._json(403, {'error': 'desktop controller capability required'})
                return
            self._json(200, {'stopping': True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        super().do_POST()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    settings_file = args.data_dir / 'desktop_settings.json'
    settings = json.loads(settings_file.read_text(encoding='utf-8')) if settings_file.exists() else {}
    if not settings.get('curator_token'):
        settings['curator_token'] = secrets.token_urlsafe(32)
        settings_file.write_text(json.dumps(settings, indent=2) + '\n', encoding='utf-8')
    server = EngineServer(('127.0.0.1', args.port), args.data_dir, settings.get('view_token'), settings.get('curator_token'))
    server.RequestHandlerClass = DesktopHandler
    server.desktop_secret = secrets.token_urlsafe(32)
    state_path = args.data_dir / 'desktop_state.json'
    info = {'url': f'http://127.0.0.1:{args.port}/', 'build_id': PREVIEW_BUILD_ID,
            'version': VERSION, 'source_root': str(ROOT), 'stop_capability': server.desktop_secret}
    state_path.write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if state_path.exists():
            recorded = json.loads(state_path.read_text(encoding='utf-8'))
            if recorded.get('stop_capability') == server.desktop_secret:
                state_path.unlink()


if __name__ == '__main__':
    main()
