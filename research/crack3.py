"""
crack3.py — 精确定位 chat_messages 字段号 + source_address 字段号
已知:
  - metadata.ide_name   = field 1
  - metadata.ide_version = field 7
  - chat_messages 不在 request.field6，在 request.field2-5 之一
  - metadata.source_address = valid IP，在 metadata 某字段
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

def err(body):
    if len(body) < 5: return str(body[:100])
    pay = body[5:5+struct.unpack('>I',body[1:5])[0]]
    try: e = json.loads(pay); return e.get('error',{}).get('message','')[:200]
    except: return str(pay[:200])

api_key = get_api_key()
print(f"api_key: {api_key[:20]}...\n")

# Build metadata: known working fields
# field 1=ide_name, field 7=ide_version
# fill field 2-6 with plausible values, field 8-15 also
def meta_base(extra_fields={}):
    m  = f_str(1, 'windsurf')      # ide_name
    m += f_str(7, '1.9577.43')     # ide_version
    for k, v in extra_fields.items():
        m += f_str(k, v)
    return m

# chat message: role=USER(1), content
def chat_msg(content, role=1):
    return f_int(1, role) + f_str(2, content)

# === TEST 1: Find chat_messages field number ===
print("=== T1: Find chat_messages field in GetChatMessageRequest ===")
meta = meta_base({3:'windsurf', 4:api_key, 5:'1.0', 6:'windsurf'})
# Use full_meta base that passes ide_name+ide_version
for chat_field in range(2, 10):
    cm = f_msg(chat_field, chat_msg("test"))
    body = f_msg(1, meta) + cm
    s, resp = post(body, timeout=8)
    e = err(resp)
    print(f"  chat@f{chat_field}: {e[:120]}")

print()

# === TEST 2: Once found, fix source_address ===
# From test1 we know chat_messages field. Now find source_address.
# source_address is a metadata field requiring valid IP
# Try setting metadata fields 8-15 to '127.0.0.1'
print("=== T2: Find source_address field in metadata ===")
for sa_field in range(2, 16):
    meta2 = meta_base({3:'windsurf', 4:api_key, 5:'1.0', 6:'windsurf', sa_field:'127.0.0.1'})
    # Use chat_messages at field 2 (best guess - will update after T1)
    # Try a few chat fields
    for chat_f in [2, 3]:
        cm = f_msg(chat_f, chat_msg("OPUS46_OK"))
        body = f_msg(1, meta2) + cm
        s, resp = post(body, timeout=8)
        e = err(resp)
        if 'source_address' not in e and 'chat_messages' not in e:
            print(f"  sa@f{sa_field} chat@f{chat_f}: DIFFERENT! → {e[:100]}")
        elif 'source_address' not in e:
            print(f"  sa@f{sa_field} (valid IP) chat@f{chat_f}: {e[:80]}")

print()

# === TEST 3: All-in-one - try all combinations ===
print("=== T3: Combined - meta fields 1-15 with valid IP at source_addr ===")
# Use meta_all with source_address field as valid IP instead of 'windsurf_v1'
for sa_f in [3, 4, 5, 6, 8, 9, 10, 11, 12]:
    meta3 = b''.join(f_str(i, '127.0.0.1' if i == sa_f else 'windsurf_v1') for i in range(1, 16))
    meta3_fixed = b''.join(
        (f_str(1, 'windsurf') if i == 1 else
         f_str(7, '1.9577.43') if i == 7 else
         f_str(i, '127.0.0.1') if i == sa_f else
         f_str(i, 'windsurf_v1'))
        for i in range(1, 16)
    )
    body = f_msg(1, meta3_fixed) + f_msg(6, f_msg(1, chat_msg("OPUS46_OK")))
    s, resp = post(body, timeout=8)
    e = err(resp)
    if 'source_address' not in e:
        print(f"  source@f{sa_f}: PAST source_address! → {e[:100]}")
    else:
        print(f"  source@f{sa_f}: still source_address error")

print()

# === TEST 4: The attempt with long timeout ===
print("=== T4: Best-guess complete request with 30s timeout ===")
# metadata: ide_name@1, ide_version@7, all others filled with windsurf_v1
# source_address as windsurf_v1 (will fail IP check but let's see next error)
meta4 = b''.join(f_str(i, 'windsurf' if i==1 else '1.9577.43' if i==7 else f'val{i}') 
                 for i in range(1, 16))
# Try all fields 2-5 for chat_messages
for chat_f in [2, 3, 4, 5]:
    cm = f_msg(chat_f, chat_msg("Respond with: OPUS_46_DIRECT_WORKS"))
    body = f_msg(1, meta4) + cm
    s, resp = post(body, timeout=20)
    e = err(resp)
    print(f"  chat@f{chat_f}: {e[:150]}")
