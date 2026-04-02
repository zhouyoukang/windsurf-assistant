"""
remote_init.py — 直连远端服务器，建立 cascade session，再调 RawGetChatMessage
关键洞察:
  - InitializeCascadePanelState 不在本地 LS (返回 415)
  - 必须直接调 server.codeium.com 远端接口
  - 建立 session 后, 本地 RawGetChatMessage 就可以工作
"""
import struct, http.client, ssl, json, sqlite3, uuid

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'

def get_api_key():
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    row = cur.fetchone(); conn.close()
    return json.loads(row[0]).get('apiKey', '')

def vi(n):
    out = []
    while n > 0x7F: out.append((n & 0x7F)|0x80); n >>= 7
    out.append(n & 0x7F); return bytes(out)
def fs(no, s):
    b = s.encode() if isinstance(s, str) else s
    return vi((no<<3)|2) + vi(len(b)) + b
def fm(no, m): return vi((no<<3)|2) + vi(len(m)) + m
def fi(no, v): return vi((no<<3)|0) + vi(v)
def frm(d): return b'\x00' + struct.pack('>I', len(d)) + d

def https_post(host, path, api_key, body_json_or_proto, use_json=True, timeout=20):
    ctx = ssl.create_default_context()
    ct = 'application/connect+json' if use_json else 'application/connect+proto'
    if use_json:
        data = json.dumps(body_json_or_proto).encode()
    else:
        data = body_json_or_proto
    framed = frm(data)
    h = {
        'Content-Type': ct, 'Accept': ct,
        'Connect-Protocol-Version': '1',
        'Authorization': f'Bearer {api_key}',
        'x-request-id': str(uuid.uuid4()),
    }
    conn = http.client.HTTPSConnection(host, 443, timeout=timeout, context=ctx)
    conn.request('POST', path, framed, h)
    r = conn.getresponse(); resp = r.read(4096)
    return r.status, dict(r.headers), resp

def parse(data, mode='json'):
    out = []
    pos = 0
    while pos < len(data):
        if pos + 5 > len(data): break
        flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]; pos += 5 + length
        if mode == 'json':
            try: out.append((flag, json.loads(chunk)))
            except: out.append((flag, chunk))
        else:
            out.append((flag, chunk))
    return out

def err(results):
    for flag, obj in results:
        if isinstance(obj, dict):
            if 'error' in obj: return obj['error'].get('message','')[:200]
            dm = obj.get('deltaMessage', {})
            if dm.get('text'): return ('[ERR]' if dm.get('isError') else '[OK]') + dm['text'][:150]
    return str(results[0][1])[:200] if results else ''

api_key = get_api_key()
print(f"api: {api_key[:20]}...\n")

meta_json = {
    'ideName': 'windsurf', 'ideVersion': '1.9577.43',
    'extensionVersion': '1.9577.43', 'apiKey': api_key,
}

# ── TEST 1: InitializeCascadePanelState on remote servers ─────────────────────
print("=== TEST 1: InitializeCascadePanelState on remote servers ===")
init_payload = {
    'metadata': meta_json,
    'workspaceRootPath': 'e:/道/道生一/一生二',
}
for host in ['server.codeium.com', 'inference.codeium.com']:
    for path in [
        '/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState',
        '/exa.cascade_pb.CascadeService/InitializeCascadePanelState',
    ]:
        try:
            s, hdrs, raw = https_post(host, path, api_key, init_payload, use_json=True, timeout=10)
            results = parse(raw, 'json')
            e = err(results)
            print(f"  {host}{path}: HTTP {s} → {e[:100]}")
        except Exception as ex:
            print(f"  {host}{path}: {str(ex)[:60]}")

# ── TEST 2: Route discovery ────────────────────────────────────────────────────
print("\n=== TEST 2: Route discovery ===")
for host in ['windsurf.fedstart.com', 'server.codeium.com']:
    for path in ['/_route/api_server', '/_route/cascade', '/api/v1/cascade/init']:
        try:
            ctx = ssl.create_default_context()
            conn = http.client.HTTPSConnection(host, 443, timeout=8, context=ctx)
            conn.request('GET', path, headers={'Authorization': f'Bearer {api_key}'})
            r = conn.getresponse()
            body = r.read(500)
            print(f"  {host}{path}: HTTP {r.status} → {body[:100]}")
        except Exception as ex:
            print(f"  {host}{path}: {str(ex)[:60]}")

# ── TEST 3: RawGetChatMessage directly on remote ───────────────────────────────
print("\n=== TEST 3: RawGetChatMessage directly on server.codeium.com ===")
conv_id = str(uuid.uuid4())
chat_payload = {
    'metadata': meta_json,
    'chatMessages': [{
        'messageId': str(uuid.uuid4()), 'role': 1,
        'content': 'Reply with: OPUS46_REMOTE_DIRECT',
        'timestamp': '2026-03-30T21:49:00Z',
        'conversationId': conv_id,
    }],
    'model': 'claude-opus-4-6',
}
for host in ['server.codeium.com', 'inference.codeium.com']:
    path = '/exa.language_server_pb.LanguageServerService/RawGetChatMessage'
    try:
        s, hdrs, raw = https_post(host, path, api_key, chat_payload, use_json=True, timeout=20)
        results = parse(raw, 'json')
        e = err(results)
        print(f"  {host}: HTTP {s} → {e[:150]}")
    except Exception as ex:
        print(f"  {host}: {str(ex)[:80]}")

# ── TEST 4: Get current windsurf server URL from fedstart route ───────────────
print("\n=== TEST 4: Dynamic server from windsurf.fedstart.com ===")
try:
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection('windsurf.fedstart.com', 443, timeout=10, context=ctx)
    conn.request('GET', '/_route/api_server', headers={
        'Authorization': f'Bearer {api_key}',
        'User-Agent': 'windsurf/1.9577.43'
    })
    r = conn.getresponse(); body = r.read(500)
    print(f"  HTTP {r.status}: {body.decode('utf-8','replace')[:300]}")
except Exception as ex:
    print(f"  error: {ex}")

# ── TEST 5: Local RawGetChatMessage with detailed response inspection ──────────
print("\n=== TEST 5: Local RawGetChatMessage - get FULL error detail ===")
PORT = 57407; CSRF = '18e67ec6-8a9b-4781-bcea-ac61a722a640'
full_payload = {
    'metadata': meta_json,
    'chatMessages': [{
        'messageId': str(uuid.uuid4()), 'role': 1,
        'content': 'Reply with: OPUS46_BREAKTHROUGH',
        'timestamp': '2026-03-30T21:49:00Z',
        'conversationId': str(uuid.uuid4()),
    }],
    'model': 'claude-opus-4-6',
}
body_bytes = json.dumps(full_payload).encode()
framed = frm(body_bytes)
h = {'Content-Type':'application/connect+json','Accept':'application/connect+json',
     'Connect-Protocol-Version':'1','x-codeium-csrf-token':CSRF}
conn2 = http.client.HTTPConnection('127.0.0.1', PORT, timeout=30)
conn2.request('POST','/exa.language_server_pb.LanguageServerService/RawGetChatMessage',framed,h)
r2 = conn2.getresponse()
print(f"  HTTP {r2.status}, headers: {dict(r2.headers)}")
data2 = r2.read(8192)
results2 = parse(data2, 'json')
for flag, obj in results2:
    print(f"  [{flag}]: {json.dumps(obj, ensure_ascii=False)[:400] if isinstance(obj,dict) else obj[:200]}")
