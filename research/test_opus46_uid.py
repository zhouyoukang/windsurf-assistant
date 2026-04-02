"""test_opus46_uid.py — 测试 claude-opus-4-6 + 相关 opus uid 是否服务端可用"""
import json, struct, time, requests

with open(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\cascade-auth.json') as f:
    KEY = json.load(f).get('apiKey','')

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
        flag=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        frames.append((flag,raw[pos:pos+n])); pos+=n
    return frames

def walk(o,d=0):
    if d>25: return []
    r=[]
    if isinstance(o,str) and 4<len(o)<300: r.append(o)
    elif isinstance(o,dict): [r.extend(walk(v,d+1)) for v in o.values()]
    elif isinstance(o,list): [r.extend(walk(i,d+1)) for i in o]
    return r

def test_model(uid):
    call("InitializeCascadePanelState",{"metadata":META,"workspaceTrusted":True})
    call("UpdateWorkspaceTrust",{"metadata":META,"workspaceTrusted":True})
    f1=call("StartCascade",{"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
    cid=next((json.loads(d).get('cascadeId') for fl,d in f1 if fl==0 and b'cascadeId' in d),None)
    if not cid: return "no cascade_id"
    
    f2=call("SendUserCascadeMessage",{"metadata":META,"cascadeId":cid,
        "items":[{"text":"1+1=?"}],
        "cascadeConfig":{"plannerConfig":{"requestedModelUid":uid,"conversational":{}}}})
    t=next((d.decode('utf-8','replace') for fl,d in f2 if fl==0x80),'')
    if 'status: 0' not in t: return f"SEND FAIL: {t.strip()[:80]}"
    
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
    if errors: return f"ERROR: {errors[0][:120]}"
    return f"OK ({len(strings)} strings, no errors)"

# Test models
MODELS = [
    "claude-opus-4-6",           # 用户期望
    "claude-opus-4-5-20251101h", # 从 windsurfConfigurations 发现
    "claude-opus-4",             # 基础 opus 4
    "claude-opus-4-20250514h",   # opus 4 with date
    "claude-sonnet-4-6",         # 已知可用
]

for uid in MODELS:
    print(f"\nTesting: {uid}")
    result = test_model(uid)
    icon = "✅" if result.startswith("OK") else "❌"
    print(f"  {icon} {result}")
