"""e2e_test.py — End-to-end: GPT-4.1 mini + 收 AI 响应文本"""
import json, sqlite3, struct, time, requests, re, sys

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
con = sqlite3.connect(DB); cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable"); rows = dict(cur.fetchall()); con.close()
API_KEY = json.loads(rows.get('windsurfAuthStatus','{}')).get('apiKey','')
CSRF = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
PORT = 64958

META = {"ideName":"Windsurf","ideVersion":"1.108.2","extensionVersion":"3.14.2",
        "extensionName":"Windsurf","extensionPath":r"D:\Windsurf\resources\app\extensions\windsurf",
        "apiKey":API_KEY,"locale":"en-US","os":"win32","url":"https://server.codeium.com"}
HDR = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
       'x-codeium-csrf-token':CSRF,'x-grpc-web':'1'}

def post(method, body, timeout=7):
    b = json.dumps(body).encode()
    d = b'\x00' + struct.pack('>I', len(b)) + b
    r = requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/{method}',
                      data=d, headers=HDR, timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames=[]; pos=0
    while pos+5<=len(raw):
        flag=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        frames.append((flag,raw[pos:pos+n])); pos+=n
    return r.status_code, frames

post("InitializeCascadePanelState", {"metadata":META,"workspaceTrusted":True})
post("UpdateWorkspaceTrust", {"metadata":META,"workspaceTrusted":True})

_, f1 = post("StartCascade", {"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
cid = None
for flag, data in f1:
    if flag == 0:
        try: cid = json.loads(data).get('cascadeId')
        except: pass
print(f"CascadeID: {cid}")
if not cid: sys.exit(1)

# Send with GPT-4.1 mini
status, f2 = post("SendUserCascadeMessage", {
    "metadata": META,
    "cascadeId": cid,
    "items": [{"text": "Reply with exactly: E2E_BACKEND_WORKS"}],
    "cascadeConfig": {"plannerConfig": {
        "requestedModelUid": "MODEL_CHAT_GPT_4_1_MINI_2025_04_14",
        "planModelUid": "MODEL_CHAT_GPT_4_1_MINI_2025_04_14",
        "conversational": {}
    }},
}, timeout=7)

trailer = next((d.decode('utf-8','replace') for flag,d in f2 if flag==0x80), 'no trailer')
print(f"Send: {status} {trailer.strip()[:60]}")

# Stream 18s
stream_b = json.dumps({"id":cid,"protocolVersion":1}).encode()
stream_d = b'\x00'+struct.pack('>I',len(stream_b))+stream_b

print("Streaming 18s...")
strings=[]; n=0
try:
    r3 = requests.post(
        f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
        data=stream_d, headers=HDR, timeout=20, stream=True)
    buf=b''; t0=time.time()
    for chunk in r3.iter_content(chunk_size=128):
        buf+=chunk
        while len(buf)>=5:
            nl=struct.unpack('>I',buf[1:5])[0]
            if len(buf)<5+nl: break
            flag=buf[0]; frame=buf[5:5+nl]; buf=buf[5+nl:]
            if flag==0x80:
                strings.append('TRAILER:'+frame.decode('utf-8','replace')[:80]); break
            try:
                parsed=json.loads(frame); n+=1
                def w(o,d=0):
                    if d>12: return
                    if isinstance(o,str) and 4<len(o)<500: strings.append(o)
                    elif isinstance(o,dict): [w(v,d+1) for v in o.values()]
                    elif isinstance(o,list): [w(i,d+1) for i in o]
                w(parsed)
            except: pass
        if time.time()-t0>17: break
except Exception as e:
    pass

print(f"Frames: {n}")

# Find AI response
SKIP = {'MODEL_','grpc-','http','D:\\','exa.','You are Cascade','The USER',
        'communication','tool_calling','making_code','Before each tool',
        'You have the ability','IMPORTANT','citation','Prefer minimal',
        'Keep dependent','Batch independent','Modifier keys','Available skills'}
found_ai = []
for s in strings:
    if any(x in s for x in ['E2E_BACKEND', 'BACKEND', 'works', 'Works', 'error', 
                              'permission_denied', 'denied', 'TRAILER']): 
        found_ai.append(s)
    elif (not any(x in s for x in SKIP) and 
          5 < len(s) < 200 and 
          not s.startswith(('CiQ', 'Cg', 'eyJ', '0a')) and
          ' ' in s):
        found_ai.append(s)

print("\n=== Result ===")
seen=set()
for s in found_ai:
    if s not in seen:
        seen.add(s)
        print(f"  {repr(s[:200])}")
