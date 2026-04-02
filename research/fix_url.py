"""fix_url.py — 找 metadata.url 字段号，完成 InitializeCascadePanelState"""
import struct, http.client, json, sqlite3, uuid, urllib.parse

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
def frm(d): return b'\x00' + struct.pack('>I', len(d)) + d

def grpc_call(path, body, timeout=12):
    framed = frm(body)
    h = {'Content-Type': 'application/grpc-web+proto', 'Accept': 'application/grpc-web+proto',
         'X-Grpc-Web': '1', 'x-codeium-csrf-token': CSRF}
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
    c.request('POST', path, framed, h)
    r = c.getresponse()
    data = b''
    while True:
        ch = r.read(4096)
        if not ch: break
        data += ch
    gs  = r.headers.get('Grpc-Status', '')
    gm  = urllib.parse.unquote(r.headers.get('Grpc-Message', ''))
    return gs, gm, data

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

# Build metadata with KNOWN fields + url at different positions
def meta_with_url_at(url_field):
    m = b''
    for i in range(1, 16):
        if i == 1:         m += fs(i, 'windsurf')
        elif i == 7:       m += fs(i, '1.9577.43')   # ideVersion
        elif i == 11:      pass                        # skip sourceAddr
        elif i == 4:       m += fs(i, api_key)        # apiKey
        elif i == url_field: m += fs(i, VALID_URL)    # url
        elif i in [2,3,8,9,10]: m += fs(i, '1.9577.43')  # versions
        else:              m += fs(i, 'windsurf')
    return m

print("=== Find url field number ===")
for url_f in range(2, 16):
    if url_f in (7, 11, 4): continue
    meta = meta_with_url_at(url_f)
    gs, gm, _ = grpc_call(PATH_INIT, fm(1, meta))
    if 'url' not in gm.lower():
        print(f"  url@f{url_f}: status={gs} DIFFERENT → {gm[:120]}")
    else:
        print(f"  url@f{url_f}: status={gs} still url error")

# Try setting ALL non-known fields to valid URL
print("\n=== All fields as valid URL ===")
def meta_all_url():
    m = b''
    for i in range(1, 16):
        if i == 1:   m += fs(i, 'windsurf')
        elif i == 7: m += fs(i, '1.9577.43')
        elif i == 11: pass
        elif i == 4: m += fs(i, api_key)
        else:        m += fs(i, VALID_URL)
    return m

meta_u = meta_all_url()
gs, gm, _ = grpc_call(PATH_INIT, fm(1, meta_u))
print(f"  all_as_url: status={gs} → {gm[:150]}")

# Also try with extensionVersion at specific fields
print("\n=== Smart metadata: known-field values ===")
def smart_meta():
    m = b''
    for i in range(1, 20):
        if i == 1:   m += fs(i, 'windsurf')              # ide_name
        elif i == 2: m += fs(i, 'windsurf')              # extension_name?
        elif i == 3: m += fs(i, '1.9577.43')             # extension_version?
        elif i == 4: m += fs(i, api_key)                 # api_key
        elif i == 5: m += fs(i, VALID_URL)               # url?
        elif i == 6: m += fs(i, VALID_URL)               # url?
        elif i == 7: m += fs(i, '1.9577.43')             # ide_version
        elif i == 8: m += fs(i, '1.9577.43')             # extension_version?
        elif i == 9: m += fs(i, VALID_URL)               # url?
        elif i == 10: m += fs(i, VALID_URL)              # url?
        elif i == 11: pass                                # source_address (skip)
        elif i == 12: m += fs(i, VALID_URL)              # url?
        elif i == 13: m += fs(i, VALID_URL)              # url?
        elif i == 14: m += fs(i, VALID_URL)              # url?
        elif i == 15: m += fs(i, VALID_URL)              # url?
    return m

gs, gm, _ = grpc_call(PATH_INIT, fm(1, smart_meta()))
print(f"  smart_meta: status={gs} → {gm[:150]}")

if gs == '0':
    print("\n✅✅✅ InitializeCascadePanelState SUCCESS! Grpc-Status=0")
    print("Testing RawGetChatMessage...")
    conv_id = str(uuid.uuid4())
    _, results = json_call(PATH_CHAT, {
        'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43',
                     'extensionVersion':'1.9577.43','apiKey':api_key},
        'chatMessages': [{'messageId':str(uuid.uuid4()),'role':1,
                          'content':'Reply with: OPUS46_WORKS',
                          'timestamp':'2026-03-30T22:05:00Z',
                          'conversationId':conv_id}],
        'model': 'claude-opus-4-6',
    })
    for flag, obj in results:
        if isinstance(obj, dict):
            dm = obj.get('deltaMessage', {})
            if dm.get('text'):
                print(f"  [{'ERR' if dm.get('isError') else 'OK'}]: {dm['text'][:200]}")

# Step: try with init + chat regardless
print("\n=== Final: smart_meta init → RawGetChatMessage ===")
# Rebuild smart meta and call init
gs2, gm2, _ = grpc_call(PATH_INIT, fm(1, smart_meta()) + b''.join(fs(i,'windsurf') for i in range(2,8)))
print(f"Init: status={gs2} {gm2[:100]}")

conv_id2 = str(uuid.uuid4())
s3, r3 = json_call(PATH_CHAT, {
    'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43',
                 'extensionVersion':'1.9577.43','apiKey':api_key},
    'chatMessages': [{'messageId':str(uuid.uuid4()),'role':1,
                      'content':'Reply with: OPUS46_WORKS_NOW',
                      'timestamp':'2026-03-30T22:05:00Z',
                      'conversationId':conv_id2}],
    'model': 'claude-opus-4-6',
})
for flag, obj in r3:
    if isinstance(obj, dict):
        dm = obj.get('deltaMessage', {})
        text = dm.get('text', '')
        if text: print(f"  [{'ERR' if dm.get('isError') else '✅OK'}]: {text[:200]}")
        if 'error' in obj: print(f"  error: {obj['error'].get('message','')[:150]}")
