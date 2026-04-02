"""poll_claude_key.py
轮询直到拿到有 Claude 权限的 WAM key，然后同时测 sonnet-4-6 和 opus-4-6
最多重试 8 次，每次间隔 8 秒
"""
import json, sqlite3, struct, time, requests

PORT = 64958
CSRF = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
HDR_TMPL = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
            'x-codeium-csrf-token':CSRF,'x-grpc-web':'1'}

def get_wam_key():
    con = sqlite3.connect(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb')
    k = json.loads(con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()[0]).get('apiKey','')
    con.close()
    return k

def make_meta(key):
    return {"ideName":"Windsurf","ideVersion":"1.108.2","extensionVersion":"3.14.2",
            "extensionName":"Windsurf","extensionPath":r"D:\Windsurf\resources\app\extensions\windsurf",
            "apiKey":key,"locale":"en-US","os":"win32","url":"https://server.codeium.com"}

def call(m, body, timeout=7):
    b = json.dumps(body).encode()
    r = requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/{m}',
                      data=b'\x00'+struct.pack('>I',len(b))+b, headers=HDR_TMPL, timeout=timeout, stream=True)
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

def test_model(uid, meta):
    call("InitializeCascadePanelState", {"metadata":meta,"workspaceTrusted":True})
    call("UpdateWorkspaceTrust", {"metadata":meta,"workspaceTrusted":True})
    f1 = call("StartCascade", {"metadata":meta,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
    cid = next((json.loads(d).get('cascadeId') for fl,d in f1 if fl==0 and b'cascadeId' in d), None)
    if not cid: return "no_cid"
    f2 = call("SendUserCascadeMessage", {
        "metadata":meta, "cascadeId":cid,
        "items":[{"text":"1+1=?"}],
        "cascadeConfig":{"plannerConfig":{"requestedModelUid":uid,"conversational":{}}}
    })
    trailer = next((d.decode('utf-8','replace') for fl,d in f2 if fl==0x80), '')
    if 'status: 0' not in trailer: return "send_fail"
    sb=json.dumps({"id":cid,"protocolVersion":1}).encode()
    sd=b'\x00'+struct.pack('>I',len(sb))+sb
    strings=[]
    try:
        r3=requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
                         data=sd, headers=HDR_TMPL, timeout=10, stream=True)
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
    errors=[s for s in strings if 'denied' in s.lower() or 'error occurred' in s.lower()]
    return "denied" if errors else f"OK({len(strings)})"

# Poll loop
TRIES = 12
for attempt in range(TRIES):
    key = get_wam_key()
    meta = make_meta(key)
    print(f"[{attempt+1}/{TRIES}] Key: {key[:30]}... ", end='', flush=True)
    
    # Quick sonnet test first
    sonnet = test_model("claude-sonnet-4-6", meta)
    print(f"sonnet={sonnet}", end=' ', flush=True)
    
    if sonnet.startswith("OK"):
        # Claude key active — now test opus-4-6
        # Get fresh key (might have rotated slightly)
        key2 = get_wam_key()
        meta2 = make_meta(key2)
        opus = test_model("claude-opus-4-6", meta2)
        print(f"opus46={opus}")
        print()
        print("=== DEFINITIVE RESULT ===")
        print(f"claude-sonnet-4-6: {sonnet}")
        print(f"claude-opus-4-6:   {opus}")
        if opus.startswith("OK"):
            print("✅ claude-opus-4-6 可从服务端底层调用!")
        elif "denied" in opus:
            print("❌ claude-opus-4-6 服务端返回 permission_denied — 模型不存在或此 key 无 Opus 4.6 权限")
        elif "send_fail" in opus:
            print("❌ claude-opus-4-6 UID 无效 — 服务端拒绝此 model uid")
        break
    else:
        print()
        if attempt < TRIES - 1:
            print(f"   (无 Claude 权限，{8}秒后重试...)")
            time.sleep(8)
else:
    print("\n⚠️  8次尝试内未获得有 Claude 权限的 WAM key，无法得出最终结论")
    print("结论基于已有证据：claude-opus-4-6 不在 windsurfConfigurations 模型列表中")
