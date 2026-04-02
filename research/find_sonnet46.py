"""find_sonnet46.py — 找 claude-sonnet-4-6 enum + 测试 cascade"""
import re, json, sqlite3, struct, time, requests

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# 1. Find all CLAUDE_4_6 enum values
print("=== MODEL_CLAUDE_4_6_* enum values ===")
for m in re.finditer(r'A\[A\.(MODEL_CLAUDE_4_6\w*)=(\d+)\]', content):
    print(f"  {m.group(1)} = {m.group(2)}")

# 2. Find claude-sonnet-4-6 mapping
print()
print("=== claude-sonnet-4-6 references ===")
for m2 in re.finditer(r'claude.sonnet.4.6', content, re.I):
    ctx = content[max(0,m2.start()-100):m2.start()+200]
    if any(x in ctx for x in ['MODEL_', 'enum', 'uid', 'model']):
        print(f"  @{m2.start()}: {repr(ctx[:250])}")
        print()

# 3. Check windsurfConfigurations full decode
print()
print("=== windsurfConfigurations model UIDs ===")
import base64
DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
con = sqlite3.connect(DB); cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable"); rows = dict(cur.fetchall()); con.close()
wsc = rows.get('windsurfConfigurations','')
if wsc:
    try:
        raw = base64.b64decode(wsc + '==')
        # Look for model uid strings (hyphenated)
        model_uids = re.findall(rb'[a-z][-a-z0-9]*-\d+[-\w]*', raw)
        print("Model UIDs found:")
        seen = set()
        for uid in model_uids:
            s = uid.decode('utf-8','replace')
            if s not in seen and len(s) > 3:
                seen.add(s)
                print(f"  {s}")
    except Exception as e:
        print(f"Error: {e}")

# 4. Now test cascade with claude-sonnet-4-6 directly as model uid
print()
print("=== Test cascade with claude-sonnet-4-6 uid ===")
API_KEY = json.loads(rows.get('windsurfAuthStatus','{}')).get('apiKey','')
CSRF = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
PORT = 64958

META = {"ideName":"Windsurf","ideVersion":"1.108.2","extensionVersion":"3.14.2",
        "extensionName":"Windsurf","extensionPath":r"D:\Windsurf\resources\app\extensions\windsurf",
        "apiKey":API_KEY,"locale":"en-US","os":"win32","url":"https://server.codeium.com"}
HDR = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
       'x-codeium-csrf-token':CSRF,'x-grpc-web':'1'}

def call(method, body, timeout=7):
    b = json.dumps(body).encode()
    r = requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/{method}',
                      data=b'\x00'+struct.pack('>I',len(b))+b, headers=HDR, timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames=[]; pos=0
    while pos+5<=len(raw):
        flag=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        frames.append((flag,raw[pos:pos+n])); pos+=n
    return frames

call("InitializeCascadePanelState", {"metadata":META,"workspaceTrusted":True})
call("UpdateWorkspaceTrust", {"metadata":META,"workspaceTrusted":True})

for model_uid in ["claude-sonnet-4-6", "claude-sonnet-4-6-thinking"]:
    print(f"\n  Testing model_uid: {model_uid}")
    _, f1 = call("StartCascade", {"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"}), call("StartCascade", {"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
    cid = None
    f1 = call("StartCascade", {"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
    for flag, data in f1:
        if flag == 0:
            try: cid = json.loads(data).get('cascadeId')
            except: pass
    print(f"  cascade_id: {cid}")
    if not cid: continue

    f2 = call("SendUserCascadeMessage", {
        "metadata": META,
        "cascadeId": cid,
        "items": [{"text": f"Say: {model_uid.upper().replace('-','_')}_WORKS"}],
        "cascadeConfig": {"plannerConfig": {
            "requestedModelUid": model_uid,  # Try uid string directly
            "conversational": {}
        }},
    })
    t = next((d.decode('utf-8','replace') for f,d in f2 if f==0x80), '')
    print(f"  Send: {t.strip()[:60]}")

    # Quick stream check
    sb = json.dumps({"id":cid,"protocolVersion":1}).encode()
    sd = b'\x00'+struct.pack('>I',len(sb))+sb
    strings=[]
    def w(o,d=0):
        if d>12:return
        if isinstance(o,str) and 4<len(o)<300: strings.append(o)
        elif isinstance(o,dict): [w(v,d+1) for v in o.values()]
        elif isinstance(o,list): [w(i,d+1) for i in o]
    try:
        r3=requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
                         data=sd,headers=HDR,timeout=8,stream=True)
        buf=b''; t0=time.time()
        for chunk in r3.iter_content(chunk_size=128):
            buf+=chunk
            while len(buf)>=5:
                nl=struct.unpack('>I',buf[1:5])[0]
                if len(buf)<5+nl: break
                fl=buf[0]; fr=buf[5:5+nl]; buf=buf[5+nl:]
                if fl!=0x80:
                    try: w(json.loads(fr))
                    except: pass
            if time.time()-t0>6: break
    except: pass
    
    errors=[s for s in strings if 'denied' in s or 'error occurred' in s]
    hits=[s for s in strings if model_uid.replace('-','_').upper() in s.upper() or 'WORKS' in s]
    if hits: print(f"  ✅ HIT: {hits[0][:100]}")
    elif errors: print(f"  ❌ Error: {errors[0][:100]}")
    else: print(f"  ? Strings: {[repr(s[:50]) for s in strings if 5<len(s)<100 and 'MODEL_' not in s][-3:]}")
    
    break  # test first one only
