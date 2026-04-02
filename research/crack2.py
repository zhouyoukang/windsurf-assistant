"""crack2.py — 找 metadata.ide_version 的真实字段号，然后完整测试"""
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

def varint(n):
    out = []
    while n > 0x7F: out.append((n & 0x7F)|0x80); n >>= 7
    out.append(n & 0x7F); return bytes(out)

def f_str(no, s):
    b = s.encode() if isinstance(s, str) else s
    return varint((no<<3)|2) + varint(len(b)) + b

def f_msg(no, m): return varint((no<<3)|2) + varint(len(m)) + m
def f_int(no, v): return varint((no<<3)|0) + varint(v)
def frame(d): return b'\x00' + struct.pack('>I', len(d)) + d

def post(body, timeout=10):
    h = {'Content-Type':'application/connect+proto','Accept':'application/connect+proto',
         'Connect-Protocol-Version':'1','x-codeium-csrf-token':CSRF}
    conn = http.client.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
    conn.request('POST', PATH, frame(body), h)
    r = conn.getresponse(); data = r.read(4096)
    return r.status, data

def decode(body):
    if len(body) < 5: return str(body)
    flag = body[0]; length = struct.unpack('>I', body[1:5])[0]
    pay = body[5:5+length]
    if flag in (0,2):
        try: e = json.loads(pay); return e.get('error',{}).get('message','')[:200]
        except: return str(pay[:200])
    return str(body[:200])

api_key = get_api_key()
print(f"api_key: {api_key[:20]}...")

# chat payload
def prompt(content, role=1):
    return f_msg(6, f_msg(1, f_int(1, role) + f_str(2, content)))

# Strategy: send metadata with ALL string fields 1-15 = 'windsurf' to satisfy any min_len
# This brute-forces past ALL string validation checks at once
print("\n=== Test: metadata with fields 1-15 all = non-empty string ===")
meta_all = b''.join(f_str(i, 'windsurf_v1') for i in range(1, 16))
body = f_msg(1, meta_all) + prompt("Say OPUS46_OK")
s, resp = post(body, timeout=15)
msg = decode(resp)
print(f"  → {msg}")

# Now add api_key at various positions AND all string fields
print("\n=== Test: meta all-fields + api_key at different positions ===")
for ak_field in [4, 5, 6, 7, 8, 9]:
    meta = b''.join(f_str(i, 'windsurf_v1') for i in range(1, 16))
    meta += f_str(ak_field, api_key)  # overwrite with real api_key
    body = f_msg(1, meta) + prompt("Say OPUS46_OK")
    s, resp = post(body, timeout=10)
    msg = decode(resp)
    print(f"  api_key@f{ak_field}: {msg[:120]}")

# If still validation errors, try sending the metadata from JSON
print("\n=== Test: meta minimal correct + longer timeout ===")
# From Codeium OSS: RequestMetadata has ide_name@1, ide_version@2... 
# but maybe GetChatMessageRequest uses a DIFFERENT metadata type
# Try: send metadata type where ide_version could be at field 6 or 8
for ide_v_field in [2, 3, 5, 6, 7, 8, 9, 10]:
    meta = f_str(1, 'windsurf') + f_str(ide_v_field, '1.9577.43') + f_str(4, api_key)
    body = f_msg(1, meta) + prompt("OPUS46_OK")
    s, resp = post(body, timeout=8)
    msg = decode(resp)
    if 'ide_version' not in msg:
        print(f"  ide_version@f{ide_v_field}: DIFFERENT ERROR → {msg[:120]}")
    else:
        print(f"  ide_version@f{ide_v_field}: still ide_version error")

# Final attempt: use the metadata directly from state.vscdb userStatusProto
print("\n=== Test: use actual Windsurf version string ===")
meta = (f_str(1, 'windsurf') +
        f_str(2, '1.9577.43') +
        f_str(3, 'windsurf') +
        f_str(4, api_key) +
        f_str(5, '1.9577.43') +
        f_str(6, 'windsurf') +
        f_str(7, '1.9577.43'))
body = f_msg(1, meta) + prompt("OPUS46_OK")
s, resp = post(body, timeout=15)
print(f"  full_meta: {decode(resp)}")
