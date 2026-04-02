"""test_opus46_final.py — 新 CSRF + 新端口，测试 opus-4-6 + 相关模型"""
import json, struct, time, requests, re

KEY = json.load(open(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\cascade-auth.json')).get('apiKey','')
META = {"ideName":"Windsurf","ideVersion":"1.108.2","extensionVersion":"3.14.2",
        "extensionName":"Windsurf","extensionPath":r"D:\Windsurf\resources\app\extensions\windsurf",
        "apiKey":KEY,"locale":"en-US","os":"win32","url":"https://server.codeium.com"}

# Try all CSRF + port combos to find working one
CSRF_LIST = [
    '18e67ec6-8a9b-4781-bcea-ac61a722a640',  # NEW - from conhost (new extensionHost)
    '7de33f15-f528-4329-9453-3618de08b9a6',  # PID 440
    '38a7a689-1e2a-41ff-904b-eefbc9dcacfe',  # PID 54108
]
PORTS = [64956, 64958]

working_combo = None
for csrf in CSRF_LIST:
    for port in PORTS:
        HDR = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
               'x-codeium-csrf-token':csrf,'x-grpc-web':'1'}
        b = json.dumps({'metadata':META,'source':'CORTEX_TRAJECTORY_SOURCE_USER'}).encode()
        try:
            r = requests.post(f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/StartCascade',
                              data=b'\x00'+struct.pack('>I',len(b))+b, headers=HDR, timeout=5, stream=True)
            raw = b''.join(r.iter_content(chunk_size=None))
            if r.status_code == 200 and len(raw) > 20:
                cid_m = re.search(rb'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', raw)
                if cid_m:
                    print(f"✅ Working: PORT={port} CSRF={csrf[:8]} cascadeId={cid_m.group(0).decode()}")
                    working_combo = (port, csrf, cid_m.group(0).decode())
                    break
                else:
                    print(f"PORT={port} CSRF={csrf[:8]}: 200 but no UUID in {len(raw)}b response: {repr(raw[:60])}")
            else:
                print(f"PORT={port} CSRF={csrf[:8]}: {r.status_code} len={len(raw)}")
        except Exception as e:
            print(f"PORT={port} CSRF={csrf[:8]}: {type(e).__name__}")
    if working_combo: break

if not working_combo:
    print("❌ No working LS combo found"); exit(1)

PORT, CSRF, _ = working_combo
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

call("InitializeCascadePanelState",{"metadata":META,"workspaceTrusted":True})
call("UpdateWorkspaceTrust",{"metadata":META,"workspaceTrusted":True})

def walk(o,d=0):
    if d>25: return []
    r=[]
    if isinstance(o,str) and 4<len(o)<300: r.append(o)
    elif isinstance(o,dict): [r.extend(walk(v,d+1)) for v in o.values()]
    elif isinstance(o,list): [r.extend(walk(i,d+1)) for i in o]
    return r

def test_model(uid):
    f1 = call("StartCascade", {"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
    cid = next((json.loads(d).get('cascadeId') for fl,d in f1 if fl==0 and b'cascadeId' in d), None)
    if not cid:
        # Try raw UUID search
        for fl, d in f1:
            if fl == 0:
                m = re.search(rb'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', d)
                if m: cid = m.group(0).decode(); break
    if not cid: return f"FAIL: no cascadeId (frames={[(fl,d[:30]) for fl,d in f1]})"
    
    f2 = call("SendUserCascadeMessage", {"metadata":META,"cascadeId":cid,
        "items":[{"text":"1+1=?"}],
        "cascadeConfig":{"plannerConfig":{"requestedModelUid":uid,"conversational":{}}}})
    t = next((d.decode('utf-8','replace') for fl,d in f2 if fl==0x80),'')
    if 'status: 0' not in t: return f"SEND FAIL: {t.strip()[:60]}"
    
    sb=json.dumps({"id":cid,"protocolVersion":1}).encode()
    sd=b'\x00'+struct.pack('>I',len(sb))+sb
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
    
    errors=[s for s in strings if 'denied' in s or 'error occurred' in s]
    if errors: return f"❌ ERROR: {errors[0][:100]}"
    return f"✅ OK (no errors, {len(strings)} strings)"

print(f"\nUsing PORT={PORT} CSRF={CSRF[:8]}")
print("Testing models:")
MODELS = [
    ("claude-opus-4-6",           "用户期望"),
    ("claude-opus-4-5-20251101h", "Opus 4.5 Nov"),
    ("claude-opus-4",             "Opus 4 base"),
    ("claude-opus-4-20250514h",   "Opus 4 May"),
    ("claude-sonnet-4-6",         "已知可用✓"),
]
for uid, label in MODELS:
    result = test_model(uid)
    print(f"  [{label:20s}] {uid}: {result}")
