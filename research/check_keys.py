import json, sqlite3, time, struct, requests

d = json.load(open(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\cascade-auth.json'))
cascade_key = d.get('api_key', '')

con = sqlite3.connect(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb')
cur = con.cursor()
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
row = cur.fetchone()
con.close()
wam_key = json.loads(row[0]).get('apiKey', '') if row else ''

ts = d.get('timestamp', 0)
age_h = round((time.time()*1000 - int(ts)) / 3600000, 1) if ts else 0

print(f"cascade key: {cascade_key[:50]}...")
print(f"WAM key:     {wam_key[:50]}...")
print(f"Same: {cascade_key == wam_key}")
print(f"cascade-auth age: {age_h} hours")

# Quick test both keys with claude-sonnet-4-6
PORT = 64958
CSRF = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
HDR = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
       'x-codeium-csrf-token':CSRF,'x-grpc-web':'1'}

def make_meta(key):
    return {"ideName":"Windsurf","ideVersion":"1.108.2","extensionVersion":"3.14.2",
            "extensionName":"Windsurf","extensionPath":r"D:\Windsurf\resources\app\extensions\windsurf",
            "apiKey":key,"locale":"en-US","os":"win32","url":"https://server.codeium.com"}

def call(m, body, timeout=7):
    b = json.dumps(body).encode()
    r = requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/{m}',
                      data=b'\x00'+struct.pack('>I',len(b))+b, headers=HDR, timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames=[]; pos=0
    while pos+5<=len(raw):
        fl=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        frames.append((fl,raw[pos:pos+n])); pos+=n
    return frames

def walk(o,d=0):
    if d>25: return []
    r=[]
    if isinstance(o,str) and 4<len(o)<300: r.append(o)
    elif isinstance(o,dict): [r.extend(walk(v,d+1)) for v in o.values()]
    elif isinstance(o,list): [r.extend(walk(i,d+1)) for i in o]
    return r

def test_sonnet_with_key(key, label):
    META = make_meta(key)
    call("InitializeCascadePanelState", {"metadata":META,"workspaceTrusted":True})
    call("UpdateWorkspaceTrust", {"metadata":META,"workspaceTrusted":True})
    f1 = call("StartCascade", {"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
    cid = next((json.loads(d).get('cascadeId') for fl,d in f1 if fl==0 and b'cascadeId' in d), None)
    if not cid:
        print(f"  {label}: no cascadeId")
        return

    f2 = call("SendUserCascadeMessage", {
        "metadata":META, "cascadeId":cid,
        "items":[{"text":"1+1=?"}],
        "cascadeConfig":{"plannerConfig":{"requestedModelUid":"claude-sonnet-4-6","conversational":{}}}
    })
    t = next((d.decode('utf-8','replace') for fl,d in f2 if fl==0x80), '')
    if 'status: 0' not in t:
        print(f"  {label}: send fail: {t.strip()[:60]}")
        return

    sb = json.dumps({"id":cid,"protocolVersion":1}).encode()
    sd = b'\x00'+struct.pack('>I',len(sb))+sb
    strings=[]
    try:
        r3=requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
                         data=sd,headers=HDR,timeout=10,stream=True)
        buf=b''; t0=time.time()
        for chunk in r3.iter_content(chunk_size=128):
            buf+=chunk
            while len(buf)>=5:
                nl=struct.unpack('>I',buf[1:5])[0]
                if len(buf)<5+nl: break
                fl=buf[0]; fr=buf[5:5+nl]; buf=buf[5+nl:]
                if fl!=0x80:
                    try: strings.extend(walk(json.loads(fr)))
                    except: pass
            if time.time()-t0>8: break
    except: pass
    errors = [s for s in strings if 'denied' in s.lower() or 'error occurred' in s.lower()]
    if errors:
        print(f"  {label}: permission_denied (key invalid for Claude)")
    else:
        print(f"  {label}: OK - no errors ({len(strings)} strings)")

print("\nTesting claude-sonnet-4-6 with both keys:")
test_sonnet_with_key(cascade_key, "cascade-auth key")
test_sonnet_with_key(wam_key, "WAM key")
