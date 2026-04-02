"""
start_cascade.py — 用 gRPC-Web 测试 StartCascade + SendUserCascadeMessage
StartCascade 应返回 cascadeId，用于后续 AI 对话
"""
import struct, http.client, json, sqlite3, uuid, urllib.parse, re

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
PORT = 57407; CSRF = '18e67ec6-8a9b-4781-bcea-ac61a722a640'

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

def grpc_call(path, body, timeout=15):
    framed = frm(body)
    h = {'Content-Type':'application/grpc-web+proto','Accept':'application/grpc-web+proto',
         'X-Grpc-Web':'1','x-codeium-csrf-token':CSRF}
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
    c.request('POST', path, framed, h)
    r = c.getresponse()
    data = b''
    while True:
        ch = r.read(4096)
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
            t = chunk.decode('utf-8','replace')
            m = re.search(r'grpc-status:\s*(\d+)', t, re.I)
            if m and not gs: gs = m.group(1)
            m2 = re.search(r'grpc-message:\s*([^\r\n]+)', t, re.I)
            if m2 and not gm: gm = urllib.parse.unquote(m2.group(1))
    return gs, gm, frames

def decode_proto(data):
    strings = []; pos = 0
    while pos < len(data):
        if pos >= len(data): break
        b = data[pos]; pos += 1
        wire = b & 7; fno = b >> 3
        if wire == 2:
            l = 0; s = 0
            while pos < len(data):
                x = data[pos]; pos += 1
                l |= (x & 0x7F) << s; s += 7
                if not (x & 0x80): break
            v = data[pos:pos+l]; pos += l
            try:
                sv = v.decode('utf-8')
                if all(32 <= ord(c) < 127 for c in sv) and len(sv) > 2:
                    strings.append((fno, sv[:200]))
            except: pass
        elif wire == 0:
            while pos < len(data) and (data[pos] & 0x80): pos += 1
            pos += 1
        elif wire in (1,5): pos += (8 if wire==1 else 4)
        else: break
    return strings

def json_call(path, payload, timeout=60):
    body = json.dumps(payload).encode(); framed = frm(body)
    h = {'Content-Type':'application/connect+json','Accept':'application/connect+json',
         'Connect-Protocol-Version':'1','x-codeium-csrf-token':CSRF}
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
    c.request('POST', path, framed, h)
    r = c.getresponse(); data = r.read(16384)
    out = []
    pos = 0
    while pos < len(data):
        if pos+5 > len(data): break
        flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]; pos += 5+length
        try: out.append((flag, json.loads(chunk)))
        except: out.append((flag, chunk))
    return r.status, out

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

meta = build_meta(api_key)

# Test all cascade-related methods with gRPC-Web
svc = '/exa.language_server_pb.LanguageServerService/'
methods = [
    'StartCascade',
    'InitializeCascadePanelState',
    'GetCascadeModelConfigs',
    'GetAllCascadeTrajectories',
    'CheckChatCapacity',
    'CheckUserMessageRateLimit',
]

print("=== Test gRPC-Web on ALL cascade methods ===")
for method in methods:
    gs, gm, frames = grpc_call(svc + method, fm(1, meta))
    data_frames = [(f,c) for f,c in frames if f==0 and c]
    print(f"  {method}: status={gs} frames={len(frames)} data_bytes={sum(len(c) for f,c in data_frames)}")
    if gm: print(f"    msg: {gm[:100]}")
    for flag, chunk in data_frames[:1]:
        strings = decode_proto(chunk)
        if strings: print(f"    data strings: {strings[:5]}")

# StartCascade specifically
print("\n=== StartCascade full test ===")
# StartCascadeRequest fields: metadata(1), workspaceRootPath(2?), model(3?)
for body_label, body in [
    ('meta_only',     fm(1, meta)),
    ('meta+ws',       fm(1, meta) + fs(2, 'e:/道/道生一/一生二')),
    ('meta+model',    fm(1, meta) + fs(3, 'claude-opus-4-6')),
    ('meta+all',      fm(1, meta) + fs(2, 'e:/道/道生一/一生二') + fs(3, 'claude-opus-4-6') + fs(4, str(uuid.uuid4()))),
    ('all_fields',    b''.join(fs(i, VALID_URL if i > 7 else ('windsurf' if i==1 else '1.9577.43')) for i in range(1,12))),
]:
    gs, gm, frames = grpc_call(svc + 'StartCascade', body)
    cascade_id = None
    for flag, chunk in frames:
        if flag == 0 and chunk:
            strings = decode_proto(chunk)
            for fno, s in strings:
                uuid_pat = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
                if uuid_pat.match(s): cascade_id = s
    print(f"  [{body_label}]: status={gs} cascade_id={cascade_id} frames={len(frames)}")
    if gm: print(f"    msg: {gm[:120]}")
    if cascade_id:
        print(f"  ✅ Got cascadeId: {cascade_id}")
        # Try RawGetChatMessage with this cascadeId
        conv_id = str(uuid.uuid4())
        s, results = json_call(svc + 'RawGetChatMessage', {
            'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43',
                         'extensionVersion':'1.9577.43','apiKey':api_key},
            'chatMessages': [{'messageId':str(uuid.uuid4()),'role':1,
                              'content':'Reply: OPUS46_CASCADE_SESSION',
                              'timestamp':'2026-03-30T22:20:00Z',
                              'conversationId':conv_id}],
            'model': 'claude-opus-4-6',
            'cascadeId': cascade_id,
        })
        for flag, obj in results:
            if isinstance(obj, dict):
                dm = obj.get('deltaMessage', {})
                text = dm.get('text', '')
                if text: print(f"  [{'✅' if not dm.get('isError') else '❌'}]: {text[:200]}")
        break
