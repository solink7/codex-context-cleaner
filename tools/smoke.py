#!/usr/bin/env python3
"""
[INPUT]: 当前系统的 ZIP 发布包，以及可选的缺环境安装场景。
[OUTPUT]: 解压、启动、清洗转发、重复启动、停止的系统级验收结果。
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


def commands(package, temporary, bootstrap):
    environment = os.environ.copy()
    environment['RELAY_HEADLESS'] = '1'
    label = None
    if sys.platform == 'darwin':
        label = 'local.codex-context-cleaner-test-' + uuid.uuid4().hex[:8]
        for name in ('启动代理.app', '停止代理.app'):
            script = package / name / 'Contents/MacOS/launcher'
            text = script.read_text(encoding='utf-8')
            text = text.replace('LABEL=local.relay-sanitizer', 'LABEL=' + label)
            text = text.replace('SERVICE="$HOME/Library/Application Support/Relay-Sanitizer"',
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
            text += '\nfunction Find-RelayPython([string]$PrivateExecutable) { return (Test-RelayPython $PrivateExecutable) }\n'
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
        try:
            subprocess.run(start, check=True, env=environment, timeout=420)
            first = health(port)
            assert first['service'] == 'relay-sanitizer'
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
            subprocess.run(stop, check=True, env=environment, timeout=30)
            try:
                health(port)
            except (OSError, http.client.HTTPException):
                pass
            else:
                raise AssertionError('停止后仍有代理响应')
            print('PASS: runtime, start, sanitization, auth, duplicate start, stop', flush=True)
        except Exception:
            for log in list(temporary.rglob('*.log')):
                print(log.name + ':\n' + log.read_text(encoding='utf-8', errors='replace')[-6000:])
            raise
        finally:
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
