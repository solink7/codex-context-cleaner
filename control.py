"""
[INPUT]: sanitizer 的配置校验、平台启停入口与本机健康响应。
[OUTPUT]: ServiceController 配置读写、状态核验与启停操作。
[POS]: 设置页与原生入口之间的控制层；复用平台进程身份和环境安装。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
import base64
import http.client
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading

from sanitizer import load_config, validate_config

DEFAULT_CONFIG = {'port': 8787, 'upstream_base_url': '', 'timeout_seconds': 600,
                  'assume_full_history': False}
CONFIG_FIELDS = frozenset(DEFAULT_CONFIG)


def write_bytes(path, data):
    # 解析配置快捷入口后原子替换目标，保留 Mac 符号链接。
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent,
                                         prefix='.config-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def write_config(path, config):
    data = (json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    write_bytes(path, data)


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


class ServiceController:
    def __init__(self, root, config_path=None, service_dir=None, label='local.relay-sanitizer'):
        self.root = Path(root).resolve()
        self.config_path = Path(config_path or self.root / 'config.json')
        self.service_dir = Path(service_dir or Path.home() / 'Library/Application Support/Relay-Sanitizer')
        self.label = label
        self.lock = threading.Lock()

    def read(self):
        try:
            config = load_config(self.config_path, allow_unconfigured=True)
            return {key: config.get(key, value) for key, value in DEFAULT_CONFIG.items()}, ''
        except FileNotFoundError:
            return DEFAULT_CONFIG.copy(), ''
        except (OSError, ValueError) as error:
            return DEFAULT_CONFIG.copy(), '配置文件无法读取，请填写并保存设置。' + str(error)

    def run(self, command, timeout=20):
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
        environment = {**os.environ, 'RELAY_HEADLESS': '1'}
        return subprocess.run(command, env=environment, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=timeout, **options)

    def powershell(self, script):
        encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
        return self.run(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive',
                         '-ExecutionPolicy', 'Bypass', '-EncodedCommand', encoded], timeout=8)

    def identity(self):
        if sys.platform == 'darwin':
            result = self.run(['/bin/launchctl', 'list', self.label], timeout=3)
            match = re.search(r'"PID"\s*=\s*(\d+)', result.stdout)
            if not match:
                return None
            active = load_config(self.service_dir / 'config.json')
            return {'pid': int(match[1]), 'port': active['port']}
        if sys.platform == 'win32':
            control = self.root / 'platform/windows/control.ps1'
            record = self.root / '.runtime/process.json'
            script = f"""$ErrorActionPreference = 'Stop'
. {ps_quote(control)}
if (Test-Path -LiteralPath {ps_quote(record)}) {{
    $state = Get-Content -LiteralPath {ps_quote(record)} -Raw -Encoding UTF8 | ConvertFrom-Json
    $process = Get-RelayProcess $state
    if ($process) {{ @{{ pid = $process.Id; port = $state.port }} | ConvertTo-Json -Compress }}
}}
"""
            result = self.powershell(script)
            if result.returncode:
                raise ValueError('无法核验运行中的代理，请查看日志。')
            return json.loads(result.stdout) if result.stdout.strip() else None
        raise ValueError('代理启停只支持 macOS 和 Windows。')

    def status(self):
        identity = self.identity()
        if not identity:
            return {'running': False, 'healthy': False, 'port': None, 'active_requests': 0}
        state = {**identity, 'running': True, 'healthy': False, 'active_requests': 0}
        connection = http.client.HTTPConnection('127.0.0.1', identity['port'], timeout=.8)
        try:
            connection.request('GET', '/health')
            response = connection.getresponse()
            health = json.loads(response.read(4096))
            state['healthy'] = (response.status == 200 and health.get('service') == 'relay-sanitizer'
                                and health.get('pid') == identity['pid'])
            if state['healthy']:
                state['active_requests'] = health.get('active_requests', 0)
        except (OSError, ValueError, http.client.HTTPException):
            pass
        finally:
            connection.close()
        return state

    def snapshot(self):
        config, error = self.read()
        try:
            status = self.status()
        except (OSError, ValueError, subprocess.SubprocessError) as failure:
            status = {'running': False, 'healthy': False, 'port': None, 'active_requests': 0,
                      'error': str(failure)}
        port = status['port'] if status['healthy'] else config['port']
        return {'config': config, 'config_error': error, 'status': status,
                'client_url': f'http://127.0.0.1:{port}/v1'}

    def check_port(self, port, status):
        if status['running'] and port == status['port']:
            return
        with socket.socket() as probe:
            if sys.platform != 'win32':
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(('127.0.0.1', port))
            except OSError as error:
                raise ValueError(f'端口 {port} 已被占用，请换一个端口。') from error

    def invoke(self, action):
        if sys.platform == 'darwin':
            name = '启动代理.app' if action == 'start' else '停止代理.app'
            command = ['/bin/zsh', str(self.root / name / 'Contents/MacOS/launcher')]
        elif sys.platform == 'win32':
            command = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive',
                       '-ExecutionPolicy', 'Bypass', '-File',
                       str(self.root / f'platform/windows/{action}.ps1')]
        else:
            raise ValueError('代理启停只支持 macOS 和 Windows。')
        result = self.run(command, timeout=420 if action == 'start' else 20)
        if result.returncode:
            detail = (result.stdout + result.stderr).strip()[-600:]
            raise ValueError(detail or '代理操作失败，请查看错误日志。')
        state = self.status()
        if action == 'start' and not state['healthy']:
            raise ValueError('代理尚未启动，请查看错误日志。')
        if action == 'stop' and state['running']:
            raise ValueError('代理尚未退出，请稍后重试。')

    def ensure_idle(self, state):
        if state.get('active_requests', 0):
            raise ValueError('正在转发聊天请求，请等待回复结束后再操作。')
        if state['running'] and not state['healthy']:
            raise ValueError('代理未通过健康检查，请使用原来的停止入口，再重新启动。')

    def apply(self, config):
        if not isinstance(config, dict) or set(config) != CONFIG_FIELDS:
            raise ValueError('请填写完整的代理设置。')
        validate_config(config)
        with self.lock:
            state = self.status()
            self.ensure_idle(state)
            self.check_port(config['port'], state)
            old_bytes = self.config_path.read_bytes() if self.config_path.exists() else None
            previous, error = self.read()
            if not error and config == previous and not state['running']:
                return self.snapshot()
            if state['running']:
                self.invoke('stop')
            try:
                write_config(self.config_path, config)
                if state['running']:
                    self.invoke('start')
            except (OSError, ValueError, subprocess.SubprocessError) as failure:
                # 新配置无法启动时恢复旧配置，避免一次保存使原代理失效。
                if old_bytes is not None:
                    write_bytes(self.config_path, old_bytes)
                else:
                    self.config_path.unlink(missing_ok=True)
                if state['running']:
                    try:
                        self.invoke('start')
                    except (OSError, ValueError, subprocess.SubprocessError):
                        raise ValueError('新配置启动失败。已恢复旧配置，但旧代理未能启动，请查看日志。') from failure
                raise failure
            return self.snapshot()

    def start(self):
        with self.lock:
            config = load_config(self.config_path)
            state = self.status()
            if state['healthy']:
                return self.snapshot()
            self.ensure_idle(state)
            self.check_port(config['port'], state)
            self.invoke('start')
            return self.snapshot()

    def stop(self):
        with self.lock:
            self.ensure_idle(self.status())
            self.invoke('stop')
            return self.snapshot()
