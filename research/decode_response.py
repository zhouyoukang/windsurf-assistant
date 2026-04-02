"""
decode_response.py — 解码 InitializeCascadePanelState 的响应 proto
找 cascadeId/sessionId，然后把它加进 RawGetChatMessage
"""
import struct, http.client, json, sqlite3, uuid, urllib.parse, re

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
PORT = 57407; CSRF = '18e67ec6-8a9b-4781-bcea-ac61a722a640'
PATH_INIT = '/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState'
PATH_CHAT = '/exa.language_server_pb.LanguageServerService/RawGetChatMessage'

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

def grpc_call(path, body, timeout=20):
    framed = frm(body)
    h = {'Content-Type':'application/grpc-web+proto','Accept':'application/grpc-web+proto',
         'X-Grpc-Web':'1','x-codeium-csrf-token':CSRF}
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
    c.request('POST', path, framed, h)
    r = c.getresponse()
    data = b''
    while True:
        ch = r.read(4096); 
        if not ch: break
        data += ch
    gs = r.headers.get('Grpc-Status','')
    gm = urllib.parse.unquote(r.headers.get('Grpc-Message',''))
    frames = []
    pos = 0
    while pos < len(data):
        if pos+5 > len(data): break
        flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]; pos += 5+length
        frames.append((flag, chunk))
    for flag, chunk in frames:
        if flag == 0x80:
            t = chunk.decode('utf-8', errors='replace')
            m = re.search(r'grpc-status:\s*(\d+)', t, re.I)
            if m and not gs: gs = m.group(1)
    return gs, gm, frames

def json_call(path, payload, timeout=60):
    body = json.dumps(payload).encode()
    framed = frm(body)
    h = {'Content-Type':'application/connect+json','Accept':'application/connect+json',
         'Connect-Protocol-Version':'1','x-codeium-csrf-token':CSRF}
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
    c.request('POST', path, framed, h)
    r = c.getresponse(); data = r.read(8192)
    out = []
    pos = 0
    while pos < len(data):
        if pos+5 > len(data): break
        flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]; pos += 5+length
        try: out.append((flag, json.loads(chunk)))
        except: out.append((flag, chunk))
    return r.status, out

def decode_proto_strings(data):
    """提取 proto binary 中所有字符串字段"""
    strings = []
    pos = 0
    while pos < len(data):
        if pos >= len(data): break
        tag_byte = data[pos]; pos += 1
        wire_type = tag_byte & 0x07
        field_no  = tag_byte >> 3
        if wire_type == 2:  # LEN
            # Read varint length
            length = 0; shift = 0
            while pos < len(data):
                b = data[pos]; pos += 1
                length |= (b & 0x7F) << shift
                if not (b & 0x80): break
                shift += 7
            if pos + length > len(data): break
            value = data[pos:pos+length]; pos += length
            try:
                s = value.decode('utf-8')
                if s.isprintable() and len(s) > 2:
                    strings.append((field_no, s[:100]))
            except: pass
        elif wire_type == 0:  # varint
            while pos < len(data) and (data[pos] & 0x80): pos += 1
            pos += 1
        elif wire_type == 5:  # 32-bit
            pos += 4
        elif wire_type == 1:  # 64-bit
            pos += 8
        else:
            break
    return strings

api_key = get_api_key()
print(f"api: {api_key[:20]}...\n")
VALID_URL = 'https://server.codeium.com'

def build_meta(api_key):
    m = b''
    for i in range(1, 16):
        if i == 1:   m += fs(i, 'windsurf')
        elif i == 7: m += fs(i, '1.9577.43')
        elif i == 11: pass
        elif i == 4: m += fs(i, api_key)
        elif i in [2,3,8,9,10]: m += fs(i, '1.9577.43')
        else: m += fs(i, VALID_URL)
    return m

# === Step 1: Call InitializeCascadePanelState and decode response ===
print("=== Step 1: Call + decode InitializeCascadePanelState response ===")
meta = build_meta(api_key)
gs, gm, frames = grpc_call(PATH_INIT, fm(1, meta))
print(f"  grpc_status={gs}")
print(f"  frames: {len(frames)}")

cascade_id = None
for flag, chunk in frames:
    print(f"  frame flag={flag}, {len(chunk)} bytes")
    if flag == 0x00 and chunk:  # data frame
        print(f"  DATA hex: {chunk.hex()}")
        strings = decode_proto_strings(chunk)
        print(f"  DATA strings: {strings}")
        # Look for UUIDs or IDs
        uuid_pat = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
        for field_no, s in strings:
            if uuid_pat.match(s) or len(s) > 10:
                print(f"    field {field_no}: {s}")
                if 'cascade' in s.lower() or uuid_pat.match(s):
                    cascade_id = s
    elif flag == 0x80:  # trailers
        print(f"  TRAILER: {chunk.decode('utf-8','replace')[:200]}")

print(f"\n  cascade_id from response: {cascade_id}")

# === Step 2: Try RawGetChatMessage with cascadeId from response ===
print("\n=== Step 2: RawGetChatMessage (with init done) ===")
conv_id = str(uuid.uuid4())
chat = {
    'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43',
                 'extensionVersion':'1.9577.43','apiKey':api_key},
    'chatMessages': [{'messageId':str(uuid.uuid4()),'role':1,
                      'content':'Reply with exactly: OPUS46_SESSION_WORKS',
                      'timestamp':'2026-03-30T22:15:00Z',
                      'conversationId':conv_id}],
    'model': 'claude-opus-4-6',
}
if cascade_id:
    chat['cascadeId'] = cascade_id
    print(f"  Using cascadeId: {cascade_id}")

s, results = json_call(PATH_CHAT, chat)
for flag, obj in results:
    if isinstance(obj, dict):
        dm = obj.get('deltaMessage', {})
        text = dm.get('text', '')
        if text: print(f"  [{'❌' if dm.get('isError') else '✅'}]: {text[:200]}")
        if 'error' in obj: print(f"  err: {obj['error'].get('message','')[:150]}")

# === Step 3: Re-init SAME connection, then chat ===
print("\n=== Step 3: Same connection re-init + chat test ===")
# Use SAME http connection for both init and chat to test connection-scoped session
import http.client as hc

conn = hc.HTTPConnection('127.0.0.1', PORT, timeout=60)

def conn_grpc(c, path, body):
    framed = frm(body)
    h = {'Content-Type':'application/grpc-web+proto','Accept':'application/grpc-web+proto',
         'X-Grpc-Web':'1','x-codeium-csrf-token':CSRF}
    c.request('POST', path, framed, h)
    r = c.getresponse(); data = b''
    while True:
        ch = r.read(4096);
        if not ch: break
        data += ch
    gs = r.headers.get('Grpc-Status','')
    gm = urllib.parse.unquote(r.headers.get('Grpc-Message',''))
    frames = []
    pos = 0
    while pos < len(data):
        if pos+5 > len(data): break
        flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]; pos += 5+length
        frames.append((flag, chunk))
    return gs, gm, frames

def conn_json(c, path, payload):
    body = json.dumps(payload).encode(); framed = frm(body)
    h = {'Content-Type':'application/connect+json','Accept':'application/connect+json',
         'Connect-Protocol-Version':'1','x-codeium-csrf-token':CSRF}
    c.request('POST', path, framed, h)
    r = c.getresponse(); data = r.read(8192)
    out = []
    pos = 0
    while pos < len(data):
        if pos+5 > len(data): break
        flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]; pos += 5+length
        try: out.append((flag, json.loads(chunk)))
        except: out.append((flag, chunk))
    return r.status, out

try:
    # Init
    gs2, _, _ = conn_grpc(conn, PATH_INIT, fm(1, meta))
    print(f"  Init: status={gs2}")
    # Chat
    conv_id2 = str(uuid.uuid4())
    s2, r2 = conn_json(conn, PATH_CHAT, {
        'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43',
                     'extensionVersion':'1.9577.43','apiKey':api_key},
        'chatMessages': [{'messageId':str(uuid.uuid4()),'role':1,
                          'content':'Reply with: OPUS46',
                          'timestamp':'2026-03-30T22:15:00Z',
                          'conversationId':conv_id2}],
        'model': 'claude-opus-4-6',
    })
    for flag, obj in r2:
        if isinstance(obj, dict):
            dm = obj.get('deltaMessage', {})
            text = dm.get('text', '')
            if text: print(f"  [{'❌' if dm.get('isError') else '✅'}]: {text[:200]}")
            if 'error' in obj: print(f"  err: {obj['error'].get('message','')[:150]}")
except Exception as e:
    print(f"  Same-connection test error: {e}")
