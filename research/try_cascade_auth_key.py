"""try_cascade_auth_key.py — 用 cascade-auth.json key 试 claude-sonnet-4-6"""
import json, sqlite3, struct, time, requests, re

# Get cascade-auth key
with open(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\cascade-auth.json') as f:
    ca = json.load(f)
KEY = ca.get('apiKey') or ca.get('authToken') or ca.get('token','')

CSRF = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
PORT = 64958

print(f"Key: {KEY[:50]}...")

META = {"ideName":"Windsurf","ideVersion":"1.108.2","extensionVersion":"3.14.2",
        "extensionName":"Windsurf","extensionPath":r"D:\Windsurf\resources\app\extensions\windsurf",
        "apiKey":KEY,"locale":"en-US","os":"win32","url":"https://server.codeium.com"}
HDR = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
       'x-codeium-csrf-token':CSRF,'x-grpc-web':'1'}

def call(m, body, timeout=7):
    b = json.dumps(body).encode()
    r = requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/{m}',
                      data=b'\x00'+struct.pack('>I',len(b))+b, headers=HDR, timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames=[]; pos=0
    while pos+5<=len(raw):
        flag=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        frames.append((flag,raw[pos:pos+n])); pos+=n
    return frames

call("InitializeCascadePanelState", {"metadata":META,"workspaceTrusted":True})
call("UpdateWorkspaceTrust", {"metadata":META,"workspaceTrusted":True})

f1 = call("StartCascade", {"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
cid = None
for flag, d in f1:
    if flag == 0:
        try: cid = json.loads(d).get('cascadeId')
        except: pass
print(f"cascade_id: {cid}")
if not cid: exit(1)

f2 = call("SendUserCascadeMessage", {
    "metadata": META,
    "cascadeId": cid,
    "items": [{"text": "Say: CASCADE_AUTH_KEY_CLAUDE_CONNECTED"}],
    "cascadeConfig": {"plannerConfig": {"requestedModelUid":"claude-sonnet-4-6","conversational":{}}},
})
trailer = next((d.decode('utf-8','replace') for fl,d in f2 if fl==0x80), 'no trailer')
data_frames = [d.decode('utf-8','replace') for fl,d in f2 if fl==0]
print(f"Send trailer: {trailer.strip()[:80]}")
print(f"Send data: {data_frames[:2]}")

# Quick 10s stream
sb = json.dumps({"id":cid,"protocolVersion":1}).encode()
sd = b'\x00'+struct.pack('>I',len(sb))+sb
strings=[]
def w(o,d=0):
    if d>25:return
    if isinstance(o,str) and 4<len(o)<400: strings.append(o)
    elif isinstance(o,dict): [w(v,d+1) for v in o.values()]
    elif isinstance(o,list): [w(i,d+1) for i in o]
n=0
try:
    r3=requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
                     data=sd,headers=HDR,timeout=12,stream=True)
    buf=b'';t0=time.time()
    for chunk in r3.iter_content(chunk_size=128):
        buf+=chunk
        while len(buf)>=5:
            nl=struct.unpack('>I',buf[1:5])[0]
            if len(buf)<5+nl:break
            fl=buf[0];fr=buf[5:5+nl];buf=buf[5+nl:]
            if fl!=0x80:
                try: w(json.loads(fr)); n+=1
                except: pass
        if time.time()-t0>10:break
except: pass
print(f"Frames: {n}")
errors=[s for s in strings if 'denied' in s or 'error occurred' in s]
hits=[s for s in strings if 'CASCADE_AUTH' in s or 'CONNECTED' in s]
if hits: print(f"✅ RESPONSE: {hits[0][:200]}")
elif errors: print(f"❌ {errors[0][:150]}")
else:
    clean=[s for s in strings if 5<len(s)<100 and 'MODEL_' not in s and 'D:\\' not in s]
    print(f"Clean strings: {[repr(s[:60]) for s in clean[-5:]]}")
