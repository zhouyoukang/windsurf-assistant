"""
opus46_final.py — 最终突破脚本
基于 crack_proto.py 的分析结果:
  - Field 1 = metadata (required, must have ide_name)
  - Field 6 = chat_message_prompts (message)
  - metadata.field_1 = ide_name (string, required, min_len=1)
  - metadata.field_4 = api_key (string)
  - Proto pkg: chat_pb.GetChatMessageRequest
"""
import struct, http.client, json, sqlite3

DB_PATH = r"C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb"
PORT    = 57407
CSRF    = '18e67ec6-8a9b-4781-bcea-ac61a722a640'
PATH    = '/exa.language_server_pb.LanguageServerService/GetChatMessage'
MODEL   = 'claude-opus-4-6'

def get_api_key():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    row  = cur.fetchone(); conn.close()
    return json.loads(row[0]).get('apiKey', '')

def varint(n):
    out = []
    while n > 0x7F:
        out.append((n & 0x7F)|0x80); n >>= 7
    out.append(n & 0x7F)
    return bytes(out)

def f_str(no, s):
    b = s.encode() if isinstance(s, str) else s
    return varint((no<<3)|2) + varint(len(b)) + b

def f_msg(no, m):
    return varint((no<<3)|2) + varint(len(m)) + m

def f_int(no, v):
    return varint((no<<3)|0) + varint(v)

def frame(data):
    return b'\x00' + struct.pack('>I', len(data)) + data

def post(body, timeout=30):
    h = {'Content-Type':             'application/connect+proto',
         'Accept':                   'application/connect+proto',
         'Connect-Protocol-Version': '1',
         'x-codeium-csrf-token':     CSRF}
    conn = http.client.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
    conn.request('POST', PATH, frame(body), h)
    r    = conn.getresponse()
    data = r.read(8192)
    return r.status, data

def decode(body):
    if len(body) < 5: return body
    flag   = body[0]
    length = struct.unpack('>I', body[1:5])[0]
    pay    = body[5:5+length]
    if flag in (0, 2):
        try: return json.loads(pay)
        except: return pay
    return body

api_key = get_api_key()
print(f"API key: {api_key[:20]}...\n")

# ─── 逐步修复 metadata 字段 ────────────────────────────────────────────────────
print("=== Phase 1: Fix metadata ===")

# ChatMessage: role=USER(1), content=field2
def chat_message(content, role=1):
    return f_int(1, role) + f_str(2, content)

# ChatMessagePrompt: field1=message
def chat_prompt(content, role=1):
    return f_msg(1, chat_message(content, role))

test_msg = "Reply with exactly: OPUS46_WORKS"

# Iteration 1: ide_name only
meta_v1 = f_str(1, 'windsurf')
body_v1 = f_msg(1, meta_v1) + f_msg(6, chat_prompt(test_msg))
s, resp = post(body_v1)
r1 = decode(resp)
print(f"v1 (ide_name only): {r1}")

# Iteration 2: ide_name + api_key
meta_v2 = f_str(1, 'windsurf') + f_str(4, api_key)
body_v2 = f_msg(1, meta_v2) + f_msg(6, chat_prompt(test_msg))
s, resp = post(body_v2)
r2 = decode(resp)
print(f"v2 (+api_key): {r2}")

# Iteration 3: ide_name + ide_version + extension + api_key
meta_v3 = (f_str(1, 'windsurf') +
           f_str(2, '1.9577.43') +
           f_str(3, 'windsurf') +
           f_str(4, api_key))
body_v3 = f_msg(1, meta_v3) + f_msg(6, chat_prompt(test_msg))
s, resp = post(body_v3)
r3 = decode(resp)
print(f"v3 (+version+ext): {r3}")

# Iteration 4: add model at various field positions
for model_field in [2, 3, 5, 10, 11, 12, 13, 15]:
    meta = f_str(1, 'windsurf') + f_str(4, api_key)
    body = f_msg(1, meta) + f_msg(6, chat_prompt(test_msg)) + f_str(model_field, MODEL)
    s, resp = post(body, timeout=8)
    r = decode(resp)
    if isinstance(r, dict):
        code = r.get('error', {}).get('code', '?')
        msg  = r.get('error', {}).get('message', '')[:100]
        print(f"  model@f{model_field}: {code} — {msg}")
    else:
        print(f"  model@f{model_field}: {r}")

print("\n=== Phase 2: Try meta+prompt with long timeout ===")
meta = f_str(1, 'windsurf') + f_str(4, api_key)
body = f_msg(1, meta) + f_msg(6, chat_prompt(test_msg))
print(f"Sending with 60s timeout...")
s, resp = post(body, timeout=60)
r = decode(resp)
print(f"HTTP {s}: {r}")
if s == 200 and isinstance(r, dict) and 'error' not in r:
    print("\n✅ SUCCESS!")
else:
    # Check full validation error
    if isinstance(r, dict):
        err = r.get('error', {})
        print(f"Code: {err.get('code')}")
        print(f"Full message: {err.get('message')}")
