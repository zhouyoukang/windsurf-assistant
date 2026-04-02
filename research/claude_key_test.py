"""claude_key_test.py — 用 cascade-auth key 调 Claude + 试 GetAuthToken"""
import json, sqlite3, struct, time, requests, re

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
con = sqlite3.connect(DB); cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable"); rows = dict(cur.fetchall()); con.close()

# Try cascade-auth key (stable, not WAM-rotated)
with open(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\cascade-auth.json') as f:
    ca = json.load(f)
CASCADE_KEY = ca.get('apiKey') or ca.get('authToken') or ca.get('token','')

CSRF = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
PORT = 64958

def make_meta(key, extra=None):
    m = {"ideName":"Windsurf","ideVersion":"1.108.2","extensionVersion":"3.14.2",
         "extensionName":"Windsurf","extensionPath":r"D:\Windsurf\resources\app\extensions\windsurf",
         "apiKey":key,"locale":"en-US","os":"win32","url":"https://server.codeium.com"}
    if extra: m.update(extra)
    return m

HDR = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
       'x-codeium-csrf-token':CSRF,'x-grpc-web':'1'}

def call(method, body, timeout=8):
    b = json.dumps(body).encode()
    r = requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/{method}',
                      data=b'\x00'+struct.pack('>I',len(b))+b, headers=HDR, timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames=[]; pos=0
    while pos+5<=len(raw):
        flag=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        frames.append((flag,raw[pos:pos+n])); pos+=n
    return r.status_code, frames

print(f"Cascade-auth key: {CASCADE_KEY[:40]}...")
print()

# 1. Try GetAuthToken to get user_jwt
print("=== GetAuthToken ===")
status, f = call("GetAuthToken", {"metadata": make_meta(CASCADE_KEY)})
for flag, data in f:
    if flag == 0x80: print(f"Trailer: {data.decode('utf-8','replace')[:100]}")
    else:
        text = data.decode('utf-8','replace')
        print(f"Data: {text[:400]}")
        # Look for JWT pattern
        jwt_m = re.search(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', text)
        if jwt_m: print(f"JWT: {jwt_m.group(0)[:100]}...")
print()

# 2. Try cascade with cascade-auth key + MODEL_CLAUDE_4_5_OPUS
print("=== Cascade with cascade-auth key + Claude 4.5 Opus ===")
META = make_meta(CASCADE_KEY)
call("InitializeCascadePanelState", {"metadata":META,"workspaceTrusted":True})
call("UpdateWorkspaceTrust", {"metadata":META,"workspaceTrusted":True})

_, f1 = call("StartCascade", {"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
cid = None
for flag, data in f1:
    if flag == 0:
        try: cid = json.loads(data).get('cascadeId')
        except: pass
print(f"cascade_id: {cid}")
if not cid: exit(1)

_, f2 = call("SendUserCascadeMessage", {
    "metadata": META,
    "cascadeId": cid,
    "items": [{"text": "Say: CLAUDE_OPUS_45_WORKS"}],
    "cascadeConfig": {"plannerConfig": {
        "requestedModelUid": "MODEL_CLAUDE_4_5_OPUS",
        "conversational": {}
    }},
})
trailer2 = next((d.decode('utf-8','replace') for f,d in f2 if f==0x80), '')
print(f"Send: {trailer2.strip()[:60]}")

# Stream 12s 
stream_b = json.dumps({"id":cid,"protocolVersion":1}).encode()
stream_d = b'\x00'+struct.pack('>I',len(stream_b))+stream_b

strings=[]
def walk(o,d=0):
    if d>12: return
    if isinstance(o,str) and 4<len(o)<400: strings.append(o)
    elif isinstance(o,dict): [walk(v,d+1) for v in o.values()]
    elif isinstance(o,list): [walk(i,d+1) for i in o]

n=0
try:
    r3 = requests.post(
        f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
        data=stream_d, headers=HDR, timeout=14, stream=True)
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
        if time.time()-t0>12: break
except: pass

print(f"Frames: {n}")
errors = [s for s in strings if 'denied' in s or 'error' in s.lower() and 'error occurred' in s]
hits = [s for s in strings if any(x in s for x in ['CLAUDE','OPUS','WORKS','OK'])]
if hits: print(f"✅ RESPONSE: {hits[0][:200]}")
elif errors: print(f"❌ Error: {errors[0][:150]}")
else:
    clean = [s for s in strings if 10<len(s)<150 and 'MODEL_' not in s and 'D:\\' not in s]
    print(f"Strings: {[repr(s[:80]) for s in clean[-5:]]}")
