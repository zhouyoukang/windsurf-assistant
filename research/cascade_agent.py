"""
cascade_agent.py — 走完整 Cascade Agent 流程
路径: StartCascade → SendUserCascadeMessage → StreamCascadeReactiveUpdates
此路径绕开 RawGetChatMessage 的 session 检查
"""
import struct, http.client, json, sqlite3, uuid, urllib.parse, re, time

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
PORT = 57407; CSRF = '18e67ec6-8a9b-4781-bcea-ac61a722a640'
SVC  = '/exa.language_server_pb.LanguageServerService/'

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

def grpc(path, body, timeout=20):
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
    return gs, gm, frames

def decode_strings(data):
    strings = []; pos = 0
    while pos < len(data):
        if pos >= len(data): break
        b = data[pos]; pos += 1
        wire = b & 7; fno = b >> 3
        if wire == 2:
            l = 0; s = 0
            while pos < len(data):
                x = data[pos]; pos += 1; l |= (x & 0x7F) << s; s += 7
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

def find_uuids(data):
    uuid_re = re.compile(rb'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
    return [m.group(0).decode() for m in uuid_re.finditer(data)]

api_key = get_api_key()
print(f"api: {api_key[:20]}...\n")
VALID_URL = 'https://server.codeium.com'

meta = b''
for i in range(1, 16):
    if i == 1:   meta += fs(i, 'windsurf')
    elif i == 7: meta += fs(i, '1.9577.43')
    elif i == 11: pass
    elif i == 4: meta += fs(i, api_key)
    elif i in [2,3,8,9,10]: meta += fs(i, '1.9577.43')
    else: meta += fs(i, VALID_URL)

# ── Step 1: StartCascade ─────────────────────────────────────────────────────
print("=== Step 1: StartCascade ===")
gs1, gm1, frames1 = grpc(SVC + 'StartCascade', fm(1, meta))
print(f"  status={gs1} msg={gm1[:80]}")

cascade_id = None
for flag, chunk in frames1:
    if flag == 0 and chunk:
        uuids = find_uuids(chunk)
        if uuids: cascade_id = uuids[0]
        strings = decode_strings(chunk)
        print(f"  data strings: {strings[:5]}")
print(f"  cascadeId: {cascade_id}")

if not cascade_id:
    print("No cascadeId from StartCascade, trying meta_only")
    gs_try, _, frames_try = grpc(SVC + 'StartCascade', b'')
    for flag, chunk in frames_try:
        if flag == 0 and chunk:
            uuids = find_uuids(chunk)
            if uuids: cascade_id = uuids[0]
    print(f"  cascadeId (meta_only): {cascade_id}")

# ── Step 2: SendUserCascadeMessage ───────────────────────────────────────────
print("\n=== Step 2: SendUserCascadeMessage ===")
# SendUserCascadeMessageRequest fields: cascadeId(1?), message(2?), model(3?)
for body_label, body in [
    # Try cascadeId at different fields
    ('cascade@f1+msg@f2', fs(1, cascade_id) + fs(2, 'Reply with: OPUS46_AGENT') if cascade_id else b''),
    ('meta+cascade@f1+msg', fm(1, meta) + fs(2, cascade_id) + fs(3, 'Reply: OPUS46') if cascade_id else b''),
    ('cascade_msg_fm1', fm(1, fm(1, fs(1, cascade_id)) + fs(2, 'Reply: OPUS46')) if cascade_id else b''),
    ('just_msg', fs(1, 'Reply with: OPUS46_AGENT')),
]:
    if not body: continue
    gs2, gm2, frames2 = grpc(SVC + 'SendUserCascadeMessage', body, timeout=15)
    print(f"  [{body_label}]: status={gs2} msg={gm2[:100]}")
    for flag, chunk in frames2:
        if flag == 0 and chunk:
            strings = decode_strings(chunk)
            if strings: print(f"    data: {strings[:3]}")

# ── Step 3: Try with JSON for SendUserCascadeMessage ────────────────────────
print("\n=== Step 3: JSON SendUserCascadeMessage ===")
def json_call(path, payload, timeout=30):
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

for field_name, cascade_val in [
    ('cascadeId', cascade_id),
    ('trajectoryId', cascade_id),
    ('conversationId', cascade_id),
]:
    if not cascade_val: continue
    s, results = json_call(SVC + 'SendUserCascadeMessage', {
        'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43',
                     'extensionVersion':'1.9577.43','apiKey':api_key},
        field_name: cascade_val,
        'message': 'Reply with exactly: OPUS46_CASCADE_AGENT_WORKS',
        'model': 'claude-opus-4-6',
    }, timeout=15)
    print(f"  [{field_name}={cascade_val[:8]}...]: HTTP {s}")
    for flag, obj in results:
        if isinstance(obj, dict):
            dm = obj.get('deltaMessage', {})
            if dm.get('text'):
                print(f"    [{'ERR' if dm.get('isError') else '✅'}]: {dm['text'][:150]}")
            if 'error' in obj:
                err = obj['error'].get('message','')
                if 'cascade session' not in err.lower():
                    print(f"    !! DIFFERENT: {err[:100]}")
                else:
                    print(f"    (same cascade session error)")

# ── Step 4: Check if StartCascade model param changes anything ──────────────
print("\n=== Step 4: StartCascade with model + RawGetChatMessage ===")
# Try starting cascade with specific model
for start_body_label, start_body in [
    ('model=opus46', fm(1, meta) + fs(2, 'claude-opus-4-6')),
    ('model+ws',     fm(1, meta) + fs(2, 'claude-opus-4-6') + fs(3, 'e:/道/道生一/一生二')),
]:
    gs_s, gm_s, frames_s = grpc(SVC + 'StartCascade', start_body)
    cid = None
    for f2, c2 in frames_s:
        if f2 == 0 and c2:
            uuids = find_uuids(c2)
            if uuids: cid = uuids[0]
    print(f"  {start_body_label}: status={gs_s} cascadeId={cid}")
    if cid and gs_s == '0':
        # Test RawGetChatMessage with this cascadeId
        s2, r2 = json_call(SVC + 'RawGetChatMessage', {
            'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43',
                         'extensionVersion':'1.9577.43','apiKey':api_key},
            'chatMessages': [{'messageId':str(uuid.uuid4()),'role':1,
                              'content':'Reply: OPUS46','timestamp':'2026-03-30T22:35:00Z',
                              'conversationId':cid}],
            'model': 'claude-opus-4-6',
            'cascadeId': cid,
        }, timeout=15)
        for flag, obj in r2:
            if isinstance(obj, dict):
                dm = obj.get('deltaMessage', {})
                text = dm.get('text', '')
                if text and 'cascade session' not in text.lower():
                    print(f"    ✅ DIFFERENT: {text[:200]}")
                elif 'error' in obj:
                    err = obj['error'].get('message','')
                    if 'cascade session' not in err.lower():
                        print(f"    !! DIFFERENT error: {err[:100]}")
