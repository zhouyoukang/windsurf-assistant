"""
breakthrough.py — 万法之资，彻底打通后端
策略:
  1. port 64958 (binary proto) 试 InitializeCascadePanelState
  2. 找正确 service typeName
  3. 完成 cascade session 初始化
  4. RawGetChatMessage 生产 claude-opus-4-6
"""
import struct, http.client, json, sqlite3, uuid, re

DB   = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
EXT  = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'

# Two LSP instances
INSTANCES = [
    {'port': 57407, 'csrf': '18e67ec6-8a9b-4781-bcea-ac61a722a640', 'proto': 'json',  'label': 'JSON-57407'},
    {'port': 64958, 'csrf': '38a7a689-1e2a-41ff-904b-eefbc9dcacfe', 'proto': 'proto', 'label': 'PROTO-64958'},
]

def get_api_key():
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    row = cur.fetchone(); conn.close()
    return json.loads(row[0]).get('apiKey', '')

# ── proto helpers ─────────────────────────────────────────────────────────────
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

def post(inst, path, body_bytes, timeout=12):
    ct = 'application/connect+json' if inst['proto']=='json' else 'application/connect+proto'
    h = {'Content-Type':ct,'Accept':ct,'Connect-Protocol-Version':'1',
         'x-codeium-csrf-token':inst['csrf']}
    data = json.dumps(body_bytes).encode() if inst['proto']=='json' else body_bytes
    framed = frm(data)
    c = http.client.HTTPConnection('127.0.0.1', inst['port'], timeout=timeout)
    c.request('POST', path, framed, h)
    r = c.getresponse(); resp = r.read(8192)
    return r.status, resp

def parse_resp(status, data, proto_mode='json'):
    results = []
    pos = 0
    while pos < len(data):
        if pos + 5 > len(data): break
        flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]; pos += 5 + length
        if proto_mode == 'json':
            try: results.append((flag, json.loads(chunk)))
            except: results.append((flag, chunk))
        else:
            results.append((flag, chunk))
    return results

def err_text(results):
    for flag, obj in results:
        if isinstance(obj, dict):
            if 'error' in obj: return obj['error'].get('message', '')[:200]
            dm = obj.get('deltaMessage', {})
            if dm.get('isError'): return dm.get('text', '')[:200]
            if dm.get('text'): return '[OK] ' + dm['text'][:150]
    if results:
        return str(results[0][1])[:200]
    return ''

api_key = get_api_key()
print(f"api: {api_key[:20]}...\n")

# ── STEP 1: Find correct service/path from extension.js ───────────────────────
print("=== STEP 1: Find service for InitializeCascadePanelState ===")
with open(EXT, 'r', encoding='utf-8', errors='replace') as f:
    js = f.read()

# Search for service typeName near InitializeCascadePanelState
idx = js.find('InitializeCascadePanelState')
region = js[max(0,idx-5000):idx+100]
# Find last typeName before this method
tnames = re.findall(r'typeName:\s*["\']([^"\']+)["\']', region)
svc = tnames[-1] if tnames else 'exa.language_server_pb.LanguageServerService'
print(f"Service: {svc}")

# Find ALL typeNames near cascade methods
cascade_idx = js.find('startCascade')
if cascade_idx > 0:
    c_region = js[max(0,cascade_idx-3000):cascade_idx+100]
    c_tnames = re.findall(r'typeName:\s*["\']([^"\']+)["\']', c_region)
    if c_tnames: print(f"Cascade service: {c_tnames[-1]}")

# ── STEP 2: Test InitializeCascadePanelState on both ports ───────────────────
print("\n=== STEP 2: InitializeCascadePanelState on PROTO port 64958 ===")
meta_proto = fs(1,'windsurf') + fs(7,'1.9577.43') + fs(3,'windsurf') + fs(4,api_key)

# Build InitializeCascadePanelStateRequest
# Common fields: metadata(1), workspace(2-4), cascade_id
for method_path in [
    '/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState',
    '/exa.cascade_pb.CascadeService/InitializeCascadePanelState',
    '/exa.language_server_pb.LanguageServerService/StartCascade',
    '/exa.cascade_pb.CascadeService/StartCascade',
]:
    for inst in INSTANCES:
        body = fm(1, meta_proto)  # binary proto body with metadata
        try:
            s, raw = post(inst, method_path, body, timeout=8)
            results = parse_resp(s, raw, inst['proto'])
            e = err_text(results)
            if s != 415:
                print(f"  [{inst['label']}] {method_path.split('/')[-1]}: HTTP {s} → {e[:100]}")
        except Exception as ex:
            print(f"  [{inst['label']}] error: {ex}")

# ── STEP 3: Try GetStatus on proto port ──────────────────────────────────────
print("\n=== STEP 3: GetStatus on PROTO port 64958 ===")
inst_proto = INSTANCES[1]  # 64958
s, raw = post(inst_proto, '/exa.language_server_pb.LanguageServerService/GetStatus', b'', timeout=8)
results = parse_resp(s, raw, 'proto')
print(f"GetStatus PROTO: HTTP {s}, {len(raw)} bytes")
if raw:
    print(f"  raw: {raw[:200].hex()}")

# ── STEP 4: Try RawGetChatMessage on PROTO port with binary body ─────────────
print("\n=== STEP 4: RawGetChatMessage on PROTO port 64958 ===")
conv_id = str(uuid.uuid4())
msg_id  = str(uuid.uuid4())
ts      = '2026-03-30T21:49:00Z'

# Build chat message proto
chat_msg = (
    fs(1, msg_id)  +   # messageId
    fi(2, 1)       +   # role=USER
    fs(3, 'Reply with exactly: OPUS46_BREAKTHROUGH') +  # content
    fs(4, ts)      +   # timestamp
    fs(5, conv_id)     # conversationId
)
body_proto = fm(1, meta_proto) + fm(2, chat_msg)

s, raw = post(inst_proto,
              '/exa.language_server_pb.LanguageServerService/RawGetChatMessage',
              body_proto, timeout=30)
print(f"RawGetChatMessage PROTO: HTTP {s}, {len(raw)} bytes")
if raw: print(f"  raw[:300]: {raw[:300]}")

# Parse proto response chunks
pos = 0
while pos < len(raw):
    if pos + 5 > len(raw): break
    flag = raw[pos]; length = struct.unpack('>I', raw[pos+1:pos+5])[0]
    chunk = raw[pos+5:pos+5+length]; pos += 5 + length
    print(f"  chunk flag={flag}: {chunk[:200]}")
    try:
        obj = json.loads(chunk)
        print(f"  → {obj}")
    except:
        pass

# ── STEP 5: Find ALL available methods on port 64958 ────────────────────────
print("\n=== STEP 5: What works on PROTO port 64958? ===")
test_methods = [
    'GetStatus', 'GetChatMessage', 'RawGetChatMessage',
    'CheckChatCapacity', 'CheckUserMessageRateLimit',
    'InitializeCascadePanelState', 'StartCascade',
    'GetCascadeModelConfigs', 'GetMessageTokenCount',
]
for m in test_methods:
    path = f'/exa.language_server_pb.LanguageServerService/{m}'
    try:
        s, raw2 = post(inst_proto, path, b'', timeout=5)
        print(f"  {m}: HTTP {s} ({len(raw2)}B)")
    except Exception as ex:
        print(f"  {m}: {ex}")

# ── STEP 6: Direct JSON RawGetChatMessage on port 57407 + try to get working ─
print("\n=== STEP 6: Exhaustive JSON RawGetChatMessage with every possible extra field ===")
inst_json = INSTANCES[0]  # 57407

payloads_to_try = [
    # Try with explicit cascadeId
    {'cascadeId': str(uuid.uuid4()), 'cascadeSessionId': str(uuid.uuid4())},
    # Try with workspaceContext
    {'workspaceContext': {'rootPath': 'e:/道/道生一/一生二', 'workspaceName': '一生二'}},
    # Try different metadata with ideVersionWithBuildInfo
    {'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43','extensionVersion':'1.9577.43',
                  'apiKey':api_key,'ideVersionWithBuildInfo':'1.9577.43 (codeium)',
                  'sessionId':str(uuid.uuid4())}},
    # Try with streaming flag
    {'stream': True},
    # Try without model (server picks default)
    {},
]

for extra in payloads_to_try:
    base = {
        'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43',
                     'extensionVersion':'1.9577.43','apiKey':api_key},
        'chatMessages': [{
            'messageId': str(uuid.uuid4()), 'role':1,
            'content':'Reply OK', 'timestamp':'2026-03-30T21:49:00Z',
            'conversationId': str(uuid.uuid4()),
        }],
        'model': 'claude-sonnet-4-5',
    }
    if 'metadata' in extra:
        base['metadata'] = extra.pop('metadata')
    base.update(extra)
    
    s, raw3 = post(inst_json,
                   '/exa.language_server_pb.LanguageServerService/RawGetChatMessage',
                   base, timeout=10)
    results = parse_resp(s, raw3, 'json')
    e = err_text(results)
    if '[OK]' in e or 'cascade session' not in e.lower():
        print(f"  DIFFERENT: {extra} → HTTP {s}: {e[:120]}")
    # else: same cascade session error, skip
