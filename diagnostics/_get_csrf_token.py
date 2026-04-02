#!/usr/bin/env python3
"""获取 Windsurf 内部 CSRF Token — 多路径并行探测"""
import sqlite3, json, os, base64, struct, re, urllib.request, urllib.error

STATE_DB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')

def decode_varint(data, pos):
    val=0; shift=0
    while pos < len(data):
        b=data[pos]; pos+=1
        val|=(b&0x7F)<<shift; shift+=7
        if not(b&0x80): break
    return val, pos

def try_http(port, path, method='GET', data=None, headers=None):
    url = f'http://127.0.0.1:{port}{path}'
    h = {'User-Agent':'Mozilla/5.0','Accept':'*/*'}
    if headers: h.update(headers)
    if isinstance(data, dict):
        data = json.dumps(data).encode()
        h['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = resp.read(4000)
            return resp.status, dict(resp.headers), body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read(2000)
    except Exception as e:
        return -1, {}, str(e).encode()

# ── PATH 1: port 1590/1595 (language server config endpoints) ──
print("="*65)
print("PATH 1: LSP config ports (1590, 1595)")
print("="*65)
for port in [1590, 1595, 42913]:
    for path in ['/', '/config', '/info', '/csrf', '/token', '/api', '/status']:
        status, hdrs, body = try_http(port, path)
        if status != -1:
            ct = hdrs.get('content-type', hdrs.get('Content-Type', ''))
            body_str = body.decode('utf-8', errors='replace')[:200]
            print(f"  port {port} {path}: {status} [{ct[:25]}] {body_str[:100]}")
            if status not in (404,):
                break

# ── PATH 2: 从 extension.js 找 CSRF token 在语言服务器启动时的传递 ──
print("\n" + "="*65)
print("PATH 2: extension.js CSRF 传递机制完整链")
print("="*65)
EXT_JS = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT_JS, 'r', encoding='utf-8', errors='replace') as f:
    ext = f.read()

# 找 csrfToken 的完整使用链
csrf_hits = [(m.start(), ext[max(0,m.start()-150):m.start()+300])
             for m in re.finditer(r'csrfToken', ext, re.I)]
print(f"csrfToken hits: {len(csrf_hits)}")
for pos, ctx in csrf_hits[:8]:
    print(f"\n@{pos}:")
    print(ctx[:300])
    print("---")

# ── PATH 3: 找语言服务器配置文件 ──
print("\n" + "="*65)
print("PATH 3: 语言服务器配置文件")
print("="*65)
search_dirs = [
    os.path.expandvars(r'%APPDATA%\Windsurf'),
    os.path.expandvars(r'%LOCALAPPDATA%\Windsurf'),
    os.path.expandvars(r'%USERPROFILE%\.codeium\windsurf'),
]
import glob
for d in search_dirs:
    if os.path.exists(d):
        # Find recent JSON/config files
        for pattern in ['**/*.json', '**/*.conf', '**/*.cfg']:
            files = glob.glob(os.path.join(d, pattern), recursive=True)
            for f in files[:5]:
                try:
                    stat = os.stat(f)
                    if stat.st_size < 10000:
                        with open(f, 'r', encoding='utf-8', errors='replace') as fh:
                            content = fh.read()
                        if 'csrf' in content.lower() or 'chat_client_port' in content.lower():
                            print(f"\n  Found in {f}:")
                            print(f"  {content[:300]}")
                except: pass

# ── PATH 4: windsurfConfigurations 精确 F4 提取 ──
print("\n" + "="*65)
print("PATH 4: windsurfConfigurations F2/F3/F4 (port/csrf_token)")
print("="*65)
conn = sqlite3.connect('file:' + STATE_DB + '?mode=ro', uri=True)
cur = conn.cursor()
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfConfigurations'")
row = cur.fetchone()
conn.close()

if row:
    raw = row[0]
    try:
        data = base64.b64decode(raw) if isinstance(raw, str) else raw
    except:
        data = raw if isinstance(raw, bytes) else raw.encode()

    print(f"Data length: {len(data)}")
    # Full recursive parse to find F4 string values
    pos = 0
    field_map = {}
    while pos < len(data):
        try:
            tag, pos = decode_varint(data, pos)
            fnum = tag >> 3; wtype = tag & 7
            if fnum == 0: break
            if wtype == 0:
                val, pos = decode_varint(data, pos)
                field_map.setdefault(fnum, []).append(('int', val))
            elif wtype == 2:
                length, pos = decode_varint(data, pos)
                val = data[pos:pos+length]; pos += length
                try:
                    t = val.decode('utf-8')
                    if 4 <= len(t) <= 200 and all(32 <= ord(c) < 128 for c in t):
                        field_map.setdefault(fnum, []).append(('str', t))
                except: pass
            elif wtype == 1: pos += 8
            elif wtype == 5: pos += 4
            else: break
        except: break

    print(f"Fields found: {sorted(field_map.keys())}")
    # Print F2, F3, F4 specifically
    for fn in [1, 2, 3, 4, 5, 6, 7, 8, 10]:
        vals = field_map.get(fn, [])
        if vals:
            print(f"  F{fn}: {vals[:3]}")

print("\n=== DONE ===")
