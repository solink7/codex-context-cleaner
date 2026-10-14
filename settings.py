#!/usr/bin/env python3
"""
[INPUT]: control.ServiceController、本机 UI 资源、TCP 监听与系统浏览器。
[OUTPUT]: 独立回环端口的设置页、认证后的配置与启停接口。
[POS]: 本机设置入口；不依赖 DNS，监听就绪后原子发布会话记录。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
import argparse
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import signal
from socketserver import TCPServer
import subprocess
import sys
import threading
from urllib.parse import urlsplit
import webbrowser

# 隔离模式不加入脚本目录；仅添加应用随包携带的受信源码目录。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from control import ServiceController

ASSETS = Path(__file__).resolve().parent / 'ui'
MAX_SETTINGS_BODY = 16 * 1024


class SettingsServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # 已固定回环地址；避免 DNS 反查拖慢离线启动和 CI 就绪检查。
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address

    def __init__(self, controller, assets=ASSETS):
        super().__init__(('127.0.0.1', 0), SettingsHandler)
        self.controller = controller
        self.assets = Path(assets)
        self.token = secrets.token_urlsafe(32)
        self.origin = f'http://127.0.0.1:{self.server_port}'
        self.url = self.origin + '/#' + self.token


class SettingsHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def respond(self, code, body, content_type='application/json; charset=utf-8'):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def allowed(self, authenticated=False):
        # 校验 Host 防止 DNS 重绑定；所有配置接口同时验证会话令牌与来源。
        host = f'127.0.0.1:{self.server.server_port}'
        if self.client_address[0] != '127.0.0.1' or self.headers.get_all('Host') != [host]:
            self.respond(403, {'error': '此设置页只允许从本机打开。'})
            return False
        origin = self.headers.get('Origin')
        if origin is not None and origin != self.server.origin:
            self.respond(403, {'error': '不接受其他网页的设置请求。'})
            return False
        supplied = self.headers.get('X-Settings-Token', '').encode('utf-8')
        if authenticated and not secrets.compare_digest(supplied, self.server.token.encode('utf-8')):
            self.respond(403, {'error': '设置页面已失效，请重新打开“设置代理”。'})
            return False
        return True

    def do_GET(self):
        if not self.allowed():
            return
        path = urlsplit(self.path).path
        if path == '/api/session':
            if self.allowed(authenticated=True):
                self.respond(200, {'service': 'codex-context-cleaner.settings', 'pid': os.getpid()})
            return
        if path == '/api/state':
            if self.allowed(authenticated=True):
                self.respond(200, {**self.server.controller.snapshot(), 'service': 'codex-context-cleaner.settings', 'pid': os.getpid()})
            return
        files = {'/': ('index.html', 'text/html; charset=utf-8'),
                 '/settings.css': ('settings.css', 'text/css; charset=utf-8'),
                 '/settings.js': ('settings.js', 'text/javascript; charset=utf-8')}
        if path not in files:
            self.respond(404, {'error': '页面不存在。'})
            return
        name, mime = files[path]
        try:
            self.respond(200, (self.server.assets / name).read_bytes(), mime)
        except OSError:
            self.respond(500, {'error': '界面文件不完整，请重新解压工具。'})

    def do_POST(self):
        if not self.allowed(authenticated=True):
            return
        try:
            if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Encoding', 'identity') != 'identity':
                raise ValueError('设置请求格式无效。')
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) != 1 or not 0 < int(lengths[0]) <= MAX_SETTINGS_BODY:
                raise ValueError('设置请求大小无效。')
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError('设置请求必须使用 JSON。')
            data = json.loads(self.rfile.read(int(lengths[0])))
            path = urlsplit(self.path).path
            if path == '/api/config':
                result = self.server.controller.apply(data)
            elif path in ('/api/start', '/api/stop') and data == {}:
                result = getattr(self.server.controller, path[5:])()
            else:
                self.respond(404, {'error': '操作不存在。'})
                return
            self.respond(200, result)
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            self.respond(400, {'error': str(error)})


def acquire_lock(path):
    stream = path.open('a+b')
    try:
        if sys.platform == 'win32':
            import msvcrt
            stream.seek(0)
            if not stream.read(1):
                stream.write(b'\0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return stream
    except OSError:
        stream.close()
        return None


def reopen_existing(path, open_browser=True):
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
        url = urlsplit(state['url'])
        if url.scheme != 'http' or url.hostname != '127.0.0.1':
            return False
        connection = http.client.HTTPConnection('127.0.0.1', url.port, timeout=2)
        try:
            connection.request('GET', '/api/session', headers={'X-Settings-Token': url.fragment})
            response = connection.getresponse()
            actual = json.loads(response.read(65536))
            if response.status != 200 or actual.get('service') != 'codex-context-cleaner.settings' or actual.get('pid') != state['pid']:
                return False
        finally:
            connection.close()
        if open_browser:
            webbrowser.open(state['url'])
        return True
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
        return False


def main():
    parser = argparse.ArgumentParser(description='打开本机代理设置')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--state-dir', type=Path)
    parser.add_argument('--service-dir', type=Path)
    parser.add_argument('--service-label', default='local.codex-context-cleaner')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--check-running', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    controller = ServiceController(args.root, args.config, args.service_dir, args.service_label)
    folder = args.state_dir or (controller.service_dir if sys.platform == 'darwin' else args.root / '.runtime')
    folder.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(str(args.root.resolve()).encode()).hexdigest()[:12]
    state_file = folder / f'settings-{key}.json'
    if args.check_running:
        raise SystemExit(0 if reopen_existing(state_file, open_browser=False) else 1)
    lock = acquire_lock(folder / f'settings-{key}.lock')
    if lock is None:
        if not reopen_existing(state_file, not args.no_browser):
            raise SystemExit('设置正在打开，请稍后重新打开。')
        return
    server = None
    try:
        server = SettingsServer(controller)
        # 先开始监听，再交给浏览器；关闭浏览器不会停止代理。
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        staging = state_file.with_suffix('.tmp')
        staging.write_text(json.dumps({'url': server.url, 'pid': os.getpid()}), encoding='utf-8')
        staging.chmod(0o600)
        staging.replace(state_file)
        if not args.no_browser:
            webbrowser.open(server.url)
        print('设置页面：' + server.url, flush=True)
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        worker.join()
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            server.shutdown()
            server.server_close()
        state_file.unlink(missing_ok=True)
        lock.close()


if __name__ == '__main__':
    main()
