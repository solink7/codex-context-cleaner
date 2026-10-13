#!/usr/bin/env python3
"""
[INPUT]: 标准库 HTTP、UTF-8 配置与客户端携带的请求头和 Responses JSON。
[OUTPUT]: Responses/SSE 转发、/health 与 --check-config 配置检查。
[POS]: 双端共用的代理源码；启动器负责进程，本文件校验配置并清洗历史。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
import base64
import argparse
import copy
import http.client
import ipaddress
import json
import math
import pathlib
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, unquote
from urllib.request import getproxies, proxy_bypass

ROOT = pathlib.Path(__file__).resolve().parent
MAX_BODY = 32 * 1024 * 1024
DEFAULT_TIMEOUT = 600
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'proxy-connection', 'te', 'trailer', 'transfer-encoding', 'upgrade', 'host', 'content-length'}


def load_config(path=None):
    config = json.loads((path or ROOT / 'config.json').read_text(encoding='utf-8-sig'))
    if not isinstance(config, dict):
        raise ValueError('config.json 必须是 JSON 对象')
    port = config.get('port')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('port 必须是 1–65535 的整数')
    timeout = config.get('timeout_seconds', DEFAULT_TIMEOUT)
    try:
        valid_timeout = type(timeout) in (int, float) and math.isfinite(timeout) and timeout > 0
    except OverflowError:
        valid_timeout = False
    if not valid_timeout:
        raise ValueError('timeout_seconds 必须是大于 0 的有限数字')
    if type(config.get('assume_full_history', False)) is not bool:
        raise ValueError('assume_full_history 必须是 true 或 false')
    base_url = config.get('upstream_base_url')
    if not isinstance(base_url, str) or any(c.isspace() for c in base_url):
        raise ValueError('upstream_base_url 必须是无空白的 http(s) 地址')
    url = urlsplit(base_url)
    if url.scheme not in ('http', 'https') or not url.hostname or url.query or url.fragment or url.username is not None:
        raise ValueError('上游地址必须是 http(s) API Base URL，不包含查询参数或凭据')
    upstream_port = url.port if url.port is not None else (443 if url.scheme == 'https' else 80)
    if not 1 <= upstream_port <= 65535:
        raise ValueError('上游端口必须是 1–65535 的整数')
    hostname = url.hostname.rstrip('.').lower()
    try:
        loopback = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        loopback = hostname == 'localhost'
    if loopback and upstream_port == port:
        raise ValueError('上游地址不能指向清洗代理自身')
    return config


def hop_headers(headers):
    # Connection 可重复出现；每一行声明的逐跳请求头都必须剔除。
    return HOP | {part.strip().lower() for name, value in headers
                  if name.lower() == 'connection' for part in value.split(',')}


def sanitize(payload, full_history=False):
    if not isinstance(payload, dict):
        raise ValueError('请求体必须为 JSON 对象')
    data = copy.deepcopy(payload)
    if data.get('conversation'):
        raise ValueError('不支持远端 conversation；请使用携带完整历史的新会话')
    if data.get('previous_response_id') and not full_history:
        raise ValueError('请求使用 previous_response_id；确认客户端携带完整历史后，才能开启 assume_full_history')
    data.pop('previous_response_id', None)
    items = data.get('input')
    if isinstance(items, list):
        cleaned = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError('input 数组成员必须为对象')
            kind = item.get('type')
            if kind in ('item_reference', 'compaction'):
                raise ValueError('历史包含远端引用或加密压缩项，无法安全清洗；请新开会话或使用固定上游账号')
            if kind == 'reasoning':
                continue
            item.pop('id', None)
            # 只移除 Responses 顶层项目 ID；call_id、file_id、内容与工具定义保持原样。
            cleaned.append(item)
        data['input'] = cleaned
    return data


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(self.server.config.get('timeout_seconds', DEFAULT_TIMEOUT))

    def reply(self, status, message):
        body = json.dumps(message, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        try:
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            # 客户端已离开时，不再向同一连接写第二份错误响应。
            pass
        self.close_connection = True

    def do_GET(self):
        if self.path == '/health':
            self.reply(200, {'service': 'relay-sanitizer', 'status': 'ok', 'pid': os.getpid()})
        else:
            self.reply(405, {'error': {'message': '仅支持 HTTP POST Responses；不支持 WebSocket'}})

    def do_POST(self):
        conn = None
        started = False
        try:
            if self.headers.get('Origin'):
                self.reply(403, {'error': {'message': '不接受网页跨域请求'}})
                return
            if self.path not in ('/v1/responses', '/responses', '/v1/responses/compact', '/responses/compact'):
                self.reply(404, {'error': {'message': '不支持此 API 路径'}})
                return
            if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Encoding', 'identity') != 'identity':
                self.reply(415, {'error': {'message': '需要未压缩的 JSON 和 Content-Length'}})
                return
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) != 1:
                self.reply(400, {'error': {'message': '需要唯一的 Content-Length'}})
                return
            length = int(lengths[0])
            if not 0 < length <= MAX_BODY:
                self.reply(413, {'error': {'message': '请求体为空或超过 32 MiB'}})
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError('请求体不完整')
            cfg = self.server.config
            payload = sanitize(json.loads(raw), cfg.get('assume_full_history', False))
            body = json.dumps(payload, ensure_ascii=False).encode()
            url = urlsplit(cfg['upstream_base_url'])
            cls = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
            conn = cls(url.hostname, url.port, timeout=cfg.get('timeout_seconds', DEFAULT_TIMEOUT))
            # 沿用系统或环境变量的 HTTP CONNECT 代理，保持目标站 TLS 验证。
            network_proxy = getproxies().get('https') if url.scheme == 'https' and not proxy_bypass(url.hostname) else None
            if network_proxy:
                proxy_url = urlsplit(network_proxy)
                if proxy_url.scheme != 'http':
                    self.reply(502, {'error': {'message': '系统 HTTPS 代理须使用 http:// CONNECT 地址'}})
                    return
                conn = http.client.HTTPSConnection(proxy_url.hostname, proxy_url.port or 80,
                                                   timeout=cfg.get('timeout_seconds', DEFAULT_TIMEOUT))
                tunnel_headers = {}
                if proxy_url.username:
                    credentials = unquote(proxy_url.username) + ':' + unquote(proxy_url.password or '')
                    tunnel_headers['Proxy-Authorization'] = 'Basic ' + base64.b64encode(credentials.encode()).decode()
                conn.set_tunnel(url.hostname, url.port or 443, headers=tunnel_headers)
            suffix = self.path.removeprefix('/v1')
            path = url.path.rstrip('/') + suffix
            excluded = hop_headers(self.headers.items())
            excluded |= {'cookie', 'accept-encoding', 'content-type', 'expect'}
            headers = {k: v for k, v in self.headers.items() if k.lower() not in excluded}
            headers.update({'Content-Type': 'application/json', 'Accept-Encoding': 'identity'})
            conn.request('POST', path, body, headers)
            response = conn.getresponse()
            self.send_response(response.status)
            excluded = hop_headers(response.getheaders())
            for name, value in response.getheaders():
                if name.lower() not in excluded:
                    self.send_header(name, value)
            self.send_header('Connection', 'close')
            self.end_headers()
            started = True
            # read1 不等待整个缓冲区填满，SSE 每个上游数据块立刻送回客户端。
            while chunk := response.read1(16384):
                self.wfile.write(chunk)
                self.wfile.flush()
            print(f'转发完成：HTTP {response.status}', flush=True)
        except (ValueError, UnicodeError) as error:
            if not started:
                self.reply(400, {'error': {'message': str(error)}})
        except (OSError, http.client.HTTPException):
            print('连接中断或上游超时；未自动重试。', flush=True)
            if not started:
                try:
                    self.reply(502, {'error': {'message': '上游连接失败或超时，请检查网络和配置'}})
                except OSError:
                    pass
        finally:
            self.close_connection = True
            if conn:
                conn.close()


def main():
    parser = argparse.ArgumentParser(description='本机 Responses 清洗代理')
    parser.add_argument('--check-config', action='store_true', help='校验配置并输出端口，不启动代理')
    args = parser.parse_args()
    try:
        config = load_config()
        if args.check_config:
            print(config['port'])
            return 0
        server = ThreadingHTTPServer(('127.0.0.1', config['port']), Handler)
        server.config = config
    except (OSError, ValueError) as error:
        print(f'启动失败：{error}。请检查 config.json 和端口占用。', flush=True)
        return 1
    print(f"清洗代理已启动：http://127.0.0.1:{config['port']}/v1")
    print(f"上游：{config['upstream_base_url']}；后台运行时请使用停止入口。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n代理已停止。')
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
