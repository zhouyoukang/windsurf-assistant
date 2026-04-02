"""
httpx_h2_session.py — httpx HTTP/2 同一 session: init + chat
同一 HTTP/2 连接上先做 InitializeCascadePanelState 再做 RawGetChatMessage
"""
import httpx, json, struct, sqlite3, uuid

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
CSRF = '18e67ec6-8a9b-4781-bcea-ac61a722a640'
SVC  = '/exa.language_server_pb.LanguageServerService'

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
def frm(d): return b'\x00' + struct.pack('>I', len(d)) + d

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

HEADERS_GRPC = {
    'content-type':        'application/grpc-web+proto',
    'accept':              'application/grpc-web+proto',
    'x-grpc-web':          '1',
    'x-codeium-csrf-token': CSRF,
}
HEADERS_JSON = {
    'content-type':             'application/connect+json',
    'accept':                   'application/connect+json',
    'connect-protocol-version': '1',
    'x-codeium-csrf-token':     CSRF,
}

def parse_grpc(data):
    """Parse gRPC-Web response frames"""
    frames = []; pos = 0
    while pos < len(data):
        if pos+5 > len(data): break
        flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]; pos += 5+length
        frames.append((flag, chunk))
    return frames

def parse_json_resp(data):
    out = []; pos = 0
    while pos < len(data):
        if pos+5 > len(data): break
        flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]; pos += 5+length
        try: out.append((flag, json.loads(chunk)))
        except: out.append((flag, chunk))
    return out

def text_from(results):
    for flag, obj in results:
        if isinstance(obj, dict):
            dm = obj.get('deltaMessage', {})
            if dm.get('text'):
                return ('ERR' if dm.get('isError') else 'OK', dm['text'][:200])
            if 'error' in obj:
                return ('ERR', obj['error'].get('message','')[:150])
    return ('EMPTY', '')

# ── Test 1: httpx HTTP/2, single Client, same connection ─────────────────────
print("=== Test 1: httpx HTTP/2 - single client ===")
BASE = 'http://127.0.0.1:57407'

try:
    with httpx.Client(http2=True, timeout=30.0) as client:
        print(f"  HTTP/2 client created")
        
        # Step A: InitializeCascadePanelState
        init_body = frm(fm(1, meta))
        r_init = client.post(f'{BASE}{SVC}/InitializeCascadePanelState',
                             content=init_body, headers=HEADERS_GRPC)
        print(f"  Init: HTTP {r_init.status_code}, "
              f"grpc-status={r_init.headers.get('grpc-status','?')}, "
              f"proto={r_init.http_version}")
        
        # Step B: StartCascade
        start_body = frm(fm(1, meta))
        r_start = client.post(f'{BASE}{SVC}/StartCascade',
                              content=start_body, headers=HEADERS_GRPC)
        print(f"  StartCascade: HTTP {r_start.status_code}, "
              f"grpc-status={r_start.headers.get('grpc-status','?')}, "
              f"{len(r_start.content)}B")
        cascade_id = None
        import re
        uuid_re = re.compile(rb'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
        for m in uuid_re.finditer(r_start.content):
            cascade_id = m.group(0).decode()
            break
        print(f"  cascadeId: {cascade_id}")
        
        # Step C: RawGetChatMessage (JSON, same client)
        conv_id = str(uuid.uuid4())
        chat_payload = {
            'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43',
                         'extensionVersion':'1.9577.43','apiKey':api_key},
            'chatMessages': [{'messageId':str(uuid.uuid4()),'role':1,
                              'content':'Reply with exactly: OPUS46_H2_SESSION',
                              'timestamp':'2026-03-30T22:45:00Z',
                              'conversationId':conv_id}],
            'model': 'claude-opus-4-6',
        }
        if cascade_id:
            chat_payload['cascadeId'] = cascade_id
        
        chat_body = frm(json.dumps(chat_payload).encode())
        r_chat = client.post(f'{BASE}{SVC}/RawGetChatMessage',
                             content=chat_body, headers=HEADERS_JSON, timeout=60.0)
        print(f"  RawGetChatMessage: HTTP {r_chat.status_code}, {len(r_chat.content)}B")
        results = parse_json_resp(r_chat.content)
        kind, text = text_from(results)
        print(f"  [{kind}]: {text[:200]}")
        
        if kind == 'OK':
            print("\n🎉🎉🎉 SUCCESS! RawGetChatMessage works via HTTP/2 session!")

except Exception as ex:
    print(f"  Error: {ex}")

# ── Test 2: httpx with different connection options ────────────────────────────
print("\n=== Test 2: httpx HTTP/2, keep-alive hints ===")
for http2_flag in [True, False]:
    try:
        with httpx.Client(http2=http2_flag, timeout=20.0) as c:
            # Init via gRPC-Web
            r = c.post(f'{BASE}{SVC}/InitializeCascadePanelState',
                       content=frm(fm(1, meta)), headers=HEADERS_GRPC)
            gs = r.headers.get('grpc-status','?')
            
            # Chat immediately after
            cp = {'metadata':{'ideName':'windsurf','ideVersion':'1.9577.43',
                              'extensionVersion':'1.9577.43','apiKey':api_key},
                  'chatMessages':[{'messageId':str(uuid.uuid4()),'role':1,
                                   'content':'Reply: OPUS46','timestamp':'2026-03-30T22:45:00Z',
                                   'conversationId':str(uuid.uuid4())}],
                  'model':'claude-opus-4-6'}
            r2 = c.post(f'{BASE}{SVC}/RawGetChatMessage',
                        content=frm(json.dumps(cp).encode()), headers=HEADERS_JSON, timeout=30.0)
            results = parse_json_resp(r2.content)
            kind, text = text_from(results)
            h2_label = 'HTTP/2' if http2_flag else 'HTTP/1.1'
            print(f"  [{h2_label}] init_status={gs} chat: [{kind}] {text[:100]}")
            if kind == 'OK':
                print(f"  ✅ WORKS with {h2_label}!")
    except Exception as ex:
        print(f"  [{h2_label}] error: {ex}")

# ── Test 3: Check if the issue is with the CONTENT TYPE of RawGetChatMessage ──
print("\n=== Test 3: RawGetChatMessage via gRPC-Web (binary proto) ===")
# Build the binary proto request for RawGetChatMessage
# Use the field numbers we discovered from crack2.py / crack3.py
# metadata at field 1 (confirmed)
# chatMessages at some field (unknown, but let's try fields 2-5)
# chat message: role@fi, content@fs, messageId@fs, timestamp@fs, conversationId@fs

def build_chat_msg_proto(msg_id, content, conv_id, ts='2026-03-30T22:45:00Z'):
    # From JSON validation: messageId (min_len), role (int), content (string), timestamp (Timestamp), conversationId (string)
    # Try common field orderings for ChatMessage
    import time
    secs = int(time.time())
    ts_proto = vi((1<<3)|0) + vi(secs) + vi((2<<3)|0) + vi(0)  # Timestamp{seconds, nanos}
    
    # Layout 1: messageId@f1, role@f2, content@f3, timestamp@f4 (as Timestamp message), conversationId@f5
    layout = (fs(1, msg_id) + vi((2<<3)|0) + vi(1) +  # role=USER
              fs(3, content) + fm(4, ts_proto) + fs(5, conv_id))
    return layout

chat_msg = build_chat_msg_proto(str(uuid.uuid4()), 'Reply: OPUS46', str(uuid.uuid4()))
# Try chatMessages at field 2 through 7
try:
    with httpx.Client(http2=True, timeout=20.0) as c2:
        # Init first
        c2.post(f'{BASE}{SVC}/InitializeCascadePanelState',
                content=frm(fm(1, meta)), headers=HEADERS_GRPC)
        
        for cm_field in range(2, 8):
            req_body = fm(1, meta) + fm(cm_field, chat_msg) + fs(10, 'claude-opus-4-6')
            r3 = c2.post(f'{BASE}{SVC}/RawGetChatMessage',
                        content=frm(req_body), headers=HEADERS_GRPC, timeout=15.0)
            frames = parse_grpc(r3.content)
            gs3 = r3.headers.get('grpc-status','?')
            gm3 = r3.headers.get('grpc-message','')[:80]
            print(f"  chat@f{cm_field}: HTTP {r3.status_code} grpc={gs3} {gm3}")
            if gs3 == '0':
                print(f"  ✅ RawGetChatMessage with binary proto succeeded!")
                for flag, chunk in frames:
                    if flag == 0: print(f"    response: {chunk[:100]}")
except Exception as ex:
    print(f"  Error: {ex}")
