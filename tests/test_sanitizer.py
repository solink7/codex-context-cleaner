"""
[INPUT]: sanitizer 的配置、清洗和 HTTP 入口；标准库本地模拟上游。
[OUTPUT]: 配置、历史、认证、SSE 首块与错误边界的回归结果。
[POS]: 代理行为测试；只监听临时端口，不连接真实上游。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
from contextlib import contextmanager, redirect_stdout
import copy
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

import sanitizer


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


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = {'port': 8787, 'upstream_base_url': 'https://example.com/v1',
                       'timeout_seconds': 600, 'assume_full_history': False}

    def load(self, config, bom=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(config), encoding='utf-8-sig' if bom else 'utf-8')
            return sanitizer.load_config(path)

    def test_utf8_and_bom_configs(self):
        for bom in (False, True):
            self.assertEqual(self.load(self.config, bom), self.config)

    def test_reject_bad_field_types_and_ranges(self):
        cases = {'port': [None, True, '8787', 0, 65536, 1.5],
                 'timeout_seconds': [None, True, '600', 0, -1, float('inf'), float('nan'), 10 ** 400],
                 'assume_full_history': [None, 0, 'false'],
                 'upstream_base_url': [None, 123, '', ' https://example.com',
                                       'https://example.com\n', 'https://example.com:0/v1',
                                       'https://example.com:65536/v1', 'ftp://example.com',
                                       'https://key@example.com', 'https://example.com?q=1']}
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.load({**self.config, field: value})

    def test_reject_non_object_and_missing_config(self):
        for value in (None, [], {}, {'port': 8787}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load(value)

    def test_loopback_and_https_default_port(self):
        for host in ('localhost', 'localhost.', '127.0.0.1', '127.0.0.2', '[::1]'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                self.load({**self.config, 'upstream_base_url': f'http://{host}:8787/v1'})
        with self.assertRaises(ValueError):
            self.load({**self.config, 'port': 443, 'upstream_base_url': 'https://localhost/v1'})
        self.load({**self.config, 'port': 80, 'upstream_base_url': 'https://localhost/v1'})

    def test_check_config_does_not_start_server(self):
        with patch('sys.argv', ['sanitizer.py', '--check-config']), \
                patch('sanitizer.load_config', return_value=self.config), \
                patch('sanitizer.ThreadingHTTPServer') as server, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(sanitizer.main(), 0)
            server.assert_not_called()
            self.assertEqual(output.getvalue().strip(), '8787')


class HistoryTests(unittest.TestCase):
    def test_preserve_content_and_tool_identity_without_mutating_source(self):
        payload = {'input': [{'type': 'reasoning', 'id': 'r', 'summary': []},
                             {'type': 'function_call', 'id': 'fc', 'call_id': 'call-1', 'name': 'tool', 'arguments': '{}'},
                             {'type': 'function_call_output', 'id': 'out', 'call_id': 'call-1', 'output': '中文'},
                             {'role': 'user', 'id': 'm', 'content': [{'type': 'input_file', 'file_id': 'file-1'}]}],
                   'tools': [{'type': 'function', 'name': 'tool'}]}
        original = copy.deepcopy(payload)
        cleaned = sanitizer.sanitize(payload)
        self.assertEqual(payload, original)
        self.assertEqual(len(cleaned['input']), 3)
        self.assertTrue(all('id' not in item for item in cleaned['input']))
        self.assertEqual(cleaned['input'][0]['call_id'], 'call-1')
        self.assertEqual(cleaned['input'][1]['output'], '中文')
        self.assertEqual(cleaned['input'][2]['content'][0]['file_id'], 'file-1')
        self.assertEqual(cleaned['tools'], payload['tools'])

    def test_reject_remote_history_by_default(self):
        cases = [{'conversation': 'conversation-1'}, {'previous_response_id': 'response-1'},
                 *({'input': [{'type': kind}]} for kind in ('item_reference', 'compaction')),
                 {'input': ['bad-item']}, [], None]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                sanitizer.sanitize(payload)

    def test_explicit_full_history_removes_previous_id(self):
        self.assertEqual(sanitizer.sanitize({'input': '你好', 'previous_response_id': 'r'}, True), {'input': '你好'})
        with self.assertRaises(ValueError):
            sanitizer.sanitize({'conversation': 'c'}, True)


class Upstream(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append((self.path, dict(self.headers), payload))
        if payload.get('test_mode') == 'sse':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(b'data: first\n\n')
            self.wfile.flush()
            self.server.release_stream.wait(3)
            self.wfile.write(b'data: last\n\n')
            self.wfile.flush()
            self.close_connection = True
            return
        if payload.get('test_mode') == 'disconnect':
            self.connection.shutdown(socket.SHUT_RDWR)
            self.close_connection = True
            return
        body = json.dumps({'received': payload}, ensure_ascii=False).encode()
        self.send_response(429 if payload.get('test_mode') == 'rate' else 200)
        self.send_header('Retry-After', '7')
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'X-First')
        self.send_header('Connection', 'X-Second, close')
        self.send_header('X-First', 'must-remove')
        self.send_header('X-Second', 'must-remove')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True


class ForwardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        cls.upstream.requests = []
        cls.upstream.release_stream = threading.Event()
        cls.proxy = ThreadingHTTPServer(('127.0.0.1', 0), sanitizer.Handler)
        cls.proxy.config = {'port': cls.proxy.server_port,
                            'upstream_base_url': f'http://127.0.0.1:{cls.upstream.server_port}/v1',
                            'timeout_seconds': 2}
        cls.contexts = [serving(cls.upstream), serving(cls.proxy)]
        for context in cls.contexts:
            context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.upstream.release_stream.set()
        for context in reversed(cls.contexts):
            context.__exit__(None, None, None)

    def setUp(self):
        self.upstream.requests.clear()
        self.client = http.client.HTTPConnection('127.0.0.1', self.proxy.server_port, timeout=2)
        self.addCleanup(self.client.close)

    def post(self, payload, headers=None, path='/v1/responses'):
        self.client.request('POST', path, json.dumps(payload).encode(), headers or {})
        return self.client.getresponse()

    def test_auth_tool_history_and_path_aliases(self):
        for path in ('/v1/responses', '/responses', '/v1/responses/compact', '/responses/compact'):
            response = self.post({'input': [{'type': 'function_call_output', 'id': 'out', 'call_id': 'keep', 'output': 'ok'}]},
                                 {'Authorization': 'Bearer simulated-key', 'Cookie': 'remove', 'Proxy-Connection': 'remove'}, path)
            self.assertEqual(response.status, 200)
            response.read()
            target, headers, payload = self.upstream.requests[-1]
            self.assertEqual(target, '/v1' + path.removeprefix('/v1'))
            self.assertEqual(headers['Authorization'], 'Bearer simulated-key')
            self.assertNotIn('Cookie', headers)
            self.assertNotIn('Proxy-Connection', headers)
            self.assertEqual(payload['input'][0]['call_id'], 'keep')
            self.assertNotIn('id', payload['input'][0])

    def test_no_auth_is_not_filled_in(self):
        self.post({'input': 'hello'}).read()
        self.assertNotIn('Authorization', self.upstream.requests[-1][1])

    def test_rate_limit_and_all_connection_headers(self):
        response = self.post({'input': 'hello', 'test_mode': 'rate'})
        self.assertEqual(response.status, 429)
        self.assertEqual(response.getheader('Retry-After'), '7')
        self.assertIsNone(response.getheader('X-First'))
        self.assertIsNone(response.getheader('X-Second'))
        response.read()

    def test_sse_first_event_before_upstream_finishes(self):
        self.upstream.release_stream.clear()
        try:
            response = self.post({'input': 'hello', 'test_mode': 'sse'})
            self.assertEqual(response.getheader('Content-Type'), 'text/event-stream')
            self.assertEqual(response.readline(), b'data: first\n')
            self.assertFalse(self.upstream.release_stream.is_set())
            self.upstream.release_stream.set()
            self.assertIn(b'data: last', response.read())
        finally:
            self.upstream.release_stream.set()

    def test_bad_json_and_unsafe_history_never_reach_upstream(self):
        for body in (b'{bad-json', b'{"previous_response_id":"r"}', b'{"input":[{"type":"compaction"}]}'):
            self.client.request('POST', '/v1/responses', body)
            response = self.client.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
        self.assertEqual(self.upstream.requests, [])

    def test_cross_origin_and_unsupported_paths(self):
        for headers, path, status in (({'Origin': 'https://example.com'}, '/v1/responses', 403),
                                      ({}, '/v1/chat/completions', 404),
                                      ({'Content-Encoding': 'gzip'}, '/responses', 415)):
            response = self.post({'input': 'hello'}, headers, path)
            self.assertEqual(response.status, status)
            response.read()
        self.assertEqual(self.upstream.requests, [])

    def test_duplicate_length_rejected(self):
        self.client.putrequest('POST', '/responses')
        self.client.putheader('Content-Length', '2')
        self.client.putheader('Content-Length', '2')
        self.client.endheaders(b'{}')
        response = self.client.getresponse()
        self.assertEqual(response.status, 400)
        response.read()
        self.assertEqual(self.upstream.requests, [])

    def test_duplicate_connection_request_headers_removed(self):
        self.client.putrequest('POST', '/responses')
        for name, value in (('Content-Length', '2'), ('Connection', 'X-First'),
                            ('Connection', 'X-Second'), ('X-First', 'remove'), ('X-Second', 'remove')):
            self.client.putheader(name, value)
        self.client.endheaders(b'{}')
        self.client.getresponse().read()
        headers = self.upstream.requests[-1][1]
        self.assertNotIn('X-First', headers)
        self.assertNotIn('X-Second', headers)

    def test_upstream_disconnect_returns_502_without_retry(self):
        response = self.post({'input': 'hello', 'test_mode': 'disconnect'})
        self.assertEqual(response.status, 502)
        response.read()
        self.assertEqual(len(self.upstream.requests), 1)

    def test_health_identifies_proxy_process(self):
        self.client.request('GET', '/health')
        response = self.client.getresponse()
        health = json.loads(response.read())
        self.assertEqual(health, {'service': 'relay-sanitizer', 'status': 'ok', 'pid': os.getpid()})

    def test_error_reply_tolerates_closed_client(self):
        handler = sanitizer.Handler.__new__(sanitizer.Handler)
        handler.send_response = lambda status: None
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: (_ for _ in ()).throw(BrokenPipeError())
        handler.reply(400, {'error': {'message': '客户端已断开'}})
        self.assertTrue(handler.close_connection)


if __name__ == '__main__':
    unittest.main()
