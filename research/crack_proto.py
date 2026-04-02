"""
crack_proto.py — 通过试错找到正确的 GetChatMessageRequest proto 格式
关键状态: CSRF 通过, 路径正确, 只差 proto 格式
端口: 57407 (csrf=18e67ec6), 64958 (csrf=38a7a689)
"""
import struct, http.client, json, sqlite3, re, sys

DB_PATH = r"C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb"

def get_api_key():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    row  = cur.fetchone(); conn.close()
    return json.loads(row[0]).get('apiKey', '')

# proto encoding
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

# HTTP call to LS
PORT  = 57407
CSRF  = '18e67ec6-8a9b-4781-bcea-ac61a722a640'
PATH  = '/exa.language_server_pb.LanguageServerService/GetChatMessage'
MODEL = 'claude-opus-4-6'

def post(body, timeout=8):
    h = {'Content-Type':'application/connect+proto',
         'Accept':'application/connect+proto',
         'Connect-Protocol-Version':'1',
         'x-codeium-csrf-token': CSRF}
    try:
        conn = http.client.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
        conn.request('POST', PATH, frame(body), h)
        r = conn.getresponse()
        return r.status, r.read(4096)
    except Exception as e:
        return 0, str(e).encode()

def decode_connect_error(body):
    """解码 Connect-RPC 错误响应"""
    if len(body) < 5:
        return body
    flag = body[0]
    length = struct.unpack('>I', body[1:5])[0]
    payload = body[5:5+length]
    if flag == 2:  # end-stream error
        try:
            return json.loads(payload)
        except:
            return payload
    return body

api_key = get_api_key()
print(f"API key: {api_key[:20]}...")
print(f"Testing port {PORT} path {PATH}\n")

# ─── Test 1: empty body ───────────────────────────────────────────────────────
print("T1: empty body")
s, body = post(b'')
print(f"  HTTP {s}: {decode_connect_error(body)}\n")

# ─── Test 2: 从 extension.js 找实际字段定义 ──────────────────────────────────
print("T2: scanning extension.js for proto fields...")
EXT_JS = r"D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
with open(EXT_JS, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# 找所有 GetChatMessage 相关的 proto 类定义
# 模式: class X extends Y { static fields = ...newFieldList([{no:...,name:...}])
field_pattern = r'no:(\d+),name:"([^"]+)",kind:"([^"]+)"(?:,T:([^,}\]]+))?'

for kw in ['GetChatMessage', 'ChatMessagePrompt', 'ChatMessage', 'RequestMetadata']:
    idx = content.find(kw)
    if idx < 0:
        continue
    # 找这个类的字段列表
    region = content[idx:idx+2000]
    fields = re.findall(field_pattern, region)
    if fields:
        print(f"\n  [{kw}] fields:")
        for no, name, kind, T in fields[:15]:
            print(f"    field {no}: {name} ({kind}{',' + T[:30] if T else ''})")

# ─── Test 3: 基于常见 Codeium proto 格式构建请求 ──────────────────────────────
print("\n\nT3: testing common Codeium API proto formats...")

# RequestMetadata (field 1 in most requests)
# Field 4 = api_key in RequestMetadata
meta = f_str(4, api_key)  # api_key in metadata

# EditorInfo (field 2)
# editor_info with ide_name
editor = f_str(1, 'windsurf') + f_str(2, '1.9577.43')

# ChatMessage (role=USER=1, content=field2)
chat_msg = f_int(1, 1) + f_str(2, 'Reply with: OPUS46_OK')

# ChatMessagePrompt (field 1 = message)
prompt = f_msg(1, chat_msg)

# Layouts to try for GetChatMessageRequest
layouts = {
    'meta_only':        f_msg(1, meta),
    'meta+model':       f_msg(1, meta) + f_str(3, MODEL),
    'meta+prompt':      f_msg(1, meta) + f_msg(6, prompt),
    'meta+editor':      f_msg(1, meta) + f_msg(2, editor),
    'meta+editor+model+prompt': f_msg(1, meta) + f_msg(2, editor) + f_str(3, MODEL) + f_msg(6, prompt),
    'model+prompt':     f_str(3, MODEL) + f_msg(6, prompt),
    'just_prompt':      f_msg(6, prompt),
    # Try field numbers for model differently
    'model_f1+prompt':  f_str(1, MODEL) + f_msg(6, prompt),
    'model_f5+prompt':  f_str(5, MODEL) + f_msg(6, prompt),
    'model_f7+prompt':  f_str(7, MODEL) + f_msg(6, prompt),
    # meta with api_key at different fields
    'meta_f1+prompt':   f_str(1, api_key) + f_msg(6, prompt),
    # Very minimal
    'meta_minimal':     f_msg(1, f_str(1, 'windsurf')) + f_msg(6, prompt),
}

best = None
for name, body in layouts.items():
    s, resp = post(body, timeout=6)
    err = decode_connect_error(resp)
    if isinstance(err, dict):
        code = err.get('error', {}).get('code', 'unknown')
        msg  = err.get('error', {}).get('message', '')[:80]
        print(f"  [{name}]: {code} — {msg}")
        if code not in ('invalid_argument', 'unauthenticated'):
            best = (name, body, code, msg)
            print(f"  *** DIFFERENT RESPONSE! ***")
    elif s == 0:
        pass  # timeout
    else:
        print(f"  [{name}]: HTTP {s} raw={resp[:60]}")

if best:
    print(f"\nBest layout: {best[0]} → {best[2]}: {best[3]}")
else:
    print("\nAll got invalid_argument or auth errors — need more fields")
    print("Trying with 30s timeout for streaming response...")
    s, resp = post(f_msg(1, meta) + f_msg(6, prompt), timeout=30)
    print(f"  Extended timeout: HTTP {s}, {len(resp)} bytes")
    if len(resp) > 5:
        print(f"  Content: {resp[:500]}")
