#!/usr/bin/env python3
"""
Pool Proxy v1.0 — 透明反代·多账号并发路由
============================================
道生一(proxy) → 一生二(路由+转发) → 二生三(无限并发) → 三生万物

核心突破: 彻底消除"换号"概念。
  旧方案: Windsurf绑定单账号 → 耗尽 → 换号(3-5s中断) → 继续
  新方案: Windsurf → 本地代理 → 每个请求自动路由最优账号 → 用户零感知

架构:
  Windsurf Client (apiServerUrl → http://127.0.0.1:19876)
       │
       ▼
  Pool Proxy (:19876)
       │ 1. 读取请求
       │ 2. Pool Engine选择最优账号
       │ 3. 替换所有auth头为最优apiKey
       │ 4. HTTPS转发到真实服务器
       │ 5. 流式回传响应
       │ 6. 检测rate limit → 标记 → 下次自动绕开
       ▼
  server.self-serve.windsurf.com (真实Codeium API)

Usage:
  python pool_proxy.py                  # 启动代理 + Pool Engine
  python pool_proxy.py --setup          # 自动配置Windsurf指向代理
  python pool_proxy.py --restore        # 恢复Windsurf原始配置
  python pool_proxy.py --status         # 代理+池状态
"""

import os, sys, json, time, threading, ssl, socket, struct
import http.client
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse
from datetime import datetime

VERSION = '1.0.0'
SCRIPT_DIR = Path(__file__).parent
PROXY_PORT = 19876

# Upstream Codeium servers
UPSTREAM_SERVERS = {
    'api': 'server.self-serve.windsurf.com',
    'inference': 'server.codeium.com',
    'eu': 'eu.windsurf.com',
}
DEFAULT_UPSTREAM = UPSTREAM_SERVERS['api']

# Import pool engine
sys.path.insert(0, str(SCRIPT_DIR))
from pool_engine import PoolEngine, HealthMonitor, MODEL_RATE_WINDOWS

# Shared state
_engine = None
_stats = {
    'total_requests': 0,
    'total_forwarded': 0,
    'total_errors': 0,
    'total_rate_limits': 0,
    'total_bytes_in': 0,
    'total_bytes_out': 0,
    'boot_time': 0,
    'last_request_time': 0,
    'accounts_used': {},  # email -> request_count
}
_stats_lock = threading.Lock()

# Optimal key file (for extension.js interceptor fallback)
OPTIMAL_KEY_FILE = SCRIPT_DIR / '_optimal_key.txt'


def _update_optimal_key_file():
    """Background thread: write current best apiKey to file for fast sync."""
    while True:
        try:
            if _engine:
                best = _engine.pick_best()
                if best and best.api_key:
                    OPTIMAL_KEY_FILE.write_text(best.api_key, encoding='utf-8')
        except Exception:
            pass
        time.sleep(3)


# ============================================================
# gRPC-Web Transparent Reverse Proxy
# ============================================================

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Thread-per-request HTTP server."""
    daemon_threads = True
    allow_reuse_address = True


class ProxyHandler(BaseHTTPRequestHandler):
    """Transparent reverse proxy with per-request account routing."""

    # Suppress default logging
    def log_message(self, fmt, *args):
        pass

    def _log(self, msg):
        ts = datetime.now().strftime('%H:%M:%S.%f')[:12]
        print(f'[{ts}] {msg}')

    # ── CORS ──
    def _send_cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Expose-Headers', '*')

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    # ── Local API endpoints (proxy management) ──
    def _is_local_api(self):
        path = self.path.split('?')[0]
        return path.startswith('/pool/')

    def _handle_local_api(self):
        path = self.path.split('?')[0]
        if path == '/pool/health':
            return self._json({'ok': True, 'proxy': VERSION, 'engine': True})
        if path == '/pool/status':
            ps = _engine.get_pool_status() if _engine else {}
            with _stats_lock:
                ps['proxy_stats'] = dict(_stats)
            return self._json(ps)
        if path == '/pool/accounts':
            accs = _engine.get_all_accounts() if _engine else []
            return self._json({'ok': True, 'accounts': accs})
        self._json({'ok': False, 'error': 'not found'}, 404)

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self._send_cors()
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── Main request handlers ──
    def do_GET(self):
        if self._is_local_api():
            return self._handle_local_api()
        self._proxy_request()

    def do_POST(self):
        if self._is_local_api():
            return self._handle_local_api()
        self._proxy_request()

    # ── Core proxy logic ──
    def _proxy_request(self):
        """Forward request to upstream with optimal account's apiKey."""
        t0 = time.time()

        # Read request body
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b''

        # Extract model hint from request path/headers
        model_hint = self._extract_model_hint()

        # Pick optimal account
        best = _engine.pick_best(model_key=model_hint) if _engine else None
        if not best or not best.api_key:
            # Fallback: forward with original headers (no key replacement)
            self._log(f'⚠ No pool account, forwarding as-is')
            best = None

        # Build upstream headers (replace auth)
        upstream_headers = {}
        for key in self.headers:
            lk = key.lower()
            # Skip hop-by-hop headers
            if lk in ('host', 'transfer-encoding', 'connection', 'keep-alive'):
                continue
            upstream_headers[key] = self.headers[key]

        # Replace ALL auth-related headers with pool account's key
        if best and best.api_key:
            upstream_headers['Authorization'] = f'Bearer {best.api_key}'
            # Codeium-specific metadata headers (Connect-RPC / gRPC-Web)
            for hdr in list(upstream_headers.keys()):
                lh = hdr.lower()
                if 'api-key' in lh or 'api_key' in lh or 'apikey' in lh:
                    upstream_headers[hdr] = best.api_key
                if lh.startswith('connect-metadata-') and 'key' in lh:
                    upstream_headers[hdr] = best.api_key
                if lh.startswith('grpc-metadata-') and 'key' in lh:
                    upstream_headers[hdr] = best.api_key

        # Set correct Host header for upstream
        upstream_host = DEFAULT_UPSTREAM
        upstream_headers['Host'] = upstream_host

        # Forward to upstream
        try:
            ctx = ssl.create_default_context()
            conn = http.client.HTTPSConnection(upstream_host, 443,
                                                timeout=120, context=ctx)
            conn.request(self.command, self.path, body, upstream_headers)
            upstream_resp = conn.getresponse()

            # Check for rate limiting
            is_rate_limited = self._check_rate_limit(upstream_resp, best, model_hint)

            # Stream response back to client
            self.send_response(upstream_resp.status)
            # Copy response headers
            for hdr, val in upstream_resp.getheaders():
                lh = hdr.lower()
                if lh in ('transfer-encoding', 'connection', 'keep-alive'):
                    continue
                self.send_header(hdr, val)
            self._send_cors()
            self.end_headers()

            # Stream response body in chunks
            total_out = 0
            while True:
                chunk = upstream_resp.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                total_out += len(chunk)

            conn.close()

            # Update stats
            elapsed_ms = int((time.time() - t0) * 1000)
            with _stats_lock:
                _stats['total_requests'] += 1
                _stats['total_forwarded'] += 1
                _stats['total_bytes_in'] += content_length
                _stats['total_bytes_out'] += total_out
                _stats['last_request_time'] = time.time()
                if best:
                    _stats['accounts_used'][best.email] = \
                        _stats['accounts_used'].get(best.email, 0) + 1

            # Track in pool engine
            if best and _engine:
                _engine.report_request(best.email, model_hint or '', 0)

            if best:
                status_icon = '⚡' if is_rate_limited else '→'
                self._log(f'{status_icon} {self.command} {self.path[:60]} '
                         f'→ #{best.index} {best.email[:20]} '
                         f'{upstream_resp.status} {total_out}B {elapsed_ms}ms')

        except Exception as e:
            with _stats_lock:
                _stats['total_errors'] += 1
            self._log(f'✖ Proxy error: {e}')
            try:
                self.send_response(502)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'error': 'proxy_error', 'detail': str(e)
                }).encode())
            except Exception:
                pass

    def _extract_model_hint(self):
        """Try to extract model info from request path or headers."""
        path = self.path.lower()
        # Common gRPC service paths that indicate model usage
        if 'chatclient' in path or 'cascade' in path:
            # Check for model hint in custom header
            model = self.headers.get('x-model-hint', '')
            if model:
                return model
            # Check grpc metadata
            for key in self.headers:
                if 'model' in key.lower():
                    return self.headers[key]
        return None

    def _check_rate_limit(self, resp, account, model_hint):
        """Detect rate limiting from upstream response."""
        if not account:
            return False

        status = resp.status
        # gRPC status codes in trailers/headers
        grpc_status = resp.getheader('grpc-status', '')
        grpc_message = resp.getheader('grpc-message', '')

        is_limited = False

        # HTTP 429 = rate limited
        if status == 429:
            is_limited = True

        # gRPC ResourceExhausted = 8
        if grpc_status == '8':
            is_limited = True

        # gRPC PermissionDenied = 7 (billing/quota)
        if grpc_status == '7':
            is_limited = True

        # Check response headers for quota exhausted hints
        for hdr, val in resp.getheaders():
            lv = val.lower() if isinstance(val, str) else ''
            if 'quota' in lv and ('exhaust' in lv or 'exceeded' in lv):
                is_limited = True
            if 'rate' in lv and 'limit' in lv:
                is_limited = True

        if is_limited and _engine:
            model_key = model_hint or 'default'
            window = MODEL_RATE_WINDOWS.get(model_key, MODEL_RATE_WINDOWS['default'])
            _engine.report_rate_limit(account.email, model_key, window)
            with _stats_lock:
                _stats['total_rate_limits'] += 1
            self._log(f'⚡ RATE LIMITED: #{account.index} {account.email[:20]} '
                     f'model={model_key} window={window}s '
                     f'(status={status} grpc={grpc_status})')
            # Write signal file for dao_engine sentinel
            try:
                sf = SCRIPT_DIR / '_ratelimit_signal.json'
                sf.write_text(json.dumps({
                    'ts': time.time(), 'model': model_key,
                    'email': account.email, 'source': 'proxy',
                    'grpc_status': grpc_status, 'http_status': status,
                }), encoding='utf-8')
            except Exception:
                pass

        return is_limited


# ============================================================
# Setup: Configure Windsurf to use proxy
# ============================================================

def setup_proxy():
    """Modify Windsurf's apiServerUrl to point to local proxy."""
    import sqlite3

    STATE_DB = Path(os.environ.get('APPDATA', '')) / 'Windsurf' / 'User' / 'globalStorage' / 'state.vscdb'
    if not STATE_DB.exists():
        print(f'  ✖ state.vscdb not found: {STATE_DB}')
        return False

    proxy_url = f'http://127.0.0.1:{PROXY_PORT}'
    secret_key = 'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.apiServerUrl"}'

    # Read current value
    conn = sqlite3.connect(str(STATE_DB), timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (secret_key,)).fetchone()

    if row:
        print(f'  Current secret value length: {len(row[0])}')
        print(f'  Will be replaced with proxy URL encoding')
    else:
        print(f'  Secret key not found, will create')

    # The secret value format: JSON Buffer with "v10" prefix + DPAPI encrypted data
    # For HTTP localhost, we can try a simpler approach:
    # Write the proxy URL as a plain v10-prefixed buffer
    try:
        # Try DPAPI encryption (Windows only)
        import ctypes, ctypes.wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [('cbData', ctypes.wintypes.DWORD),
                        ('pbData', ctypes.POINTER(ctypes.c_char))]

        plaintext = proxy_url.encode('utf-8')
        blob_in = DATA_BLOB()
        blob_in.cbData = len(plaintext)
        blob_in.pbData = ctypes.cast(
            ctypes.create_string_buffer(plaintext),
            ctypes.POINTER(ctypes.c_char))
        blob_out = DATA_BLOB()

        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0,
            ctypes.byref(blob_out))

        if ok:
            encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)

            # Format: v10 + DPAPI blob → JSON Buffer
            v10_encrypted = b'v10' + encrypted
            buffer_data = list(v10_encrypted)
            value_json = json.dumps({"type": "Buffer", "data": buffer_data})

            # Backup current value
            if row:
                backup_key = secret_key + '__proxy_backup'
                conn.execute(
                    "INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)",
                    (backup_key, row[0]))

            # Write new value
            conn.execute(
                "INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)",
                (secret_key, value_json))
            conn.commit()
            print(f'  ✅ apiServerUrl → {proxy_url}')
            print(f'  ✅ Backup saved as {secret_key}__proxy_backup')
            print(f'  ⚠ Restart Windsurf for changes to take effect')
            conn.close()
            return True
        else:
            print(f'  ✖ DPAPI encryption failed (error={ctypes.GetLastError()})')
            conn.close()
            return False

    except Exception as e:
        print(f'  ✖ Setup failed: {e}')
        conn.close()
        return False


def restore_proxy():
    """Restore Windsurf's original apiServerUrl."""
    import sqlite3

    STATE_DB = Path(os.environ.get('APPDATA', '')) / 'Windsurf' / 'User' / 'globalStorage' / 'state.vscdb'
    if not STATE_DB.exists():
        print(f'  ✖ state.vscdb not found')
        return False

    secret_key = 'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.apiServerUrl"}'
    backup_key = secret_key + '__proxy_backup'

    conn = sqlite3.connect(str(STATE_DB), timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')

    backup = conn.execute("SELECT value FROM ItemTable WHERE key=?",
                          (backup_key,)).fetchone()
    if backup:
        conn.execute(
            "INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)",
            (secret_key, backup[0]))
        conn.execute("DELETE FROM ItemTable WHERE key=?", (backup_key,))
        conn.commit()
        print(f'  ✅ apiServerUrl restored from backup')
        print(f'  ⚠ Restart Windsurf for changes to take effect')
        conn.close()
        return True
    else:
        print(f'  ✖ No backup found. Manual restore needed.')
        conn.close()
        return False


# ============================================================
# CLI
# ============================================================

def cli_serve():
    global _engine

    print('=' * 65)
    print(f'  Pool Proxy v{VERSION} — 透明反代·多账号并发路由')
    print(f'  道法自然: 每个请求自动路由最优账号，用户零感知')
    print('=' * 65)

    # Init pool engine
    _engine = PoolEngine()
    monitor = HealthMonitor(_engine, interval=10)
    monitor.start()

    # Start optimal key file writer
    key_writer = threading.Thread(target=_update_optimal_key_file, daemon=True)
    key_writer.start()

    # Print pool status
    s = _engine.get_pool_status()
    p = s['pool']
    print(f'\n  Pool: {p["total"]} accounts, {p["available"]} available, '
          f'{p["has_api_key"]} with apiKey')
    print(f'  Capacity: D{p["total_daily"]}% · W{p["total_weekly"]}%')
    if s.get('active'):
        a = s['active']
        print(f'  Active: #{a["index"]} {a["email"][:30]} D{a["daily"]}%·W{a["weekly"]}%')

    # Start proxy server
    port = PROXY_PORT
    server = None
    for attempt in range(5):
        try:
            server = ThreadedHTTPServer(('127.0.0.1', port), ProxyHandler)
            break
        except OSError:
            port += 1

    if not server:
        print(f'\n  ✖ Cannot bind port {PROXY_PORT}-{port}')
        return

    print(f'\n  Proxy:     http://127.0.0.1:{port}')
    print(f'  Upstream:  https://{DEFAULT_UPSTREAM}')
    print(f'  Pool API:  http://127.0.0.1:{port}/pool/status')
    print(f'  Key file:  {OPTIMAL_KEY_FILE}')
    print(f'\n  Setup:     python pool_proxy.py --setup')
    print(f'  Restore:   python pool_proxy.py --restore')
    print(f'\n  Ctrl+C to stop\n')

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        monitor.stop()
        server.server_close()
        print('\nProxy stopped.')


def cli_status():
    """Check proxy and pool status."""
    import urllib.request

    print('=' * 65)
    print(f'  Pool Proxy Status v{VERSION}')
    print('=' * 65)

    # Check proxy
    for port in range(PROXY_PORT, PROXY_PORT + 5):
        try:
            r = urllib.request.urlopen(
                f'http://127.0.0.1:{port}/pool/health', timeout=2)
            d = json.loads(r.read())
            print(f'\n  ✅ Proxy running on :{port}')
            break
        except Exception:
            continue
    else:
        print(f'\n  ✖ Proxy not running (tried :{PROXY_PORT}-:{PROXY_PORT+4})')

    # Check pool engine
    _engine_local = PoolEngine()
    s = _engine_local.get_pool_status()
    p = s['pool']
    print(f'  Pool: {p["total"]} accounts, {p["available"]} available, '
          f'{p["has_api_key"]} apiKeys')
    print(f'  Capacity: D{p["total_daily"]}% · W{p["total_weekly"]}%')

    # Check optimal key file
    if OPTIMAL_KEY_FILE.exists():
        key = OPTIMAL_KEY_FILE.read_text(encoding='utf-8').strip()
        print(f'  Key file: {key[:30]}... ({len(key)} chars)')
    else:
        print(f'  Key file: not found')

    print('=' * 65)


def main():
    args = sys.argv[1:]
    if '--setup' in args:
        print('\n  Setting up Windsurf to use proxy...')
        setup_proxy()
    elif '--restore' in args:
        print('\n  Restoring Windsurf original config...')
        restore_proxy()
    elif '--status' in args:
        cli_status()
    elif not args or args[0] in ('serve', 'start'):
        cli_serve()
    else:
        print(f'Pool Proxy v{VERSION}')
        print(f'  [serve]     Start proxy + pool engine (default)')
        print(f'  --setup     Configure Windsurf → proxy')
        print(f'  --restore   Restore Windsurf original config')
        print(f'  --status    Check proxy + pool status')


if __name__ == '__main__':
    main()
