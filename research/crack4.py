"""
crack4.py — 最终收敛: 找 extension_version + url + chat_messages 字段号
已确认:
  metadata.ide_name     = field 1
  metadata.ide_version  = field 7
  metadata.source_addr  = field 11 (valid IP, or omit)
  metadata.extension_version = unknown, needs finding
  metadata.url          = unknown, needs valid URL
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

def post(body, timeout=12):
    h = {'Content-Type':'application/connect+proto','Accept':'application/connect+proto',
         'Connect-Protocol-Version':'1','x-codeium-csrf-token':CSRF}
    conn = http.client.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
    conn.request('POST', PATH, frame(body), h)
    r = conn.getresponse(); data = r.read(4096)
    return r.status, data

def err(body):
    if len(body) < 5: return str(body[:200])
    pay = body[5:5+struct.unpack('>I',body[1:5])[0]]
    try: e = json.loads(pay); return e.get('error',{}).get('message','')[:300]
    except: return str(pay[:200])

api_key = get_api_key()
print(f"api_key: {api_key[:20]}...\n")

def chat_msg(content): return f_int(1, 1) + f_str(2, content)  # role=USER, content

# === T1: Find extension_version field ===
# meta with ide_name@1, ide_version@7, test one extra field at a time
# When extension_version passes, next error will be different from "extension_version"
print("=== T1: Find extension_version field ===")
for ev_field in range(2, 16):
    if ev_field in (7, 11): continue  # skip known fields
    meta = f_str(1, 'windsurf') + f_str(7, '1.9577.43') + f_str(ev_field, '1.9577.43')
    body = f_msg(1, meta) + f_msg(2, chat_msg("test"))
    s, resp = post(body)
    e = err(resp)
    if 'extension_version' not in e:
        print(f"  ev@f{ev_field}: DIFFERENT → {e[:120]}")
    else:
        print(f"  ev@f{ev_field}: still extension_version")

print()

# === T2: With extension_version fixed, find url field ===
# Use ide_name@1 + ide_version@7 + extension_version@X + test url fields
# Try each field for 'url' with a valid URL value
print("=== T2: Find url field (needs valid URL format) ===")
# Best guess for extension_version based on T1 (will update)
# Try extension_version at field 8 first (common pattern)
for ev_f in [2, 8, 9, 10, 3, 4, 5, 6]:
    meta_base = f_str(1, 'windsurf') + f_str(7, '1.9577.43') + f_str(ev_f, '1.0.0')
    for url_f in range(2, 16):
        if url_f in (ev_f, 7, 11): continue
        meta = meta_base + f_str(url_f, 'https://windsurf.ai')
        body = f_msg(1, meta) + f_msg(2, chat_msg("test"))
        s, resp = post(body)
        e = err(resp)
        if 'extension_version' not in e and 'url' not in e and 'source_address' not in e:
            print(f"  ev@f{ev_f} url@f{url_f}: BOTH PASSED! → {e[:150]}")
        elif 'extension_version' not in e and 'url' not in e:
            print(f"  ev@f{ev_f} url@f{url_f}: ev+url passed → {e[:120]}")

print()

# === T3: Meta all (1-15) with smart values, try all request chat fields ===
print("=== T3: Smart meta_all, find chat_messages request field ===")
# Smart metadata: all fields, with known-correct values where known
# Field 11 = valid IP, others = plausible strings, skip 11 by setting to valid IP
def smart_meta():
    m = b''
    for i in range(1, 20):
        if i == 1:  m += f_str(i, 'windsurf')
        elif i == 7: m += f_str(i, '1.9577.43')
        elif i == 11: m += f_str(i, '127.0.0.1')
        elif i in (4, 5, 6, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19):
            m += f_str(i, 'windsurf_v1')
        elif i in (2, 3): m += f_str(i, 'https://windsurf.ai')  # try URL here
    return m

for chat_f in range(2, 10):
    body = f_msg(1, smart_meta()) + f_msg(chat_f, chat_msg("OPUS46_OK"))
    s, resp = post(body)
    e = err(resp)
    print(f"  chat@f{chat_f}: {e[:150]}")

print()

# === T4: Skip all troublesome metadata fields, just use required ones ===
print("=== T4: Minimal valid metadata, brute-force chat field ===")
# Only set definitely required fields: ide_name@1, ide_version@7
# Don't set anything else (avoid triggering optional-field validators)
min_meta = f_str(1, 'windsurf') + f_str(7, '1.9577.43')
for chat_f in range(2, 8):
    body = f_msg(1, min_meta) + f_msg(chat_f, chat_msg("OPUS46_OK"))
    s, resp = post(body, timeout=15)
    e = err(resp)
    print(f"  minimal_meta chat@f{chat_f}: {e[:150]}")

print()

# === T5: Full attempt - use the state.vscdb userStatusProto for metadata ===
print("=== T5: Metadata from state.vscdb ===")
try:
    conn2 = sqlite3.connect(DB_PATH); cur2 = conn2.cursor()
    cur2.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    row2 = cur2.fetchone(); conn2.close()
    auth_data = json.loads(row2[0])
    user_id = auth_data.get('userId', auth_data.get('user_id', ''))
    print(f"  userId: {user_id[:30]}")

    # Build metadata with userId (often field 5 or 6 in Codeium)
    for uid_f in [5, 6, 4, 3]:
        meta = (f_str(1, 'windsurf') + f_str(7, '1.9577.43') +
                f_str(uid_f, user_id if user_id else 'user123') +
                f_str(4, api_key))
        for chat_f in [2, 3]:
            body = f_msg(1, meta) + f_msg(chat_f, chat_msg("OPUS46_OK"))
            s, resp = post(body)
            e = err(resp)
            print(f"  uid@f{uid_f} chat@f{chat_f}: {e[:120]}")
except Exception as ex:
    print(f"  error: {ex}")
