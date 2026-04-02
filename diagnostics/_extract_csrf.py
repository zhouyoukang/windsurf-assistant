#!/usr/bin/env python3
"""提取 CSRF token + 深度解析 windsurfConfigurations"""
import sqlite3, json, os, base64, struct, re, urllib.request, urllib.error

STATE_DB = os.path.expandvars(r'%APPDATA%\\Windsurf\\User\\globalStorage\\state.vscdb')
PORT = 1588

def decode_varint(data, pos):
    val=0; shift=0
    while pos < len(data):
        b=data[pos]; pos+=1
        val|=(b&0x7F)<<shift; shift+=7
        if not(b&0x80): break
    return val, pos

def extract_all_strings(data, min_len=4, max_len=500):
    results = []
    pos = 0
    while pos < len(data):
        try:
            tag, pos = decode_varint(data, pos)
            fnum=tag>>3; wtype=tag&7
            if fnum==0: break
            if wtype==2:
                length, pos = decode_varint(data, pos)
                val = data[pos:pos+length]; pos+=length
                try:
                    t = val.decode('utf-8')
                    if min_len<=len(t)<=max_len and all(32<=ord(c)<128 for c in t):
                        results.append((fnum, t))
                except: pass
            elif wtype==0: _, pos = decode_varint(data, pos)
            elif wtype==1: pos+=8
            elif wtype==5: pos+=4
            else: break
        except: break
    return results

conn = sqlite3.connect('file:'+STATE_DB+'?mode=ro', uri=True)
cur = conn.cursor()

# ── 1. windsurfConfigurations ──
print("="*65)
print("windsurfConfigurations 深度解析")
print("="*65)
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfConfigurations'")
row = cur.fetchone()
if row:
    raw = row[0]
    print(f"Value type: {type(raw).__name__}, len: {len(raw)}")
    # Try base64 decode
    try:
        data = base64.b64decode(raw)
        strs = extract_all_strings(data)
        print(f"\nProtobuf strings ({len(strs)}):")
        csrf_tokens = []
        ports = []
        for fn, s in strs:
            print(f"  F{fn:3d}: {s[:120]}")
            if re.match(r'^[a-f0-9]{16,}$', s) or len(s)==36 and s.count('-')==4:
                csrf_tokens.append(s)
            if s.isdigit() and 1000<=int(s)<=65535:
                ports.append(s)
        if csrf_tokens: print(f"\nPossible CSRF tokens: {csrf_tokens}")
        if ports: print(f"Possible ports: {ports}")
    except Exception as e:
        print(f"base64 decode failed: {e}")
        # Try raw text
        if isinstance(raw, str):
            print(f"Raw text: {raw[:500]}")
        elif isinstance(raw, bytes):
            print(f"Raw hex: {raw[:200].hex()}")
            strs = extract_all_strings(raw)
            print(f"Direct pb strings: {strs[:20]}")

# ── 2. 所有key扫描找csrf/token相关 ──
print("\n" + "="*65)
print("全量key扫描 (csrf/token/port相关)")
print("="*65)
cur.execute("SELECT key FROM ItemTable")
all_keys = [r[0] for r in cur.fetchall()]
print(f"Total keys: {len(all_keys)}")
interesting = [k for k in all_keys if any(x in k.lower() for x in
    ['csrf', 'token', 'port', 'cascade', 'internal', 'server', 'url', 'secret'])]
print(f"Interesting keys ({len(interesting)}):")
for k in interesting:
    cur.execute("SELECT substr(value,1,200) FROM ItemTable WHERE key=?", (k,))
    v = cur.fetchone()
    print(f"  {k[:60]}: {str(v[0])[:100] if v else 'NULL'}")

# ── 3. webview storage 搜索 ──
print("\n" + "="*65)
print("WebStorage (LocalStorage) 中搜索 csrf/port")
print("="*65)
ws_path = os.path.expandvars(r'%APPDATA%\Windsurf\User\workspaceStorage')
if os.path.exists(ws_path):
    ws_db = os.path.join(ws_path, 'backup.db')
    if not os.path.exists(ws_db):
        # Find any .db files
        import glob
        dbs = glob.glob(os.path.join(ws_path, '**', '*.db'), recursive=True)[:3]
        print(f"  Found DBs: {dbs}")
# Also check globalStorage webstorage
gs_ws = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\backup.db')
if os.path.exists(gs_ws):
    wc = sqlite3.connect('file:'+gs_ws+'?mode=ro', uri=True)
    wc.execute("SELECT key,substr(value,1,100) FROM ItemTable WHERE key LIKE '%csrf%' OR key LIKE '%token%' OR key LIKE '%port%'")
    for row in wc.fetchall():
        print(f"  {row[0]}: {row[1]}")
    wc.close()

# ── 4. 直接从 extension.js 查找 CSRF 生成 ──
print("\n" + "="*65)
print("extension.js CSRF token 生成机制")
print("="*65)
EXT_JS = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
if os.path.exists(EXT_JS):
    with open(EXT_JS, 'r', encoding='utf-8', errors='replace') as f:
        ext = f.read()
    # 找 csrfToken 或 csrf 生成
    for pat in ['csrfToken', 'csrf_token', 'randomUUID', 'generateToken', 'CSRF']:
        hits = [m.start() for m in re.finditer(pat, ext, re.I)]
        if hits:
            pos = hits[0]
            ctx = ext[max(0,pos-100):pos+250]
            print(f"\n[{pat}] {len(hits)} hits, first @{pos}:")
            print(ctx[:300])

conn.close()
print("\n=== DONE ===")
