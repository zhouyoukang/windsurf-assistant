"""quick_cascade.py — 快速验证 cascade pipeline（不指定模型用服务器默认）"""
import json, sqlite3, struct, time, requests, re

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

def call(method, body, timeout=6):
    b = json.dumps(body).encode()
    r = requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/{method}',
                      data=b'\x00'+struct.pack('>I',len(b))+b, headers=HDR, timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames=[]; pos=0
    while pos+5<=len(raw):
        flag=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        frames.append((flag,raw[pos:pos+n])); pos+=n
    return frames

# Step 1
call("InitializeCascadePanelState", {"metadata":META,"workspaceTrusted":True})
call("UpdateWorkspaceTrust", {"metadata":META,"workspaceTrusted":True})

# Step 2: StartCascade
f1 = call("StartCascade", {"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
cid = next((json.loads(d).get('cascadeId') for flag,d in f1 if flag==0 and b'cascadeId' in d), None)
print(f"CascadeID: {cid}")
if not cid: exit(1)

# Step 3: Send WITHOUT specifying model (use server's default)
f2 = call("SendUserCascadeMessage", {
    "metadata": META,
    "cascadeId": cid,
    "items": [{"text": "Reply with just: OK_2_PLUS_2_EQUALS_4"}],
}, timeout=6)
trailer = next((d.decode('utf-8','replace') for flag,d in f2 if flag==0x80), '')
print(f"Send result: {trailer[:60]}")

# Step 4: Stream 15s
stream_b = json.dumps({"id":cid,"protocolVersion":1}).encode()
stream_d = b'\x00'+struct.pack('>I',len(stream_b))+stream_b
strings = []

def walk(o, d=0):
    if d>12: return
    if isinstance(o,str) and 5<len(o)<400: strings.append(o)
    elif isinstance(o,dict): [walk(v,d+1) for v in o.values()]
    elif isinstance(o,list): [walk(i,d+1) for i in o]

n=0
try:
    r3 = requests.post(
        f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
        data=stream_d,headers=HDR,timeout=16,stream=True)
    buf=b''; t0=time.time()
    for chunk in r3.iter_content(chunk_size=128):
        buf+=chunk
        while len(buf)>=5:
            nl=struct.unpack('>I',buf[1:5])[0]
            if len(buf)<5+nl: break
            flag=buf[0]; frame=buf[5:5+nl]; buf=buf[5+nl:]
            if flag!=0x80:
                try: walk(json.loads(frame)); n+=1
                except: pass
        if time.time()-t0>14: break
except: pass

print(f"Frames: {n}, strings: {len(strings)}")
errors = [s for s in strings if 'denied' in s or 'error' in s.lower()]
hits = [s for s in strings if any(x in s for x in ['OK_2','EQUALS','2+2','4','OK'])]
if hits: print(f"RESPONSE: {hits[0][:200]}")
elif errors: print(f"ERROR: {errors[0][:200]}")
else:
    clean = [s for s in strings if 10<len(s)<150 and 'MODEL_' not in s and 'D:\\' not in s and len(s.split())<30]
    if clean: print(f"Last string: {repr(clean[-1][:150])}")
    else: print(f"No clean strings. Total strings sample: {[repr(s[:60]) for s in strings[-3:]]}")
