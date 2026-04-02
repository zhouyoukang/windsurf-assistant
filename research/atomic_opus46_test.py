"""atomic_opus46_test.py
用当前 WAM key 同时测 claude-sonnet-4-6（对照）和 claude-opus-4-6（目标）
在一次 cascade session 初始化后立刻发两个并发消息，比较结果
"""
import json, sqlite3, struct, time, requests, threading

PORT = 64958
CSRF = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'

def get_wam_key():
    con = sqlite3.connect(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb')
    k = json.loads(con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()[0]).get('apiKey','')
    con.close()
    return k

KEY = get_wam_key()
print(f"WAM Key: {KEY[:40]}...")

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

def walk(o,d=0):
    if d>25: return []
    r=[]
    if isinstance(o,str) and 4<len(o)<300: r.append(o)
    elif isinstance(o,dict): [r.extend(walk(v,d+1)) for v in o.values()]
    elif isinstance(o,list): [r.extend(walk(i,d+1)) for i in o]
    return r

def test_one(uid, result_dict):
    """Start cascade, send message, stream 9s, record result"""
    # Need fresh init for each cascade
    META2 = {**META}  # same key
    call("InitializeCascadePanelState", {"metadata":META2,"workspaceTrusted":True})
    call("UpdateWorkspaceTrust", {"metadata":META2,"workspaceTrusted":True})

    f1 = call("StartCascade", {"metadata":META2,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
    cid = next((json.loads(d).get('cascadeId') for fl,d in f1 if fl==0 and b'cascadeId' in d), None)
    if not cid:
        result_dict[uid] = "no cascadeId"
        return

    f2 = call("SendUserCascadeMessage", {
        "metadata":META2,"cascadeId":cid,
        "items":[{"text":"1+1=?"}],
        "cascadeConfig":{"plannerConfig":{"requestedModelUid":uid,"conversational":{}}}
    })
    trailer = next((d.decode('utf-8','replace') for fl,d in f2 if fl==0x80), '')
    if 'status: 0' not in trailer:
        result_dict[uid] = f"SEND_FAIL (trailer={trailer.strip()[:40]})"
        return

    sb=json.dumps({"id":cid,"protocolVersion":1}).encode()
    sd=b'\x00'+struct.pack('>I',len(sb))+sb
    strings=[]
    try:
        r3=requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
                         data=sd,headers=HDR,timeout=11,stream=True)
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

    errors=[s for s in strings if 'denied' in s.lower() or 'error occurred' in s.lower()]
    if errors:
        result_dict[uid] = f"PERM_DENIED: {errors[0][:80]}"
    else:
        result_dict[uid] = f"OK ({len(strings)} strings, no errors)"

# Run both tests concurrently to use same WAM key window
results = {}
t1 = threading.Thread(target=test_one, args=("claude-sonnet-4-6", results))
t2 = threading.Thread(target=test_one, args=("claude-opus-4-6", results))
t1.start()
time.sleep(0.3)  # slight stagger to avoid cascade session conflicts
t2.start()
t1.join()
t2.join()

print("\nResults with same WAM key:")
for uid in ["claude-sonnet-4-6", "claude-opus-4-6"]:
    r = results.get(uid, "not tested")
    icon = "✅" if r.startswith("OK") else "❌"
    print(f"  {icon} {uid}: {r}")

# Interpretation
s46 = results.get("claude-sonnet-4-6","")
o46 = results.get("claude-opus-4-6","")
print()
if s46.startswith("OK") and o46.startswith("OK"):
    print("→ claude-opus-4-6 可从服务端底层调用 ✅")
elif s46.startswith("OK") and "PERM_DENIED" in o46:
    print("→ Sonnet 4.6 可用但 Opus 4.6 权限被拒 — opus-4-6 模型不存在或需更高权限 ❌")
elif s46.startswith("OK") and "SEND_FAIL" in o46:
    print("→ Sonnet 4.6 可用但 Opus 4.6 UID 无效（LS 断连）— opus-4-6 模型 UID 不被识别 ❌")
elif "PERM_DENIED" in s46:
    print("→ 当前 WAM key 无 Claude 权限（对照组也失败），结论待确认")
else:
    print(f"→ 结论未定: sonnet={s46} opus={o46}")
