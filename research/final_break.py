"""
final_break.py — 最终突破: 解析 gRPC-Web body trailers + 提取 cascadeId
关键: status= (空HTTP header) 可能意味着 grpc-status:0 在 body trailers 里
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

def grpc_call_full(path, body, timeout=20):
    """Full gRPC-Web call, properly parses trailers from body AND headers"""
    framed = frm(body)
    h = {'Content-Type': 'application/grpc-web+proto', 'Accept': 'application/grpc-web+proto',
         'X-Grpc-Web': '1', 'x-codeium-csrf-token': CSRF}
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
    c.request('POST', path, framed, h)
    r = c.getresponse()
    # Read ALL data
    data = b''
    while True:
        ch = r.read(4096)
        if not ch: break
        data += ch
    # Parse HTTP headers
    http_grpc_status = r.headers.get('Grpc-Status', None)
    http_grpc_msg    = urllib.parse.unquote(r.headers.get('Grpc-Message', ''))
    # Parse gRPC-Web frames from body
    frames = []
    pos = 0
    while pos < len(data):
        if pos + 5 > len(data): break
        flag   = data[pos]
        length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk  = data[pos+5:pos+5+length]
        pos   += 5 + length
        frames.append((flag, chunk))
    # Extract status from trailer frame (flag=0x80)
    body_grpc_status = None
    body_grpc_msg    = None
    response_proto   = None
    for flag, chunk in frames:
        if flag == 0x80:  # trailers
            trailer_str = chunk.decode('utf-8', errors='replace')
            m = re.search(r'grpc-status:\s*(\d+)', trailer_str, re.I)
            if m: body_grpc_status = m.group(1)
            m2 = re.search(r'grpc-message:\s*([^\r\n]+)', trailer_str, re.I)
            if m2: body_grpc_msg = urllib.parse.unquote(m2.group(1))
        elif flag == 0x00:  # data
            response_proto = chunk
    # Combine: prefer HTTP header status if present, else body status
    final_status = http_grpc_status if http_grpc_status is not None else body_grpc_status
    final_msg    = http_grpc_msg if http_grpc_msg else (body_grpc_msg or '')
    return {
        'http_status': r.status,
        'grpc_status': final_status,
        'grpc_message': final_msg,
        'frames': frames,
        'response_proto': response_proto,
        'all_headers': dict(r.headers),
    }

def json_call(path, payload, timeout=30):
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

api_key = get_api_key()
print(f"api: {api_key[:20]}...\n")

VALID_URL = 'https://server.codeium.com'

def build_meta(api_key, url=''):
    m = b''
    for i in range(1, 16):
        if i == 1:   m += fs(i, 'windsurf')
        elif i == 7: m += fs(i, '1.9577.43')
        elif i == 11: pass
        elif i == 4: m += fs(i, api_key)
        elif i in [2, 3, 5, 6, 8, 9, 10]:
            m += fs(i, '1.9577.43')
        elif url:
            m += fs(i, url)
        else:
            m += fs(i, 'windsurf')
    return m

# === T1: Parse full response from all-url metadata ===
print("=== T1: Full response parsing (all fields as URL) ===")
meta = build_meta(api_key, url=VALID_URL)
result = grpc_call_full(PATH_INIT, fm(1, meta))
print(f"  HTTP={result['http_status']}, grpc_status={result['grpc_status']}")
print(f"  grpc_msg={result['grpc_message'][:150]}")
print(f"  frames: {len(result['frames'])} (data={sum(1 for f,_ in result['frames'] if f==0)}, trailer={sum(1 for f,_ in result['frames'] if f==0x80)})")
print(f"  response_proto={result['response_proto'][:50] if result['response_proto'] else None}")
print(f"  relevant headers: {[(k,v[:40]) for k,v in result['all_headers'].items() if any(x in k.lower() for x in ['grpc','content','trailer'])]}")

# === T2: Try url at field 14 specifically ===
print("\n=== T2: URL at field 14 ===")
def meta_url_14(api_key):
    m = b''
    for i in range(1, 16):
        if i == 1:   m += fs(i, 'windsurf')
        elif i == 7: m += fs(i, '1.9577.43')
        elif i == 11: pass
        elif i == 4: m += fs(i, api_key)
        elif i == 14: m += fs(i, VALID_URL)
        elif i in [2,3,5,6,8,9,10,12,13,15]: m += fs(i, '1.9577.43')
    return m

result2 = grpc_call_full(PATH_INIT, fm(1, meta_url_14(api_key)))
print(f"  HTTP={result2['http_status']}, grpc_status={result2['grpc_status']}, msg={result2['grpc_message'][:120]}")
if result2['response_proto']:
    print(f"  response data: {result2['response_proto'].hex()}")

# === T3: Iterative approach - fix remaining errors ===
print("\n=== T3: Iterate until status=0 ===")
for attempt in range(1, 8):
    result3 = grpc_call_full(PATH_INIT, fm(1, meta))
    gs = result3['grpc_status']
    gm = result3['grpc_message'][:150]
    print(f"  attempt {attempt}: status={gs} {gm[:100]}")
    if gs == '0' or gs is None:
        print(f"  ✅ InitializeCascadePanelState SUCCESS! status={gs}")
        if result3['response_proto']:
            print(f"  Response proto: {result3['response_proto'].hex()[:100]}")
        break
    # Try to fix whatever the error says
    if 'url' in gm.lower():
        # Use valid URL everywhere
        meta = build_meta(api_key, url=VALID_URL)
    elif 'extension_version' in gm.lower():
        meta = build_meta(api_key, url=VALID_URL)  
    else:
        break

# === T4: Regardless, try RawGetChatMessage after init ===
print("\n=== T4: RawGetChatMessage after InitializeCascadePanelState ===")
# Call init one more time
grpc_call_full(PATH_INIT, fm(1, meta))
# Try chat
conv_id = str(uuid.uuid4())
s, results = json_call(PATH_CHAT, {
    'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43',
                 'extensionVersion':'1.9577.43','apiKey':api_key},
    'chatMessages': [{'messageId':str(uuid.uuid4()),'role':1,
                      'content':'Reply with exactly: OPUS46_BREAKTHROUGH',
                      'timestamp':'2026-03-30T22:10:00Z',
                      'conversationId':conv_id}],
    'model': 'claude-opus-4-6',
})
print(f"  HTTP {s}")
for flag, obj in results:
    if isinstance(obj, dict):
        dm = obj.get('deltaMessage', {})
        text = dm.get('text', '')
        if text: print(f"  [{flag}] {'❌' if dm.get('isError') else '✅'}: {text[:200]}")
        if 'error' in obj: print(f"  err: {obj['error'].get('message','')[:150]}")
