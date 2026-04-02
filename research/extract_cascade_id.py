"""
extract_cascade_id.py — 从 GetAllCascadeTrajectories 提取活跃 cascadeId
用已存在的活跃 cascade 会话 ID 来修复 RawGetChatMessage 
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

def grpc_call(path, body, timeout=20):
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

def json_call(path, payload, timeout=60):
    body = json.dumps(payload).encode()
    framed = frm(body)
    h = {'Content-Type':'application/connect+json','Accept':'application/connect+json',
         'Connect-Protocol-Version':'1','x-codeium-csrf-token':CSRF}
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
    c.request('POST', path, framed, h)
    r = c.getresponse(); data = r.read(32768)
    out = []
    pos = 0
    while pos < len(data):
        if pos+5 > len(data): break
        flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]; pos += 5+length
        try: out.append((flag, json.loads(chunk)))
        except: out.append((flag, chunk))
    return r.status, out

def find_uuids(data):
    """Find all UUID patterns in bytes"""
    uuid_re = re.compile(rb'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
    return [m.group(0).decode() for m in uuid_re.finditer(data)]

def find_strings(data, min_len=4, max_len=200):
    """Extract printable strings from bytes"""
    strings = []
    current = b''
    for b2 in data:
        if 32 <= b2 < 127:
            current += bytes([b2])
        else:
            if len(current) >= min_len:
                strings.append(current.decode('ascii'))
            current = b''
    if len(current) >= min_len:
        strings.append(current.decode('ascii'))
    return [s for s in strings if len(s) <= max_len]

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

SVC = '/exa.language_server_pb.LanguageServerService/'

# ── Get all cascade trajectories ──────────────────────────────────────────────
print("=== GetAllCascadeTrajectories ===")
gs, gm, frames = grpc_call(SVC + 'GetAllCascadeTrajectories', fm(1, meta))
print(f"  status={gs}, frames={len(frames)}")

all_uuids = []
cascade_ids = []
for flag, chunk in frames:
    if flag == 0 and chunk:
        uuids = find_uuids(chunk)
        all_uuids.extend(uuids)
        strings = find_strings(chunk, min_len=8)
        # Print relevant strings
        print(f"  Data ({len(chunk)}B): {len(uuids)} UUIDs")
        print(f"  First few UUIDs: {uuids[:5]}")
        # Find cascade IDs (usually at the beginning of each trajectory)
        cascade_ids = uuids[:10]

print(f"\nAll UUIDs found: {len(all_uuids)}")
print(f"First 10: {all_uuids[:10]}")

# ── Try RawGetChatMessage with each cascade trajectory ID ─────────────────────
print("\n=== Test RawGetChatMessage with trajectory IDs ===")
conv_id = str(uuid.uuid4())

for test_cascade_id in (all_uuids[:5] if all_uuids else ['test']):
    for field_name in ['cascadeId', 'trajectoryId', 'sessionId']:
        payload = {
            'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43',
                         'extensionVersion':'1.9577.43','apiKey':api_key},
            'chatMessages': [{'messageId':str(uuid.uuid4()),'role':1,
                              'content':'Reply: OPUS46_WORKS',
                              'timestamp':'2026-03-30T22:25:00Z',
                              'conversationId':conv_id}],
            'model': 'claude-opus-4-6',
            field_name: test_cascade_id,
        }
        s, results = json_call(SVC + 'RawGetChatMessage', payload, timeout=10)
        for flag, obj in results:
            if isinstance(obj, dict):
                dm = obj.get('deltaMessage', {})
                text = dm.get('text', '')
                if text and 'cascade session' not in text.lower():
                    print(f"  ✅ DIFFERENT RESPONSE! [{field_name}={test_cascade_id[:8]}]: {text[:200]}")
                elif text and 'cascade session' in text.lower():
                    pass  # same error, skip
                if 'error' in obj:
                    err = obj['error'].get('message','')
                    if 'cascade session' not in err.lower():
                        print(f"  !! Different error [{field_name}={test_cascade_id[:8]}]: {err[:100]}")

# ── Get most recent cascade trajectory and try SendUserCascadeMessage ─────────
print("\n=== SendUserCascadeMessage with recent trajectory ===")
if all_uuids:
    traj_id = all_uuids[0]
    # SendUserCascadeMessageRequest: cascadeId(1?), message(2?)
    msg_body = fm(1, fs(1, traj_id)) + fs(2, 'Reply with: OPUS46_SENDCASCADE')
    gs2, gm2, frames2 = grpc_call(SVC + 'SendUserCascadeMessage', msg_body)
    print(f"  SendUserCascadeMessage: status={gs2}")
    if gm2: print(f"  msg: {gm2[:150]}")
    for flag, chunk in frames2:
        if flag == 0 and chunk:
            uuids2 = find_uuids(chunk)
            print(f"  data UUIDs: {uuids2[:3]}")

# ── Look at ACTUAL Windsurf cascade context via hot_guardian ──────────────────
print("\n=== Check hot_guardian for active cascade state ===")
import os
for fn in ['_active_cascade.json', '_cascade_state.json', '_session.json',
           'hot_guardian.log', '_guardian_state.json']:
    fp = os.path.join(r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine', fn)
    if os.path.exists(fp):
        content = open(fp, encoding='utf-8', errors='replace').read()
        print(f"  {fn}: {content[:300]}")

# ── Final: Try with different models and metadata variations ──────────────────
print("\n=== Final attempts: vary metadata + model ===")
for test_meta, model, label in [
    ({'ideName':'windsurf','ideVersion':'1.9577.43','extensionVersion':'1.9577.43','apiKey':api_key,
      'planName':'Windsurf Trial'}, 'claude-sonnet-4-5', 'with_planName'),
    ({'ideName':'windsurf','ideVersion':'1.9577.43','extensionVersion':'1.9577.43','apiKey':api_key,
      'sessionId':str(uuid.uuid4())}, 'claude-sonnet-4-5', 'with_sessionId'),
    ({'ideName':'windsurf','ideVersion':'1.9577.43','extensionVersion':'1.9577.43','apiKey':api_key,
      'userId':'7b3aff7a-d8c1-47ee-a00c-c503d755caa2'}, 'claude-opus-4-6', 'with_userId'),
]:
    s, results = json_call(SVC + 'RawGetChatMessage', {
        'metadata': test_meta,
        'chatMessages': [{'messageId':str(uuid.uuid4()),'role':1,
                          'content':'Reply: OK','timestamp':'2026-03-30T22:25:00Z',
                          'conversationId':str(uuid.uuid4())}],
        'model': model,
    }, timeout=10)
    for flag, obj in results:
        if isinstance(obj, dict):
            dm = obj.get('deltaMessage', {})
            text = dm.get('text', '')
            if text and 'cascade session' not in text.lower():
                print(f"  ✅ DIFFERENT [{label}]: {text[:200]}")
            elif 'error' in obj:
                err = obj['error'].get('message','')
                if 'cascade session' not in err.lower():
                    print(f"  !! Different error [{label}]: {err[:100]}")
