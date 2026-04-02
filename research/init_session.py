"""
init_session.py — 用 binary proto 调 InitializeCascadePanelState 建立 session
步骤:
  1. 迭代找 InitializeCascadePanelStateRequest 必填字段
  2. 成功后获取 cascadeId / sessionId
  3. 用该 ID 调 RawGetChatMessage
"""
import struct, http.client, json, sqlite3, uuid

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
PORT = 57407; CSRF = '18e67ec6-8a9b-4781-bcea-ac61a722a640'

conn = sqlite3.connect(DB); cur = conn.cursor()
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
row = cur.fetchone(); conn.close()
api_key = json.loads(row[0]).get('apiKey', '')
print(f"api_key: {api_key[:20]}...\n")

def varint(n):
    out = []
    while n > 0x7F: out.append((n & 0x7F)|0x80); n >>= 7
    out.append(n & 0x7F); return bytes(out)

def f_str(no, s):
    b = s.encode() if isinstance(s, str) else s
    return varint((no<<3)|2) + varint(len(b)) + b

def f_msg(no, m): return varint((no<<3)|2) + varint(len(m)) + m
def f_int(no, v): return varint((no<<3)|0) + varint(v)
def frame(d): return b'\x00' + struct.pack('>I', len(d)) + d

def post_proto(method, body, timeout=15):
    path = f'/exa.language_server_pb.LanguageServerService/{method}'
    framed = frame(body)
    h = {'Content-Type':'application/connect+proto',
         'Accept':'application/connect+proto',
         'Connect-Protocol-Version':'1',
         'x-codeium-csrf-token':CSRF}
    conn2 = http.client.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
    conn2.request('POST', path, framed, h)
    r = conn2.getresponse(); data = r.read(8192)
    chunks = []
    pos = 0
    while pos < len(data):
        if pos + 5 > len(data): break
        flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]; pos += 5 + length
        chunks.append((flag, chunk))
    return r.status, chunks

def err(chunks):
    for flag, chunk in chunks:
        try:
            obj = json.loads(chunk)
            if 'error' in obj:
                return obj['error'].get('message', '')[:250]
        except: pass
    return str(chunks[0][1][:200]) if chunks else ''

# Build RequestMetadata proto
meta = f_str(1, 'windsurf') + f_str(7, '1.9577.43') + f_str(3, 'windsurf') + f_str(4, api_key)

print("=== InitializeCascadePanelState — finding required fields ===")

# T1: empty
s, chunks = post_proto('InitializeCascadePanelState', b'')
print(f"T1 empty: HTTP {s} → {err(chunks)[:150]}")

# T2: just metadata
s, chunks = post_proto('InitializeCascadePanelState', f_msg(1, meta))
print(f"T2 meta: HTTP {s} → {err(chunks)[:150]}")

# T3: add workspace path
for fname in ['workspaceRootPath', 'workspaceName', 'cascadeId', 'sessionId']:
    # Try as string field at positions 2-6
    for fno in range(2, 7):
        body = f_msg(1, meta) + f_str(fno, 'e:/道/道生一/一生二')
        s, chunks = post_proto('InitializeCascadePanelState', body)
        e = err(chunks)
        if e and 'invalid_argument' not in e.lower() and 'unmarshal' not in e.lower():
            print(f"T3 field{fno}: HTTP {s} → {e[:120]}")
        elif 'unimplemented' in e.lower() or ('invalid_argument' in e.lower() and 'validation' in e.lower()):
            print(f"T3 field{fno}: HTTP {s} → {e[:120]}")
            break

# T4: Send all fields 1-10 as strings
body_all = b''.join(f_str(i, 'windsurf_val') for i in range(1, 11))
s, chunks = post_proto('InitializeCascadePanelState', body_all)
print(f"T4 all-fields: HTTP {s} → {err(chunks)[:150]}")

# T5: meta + all other fields
body_meta_all = f_msg(1, meta) + b''.join(f_str(i, 'windsurf_val') for i in range(2, 10))
s, chunks = post_proto('InitializeCascadePanelState', body_meta_all)
print(f"T5 meta+all: HTTP {s} → {err(chunks)[:150]}")

# T6: Try with JSON (should be 415 or different error)
print("\n=== Also try JSON content-type ===")
jp = {'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43','extensionVersion':'1.9577.43','apiKey':api_key}}
jb = json.dumps(jp).encode()
jf = frame(jb)
h2 = {'Content-Type':'application/connect+json','Accept':'application/connect+json',
      'Connect-Protocol-Version':'1','x-codeium-csrf-token':CSRF}
c2 = http.client.HTTPConnection('127.0.0.1', PORT, timeout=10)
c2.request('POST','/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState',jf,h2)
r2 = c2.getresponse()
print(f"JSON init: HTTP {r2.status} → {r2.read(200)}")

# T7: GetStatus - known to return something
print("\n=== GetStatus (baseline) ===")
s7, chunks7 = post_proto('GetStatus', b'')
print(f"GetStatus: HTTP {s7}")
for flag, chunk in chunks7:
    try:
        obj = json.loads(chunk)
        print(f"  {flag}: {json.dumps(obj, ensure_ascii=False)[:300]}")
    except:
        print(f"  {flag}: {chunk[:100]}")
