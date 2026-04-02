"""
local_grpcweb.py — 用 gRPC-Web 调 LOCAL LS 的 InitializeCascadePanelState
关键推理: 本地 LS 415 只测了 JSON/proto，grpc-web 从未测过！
如果 local grpc-web init 成功 → RawGetChatMessage 可以工作
"""
import struct, http.client, json, sqlite3, uuid

DB   = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'

# Both LSP instances
INSTS = [
    (57407, '18e67ec6-8a9b-4781-bcea-ac61a722a640'),
    (64958, '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'),
]

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

def lsp_call(port, csrf, path, body, ct, timeout=12):
    framed = frm(body)
    h = {'Content-Type': ct, 'Accept': ct,
         'x-codeium-csrf-token': csrf,
         'Connect-Protocol-Version': '1',
         'X-Grpc-Web': '1'}
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    conn.request('POST', path, framed, h)
    r = conn.getresponse()
    chunks = []
    while True:
        c = r.read(4096)
        if not c: break
        chunks.append(c)
    data = b''.join(chunks)
    return r.status, dict(r.headers), data

def parse(data, mode='json'):
    out = []
    pos = 0
    while pos < len(data):
        if pos + 5 > len(data): break
        flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]; pos += 5 + length
        if mode == 'json':
            try: out.append((flag, json.loads(chunk)))
            except: out.append((flag, chunk))
        else:
            out.append((flag, chunk))
    return out

api_key = get_api_key()
print(f"api: {api_key[:20]}...\n")

meta = fs(1,'windsurf') + fs(7,'1.9577.43') + fs(3,'windsurf') + fs(4,api_key)
init_body = fm(1, meta)

# Test all content types on BOTH local ports
print("=== Local InitializeCascadePanelState - all content types ===")
for port, csrf in INSTS:
    for ct in [
        'application/grpc-web+proto',
        'application/grpc-web',
        'application/grpc',
        'application/connect+proto',
        'application/connect+json',  # we know this returns 415
    ]:
        body_to_use = init_body
        if ct == 'application/connect+json':
            # JSON version
            j = {'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43',
                              'extensionVersion':'1.9577.43','apiKey':api_key}}
            body_to_use = json.dumps(j).encode()
        try:
            s, hdrs, data = lsp_call(port, csrf,
                '/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState',
                body_to_use, ct, timeout=8)
            print(f"  port={port} [{ct}]: HTTP {s}, {len(data)}B, "
                  f"hdrs={[f'{k}:{v[:30]}' for k,v in hdrs.items() if k.lower() in ('content-type','grpc-status','grpc-message','trailer')]}")
            if data:
                frames = parse(data, 'proto')
                for flag, chunk in frames:
                    print(f"    frame flag={flag}: {chunk[:100]}")
        except Exception as ex:
            print(f"  port={port} [{ct}]: {ex}")

# If any init works, test RawGetChatMessage immediately after
print("\n=== Attempt: gRPC-Web init → RawGetChatMessage ===")
for port, csrf in INSTS:
    for ct in ['application/grpc-web+proto', 'application/grpc-web']:
        try:
            s, hdrs, data = lsp_call(port, csrf,
                '/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState',
                init_body, ct, timeout=8)
            if s == 200:
                print(f"  Init on port={port} [{ct}]: HTTP 200, {len(data)}B")
                all_hdrs = '\n    '.join(f'{k}: {v}' for k,v in hdrs.items())
                print(f"  Response headers:\n    {all_hdrs}")
                
                # Now immediately try RawGetChatMessage
                conv_id = str(uuid.uuid4())
                chat_payload = {
                    'metadata': {
                        'ideName':'windsurf','ideVersion':'1.9577.43',
                        'extensionVersion':'1.9577.43','apiKey':api_key,
                    },
                    'chatMessages': [{
                        'messageId': str(uuid.uuid4()), 'role': 1,
                        'content': 'Reply with: OPUS46_BREAKTHROUGH',
                        'timestamp': '2026-03-30T22:00:00Z',
                        'conversationId': conv_id,
                    }],
                    'model': 'claude-opus-4-6',
                }
                
                # Use JSON for RawGetChatMessage (works on port 57407)
                json_body = json.dumps(chat_payload).encode()
                json_framed = frm(json_body)
                h2 = {'Content-Type':'application/connect+json',
                      'Accept':'application/connect+json',
                      'Connect-Protocol-Version':'1',
                      'x-codeium-csrf-token':'18e67ec6-8a9b-4781-bcea-ac61a722a640'}
                conn2 = http.client.HTTPConnection('127.0.0.1', 57407, timeout=30)
                conn2.request('POST',
                    '/exa.language_server_pb.LanguageServerService/RawGetChatMessage',
                    json_framed, h2)
                r2 = conn2.getresponse()
                data2 = b''
                while True:
                    c2 = r2.read(4096)
                    if not c2: break
                    data2 += c2
                
                results = parse(data2, 'json')
                print(f"  RawGetChatMessage after init: HTTP {r2.status}")
                for flag, obj in results:
                    if isinstance(obj, dict):
                        dm = obj.get('deltaMessage', {})
                        text = dm.get('text', '')
                        if text:
                            print(f"  [{flag}] {'ERR' if dm.get('isError') else '✅OK'}: {text[:200]}")
                        if 'error' in obj:
                            print(f"  [{flag}] error: {obj['error'].get('message','')[:150]}")
        except Exception as ex:
            print(f"  port={port} [{ct}]: {ex}")
