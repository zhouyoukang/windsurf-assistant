"""test_opus_models.py — 测试 opus-4-6 及相关模型是否服务端可调用"""
import json, struct, time, requests, re

d = json.load(open(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\cascade-auth.json'))
KEY = d.get('api_key') or d.get('apiKey') or d.get('authToken') or d.get('token', '')
CSRF = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
PORT = 64958

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
        fl=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        frames.append((fl,raw[pos:pos+n])); pos+=n
    return frames

def walk(o, d=0):
    if d > 25: return []
    r = []
    if isinstance(o, str) and 4 < len(o) < 300: r.append(o)
    elif isinstance(o, dict): [r.extend(walk(v,d+1)) for v in o.values()]
    elif isinstance(o, list): [r.extend(walk(i,d+1)) for i in o]
    return r

call("InitializeCascadePanelState", {"metadata":META,"workspaceTrusted":True})
call("UpdateWorkspaceTrust", {"metadata":META,"workspaceTrusted":True})

def test_model(uid):
    f1 = call("StartCascade", {"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
    cid = next((json.loads(d).get('cascadeId') for fl,d in f1 if fl==0 and b'cascadeId' in d), None)
    if not cid:
        return f"no cascadeId"
    
    f2 = call("SendUserCascadeMessage", {
        "metadata": META, "cascadeId": cid,
        "items": [{"text": "1+1=?"}],
        "cascadeConfig": {"plannerConfig": {"requestedModelUid": uid, "conversational": {}}}
    })
    trailer = next((d.decode('utf-8','replace') for fl,d in f2 if fl==0x80), '')
    if 'status: 0' not in trailer:
        return f"SEND FAIL: {trailer.strip()[:60]}"
    
    # Stream 9s
    sb = json.dumps({"id":cid,"protocolVersion":1}).encode()
    sd = b'\x00'+struct.pack('>I',len(sb))+sb
    strings = []
    try:
        r3 = requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
                           data=sd, headers=HDR, timeout=11, stream=True)
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
            if time.time()-t0>9: break
    except: pass
    
    errors = [s for s in strings if 'denied' in s.lower() or 'error occurred' in s.lower()]
    if errors:
        return f"ERROR: {errors[0][:120]}"
    return f"OK (send:grpc-status:0, stream:{len(strings)} strings, no errors)"

MODELS = [
    ("claude-opus-4-6",            "用户期望"),
    ("claude-opus-4-5-20251101h",  "Opus 4.5 Nov2025"),
    ("claude-opus-4",              "Opus 4 base"),
    ("claude-opus-4-20250514h",    "Opus 4 May2025"),
    ("claude-sonnet-4-6",          "Sonnet 4.6 (已知✓)"),
    ("claude-sonnet-4-6-thinking", "Sonnet 4.6 Thinking"),
]

print(f"Key: {KEY[:35]}...\n")
for uid, label in MODELS:
    result = test_model(uid)
    icon = "✅" if result.startswith("OK") else "❌" if "ERROR" in result else "⚠️"
    print(f"{icon} [{label:22s}] {uid}")
    print(f"     → {result}")
