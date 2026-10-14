#!/usr/bin/env python3
"""
[INPUT]: 当前系统的 ZIP 发布包，以及可选的缺环境安装场景。
[OUTPUT]: 解压、清洗转发、设置鉴权、端口切换与启停的系统级验收。
[POS]: CI 发布闸门；使用临时端口、服务标签与目录，不碰用户运行记录。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import uuid
import zipfile
import time
from urllib.parse import urlsplit


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.received = (payload, self.headers.get('Authorization'))
        body = b'{"id":"smoke-response"}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def health(port):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
    try:
        connection.request('GET', '/health')
        response = connection.getresponse()
        if response.status != 200:
            raise AssertionError('代理健康检查失败')
        return json.loads(response.read())
    finally:
        connection.close()


def powershell_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def settings_request(url, path, payload=None, authenticated=True, timeout=30):
    target = urlsplit(url)
    connection = http.client.HTTPConnection(target.hostname, target.port, timeout=timeout)
    headers = {'Content-Type': 'application/json'}
    if authenticated:
        headers['X-Settings-Token'] = target.fragment
    try:
        connection.request('GET' if payload is None else 'POST', path,
                           None if payload is None else json.dumps(payload), headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def start_settings(package, temporary, environment, label):
    script = (package / '启动代理.app/Contents/Resources/settings.py'
              if sys.platform == 'darwin' else package / 'settings.py')
    state_dir = temporary / 'settings-state'
    command = [sys.executable, '-I', str(script), '--root', str(package),
               '--config', str(package / 'config.json'), '--state-dir', str(state_dir), '--no-browser']
    if label:
        command += ['--service-dir', str(temporary / 'service'), '--service-label', label]
    error_log = temporary / 'settings.stderr.log'
    with error_log.open('wb') as stream:
        process = subprocess.Popen(command, env=environment, stdout=subprocess.DEVNULL, stderr=stream)
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            records = list(state_dir.glob('settings-*.json'))
            if records:
                try:
                    record = json.loads(records[0].read_text(encoding='utf-8'))
                    status, session = settings_request(record['url'], '/api/session', timeout=1)
                    if status == 200 and session.get('pid') == process.pid:
                        return process, record['url'], command
                except (OSError, ValueError, http.client.HTTPException):
                    pass
            if process.poll() is not None:
                raise AssertionError('设置服务启动失败：' + error_log.read_text(encoding='utf-8', errors='replace'))
            time.sleep(.1)
        raise AssertionError('设置服务未在规定时间内启动')
    except Exception:
        process.terminate()
        process.wait(5)
        raise


def commands(package, temporary, bootstrap):
    environment = os.environ.copy()
    environment['CODEX_CONTEXT_CLEANER_HEADLESS'] = '1'
    label = None
    if sys.platform == 'darwin':
        label = 'local.codex-context-cleaner-test-' + uuid.uuid4().hex[:8]
        for name in ('启动代理.app', '停止代理.app'):
            legacy = package / name / 'Contents/MacOS/legacy.sh'
            legacy.write_text(legacy.read_text().replace('local.relay-sanitizer', label + '-previous'), encoding='utf-8')
            script = package / name / 'Contents/MacOS/launcher'
            text = script.read_text(encoding='utf-8')
            text = text.replace('LABEL=local.codex-context-cleaner', 'LABEL=' + label)
            text = text.replace('SERVICE="$HOME/Library/Application Support/codex-context-cleaner"',
                                'SERVICE="' + str(temporary / 'service') + '"')
            if bootstrap and name == '启动代理.app':
                text = re.sub(r'^PYTHON_CANDIDATES=.*$', 'PYTHON_CANDIDATES=()', text, flags=re.M)
                text = re.sub(r'^if /usr/bin/xcode-select.*$', '', text, flags=re.M)
            script.write_text(text, encoding='utf-8')
        start = ['/bin/zsh', str(package / '启动代理.app/Contents/MacOS/launcher')]
        stop = ['/bin/zsh', str(package / '停止代理.app/Contents/MacOS/launcher')]
    elif sys.platform == 'win32':
        scripts = package / 'platform/windows'
        start_script = scripts / 'start.ps1'
        text = start_script.read_text(encoding='utf-8-sig')
        text = re.sub(r'^    \$runtimeRoot = .*$',
                      lambda _: '    $runtimeRoot = ' + powershell_quote(temporary / 'python-runtime'),
                      text, flags=re.M)
        start_script.write_bytes(b'\xef\xbb\xbf' + text.replace('\n', '\r\n').encode('utf-8'))
        if bootstrap:
            runtime = scripts / 'runtime.ps1'
            text = runtime.read_text(encoding='utf-8-sig')
            text += '\nfunction Find-CleanerPython([string]$PrivateExecutable) { return (Test-CleanerPython $PrivateExecutable) }\n'
            runtime.write_bytes(b'\xef\xbb\xbf' + text.replace('\n', '\r\n').encode('utf-8'))
        prefix = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File']
        start, stop = prefix + [str(start_script)], prefix + [str(scripts / 'stop.ps1')]
    else:
        raise ValueError('系统验收只支持 macOS 和 Windows')
    return start, stop, environment, label


def run(archive, bootstrap=False):
    with tempfile.TemporaryDirectory(prefix='context-cleaner-smoke-') as name:
        temporary = Path(name).resolve()
        if sys.platform == 'darwin':
            subprocess.run(['/usr/bin/ditto', '-x', '-k', str(archive.resolve()), str(temporary)], check=True)
        else:
            with zipfile.ZipFile(archive) as package_zip:
                package_zip.extractall(temporary)
        folders = [path for path in temporary.iterdir() if path.is_dir()]
        if len(folders) != 1:
            raise AssertionError('压缩包必须包含一个产品目录')
        package = folders[0]
        config_file = package / 'config.json'
        config = json.loads(config_file.read_text(encoding='utf-8-sig'))
        port = free_port()
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        upstream.received = None
        server_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        server_thread.start()
        config.update(port=port, upstream_base_url=f'http://127.0.0.1:{upstream.server_port}/v1')
        config_file.write_text(json.dumps(config), encoding='utf-8')
        start, stop, environment, label = commands(package, temporary, bootstrap)
        settings_process = None
        try:
            subprocess.run(start, check=True, env=environment, timeout=420)
            first = health(port)
            assert first['service'] == 'codex-context-cleaner'
            client = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
            try:
                client.request('POST', '/v1/responses', json.dumps({'input': [
                    {'type': 'reasoning', 'id': 'remove', 'encrypted_content': 'test-only'},
                    {'role': 'user', 'id': 'remove', 'content': 'hello'}]}),
                    {'Authorization': 'Bearer smoke-test'})
                response = client.getresponse()
                assert response.status == 200
                assert json.loads(response.read())['id'] == 'smoke-response'
            finally:
                client.close()
            payload, authorization = upstream.received
            assert payload['input'] == [{'role': 'user', 'content': 'hello'}]
            assert authorization == 'Bearer smoke-test'
            subprocess.run(start, check=True, env=environment, timeout=30)
            assert health(port)['pid'] == first['pid']
            settings_process, settings_url, settings_command = start_settings(package, temporary, environment, label)
            assert settings_request(settings_url, '/api/state', authenticated=False)[0] == 403
            status, state = settings_request(settings_url, '/api/state')
            assert status == 200 and state['status']['healthy'] and state['status']['port'] == port
            subprocess.run(settings_command, check=True, env=environment, timeout=5, stdout=subprocess.DEVNULL)
            assert settings_request(settings_url, '/api/session')[1]['pid'] == settings_process.pid
            previous_port = port
            port = free_port()
            config['port'] = port
            status, state = settings_request(settings_url, '/api/config', config)
            assert status == 200 and state['status']['healthy'] and state['status']['port'] == port, state
            assert health(port)['pid'] != first['pid']
            try:
                health(previous_port)
            except (OSError, http.client.HTTPException):
                pass
            else:
                raise AssertionError('应用配置后旧端口仍在监听')
            assert settings_request(settings_url, '/api/stop', {})[0] == 200
            try:
                health(port)
            except (OSError, http.client.HTTPException):
                pass
            else:
                raise AssertionError('停止后仍有代理响应')
            print('PASS: runtime, sanitization, settings auth, singleton, port change, stop', flush=True)
        except Exception:
            for log in list(temporary.rglob('*.log')):
                print(log.name + ':\n' + log.read_text(encoding='utf-8', errors='replace')[-6000:])
            raise
        finally:
            if settings_process:
                settings_process.terminate()
                settings_process.wait(5)
            subprocess.run(stop, env=environment, timeout=30, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if label:
                subprocess.run(['/bin/launchctl', 'remove', label], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            upstream.shutdown()
            upstream.server_close()
            server_thread.join(3)


def main():
    parser = argparse.ArgumentParser(description='验证发布包在本机的完整启停链路')
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--bootstrap', action='store_true', help='模拟缺少环境，真实下载并安装专用 Python')
    args = parser.parse_args()
    run(args.archive, args.bootstrap)


if __name__ == '__main__':
    main()
