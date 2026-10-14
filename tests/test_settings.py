"""
[INPUT]: 共用配置控制层、本机设置服务与临时文件和 HTTP 夹具。
[OUTPUT]: 后台进程输出继承、配置恢复、端口冲突与设置鉴权回归。
[POS]: 设置功能测试；不调用用户的代理，不连接真实上游。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
from contextlib import contextmanager
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from control import DEFAULT_CONFIG, ServiceController, write_config
from sanitizer import load_config
from settings import SettingsServer, acquire_lock, reopen_existing

STOPPED = {'running': False, 'healthy': False, 'port': None, 'active_requests': 0}
RUNNING = {'running': True, 'healthy': True, 'port': 8787, 'active_requests': 0}


@contextmanager
def serving(server):
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="设置 '测试' ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.controller = ServiceController(self.root)
        self.controller.status = Mock(return_value=STOPPED.copy())
        self.controller.invoke = Mock()
        self.config = {**DEFAULT_CONFIG, 'port': free_port(), 'upstream_base_url': 'https://example.com/v1'}
        self.running = {**RUNNING, 'port': self.config['port']}

    def test_empty_first_run_can_open_but_cannot_start(self):
        write_config(self.controller.config_path, DEFAULT_CONFIG)
        self.assertEqual(self.controller.snapshot()['config'], DEFAULT_CONFIG)
        self.assertEqual(load_config(self.controller.config_path, allow_unconfigured=True), DEFAULT_CONFIG)
        with self.assertRaisesRegex(ValueError, '设置代理'):
            self.controller.start()
        self.controller.invoke.assert_not_called()

    def test_invalid_json_is_recoverable_without_loading_a_service(self):
        self.controller.config_path.write_text('{bad-json')
        self.assertIn('无法读取', self.controller.snapshot()['config_error'])
        result = self.controller.apply(self.config)
        self.assertFalse(result['config_error'])
        self.assertEqual(load_config(self.controller.config_path), self.config)

    def test_save_preserves_mac_config_link(self):
        target = self.root / 'Resources/config.json'
        write_config(target, self.config)
        shortcut = self.root / 'config.json'
        try:
            shortcut.symlink_to(target)
        except OSError:
            self.skipTest('系统不允许创建符号链接')
        self.controller.apply({**self.config, 'timeout_seconds': 300})
        self.assertTrue(shortcut.is_symlink())
        self.assertEqual(load_config(target)['timeout_seconds'], 300)
        self.assertEqual(list(target.parent.glob('.config-*')), [])

    def test_invalid_configuration_never_changes_saved_file(self):
        write_config(self.controller.config_path, self.config)
        before = self.controller.config_path.read_bytes()
        for change in ({'port': 0}, {'upstream_base_url': ''}, {'upstream_base_url': 'https://key@example.com'},
                       {'assume_full_history': 'true'}, {'timeout_seconds': float('nan')}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.controller.apply({**self.config, **change})
        self.assertEqual(self.controller.config_path.read_bytes(), before)
        self.controller.invoke.assert_not_called()

    def test_port_conflict_keeps_old_config_and_service(self):
        write_config(self.controller.config_path, self.config)
        self.controller.status.return_value = self.running.copy()
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            with self.assertRaisesRegex(ValueError, '已被占用'):
                self.controller.apply({**self.config, 'port': occupied.getsockname()[1]})
        self.assertEqual(load_config(self.controller.config_path), self.config)
        self.controller.invoke.assert_not_called()

    def test_live_requests_prevent_restarting_and_stopping(self):
        write_config(self.controller.config_path, self.config)
        self.controller.status.return_value = {**self.running, 'active_requests': 1}
        for operation in (lambda: self.controller.apply({**self.config, 'timeout_seconds': 30}), self.controller.stop):
            with self.assertRaisesRegex(ValueError, '等待回复结束'):
                operation()
        self.controller.invoke.assert_not_called()
        self.assertEqual(load_config(self.controller.config_path), self.config)

    def test_running_service_applies_and_rolls_back_on_failure(self):
        write_config(self.controller.config_path, self.config)
        self.controller.status.return_value = self.running.copy()
        self.controller.invoke.side_effect = [None, ValueError('模拟启动失败'), None]
        with self.assertRaisesRegex(ValueError, '模拟启动失败'):
            self.controller.apply({**self.config, 'timeout_seconds': 30})
        self.assertEqual(load_config(self.controller.config_path), self.config)
        self.assertEqual([call.args[0] for call in self.controller.invoke.call_args_list], ['stop', 'start', 'start'])

    def test_running_service_applies_new_config(self):
        write_config(self.controller.config_path, self.config)
        self.controller.status.return_value = self.running.copy()
        self.controller.apply({**self.config, 'timeout_seconds': 30})
        self.assertEqual(load_config(self.controller.config_path)['timeout_seconds'], 30)
        self.assertEqual([call.args[0] for call in self.controller.invoke.call_args_list], ['stop', 'start'])

    def test_apply_reloads_file_edits_while_proxy_is_running(self):
        write_config(self.controller.config_path, self.config)
        self.controller.status.return_value = self.running.copy()
        self.controller.apply(self.config)
        self.assertEqual([call.args[0] for call in self.controller.invoke.call_args_list], ['stop', 'start'])

    def test_repeated_start_does_not_create_another_process(self):
        write_config(self.controller.config_path, self.config)
        self.controller.status.return_value = self.running.copy()
        self.assertTrue(self.controller.start()['status']['running'])
        self.controller.invoke.assert_not_called()

    def test_launcher_returns_while_background_process_keeps_output_handles(self):
        release = self.root / 'release-child'
        finished = self.root / 'child-finished'
        child_script = """import sys, time
from pathlib import Path
release, finished = map(Path, sys.argv[1:])
for attempt in range(100):
    if release.exists():
        break
    time.sleep(.1)
finished.touch()
"""
        launcher = f"""import subprocess, sys
subprocess.Popen([sys.executable, '-c', {child_script!r}, {str(release)!r}, {str(finished)!r}])
print('入口已完成', flush=True)
sys.stderr.buffer.write(b'\\xff')
sys.stderr.flush()
sys.exit(7)
"""
        try:
            result = self.controller.run([sys.executable, '-X', 'utf8', '-c', launcher], timeout=3)
            self.assertEqual(result.returncode, 7)
            self.assertEqual(result.stdout.strip(), '入口已完成')
            self.assertEqual(result.stderr, '\ufffd')
            self.assertFalse(finished.exists(), '入口等待了后台进程退出')
        finally:
            release.touch()
            # 等待夹具退出后再删除目录，避免遗留后台测试进程。
            deadline = time.monotonic() + 3
            while not finished.exists() and time.monotonic() < deadline:
                time.sleep(.05)

    def test_control_command_timeout_is_preserved(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.controller.run([sys.executable, '-c', 'import time; time.sleep(10)'], timeout=.2)


class SettingsHttpTests(unittest.TestCase):
    def test_startup_does_not_wait_for_dns_resolution(self):
        with patch('socket.getfqdn', side_effect=AssertionError('不应查询 DNS')):
            server = SettingsServer(self.controller)
            server.server_close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='设置接口测试 ')
        self.addCleanup(self.temp.cleanup)
        self.controller = ServiceController(Path(self.temp.name))
        self.controller.status = Mock(return_value=STOPPED.copy())
        self.controller.invoke = Mock()
        self.server = SettingsServer(self.controller)
        self.context = serving(self.server)
        self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.headers = {'X-Settings-Token': self.server.token, 'Content-Type': 'application/json'}
        self.config = {**DEFAULT_CONFIG, 'port': free_port(), 'upstream_base_url': 'https://example.com/v1'}
        self.running = {**RUNNING, 'port': self.config['port']}

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=2)
        try:
            connection.request(method, path, json.dumps(body) if body is not None else None, headers or {})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_page_opens_when_proxy_port_is_occupied_and_configuration_empty(self):
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            write_config(self.controller.config_path, {**DEFAULT_CONFIG, 'port': occupied.getsockname()[1]})
            status, html, headers = self.request('GET', '/')
            self.assertEqual(status, 200)
            self.assertIn('代理设置'.encode(), html)
            self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
            status, body, _ = self.request('GET', '/api/state', headers=self.headers)
            self.assertEqual(status, 200)
            self.assertFalse(json.loads(body)['status']['running'])

    def test_settings_require_token_and_reject_other_origins_and_hosts(self):
        for headers in ({}, {**self.headers, 'X-Settings-Token': 'wrong'},
                        {**self.headers, 'X-Settings-Token': '\u00ff'},
                        {**self.headers, 'Origin': 'https://example.com'},
                        {**self.headers, 'Host': 'attacker.example'}):
            for method in ('GET', 'POST'):
                with self.subTest(headers=headers, method=method):
                    status, _, _ = self.request(method, '/api/state' if method == 'GET' else '/api/config',
                                               self.config if method == 'POST' else None, headers)
                    self.assertEqual(status, 403)
        self.assertFalse(self.controller.config_path.exists())

    def test_duplicate_host_headers_are_rejected(self):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=2)
        try:
            connection.putrequest('GET', '/api/state', skip_host=True)
            connection.putheader('Host', f'127.0.0.1:{self.server.server_port}')
            connection.putheader('Host', 'attacker.example')
            connection.putheader('X-Settings-Token', self.server.token)
            connection.endheaders()
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
        finally:
            connection.close()

    def test_authenticated_save_and_validation(self):
        headers = {**self.headers, 'Origin': self.server.origin}
        status, body, _ = self.request('POST', '/api/config', self.config, headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['config'], self.config)
        status, _, _ = self.request('POST', '/api/config', {**self.config, 'port': -1}, headers)
        self.assertEqual(status, 400)
        self.assertEqual(load_config(self.controller.config_path), self.config)

    def test_oversized_wrong_format_and_traversal_are_rejected(self):
        for body, headers in (({'data': 'x' * 20000}, self.headers),
                              ({}, {**self.headers, 'Content-Type': 'text/plain'}),
                              ({}, {**self.headers, 'Content-Encoding': 'gzip'})):
            status, _, _ = self.request('POST', '/api/config', body, headers)
            self.assertEqual(status, 400)
        status, _, _ = self.request('GET', '/../config.json')
        self.assertEqual(status, 404)
        self.controller.invoke.assert_not_called()

    def test_reopen_validates_server_identity_and_uses_same_instance(self):
        path = Path(self.temp.name) / 'settings.json'
        path.write_text(json.dumps({'url': self.server.url, 'pid': os.getpid()}))
        self.assertTrue(reopen_existing(path, open_browser=False))
        path.write_text(json.dumps({'url': self.server.url, 'pid': -1}))
        self.assertFalse(reopen_existing(path, open_browser=False))

    def test_singleton_lock_releases_after_close(self):
        path = Path(self.temp.name) / 'settings.lock'
        lock = acquire_lock(path)
        self.assertIsNotNone(lock)
        self.assertIsNone(acquire_lock(path))
        lock.close()
        second = acquire_lock(path)
        self.assertIsNotNone(second)
        second.close()


if __name__ == '__main__':
    unittest.main()
