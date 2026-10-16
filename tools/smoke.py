#!/usr/bin/env python3
"""
[INPUT]: 当前系统 ZIP、真实设置入口与禁用外部环境发现的安装场景。
[OUTPUT]: 覆盖下载时限的设置入口、鉴权、端口切换与启停验收。
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
import signal
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


def start_settings(package, temporary, environment, label, quarantine=False, bootstrap=False):
    if sys.platform == 'darwin':
        script = package / '设置代理.app/Contents/MacOS/launcher'
        text = script.read_text(encoding='utf-8')
        text = text.replace('SERVICE="$HOME/Library/Application Support/codex-context-cleaner"',
                            'SERVICE="' + str(temporary / 'service') + '"')
        text = text.replace('RUNTIME_ROOT="$HOME/Library/Application Support/codex-context-cleaner"',
                            'RUNTIME_ROOT="' + str(temporary / 'service') + '"')
        text = text.replace('--root "$ROOT"', '--root "$ROOT" --service-dir "' +
                            str(temporary / 'service') + '" --service-label ' + label)
        if bootstrap:
            text = text.replace('source "$RUNTIME" || exit 1',
                                'source "$RUNTIME" || exit 1\npython_candidates() { return 0; }')
        script.write_text(text, encoding='utf-8')
        command = ['/bin/zsh', str(script)]
        state_dir = temporary / 'service'
        if quarantine:
            application = script.parents[2]
            marker = f'00c1;{int(time.time()):x};CleanerRegression;{uuid.uuid4()}'
            subprocess.run(['/usr/bin/xattr', '-w', 'com.apple.quarantine', marker, str(application)], check=True)
            command = ['/usr/bin/open', '-n', '-W', '--env', 'CODEX_CONTEXT_CLEANER_HEADLESS=1', str(application)]
    else:
        script = package / 'platform/windows/settings.ps1'
        text = script.read_text(encoding='utf-8-sig')
        text = re.sub(r'^    \$runtimeRoot = .*$',
                      lambda _: '    $runtimeRoot = ' + powershell_quote(temporary / 'python-runtime'),
                      text, flags=re.M)
        script.write_bytes(b'\xef\xbb\xbf' + text.replace('\n', '\r\n').encode('utf-8'))
        command = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive',
                   '-ExecutionPolicy', 'Bypass', '-File', str(script)]
        state_dir = package / '.runtime'
    # 首次安装允许下载 30 分钟；预检、解压和服务就绪另留余量。
    subprocess.run(command, env=environment, check=True, timeout=1860 if bootstrap else 60)
    if quarantine and '/AppTranslocation/' not in (state_dir / 'settings-launcher.log').read_text(encoding='utf-8'):
        raise AssertionError('未进入真实 Mac 下载隔离路径')
    records = list(state_dir.glob('settings-*.json'))
    if len(records) != 1:
        raise AssertionError('设置入口未生成唯一会话记录')
    record = json.loads(records[0].read_text(encoding='utf-8'))
    status, session = settings_request(record['url'], '/api/session')
    if status != 200 or session.get('pid') != record['pid']:
        raise AssertionError('设置入口未启动可用服务')
    target = urlsplit(record['url'])
    connection = http.client.HTTPConnection(target.hostname, target.port, timeout=3)
    try:
        for path in ('/', '/settings.js', '/settings.css'):
            connection.request('GET', path)
            response = connection.getresponse()
            if response.status != 200 or not response.read():
                raise AssertionError('设置资源不可用：' + path)
    finally:
        connection.close()
    return record['pid'], record['url'], command


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
                text = text.replace('MAC_VERSION=$(', 'python_candidates() { return 0; }\nMAC_VERSION=$(')
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


def run(archive, bootstrap=False, quarantine=False):
    if quarantine and sys.platform != 'darwin':
        raise ValueError('下载隔离验收只支持 macOS')
    with tempfile.TemporaryDirectory(prefix="cleaner 验收 '路径'-") as name:
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
        start, stop, environment, label = commands(package, temporary, bootstrap)
        settings_process = None
        try:
            # 首次使用先打开空配置设置页；从页面保存后才启动代理。
            settings_process, settings_url, settings_command = start_settings(
                package, temporary, environment, label, quarantine, bootstrap)
            assert settings_request(settings_url, '/api/state', authenticated=False)[0] == 403
            status, state = settings_request(settings_url, '/api/state')
            assert status == 200 and not state['status']['running']
            assert state['config']['upstream_base_url'] == ''
            status, state = settings_request(settings_url, '/api/config', config)
            assert status == 200 and state['config'] == config, state
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
            status, state = settings_request(settings_url, '/api/state')
            assert status == 200 and state['status']['healthy'] and state['status']['port'] == port
            subprocess.run(settings_command, check=True, env=environment, timeout=5, stdout=subprocess.DEVNULL)
            assert settings_request(settings_url, '/api/session')[1]['pid'] == settings_process
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
                os.kill(settings_process, signal.SIGTERM)
                deadline = time.monotonic() + 5
                while list((temporary / 'service' if label else package / '.runtime').glob('settings-*.json')) and time.monotonic() < deadline:
                    time.sleep(.1)
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
    parser.add_argument('--quarantine', action='store_true', help='Mac 使用下载标记和 Launch Services 验证真实隔离启动')
    args = parser.parse_args()
    run(args.archive, args.bootstrap, args.quarantine)


if __name__ == '__main__':
    main()
