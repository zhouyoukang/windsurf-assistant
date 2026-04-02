"""
grpcweb_init.py — gRPC-Web 调 server.codeium.com/InitializeCascadePanelState
application/grpc-web+proto → HTTP 200 (confirmed!)
gRPC-Web 帧格式: flag(1) + length(4big) + data
  flag=0x00 = data, flag=0x80 = trailers
"""
import struct, http.client, ssl, json, sqlite3, uuid, time, re

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'

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

def grpc_frame(data):
    """gRPC-Web data frame: 0x00 + 4-byte big-endian length + data"""
    return b'\x00' + struct.pack('>I', len(data)) + data

def read_grpc_frames(data):
    """Parse gRPC-Web frames from response body"""
    frames = []
    pos = 0
    while pos < len(data):
        if pos + 5 > len(data): break
        flag = data[pos]
        length = struct.unpack('>I', data[pos+1:pos+5])[0]
        if pos + 5 + length > len(data): break
        payload = data[pos+5:pos+5+length]
        frames.append((flag, payload))
        pos += 5 + length
    return frames

def grpc_web_call(host, path, api_key, proto_body, timeout=20):
    """Make a gRPC-Web call and return parsed frames"""
    ctx = ssl.create_default_context()
    framed = grpc_frame(proto_body)
    headers = {
        'Content-Type': 'application/grpc-web+proto',
        'Accept': 'application/grpc-web+proto',
        'X-Grpc-Web': '1',
        'Authorization': f'Bearer {api_key}',
        'X-Request-Id': str(uuid.uuid4()),
        'User-Agent': 'windsurf/1.9577.43',
        'Content-Length': str(len(framed)),
    }
    conn = http.client.HTTPSConnection(host, 443, timeout=timeout, context=ctx)
    conn.request('POST', path, framed, headers)
    r = conn.getresponse()
    
    # Read ALL response data (including chunked)
    chunks = []
    while True:
        chunk = r.read(4096)
        if not chunk:
            break
        chunks.append(chunk)
    
    data = b''.join(chunks)
    return r.status, dict(r.headers), data

api_key = get_api_key()
print(f"api: {api_key[:20]}...\n")

HOST = 'server.codeium.com'
PATH_INIT = '/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState'

# Build RequestMetadata
meta = fs(1,'windsurf') + fs(7,'1.9577.43') + fs(3,'windsurf') + fs(4,api_key)

# Build InitializeCascadePanelStateRequest
# Fields: metadata(1) + workspaceRootPath(2?) + additional context
init_body_v1 = fm(1, meta)
init_body_v2 = fm(1, meta) + fs(2, 'e:/道/道生一/一生二')
init_body_v3 = fm(1, meta) + fs(2, 'e:/道/道生一/一生二') + fs(3, '一生二') + fs(4, str(uuid.uuid4()))

print("=== InitializeCascadePanelState via gRPC-Web ===")
for label, body in [('minimal', init_body_v1), ('with_path', init_body_v2), ('with_name', init_body_v3)]:
    s, hdrs, data = grpc_web_call(HOST, PATH_INIT, api_key, body, timeout=15)
    frames = read_grpc_frames(data)
    print(f"\n  [{label}]: HTTP {s}, {len(data)} bytes, {len(frames)} frames")
    print(f"  headers: Content-Type={hdrs.get('Content-Type','')} grpc-status={hdrs.get('Grpc-Status','')}")
    for flag, payload in frames:
        if flag == 0x00:  # data frame
            print(f"  data frame ({len(payload)}B): {payload[:200].hex()}")
            # Try to parse as proto
            if payload:
                print(f"  data raw: {payload[:100]}")
        elif flag == 0x80:  # trailers frame
            trailer_str = payload.decode('utf-8', errors='replace')
            print(f"  trailers: {trailer_str[:200]}")

# Also try with empty body (to probe the endpoint)
print("\n=== Empty body probe ===")
s, hdrs, data = grpc_web_call(HOST, PATH_INIT, api_key, b'', timeout=10)
frames = read_grpc_frames(data)
print(f"  empty: HTTP {s}, {len(data)} bytes, {len(frames)} frames")
for flag, payload in frames:
    if flag == 0x80:
        print(f"  trailers: {payload.decode('utf-8','replace')[:200]}")
    else:
        print(f"  data ({len(payload)}B): {payload[:100].hex()}")

# Now try RawGetChatMessage with correct cascade session
print("\n=== After InitializeCascadePanelState - test RawGetChatMessage ===")
PORT = 57407; CSRF = '18e67ec6-8a9b-4781-bcea-ac61a722a640'
import http.client as hc

conv_id = str(uuid.uuid4())
chat_payload = {
    'metadata': {
        'ideName': 'windsurf', 'ideVersion': '1.9577.43',
        'extensionVersion': '1.9577.43', 'apiKey': api_key,
    },
    'chatMessages': [{
        'messageId': str(uuid.uuid4()), 'role': 1,
        'content': 'Reply with exactly: OPUS46_WORKS',
        'timestamp': '2026-03-30T21:57:00Z',
        'conversationId': conv_id,
    }],
    'model': 'claude-opus-4-6',
}

def local_json_call(payload, timeout=30):
    body = json.dumps(payload).encode()
    framed = b'\x00' + struct.pack('>I', len(body)) + body
    h = {'Content-Type':'application/connect+json','Accept':'application/connect+json',
         'Connect-Protocol-Version':'1','x-codeium-csrf-token':CSRF}
    conn2 = hc.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
    conn2.request('POST','/exa.language_server_pb.LanguageServerService/RawGetChatMessage',framed,h)
    r2 = conn2.getresponse(); data2 = r2.read(8192)
    results = []
    pos = 0
    while pos < len(data2):
        if pos+5 > len(data2): break
        flag = data2[pos]; length = struct.unpack('>I', data2[pos+1:pos+5])[0]
        chunk = data2[pos+5:pos+5+length]; pos += 5+length
        try: results.append((flag, json.loads(chunk)))
        except: results.append((flag, chunk))
    return r2.status, results

s2, results = local_json_call(chat_payload)
for flag, obj in results:
    if isinstance(obj, dict):
        dm = obj.get('deltaMessage', {})
        text = dm.get('text', '')
        if text:
            print(f"  [{flag}] {'ERR' if dm.get('isError') else 'OK'}: {text[:200]}")
        if 'error' in obj:
            print(f"  error: {obj['error'].get('message','')[:150]}")
