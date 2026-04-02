"""
grpc_native.py — 用 grpcio (HTTP/2) 建立持久连接，解决 cascade session 问题
grpcio 使用 HTTP/2，与 Windsurf 扩展的真实连接方式一致
"""
import grpc, json, sqlite3, uuid, struct, re

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
CSRF_57407 = '18e67ec6-8a9b-4781-bcea-ac61a722a640'
CSRF_64958 = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'

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
    if isinstance(data, str): data = data.encode()
    uuid_re = re.compile(rb'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
    return [m.group(0).decode() for m in uuid_re.finditer(data)]

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

# ── Test 1: Local LS with grpcio (insecure HTTP/2) ────────────────────────────
print("=== Test 1: Local LS gRPC (insecure) ===")
SVC = '/exa.language_server_pb.LanguageServerService'

def raw_unary(channel, method, request_bytes, metadata):
    """Raw unary gRPC call"""
    stub = channel.unary_unary(
        method,
        request_serializer=lambda x: x,
        response_deserializer=lambda x: x
    )
    try:
        response, call = stub.with_call(request_bytes, metadata=metadata)
        return response, None, call
    except grpc.RpcError as e:
        return None, e, None

def raw_stream(channel, method, request_bytes, metadata):
    """Raw server-streaming gRPC call"""
    stub = channel.unary_stream(
        method,
        request_serializer=lambda x: x,
        response_deserializer=lambda x: x
    )
    try:
        responses = stub(request_bytes, metadata=metadata)
        results = []
        for resp in responses:
            results.append(resp)
        return results, None
    except grpc.RpcError as e:
        return [], e

for port, csrf, label in [(57407, CSRF_57407, 'port-57407'), (64958, CSRF_64958, 'port-64958')]:
    print(f"\n  --- {label} ---")
    try:
        channel = grpc.insecure_channel(f'127.0.0.1:{port}')
        metadata = [
            ('x-codeium-csrf-token', csrf),
        ]
        
        # Test InitializeCascadePanelState
        resp, err, call = raw_unary(channel, f'{SVC}/InitializeCascadePanelState',
                                     fm(1, meta), metadata)
        if resp is not None:
            print(f"  InitializeCascadePanelState: OK ({len(resp)} bytes)")
            strings = decode_strings(resp)
            print(f"    strings: {strings[:3]}")
        elif err:
            print(f"  InitializeCascadePanelState: {err.code()} {err.details()[:100]}")
        
        # Test StartCascade
        resp2, err2, call2 = raw_unary(channel, f'{SVC}/StartCascade',
                                        fm(1, meta), metadata)
        cascade_id = None
        if resp2 is not None:
            uuids = find_uuids(resp2)
            cascade_id = uuids[0] if uuids else None
            print(f"  StartCascade: OK cascadeId={cascade_id}")
        elif err2:
            print(f"  StartCascade: {err2.code()} {err2.details()[:80]}")
        
        # Test RawGetChatMessage (server-streaming)
        conv_id = str(uuid.uuid4())
        chat_body = json.dumps({
            'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43',
                         'extensionVersion':'1.9577.43','apiKey':api_key},
            'chatMessages': [{'messageId':str(uuid.uuid4()),'role':1,
                              'content':'Reply with: OPUS46_GRPC_NATIVE',
                              'timestamp':'2026-03-30T22:40:00Z',
                              'conversationId':conv_id}],
            'model': 'claude-opus-4-6',
        }).encode()
        
        # Note: JSON content for JSON-capable endpoints, or binary proto
        # Try with JSON content type hint
        meta_with_ct = metadata + [('content-type', 'application/grpc+json')]
        responses, err3 = raw_stream(channel, f'{SVC}/RawGetChatMessage',
                                      chat_body, metadata)
        if responses:
            print(f"  RawGetChatMessage: {len(responses)} chunks")
            for resp in responses[:3]:
                print(f"    chunk ({len(resp)}B): {resp[:100]}")
        elif err3:
            print(f"  RawGetChatMessage: {err3.code()} {err3.details()[:100]}")
        
        channel.close()
    except Exception as ex:
        print(f"  Error: {ex}")

# ── Test 2: Remote server.codeium.com with grpcio (SSL/HTTP2) ────────────────
print("\n=== Test 2: Remote server.codeium.com (gRPC over TLS/HTTP2) ===")
try:
    ssl_creds = grpc.ssl_channel_credentials()
    remote_channel = grpc.secure_channel('server.codeium.com:443', ssl_creds)
    r_meta = [('authorization', f'bearer {api_key}')]
    
    # InitializeCascadePanelState
    resp_r, err_r, _ = raw_unary(remote_channel, f'{SVC}/InitializeCascadePanelState',
                                   fm(1, meta), r_meta)
    if resp_r is not None:
        print(f"  Remote InitCascade: OK ({len(resp_r)} bytes)")
        strings = decode_strings(resp_r)
        print(f"  strings: {strings[:3]}")
    elif err_r:
        print(f"  Remote InitCascade: {err_r.code()} {err_r.details()[:120]}")
    
    remote_channel.close()
except Exception as ex:
    print(f"  Remote error: {ex}")

# ── Test 3: After grpc init, test JSON RawGetChatMessage ────────────────────
print("\n=== Test 3: gRPC init then JSON RawGetChatMessage ===")
import http.client as hc

def json_raw_chat(api_key, model, timeout=30):
    body = json.dumps({
        'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43',
                     'extensionVersion':'1.9577.43','apiKey':api_key},
        'chatMessages': [{'messageId':str(uuid.uuid4()),'role':1,
                          'content':'Reply with: OPUS46_FINAL_TEST',
                          'timestamp':'2026-03-30T22:40:00Z',
                          'conversationId':str(uuid.uuid4())}],
        'model': model,
    }).encode()
    framed = b'\x00' + struct.pack('>I', len(body)) + body
    h = {'Content-Type':'application/connect+json','Accept':'application/connect+json',
         'Connect-Protocol-Version':'1','x-codeium-csrf-token':CSRF_57407}
    c = hc.HTTPConnection('127.0.0.1', 57407, timeout=timeout)
    c.request('POST', f'{SVC}/RawGetChatMessage', framed, h)
    r = c.getresponse(); data = r.read(8192)
    out = []
    pos = 0
    while pos < len(data):
        if pos+5 > len(data): break
        flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]; pos += 5+length
        try: out.append((flag, json.loads(chunk)))
        except: out.append((flag, chunk))
    return out

# First, do grpc InitializeCascadePanelState
try:
    channel2 = grpc.insecure_channel('127.0.0.1:57407')
    raw_unary(channel2, f'{SVC}/InitializeCascadePanelState', 
              fm(1, meta), [('x-codeium-csrf-token', CSRF_57407)])
    print("  gRPC InitCascade done")
    channel2.close()
except Exception as ex:
    print(f"  gRPC init error: {ex}")

# Then try JSON RawGetChatMessage
for model in ['claude-opus-4-6', 'claude-sonnet-4-5']:
    results = json_raw_chat(api_key, model)
    for flag, obj in results:
        if isinstance(obj, dict):
            dm = obj.get('deltaMessage', {})
            text = dm.get('text', '')
            if text and 'cascade session' not in text.lower():
                print(f"  ✅ DIFFERENT [{model}]: {text[:200]}")
            elif text:
                print(f"  [{model}]: same cascade session error")
            if 'error' in obj:
                err = obj['error'].get('message','')
                if 'cascade session' not in err.lower():
                    print(f"  !! DIFFERENT error [{model}]: {err[:100]}")
