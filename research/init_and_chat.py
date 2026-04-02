"""
init_and_chat.py — 用 gRPC-Web 完成 InitializeCascadePanelState + RawGetChatMessage
gRPC-Web 在本地 LS 上有效！(Grpc-Status:3 = validation error, not 415)
只需补全 metadata 字段，session 初始化成功后 RawGetChatMessage 生效
"""
import struct, http.client, json, sqlite3, uuid

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
PORT_JSON  = 57407; CSRF_JSON  = '18e67ec6-8a9b-4781-bcea-ac61a722a640'
PORT_GRPC  = 57407; CSRF_GRPC  = '18e67ec6-8a9b-4781-bcea-ac61a722a640'

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

def grpcweb_call(port, csrf, path, body, timeout=15):
    """Call via gRPC-Web, return (grpc_status, grpc_message, response_body)"""
    framed = frm(body)
    h = {
        'Content-Type': 'application/grpc-web+proto',
        'Accept': 'application/grpc-web+proto',
        'X-Grpc-Web': '1',
        'x-codeium-csrf-token': csrf,
    }
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    conn.request('POST', path, framed, h)
    r = conn.getresponse()
    # Read ALL response
    data = b''
    while True:
        chunk = r.read(4096)
        if not chunk: break
        data += chunk
    # grpc-status is in HTTP response headers for gRPC-Web
    grpc_status = r.headers.get('Grpc-Status', '')
    grpc_msg    = r.headers.get('Grpc-Message', '')
    return grpc_status, grpc_msg, data

def json_rpc(port, csrf, path, payload, timeout=30):
    """Call via Connect-RPC JSON"""
    body = json.dumps(payload).encode()
    framed = frm(body)
    h = {'Content-Type': 'application/connect+json', 'Accept': 'application/connect+json',
         'Connect-Protocol-Version': '1', 'x-codeium-csrf-token': csrf}
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    conn.request('POST', path, framed, h)
    r = conn.getresponse()
    data = r.read(8192)
    results = []
    pos = 0
    while pos < len(data):
        if pos + 5 > len(data): break
        flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]; pos += 5+length
        try: results.append((flag, json.loads(chunk)))
        except: results.append((flag, chunk))
    return r.status, results

api_key = get_api_key()
print(f"api: {api_key[:20]}...\n")

PATH_INIT = '/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState'
PATH_CHAT = '/exa.language_server_pb.LanguageServerService/RawGetChatMessage'

# Build full metadata: all fields 1-15 filled
# Known: field1=ideName, field7=ideVersion, field11=sourceAddr (optional, IP)
# Unknown: extension_version at field 2,8,9,10,12-15
# Strategy: fill all 1-15 with reasonable values, leave 11 empty (avoid IP check)
def build_full_meta(api_key, ext_version='1.9577.43'):
    m = b''
    for i in range(1, 16):
        if i == 1:   m += fs(i, 'windsurf')
        elif i == 7: m += fs(i, ext_version)    # ideVersion
        elif i == 11: pass                         # skip sourceAddr (IP validation)
        elif i == 4:  m += fs(i, api_key)         # apiKey (try at field 4)
        else:         m += fs(i, ext_version if i in [2,3,8,9,10] else 'windsurf')
    return m

# Step 1: Initialize cascade session via gRPC-Web
print("=== Step 1: InitializeCascadePanelState (gRPC-Web) ===")

# Progressively add metadata fields
for label, meta_body in [
    ('all_fields',  fm(1, build_full_meta(api_key))),
    ('all_fields+workspace', fm(1, build_full_meta(api_key)) + fs(2, 'e:/道/道生一/一生二')),
    ('minimal',     fm(1, fs(1,'windsurf') + fs(7,'1.9577.43') + fs(3,'1.9577.43') + fs(4,api_key))),
]:
    gs, gm, data = grpcweb_call(PORT_GRPC, CSRF_GRPC, PATH_INIT, meta_body)
    import urllib.parse
    gm_decoded = urllib.parse.unquote(gm)
    print(f"  [{label}]: grpc_status={gs} msg={gm_decoded[:150]}")

# Step 2: Iterate through validation errors to find correct request format
print("\n=== Step 2: Iterate InitializeCascadePanelState validation ===")
meta_full = build_full_meta(api_key)

# Try with different workspace field numbers
for ws_field in [2, 3, 4, 5, 6]:
    body = fm(1, meta_full) + fs(ws_field, 'e:/道/道生一/一生二')
    gs, gm, data = grpcweb_call(PORT_GRPC, CSRF_GRPC, PATH_INIT, body, timeout=8)
    import urllib.parse
    gm_d = urllib.parse.unquote(gm)
    print(f"  workspace@f{ws_field}: status={gs} {gm_d[:120]}")
    if gs == '0':
        print(f"  ✅ SUCCESS! InitializeCascadePanelState worked!")
        break

# Step 3: Also try ALL request fields filled
print("\n=== Step 3: All request fields ===")
meta_full2 = build_full_meta(api_key)
# Try adding more request-level fields: cascadeId, workspaceId, etc
for body_label, body in [
    ('meta+workspace', fm(1, meta_full2) + fs(2, 'e:/道/道生一/一生二')),
    ('meta_only',      fm(1, meta_full2)),
    ('all_req_fields', fm(1, meta_full2) + b''.join(fs(i, 'windsurf') for i in range(2, 12))),
]:
    gs, gm, data = grpcweb_call(PORT_GRPC, CSRF_GRPC, PATH_INIT, body, timeout=8)
    import urllib.parse
    gm_d = urllib.parse.unquote(gm)
    status_emoji = '✅' if gs == '0' else '⚠' if gs == '3' else '❌'
    print(f"  {status_emoji} [{body_label}]: status={gs} {gm_d[:150]}")
    if gs == '0':
        print("  ✅ CASCADE SESSION INITIALIZED!")
        # Now try RawGetChatMessage
        break

# Step 4: Regardless of init status, test RawGetChatMessage after attempted init
print("\n=== Step 4: RawGetChatMessage after init attempts ===")
conv_id = str(uuid.uuid4())
chat_payload = {
    'metadata': {
        'ideName': 'windsurf', 'ideVersion': '1.9577.43',
        'extensionVersion': '1.9577.43', 'apiKey': api_key,
    },
    'chatMessages': [{
        'messageId': str(uuid.uuid4()), 'role': 1,
        'content': 'Reply with exactly: OPUS46_FINAL_BREAKTHROUGH',
        'timestamp': '2026-03-30T22:00:00Z',
        'conversationId': conv_id,
    }],
    'model': 'claude-opus-4-6',
}

s, results = json_rpc(PORT_JSON, CSRF_JSON, PATH_CHAT, chat_payload)
print(f"  HTTP {s}")
for flag, obj in results:
    if isinstance(obj, dict):
        dm = obj.get('deltaMessage', {})
        text = dm.get('text', '')
        if text:
            print(f"  [{flag}] {'❌ERR' if dm.get('isError') else '✅OK'}: {text[:200]}")
        if 'error' in obj:
            print(f"  [{flag}] error: {obj['error'].get('message','')[:200]}")
