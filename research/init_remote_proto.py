"""
init_remote_proto.py — 用 binary proto / grpc-web 直调 server.codeium.com
InitializeCascadePanelState 路径存在 (HTTP 415 for JSON = path OK, wrong CT)
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

# Connect-RPC frame (flag byte + 4-byte length)
def frm(d): return b'\x00' + struct.pack('>I', len(d)) + d

# gRPC-Web frame (flag byte + 4-byte length, same as Connect-RPC!)
def grpc_web_frm(d): return b'\x00' + struct.pack('>I', len(d)) + d

api_key = get_api_key()
print(f"api: {api_key[:20]}...\n")

HOST = 'server.codeium.com'
PATH_INIT = '/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState'
PATH_CHAT = '/exa.language_server_pb.LanguageServerService/RawGetChatMessage'

meta_proto = fs(1,'windsurf') + fs(7,'1.9577.43') + fs(3,'windsurf') + fs(4,api_key)

def https_call(host, path, api_key, body_bytes, ct, timeout=15):
    ctx = ssl.create_default_context()
    framed = frm(body_bytes)
    h = {
        'Content-Type': ct, 'Accept': ct,
        'Connect-Protocol-Version': '1',
        'Authorization': f'Bearer {api_key}',
        'x-request-id': str(uuid.uuid4()),
    }
    conn = http.client.HTTPSConnection(host, 443, timeout=timeout, context=ctx)
    conn.request('POST', path, framed, h)
    r = conn.getresponse()
    resp = r.read(4096)
    return r.status, dict(r.headers), resp

def parse(data):
    out = []
    pos = 0
    while pos < len(data):
        if pos + 5 > len(data): break
        flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]; pos += 5 + length
        try: out.append((flag, json.loads(chunk)))
        except: out.append((flag, chunk))
    return out

# Build InitializeCascadePanelState request (binary proto)
# Fields: metadata(1) + workspaceRootPath(2?) + workspaceName(3?)
init_body = fm(1, meta_proto) + fs(2, 'e:/道/道生一/一生二') + fs(3, '一生二')

print("=== Test all Content-Types for InitializeCascadePanelState ===")
content_types = [
    'application/connect+proto',
    'application/grpc-web+proto',
    'application/grpc-web',
    'application/grpc',
    'application/proto',
]
for ct in content_types:
    try:
        s, hdrs, raw = https_call(HOST, PATH_INIT, api_key, init_body, ct, timeout=10)
        results = parse(raw)
        if results:
            flag, obj = results[0]
            if isinstance(obj, dict):
                e = obj.get('error', {}).get('message', '')[:150]
                print(f"  [{ct}]: HTTP {s} → {e or json.dumps(obj)[:150]}")
            else:
                print(f"  [{ct}]: HTTP {s} → {raw[:100]}")
        else:
            print(f"  [{ct}]: HTTP {s} → {raw[:80]}")
    except Exception as ex:
        print(f"  [{ct}]: {ex}")

# Also try with empty body
print("\n=== Empty body variants ===")
for ct in ['application/connect+proto', 'application/grpc-web+proto']:
    try:
        s, hdrs, raw = https_call(HOST, PATH_INIT, api_key, b'', ct, timeout=8)
        print(f"  empty [{ct}]: HTTP {s} → {raw[:100]}")
    except Exception as ex:
        print(f"  empty [{ct}]: {ex}")

# ── Also test RawGetChatMessage directly on server.codeium.com ────────────────
print("\n=== RawGetChatMessage direct (binary proto) ===")
conv_id = str(uuid.uuid4())
msg_id  = str(uuid.uuid4())

# ChatMessage fields (from JSON exploration, mapping to proto):
# role=USER=1, content, messageId, timestamp, conversationId
# In proto, Timestamp is a message {seconds=int64, nanos=int32}
import time
now_secs = int(time.time())
ts_proto = fi(1, now_secs) + fi(2, 0)  # Timestamp{seconds, nanos}

chat_msg_proto = (
    fs(1, msg_id)       +  # messageId (field 1)
    fi(2, 1)            +  # role=USER (field 2)
    fs(3, 'Reply with exactly: OPUS46_WORKS') +  # content (field 3)
    fm(4, ts_proto)     +  # timestamp (field 4, Timestamp message)
    fs(5, conv_id)         # conversationId (field 5)
)

# Try different positions for chatMessages in the request
for cm_field in [2, 3, 5, 6, 7]:
    body = fm(1, meta_proto) + fm(cm_field, chat_msg_proto) + fs(10, 'claude-opus-4-6')
    try:
        s, hdrs, raw = https_call(HOST, PATH_CHAT, api_key, body,
                                   'application/connect+proto', timeout=15)
        results = parse(raw)
        if results:
            flag, obj = results[0]
            e = obj.get('error', {}).get('message', '')[:150] if isinstance(obj, dict) else str(raw[:100])
            print(f"  chat@f{cm_field}: HTTP {s} → {e or json.dumps(obj)[:150]}")
        else:
            print(f"  chat@f{cm_field}: HTTP {s} → {raw[:80]}")
    except Exception as ex:
        print(f"  chat@f{cm_field}: {ex}")

# ── Final: Local JSON with Proto timestamp ────────────────────────────────────
print("\n=== Local JSON RawGetChatMessage with all fields ===")
PORT = 57407; CSRF = '18e67ec6-8a9b-4781-bcea-ac61a722a640'

import datetime
ts_str = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

payload = {
    'metadata': {
        'ideName': 'windsurf', 'ideVersion': '1.9577.43',
        'extensionVersion': '1.9577.43', 'apiKey': api_key,
    },
    'chatMessages': [{
        'messageId': str(uuid.uuid4()), 'role': 1,
        'content': 'Reply with: OPUS46_REMOTE',
        'timestamp': ts_str,
        'conversationId': str(uuid.uuid4()),
    }],
    'model': 'claude-opus-4-6',
}
body2 = json.dumps(payload).encode()
framed2 = frm(body2)
h2 = {'Content-Type':'application/connect+json','Accept':'application/connect+json',
      'Connect-Protocol-Version':'1','x-codeium-csrf-token':CSRF}
conn2 = http.client.HTTPConnection('127.0.0.1', PORT, timeout=30)
conn2.request('POST','/exa.language_server_pb.LanguageServerService/RawGetChatMessage',framed2,h2)
r2 = conn2.getresponse()
data2 = r2.read(8192)
results2 = parse(data2)
for flag, obj in results2:
    if isinstance(obj, dict):
        dm = obj.get('deltaMessage', {})
        text = dm.get('text', '')
        err = obj.get('error', {})
        if text: print(f"  [{flag}] {'ERR' if dm.get('isError') else 'OK'}: {text[:200]}")
        if err: print(f"  [{flag}] error: {err.get('message','')[:200]}")
