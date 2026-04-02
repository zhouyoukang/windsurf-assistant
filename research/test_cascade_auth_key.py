"""Test using windsurf-auth.json key as cascade metadata apiKey"""
import requests, json, struct, time, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PORT = 61476
CSRF = '4ebfe20f-7564-49fc-a3c9-549266121427'

# Try the long auth key from windsurf-auth.json
AUTH_KEY = json.load(open(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\windsurf-auth.json')).get('api_key','')
print(f"Auth key: {AUTH_KEY[:40]}...")

meta = {'ideName':'Windsurf','ideVersion':'1.108.2','extensionVersion':'3.14.2',
        'apiKey':AUTH_KEY,'locale':'en-US','os':'win32','url':'https://server.codeium.com'}

HDR = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
       'x-codeium-csrf-token':CSRF,'x-grpc-web':'1'}

def call(method, body):
    b = json.dumps(body).encode()
    r = requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/{method}',
        data=b'\x00'+struct.pack('>I',len(b))+b, headers=HDR, timeout=8, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames=[]; pos=0
    while pos+5<=len(raw):
        fl=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        frames.append((fl,raw[pos:pos+n])); pos+=n
    return r.status_code, frames

sc, f = call('InitializeCascadePanelState', {'metadata':meta,'workspaceTrusted':True})
# check trailer
for fl,d in f:
    if fl==0x80: print(f"Init trailer: {d.decode('utf-8','replace')[:60]}")

call('UpdateWorkspaceTrust', {'metadata':meta,'workspaceTrusted':True})
sc2, f2 = call('StartCascade', {'metadata':meta,'source':'CORTEX_TRAJECTORY_SOURCE_USER'})
cid = None
for fl,d in f2:
    if fl==0:
        try: cid=json.loads(d).get('cascadeId')
        except: pass
    if fl==0x80: print(f"StartCascade trailer: {d.decode('utf-8','replace')[:80]}")
print(f"cascadeId: {cid}")

if not cid: print("FAILED"); sys.exit(1)

call('SendUserCascadeMessage', {
    'metadata':meta, 'cascadeId':cid,
    'items':[{'text':'你是谁？用一句话回答'}],
    'cascadeConfig':{'plannerConfig':{'requestedModelUid':'claude-opus-4-6','conversational':{}}}
})

print("\nStreaming...")
sb = json.dumps({'id':cid,'protocolVersion':1}).encode()
r3 = requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
    data=b'\x00'+struct.pack('>I',len(sb))+sb, headers=HDR, timeout=25, stream=True)

buf=b''; t0=time.time(); count=0; denied=False
for chunk in r3.iter_content(chunk_size=128):
    buf+=chunk
    while len(buf)>=5:
        nl=struct.unpack('>I',buf[1:5])[0]
        if len(buf)<5+nl: break
        fr=buf[5:5+nl]; buf=buf[5+nl:]; count+=1
        try:
            s = json.dumps(json.loads(fr))
            if 'permission_denied' in s.lower():
                denied=True
                print(f"[DENIED] frame {count}")
            else:
                print(f"frame {count}: {s[:200]}")
        except: pass
    if denied or time.time()-t0>15: break

print(f"\nTotal: {count} frames, denied={denied}")
