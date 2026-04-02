"""live_test.py — 当前状态全流程验证"""
import requests, json, struct, sqlite3, time, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PORT = 61476
CSRF = '4ebfe20f-7564-49fc-a3c9-549266121427'

con = sqlite3.connect(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb')
KEY = json.loads(con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()[0]).get('apiKey','')
con.close()
print(f"Current WAM key: {KEY[:30]}...")

meta = {'ideName':'Windsurf','ideVersion':'1.108.2','extensionVersion':'3.14.2',
        'apiKey':KEY,'locale':'en-US','os':'win32','url':'https://server.codeium.com'}

def call(method, body):
    b = json.dumps(body).encode()
    r = requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/{method}',
        data=b'\x00'+struct.pack('>I',len(b))+b,
        headers={'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
                 'x-codeium-csrf-token':CSRF,'x-grpc-web':'1'},
        timeout=8, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames=[]; pos=0
    while pos+5<=len(raw):
        fl=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        frames.append((fl, raw[pos:pos+n])); pos+=n
    return r.status_code, frames

call('InitializeCascadePanelState', {'metadata':meta,'workspaceTrusted':True})
call('UpdateWorkspaceTrust',        {'metadata':meta,'workspaceTrusted':True})
sc, frames = call('StartCascade', {'metadata':meta,'source':'CORTEX_TRAJECTORY_SOURCE_USER'})
cid = None
for fl,d in frames:
    if fl==0:
        try: cid=json.loads(d).get('cascadeId')
        except: pass
print(f"cascadeId: {cid}")

if not cid:
    print("FAILED: no cascadeId"); sys.exit(1)

call('SendUserCascadeMessage', {
    'metadata':meta, 'cascadeId':cid,
    'items':[{'text':'你是谁？用一句话回答'}],
    'cascadeConfig':{'plannerConfig':{'requestedModelUid':'claude-opus-4-6','conversational':{}}}
})

print("\nStreaming (15s)...")
sb = json.dumps({'id':cid,'protocolVersion':1}).encode()
r3 = requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
    data=b'\x00'+struct.pack('>I',len(sb))+sb,
    headers={'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
             'x-codeium-csrf-token':CSRF,'x-grpc-web':'1'},
    timeout=20, stream=True)

buf=b''; t0=time.time(); count=0; denied=False; texts=[]
for chunk in r3.iter_content(chunk_size=128):
    buf+=chunk
    while len(buf)>=5:
        nl=struct.unpack('>I',buf[1:5])[0]
        if len(buf)<5+nl: break
        fr=buf[5:5+nl]; buf=buf[5+nl:]
        count+=1
        try:
            d=json.loads(fr)
            s=json.dumps(d)
            if 'permission_denied' in s.lower():
                denied=True
                print(f"  [DENIED] permission_denied in frame")
            elif count<=5:
                print(f"  frame {count}: {s[:150]}")
            # Extract any text strings from nested dicts
            def extract_texts(o, depth=0):
                if depth>10: return
                if isinstance(o,str) and 10<len(o)<500:
                    texts.append(o)
                elif isinstance(o,dict):
                    for v in o.values(): extract_texts(v,depth+1)
                elif isinstance(o,list):
                    for i in o: extract_texts(i,depth+1)
            extract_texts(d)
        except: pass
    if denied or time.time()-t0>15: break

print(f"\nTotal frames: {count}, denied: {denied}")
print(f"Text candidates: {texts[:5]}")
