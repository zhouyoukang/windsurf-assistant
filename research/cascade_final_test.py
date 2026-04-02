"""cascade_final_test.py — 用固定 cascade-auth key 测试默认模型"""
import json, sqlite3, struct, time, requests, re

# Try stable cascade-auth key
with open(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\cascade-auth.json') as f:
    cascade_auth = json.load(f)
CASCADE_KEY = cascade_auth.get('apiKey') or cascade_auth.get('authToken') or cascade_auth.get('token')

# Also get current WAM key
DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
con = sqlite3.connect(DB); cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable")
rows = dict(cur.fetchall()); con.close()
WAM_KEY = json.loads(rows.get('windsurfAuthStatus','{}')).get('apiKey','')

CSRF = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
PORT = 64958

print(f"CascadeAuth key: {CASCADE_KEY[:40]}...")
print(f"WAM key:         {WAM_KEY[:40]}...")
print()

def make_meta(api_key):
    return {"ideName":"Windsurf","ideVersion":"1.108.2","extensionVersion":"3.14.2",
            "extensionName":"Windsurf","extensionPath":r"D:\Windsurf\resources\app\extensions\windsurf",
            "apiKey":api_key,"locale":"en-US","os":"win32","url":"https://server.codeium.com"}

HDR = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
       'x-codeium-csrf-token':CSRF,'x-grpc-web':'1'}

def call(method, body, timeout=8):
    b = json.dumps(body).encode()
    r = requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/{method}',
                      data=b'\x00'+struct.pack('>I',len(b))+b, headers=HDR, timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames=[]; pos=0
    while pos+5<=len(raw):
        flag=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        frames.append((flag,raw[pos:pos+n])); pos+=n
    return frames

def stream_cascade(cascade_id, meta, wait_secs=25):
    """Stream and collect response strings"""
    stream_b = json.dumps({"id":cascade_id,"protocolVersion":1}).encode()
    stream_d = b'\x00'+struct.pack('>I',len(stream_b))+stream_b
    
    found_strings = []
    def walk(obj, depth=0):
        if depth > 15: return
        if isinstance(obj, str) and 5 < len(obj) < 600:
            found_strings.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values(): walk(v, depth+1)
        elif isinstance(obj, list):
            for item in obj: walk(item, depth+1)
    
    frame_n = 0
    try:
        r3 = requests.post(
            f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
            data=stream_d, headers=HDR, timeout=wait_secs+2, stream=True)
        buf=b''; t0=time.time()
        for chunk in r3.iter_content(chunk_size=128):
            buf += chunk
            while len(buf) >= 5:
                n = struct.unpack('>I', buf[1:5])[0]
                if len(buf) < 5+n: break
                flag=buf[0]; frame=buf[5:5+n]; buf=buf[5+n:]
                if flag == 0x80:
                    t = frame.decode('utf-8','replace')
                    found_strings.append(f"TRAILER:{t[:100]}")
                    break
                try:
                    parsed = json.loads(frame)
                    frame_n += 1
                    walk(parsed)
                except: pass
            if time.time()-t0 > wait_secs: break
    except Exception as e:
        pass
    return frame_n, found_strings

# Test 1: No model specified (use server default), with WAM key
print("=== Test 1: No model (WAM key) ===")
META1 = make_meta(WAM_KEY)
call("InitializeCascadePanelState", {"metadata":META1,"workspaceTrusted":True})
call("UpdateWorkspaceTrust", {"metadata":META1,"workspaceTrusted":True})
f1 = call("StartCascade", {"metadata":META1,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
cid1 = None
for flag, data in f1:
    if flag == 0:
        try: cid1 = json.loads(data).get('cascadeId')
        except: pass
print(f"cascade_id: {cid1}")
f2 = call("SendUserCascadeMessage", {
    "metadata": META1,
    "cascadeId": cid1,
    "items": [{"text": "Reply: CONNECTED"}],
    "cascadeConfig": {"plannerConfig": {"conversational": {}}},
}, timeout=8)
ok1 = any(b'status: 0' in d for f, d in f2)
print(f"Sent: {ok1}")
fn1, strings1 = stream_cascade(cid1, META1, wait_secs=20)
print(f"Frames: {fn1}, strings: {len(strings1)}")
errors1 = [s for s in strings1 if 'error' in s.lower() or 'denied' in s.lower() or 'TRAILER' in s]
responses1 = [s for s in strings1 if any(x in s for x in ['CONNECTED','reply','Reply','4','2+2'])]
if errors1: print(f"Errors: {errors1[0][:100]}")
if responses1: print(f"RESPONSE: {responses1[0][:200]}")
if not errors1 and not responses1:
    # Show last few strings
    clean = [s for s in strings1 if 10 < len(s) < 200 and 'MODEL_' not in s and 'D:\\' not in s]
    for s in clean[-5:]:
        print(f"  str: {repr(s[:100])}")
print()

# Test 2: cascade-auth key, with Windsurf Fast (should always work)
print("=== Test 2: Windsurf Fast (cascade-auth key) ===")
META2 = make_meta(CASCADE_KEY)
call("InitializeCascadePanelState", {"metadata":META2,"workspaceTrusted":True})
call("UpdateWorkspaceTrust", {"metadata":META2,"workspaceTrusted":True})
f3 = call("StartCascade", {"metadata":META2,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
cid2 = None
for flag, data in f3:
    if flag == 0:
        try: cid2 = json.loads(data).get('cascadeId')
        except: pass
print(f"cascade_id: {cid2}")
f4 = call("SendUserCascadeMessage", {
    "metadata": META2,
    "cascadeId": cid2,
    "items": [{"text": "Reply: CONNECTED"}],
    "cascadeConfig": {"plannerConfig": {
        "requestedModelUid": "MODEL_WINDSURF_FAST",
        "conversational": {}
    }},
}, timeout=8)
ok2 = any(b'status: 0' in d for f, d in f4)
print(f"Sent: {ok2}")
fn2, strings2 = stream_cascade(cid2, META2, wait_secs=20)
print(f"Frames: {fn2}, strings: {len(strings2)}")
errors2 = [s for s in strings2 if 'error' in s.lower() or 'denied' in s.lower() or 'TRAILER' in s]
responses2 = [s for s in strings2 if any(x in s for x in ['CONNECTED','BACKEND','4','2'])]
if errors2: print(f"Error: {errors2[0][:150]}")
if responses2: print(f"RESPONSE: {responses2[0][:200]}")
clean2 = [s for s in strings2 if 10 < len(s) < 200 and 'MODEL_' not in s and 'D:\\' not in s and 'TRAILER' not in s]
print(f"Sample strings: {[repr(s[:80]) for s in clean2[-5:]]}")
