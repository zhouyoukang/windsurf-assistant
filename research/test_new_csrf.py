import requests, json, struct, sqlite3, io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

con = sqlite3.connect(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb')
key = json.loads(con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()[0]).get('apiKey','')
con.close()

meta = {'ideName':'Windsurf','ideVersion':'1.108.2','extensionVersion':'3.14.2',
        'apiKey':key,'locale':'en-US','os':'win32','url':'https://server.codeium.com'}

def grpc_call(port, csrf, method, body_dict):
    b = json.dumps(body_dict).encode()
    r = requests.post(
        f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{method}',
        data=b'\x00'+struct.pack('>I',len(b))+b,
        headers={'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
                 'x-codeium-csrf-token':csrf,'x-grpc-web':'1'},
        timeout=6, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    trailer = ''
    pos=0
    while pos+5<=len(raw):
        fl=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        chunk=raw[pos:pos+n]; pos+=n
        if fl==0x80: trailer=chunk.decode('utf-8','replace')
    return r.status_code, trailer, raw

PORT = 61476
CSRF = '4ebfe20f-7564-49fc-a3c9-549266121427'
print(f"Testing port={PORT} CSRF={CSRF[:8]}...")

sc, t, raw = grpc_call(PORT, CSRF, 'InitializeCascadePanelState', {'metadata':meta,'workspaceTrusted':True})
print(f"Init: HTTP={sc} grpc={t.strip()[:60]}")

if 'grpc-status: 0' in t:
    print("CSRF OK! Testing full cascade...")
    grpc_call(PORT, CSRF, 'UpdateWorkspaceTrust', {'metadata':meta,'workspaceTrusted':True})
    sc2, t2, raw2 = grpc_call(PORT, CSRF, 'StartCascade', {'metadata':meta,'source':'CORTEX_TRAJECTORY_SOURCE_USER'})
    print(f"StartCascade: HTTP={sc2} grpc={t2.strip()[:60]}")
    # Extract cascadeId
    cid = None
    pos=0
    while pos+5<=len(raw2):
        fl=raw2[pos]; n=struct.unpack('>I',raw2[pos+1:pos+5])[0]; pos+=5
        chunk=raw2[pos:pos+n]; pos+=n
        if fl==0:
            try: cid=json.loads(chunk).get('cascadeId')
            except: pass
    print(f"cascadeId: {cid}")
    if cid:
        sc3,t3,_ = grpc_call(PORT, CSRF, 'SendUserCascadeMessage', {
            'metadata':meta, 'cascadeId':cid,
            'items':[{'text':'你好，你是谁？'}],
            'cascadeConfig':{'plannerConfig':{'requestedModelUid':'claude-opus-4-6','conversational':{}}}
        })
        print(f"SendMsg: HTTP={sc3} grpc={t3.strip()[:60]}")
        # Stream
        sb = json.dumps({'id':cid,'protocolVersion':1}).encode()
        r4 = requests.post(
            f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
            data=b'\x00'+struct.pack('>I',len(sb))+sb,
            headers={'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
                     'x-codeium-csrf-token':CSRF,'x-grpc-web':'1'},
            timeout=25, stream=True)
        buf=b''; t0=time.time(); responses=[]
        for chunk in r4.iter_content(chunk_size=128):
            buf+=chunk
            while len(buf)>=5:
                nl=struct.unpack('>I',buf[1:5])[0]
                if len(buf)<5+nl: break
                fr=buf[5:5+nl]; buf=buf[5+nl:]
                try:
                    d=json.loads(fr)
                    s=json.dumps(d)
                    if len(s)>10 and 'permission_denied' not in s.lower():
                        responses.append(s[:200])
                except: pass
            if len(responses)>=3 or time.time()-t0>15: break
        print(f"\nStream responses:")
        for r_ in responses[:3]:
            print(f"  {r_[:150]}")
else:
    print("CSRF FAILED")
    # Try other ports
    for port2 in [61484, 61469]:
        sc, t, _ = grpc_call(port2, CSRF, 'InitializeCascadePanelState', {'metadata':meta,'workspaceTrusted':True})
        print(f"  port={port2}: HTTP={sc} grpc={t.strip()[:50]}")
