#!/usr/bin/env python3
"""逆向 Windsurf 内部 API port 1588 — 找 CSRF token + 探测所有端点"""
import urllib.request, urllib.error, json, sqlite3, os, re

STATE_DB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')
PORT = 1588

def try_get(path, headers=None, data=None):
    url = f'http://127.0.0.1:{PORT}{path}'
    h = {'User-Agent': 'Mozilla/5.0', 'Accept': '*/*', 'Origin': 'vscode-file://vscode-app'}
    if headers: h.update(headers)
    method = 'POST' if data else 'GET'
    body = json.dumps(data).encode() if isinstance(data, dict) else data
    if isinstance(data, dict): h['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            raw = resp.read(2000)
            return resp.status, dict(resp.headers), raw
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read(2000)
    except Exception as e:
        return -1, {}, str(e).encode()

# ── 1. 查找 CSRF token ──
print("=" * 60)
print("STEP 1: 查找 CSRF Token")
print("=" * 60)

# 从 state.vscdb 搜索 csrf/token
conn = sqlite3.connect('file:' + STATE_DB + '?mode=ro', uri=True)
cur = conn.cursor()
cur.execute("SELECT key, length(value) FROM ItemTable WHERE key LIKE '%csrf%' OR key LIKE '%token%' OR key LIKE '%nonce%'")
rows = cur.fetchall()
print(f"CSRF/token keys in state.vscdb: {rows}")

# 也查找 windsurf internal server token
cur.execute("SELECT key, substr(value,1,100) FROM ItemTable WHERE key LIKE '%server%' OR key LIKE '%internal%' OR key LIKE '%port%'")
rows2 = cur.fetchall()
print(f"Server/port keys: {rows2}")
conn.close()

# ── 2. 探测 port 1588 端点 ──
print("\n" + "=" * 60)
print("STEP 2: 探测 port 1588 端点")
print("=" * 60)

paths = [
    '/', '/favicon.ico', '/api', '/api/v1',
    '/api/auth', '/api/login',
    '/rpc', '/ws', '/socket',
    '/api/models', '/api/chat', '/api/completion',
    '/api/cascade', '/cascade/api',
    '/api/windsurf', '/windsurf',
    '/session', '/api/session',
    '/info', '/version', '/health',
    '/_cascade', '/_api',
]

print(f"\nPort {PORT} endpoint scan:")
found = []
for path in paths:
    status, hdrs, body = try_get(path)
    if status != -1:
        body_str = body.decode('utf-8', errors='replace')[:100]
        ct = hdrs.get('content-type', hdrs.get('Content-Type', '?'))
        print(f"  {status} {path:30} [{ct[:30]}] {body_str[:80]}")
        if status not in (404,):
            found.append((status, path, body_str))

print(f"\nInteresting endpoints: {len(found)}")
for s, p, b in found:
    print(f"  {s} {p}: {b[:100]}")

# ── 3. 查看响应头中是否有 CSRF token ──
print("\n" + "=" * 60)
print("STEP 3: 从响应头提取 CSRF token")
print("=" * 60)
status, hdrs, body = try_get('/')
print(f"Root response: {status}")
print(f"Headers: {json.dumps({k:v for k,v in hdrs.items()}, indent=2)[:500]}")
body_str = body.decode('utf-8', errors='replace')
print(f"Body (500B): {body_str[:500]}")

# ── 4. 查找 workbench.js 中对 port 1588 的引用 ──
print("\n" + "=" * 60)
print("STEP 4: workbench.js 中 port 1588 的 API 路径")
print("=" * 60)

WB_JS = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
with open(WB_JS, 'r', encoding='utf-8', errors='replace') as f:
    wb = f.read()

# 查找 CSRF 处理逻辑
for pattern in ['csrf', 'CSRF', 'Invalid CSRF', 'csrfToken', 'x-csrf']:
    hits = [m.start() for m in re.finditer(pattern, wb, re.I)]
    if hits:
        pos = hits[0]
        ctx = wb[max(0, pos-100):pos+300]
        print(f"\n[{pattern}] {len(hits)} hits, first @{pos}:")
        print(ctx[:350])

# 查找 port 1588 相关路由
for pattern in [r'"/api/', r"'/api/", r'route:', r'express', r'app\.get', r'app\.post']:
    m = re.search(pattern, wb, re.I)
    if m:
        pos = m.start()
        print(f"\n[{pattern}] @{pos}: {wb[pos:pos+200][:200]}")
