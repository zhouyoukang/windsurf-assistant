"""cascade_gpt_test.py — 用 GPT-4.1 mini 验证完整 cascade 管道，再搜索 Claude 可用账号"""
import json, sqlite3, struct, time, requests, base64, re

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
con = sqlite3.connect(DB); cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable")
rows = dict(cur.fetchall()); con.close()

auth_status = json.loads(rows.get('windsurfAuthStatus', '{}'))
API_KEY = auth_status.get('apiKey', '')
CSRF = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
PORT = 64958

print(f"Current API key: {API_KEY[:40]}...")
print()

# Check allowed models for current key
print("=== Allowed models for current key ===")
for i, b64 in enumerate(auth_status.get('allowedCommandModelConfigsProtoBinaryBase64', [])):
    try:
        data = base64.b64decode(b64 + '==')
        # Extract label (field 1, string)
        label = re.search(rb'\x0a([\x01-\x7f])([\x20-\x7e]+)', data)
        if label:
            length = label.group(1)[0]
            name = label.group(2)[:length].decode('utf-8', 'replace')
            print(f"  [{i}] {name}")
    except: pass
print()

META = {
    "ideName": "Windsurf", "ideVersion": "1.108.2",
    "extensionVersion": "3.14.2", "extensionName": "Windsurf",
    "extensionPath": r"D:\Windsurf\resources\app\extensions\windsurf",
    "apiKey": API_KEY, "locale": "en-US", "os": "win32",
    "url": "https://server.codeium.com",
}
HDR = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
       'x-codeium-csrf-token':CSRF,'x-grpc-web':'1'}

def call(method, body, timeout=10):
    b = json.dumps(body).encode()
    r = requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/{method}',
                      data=b'\x00'+struct.pack('>I',len(b))+b, headers=HDR, timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames = []; pos = 0
    while pos+5 <= len(raw):
        flag=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        frames.append({'flag':flag,'data':raw[pos:pos+n]}); pos+=n
    return r.status_code, frames

def read_frames(frames):
    results = []
    for f in frames:
        if f['flag'] == 0x80:
            results.append(('trailer', f['data'].decode('utf-8','replace')))
        else:
            try: results.append(('data', json.loads(f['data'])))
            except: results.append(('raw', f['data'].decode('utf-8','replace')))
    return results

# Init
call("InitializeCascadePanelState", {"metadata":META,"workspaceTrusted":True})
call("UpdateWorkspaceTrust", {"metadata":META,"workspaceTrusted":True})

# Start cascade
_, f1 = call("StartCascade", {"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
cascade_id = None
for ftype, fdata in read_frames(f1):
    if ftype == 'data' and isinstance(fdata, dict):
        cascade_id = fdata.get('cascadeId') or fdata.get('cascade_id')
print(f"cascade_id: {cascade_id}")

# Try different models - start with GPT-4.1 mini (currently working in UI)
# MODEL_CHAT_GPT_4_1_MINI_2025_04_14 - from fullState analysis
MODELS_TO_TRY = [
    "MODEL_CHAT_GPT_4_1_MINI_2025_04_14",
    "MODEL_WINDSURF_FAST",
    "MODEL_GPT_4_1",
    "MODEL_CLAUDE_4_5_OPUS",
    "MODEL_CLAUDE_4_6_OPUS",
]

for model_name in MODELS_TO_TRY[:2]:  # try first 2 models
    print(f"\n=== Testing model: {model_name} ===")
    
    _, f_start = call("StartCascade", {"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
    cid = None
    for ftype, fdata in read_frames(f_start):
        if ftype == 'data' and isinstance(fdata, dict):
            cid = fdata.get('cascadeId')
    
    if not cid: print("No cascade_id"); continue
    print(f"cascade_id: {cid}")
    
    # Send message
    _, f_send = call("SendUserCascadeMessage", {
        "metadata": META,
        "cascadeId": cid,
        "items": [{"text": "Reply with exactly: OK"}],
        "cascadeConfig": {"plannerConfig": {
            "requestedModelUid": model_name,
            "planModelUid": model_name,
            "conversational": {}
        }},
    })
    send_status = [(ft, fd[:100] if isinstance(fd, str) else str(fd)[:100]) for ft, fd in read_frames(f_send)]
    print(f"Send: {send_status}")
    
    # Stream response
    stream_b = json.dumps({"id": cid, "protocolVersion": 1}).encode()
    stream_d = b'\x00'+struct.pack('>I',len(stream_b))+stream_b
    
    print(f"Streaming (8s)...")
    error_seen = None; response_text = None
    try:
        r3 = requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
                           data=stream_d, headers=HDR, timeout=10, stream=True)
        buf = b''; t0 = time.time()
        for chunk in r3.iter_content(chunk_size=64):
            buf += chunk
            while len(buf) >= 5:
                n = struct.unpack('>I', buf[1:5])[0]
                if len(buf) < 5+n: break
                flag=buf[0]; frame=buf[5:5+n]; buf=buf[5+n:]
                try:
                    parsed = json.loads(frame)
                    # Look for error or response text in all string values
                    def find_strings(obj, depth=0):
                        if depth > 10: return []
                        found = []
                        if isinstance(obj, str) and len(obj) > 5:
                            found.append(obj)
                        elif isinstance(obj, dict):
                            for v in obj.values():
                                found.extend(find_strings(v, depth+1))
                        elif isinstance(obj, list):
                            for item in obj[:5]:
                                found.extend(find_strings(item, depth+1))
                        return found
                    
                    strings = find_strings(parsed)
                    for s in strings:
                        if 'error' in s.lower() or 'permission' in s.lower() or 'denied' in s.lower():
                            error_seen = s[:150]
                        elif any(x in s for x in ['OK', 'BACKEND', 'connected', '1+1', '2', 'Hello']):
                            response_text = s[:200]
                except: pass
            if time.time() - t0 > 8:
                break
    except Exception as e:
        print(f"  Stream timeout/error: {type(e).__name__}")
    
    if response_text:
        print(f"  ✅ GOT RESPONSE: {response_text}")
    elif error_seen:
        print(f"  ❌ Error: {error_seen[:100]}")
    else:
        print(f"  ? No clear response in 8s")

# Check WAM pool for accounts with Claude access
print("\n=== WAM pool accounts with Claude access ===")
for key in rows:
    if key.startswith('windsurf_auth-') and not key.endswith('-usages'):
        try:
            data = json.loads(rows[key])
            allowed = data.get('allowedCommandModelConfigsProtoBinaryBase64', [])
            for b64 in allowed:
                decoded = base64.b64decode(b64 + '==')
                if b'Claude' in decoded:
                    name = key.replace('windsurf_auth-', '')
                    ak = data.get('apiKey', data.get('token', '?'))
                    print(f"  {name}: has Claude, key={ak[:30]}...")
                    break
        except: pass
