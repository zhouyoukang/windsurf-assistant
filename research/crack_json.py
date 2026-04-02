"""
crack_json.py — 用 JSON 编码代替 binary proto
Connect-RPC 支持 application/connect+json，直接用字段名，跳过所有字段号猜测

JSON-proto 规则:
  - 字段名用 camelCase
  - enum 用 int 或 string
  - repeated = JSON array
"""
import struct, http.client, json, sqlite3

DB_PATH = r"C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb"
PORT = 57407; CSRF = '18e67ec6-8a9b-4781-bcea-ac61a722a640'
PATH = '/exa.language_server_pb.LanguageServerService/GetChatMessage'
MODEL = 'claude-opus-4-6'

def get_api_key():
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    row = cur.fetchone(); conn.close()
    return json.loads(row[0]).get('apiKey', '')

def connect_frame_json(data_bytes):
    """Connect-RPC JSON framing: flag=0 + 4-byte big-endian len + payload"""
    return b'\x00' + struct.pack('>I', len(data_bytes)) + data_bytes

def post_json(payload_dict, timeout=20):
    """Send as application/connect+json"""
    body_bytes = json.dumps(payload_dict).encode('utf-8')
    framed = connect_frame_json(body_bytes)
    h = {
        'Content-Type':             'application/connect+json',
        'Accept':                   'application/connect+json',
        'Connect-Protocol-Version': '1',
        'x-codeium-csrf-token':     CSRF,
    }
    conn = http.client.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
    conn.request('POST', PATH, framed, h)
    r = conn.getresponse()
    data = r.read(8192)
    return r.status, data

def decode(body):
    if len(body) < 5: return str(body[:300])
    flag = body[0]
    length = struct.unpack('>I', body[1:5])[0]
    pay = body[5:5+length]
    try: return json.loads(pay)
    except: return str(pay[:300])

api_key = get_api_key()
print(f"api_key: {api_key[:20]}...")
print(f"port={PORT} csrf={CSRF[:8]}...")
print()

# ─── Test 1: Minimal JSON request ────────────────────────────────────────────
print("=== T1: Minimal JSON ===")
payload = {
    "metadata": {
        "ideName": "windsurf",
        "ideVersion": "1.9577.43"
    },
    "chatMessages": [
        {"role": 1, "content": "Say: OPUS46_OK"}
    ]
}
s, resp = post_json(payload)
r = decode(resp)
print(f"HTTP {s}: {r}")
print()

# ─── Test 2: Add more metadata fields ────────────────────────────────────────
print("=== T2: More metadata ===")
payload2 = {
    "metadata": {
        "ideName": "windsurf",
        "ideVersion": "1.9577.43",
        "extensionVersion": "1.9577.43",
        "apiKey": api_key,
    },
    "chatMessages": [
        {"role": 1, "content": "Say: OPUS46_OK"}
    ]
}
s, resp = post_json(payload2)
r = decode(resp)
print(f"HTTP {s}: {r}")
print()

# ─── Test 3: Full metadata with model ────────────────────────────────────────
print("=== T3: Full metadata + model ===")
payload3 = {
    "metadata": {
        "ideName": "windsurf",
        "ideVersion": "1.9577.43",
        "extensionName": "windsurf",
        "extensionVersion": "1.9577.43",
        "apiKey": api_key,
        "sessionId": "test-session-001",
        "requestId": "req-001",
    },
    "chatMessages": [
        {"role": 1, "content": "Reply with exactly: OPUS46_DIRECT_WORKS"}
    ],
    "model": MODEL,
    "modelUid": MODEL,
}
s, resp = post_json(payload3)
r = decode(resp)
print(f"HTTP {s}: {r}")
print()

# ─── Test 4: Try different field names for chat messages ─────────────────────
print("=== T4: Different chat field names ===")
for field_name in ['chatMessages', 'messages', 'chat_messages', 'prompt', 'chatMessagePrompts']:
    payload4 = {
        "metadata": {"ideName": "windsurf", "ideVersion": "1.9577.43", "apiKey": api_key},
        field_name: [{"role": 1, "content": "OPUS46_OK"}]
    }
    s, resp = post_json(payload4, timeout=8)
    r = decode(resp)
    err_msg = r.get('error', {}).get('message', str(r))[:120] if isinstance(r, dict) else str(r)[:120]
    print(f"  {field_name}: {err_msg}")
print()

# ─── Test 5: Look at actual validation error for field names ─────────────────
print("=== T5: Empty request to see ALL required fields ===")
s, resp = post_json({}, timeout=8)
r = decode(resp)
print(f"HTTP {s}: {r}")
print()

# ─── Test 6: Long timeout attempt ────────────────────────────────────────────
print("=== T6: Full request with 60s timeout ===")
payload6 = {
    "metadata": {
        "ideName": "windsurf",
        "ideVersion": "1.9577.43",
        "extensionVersion": "1.9577.43",
        "apiKey": api_key,
        "userId": "",
    },
    "chatMessages": [
        {
            "role": 1,
            "content": "Reply with exactly three words: OPUS FORTY SIX"
        }
    ],
    "model": MODEL,
}
print(f"Sending {MODEL} request... (60s timeout)")
s, resp = post_json(payload6, timeout=60)
r = decode(resp)
print(f"HTTP {s}: {r}")
if isinstance(r, dict) and 'error' not in r:
    print("\n🎉 SUCCESS! Claude Opus 4.6 direct call works!")
elif isinstance(r, dict):
    err = r.get('error', {})
    print(f"Error: {err.get('code')} — {err.get('message', '')[:300]}")
