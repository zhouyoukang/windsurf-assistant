"""
final_cascade.py — 完整后端直调验证
使用 MODEL_CLAUDE_4_5_OPUS，读取完整 AI 响应
"""
import json, sqlite3, struct, time, requests, re, base64

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
con = sqlite3.connect(DB); cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable")
rows = dict(cur.fetchall()); con.close()
API_KEY = json.loads(rows.get('windsurfAuthStatus','{}')).get('apiKey','')
CSRF = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
PORT = 64958

META = {"ideName":"Windsurf","ideVersion":"1.108.2","extensionVersion":"3.14.2",
        "extensionName":"Windsurf","extensionPath":r"D:\Windsurf\resources\app\extensions\windsurf",
        "apiKey":API_KEY,"locale":"en-US","os":"win32","url":"https://server.codeium.com"}
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

# --- init ---
call("InitializeCascadePanelState", {"metadata":META,"workspaceTrusted":True})
call("UpdateWorkspaceTrust", {"metadata":META,"workspaceTrusted":True})

# --- start cascade ---
f1 = call("StartCascade", {"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
cascade_id = None
for flag, data in f1:
    if flag == 0:
        try: cascade_id = json.loads(data).get('cascadeId')
        except:
            m = re.search(rb'[0-9a-f-]{36}', data)
            if m: cascade_id = m.group(0).decode()
print(f"cascade_id: {cascade_id}")

# --- send message ---
USER_MSG = "Say exactly: 'Backend fully connected! Claude 4.5 Opus responding.' Then: 1+1=?"
f2 = call("SendUserCascadeMessage", {
    "metadata": META,
    "cascadeId": cascade_id,
    "items": [{"text": USER_MSG}],
    "cascadeConfig": {"plannerConfig": {
        "requestedModelUid": "MODEL_CLAUDE_4_5_OPUS",
        "planModelUid": "MODEL_CLAUDE_4_5_OPUS",
        "conversational": {}
    }},
}, timeout=8)
statuses = [data.decode('utf-8','replace')[:50] for flag,data in f2 if flag==0x80]
print(f"Send status: {statuses}")

# --- stream and collect AI response ---
print("Streaming response...")
stream_b = json.dumps({"id":cascade_id,"protocolVersion":1}).encode()
stream_d = b'\x00'+struct.pack('>I',len(stream_b))+stream_b

# Collect ALL string values from diff frames
all_strings = []

def walk_for_strings(obj, depth=0):
    if depth > 12: return
    if isinstance(obj, str) and len(obj) > 3:
        all_strings.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            walk_for_strings(v, depth+1)
    elif isinstance(obj, list):
        for item in obj:
            walk_for_strings(item, depth+1)

frame_n = 0
try:
    r3 = requests.post(
        f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
        data=stream_d, headers=HDR, timeout=14, stream=True)
    buf=b''; t0=time.time()
    for chunk in r3.iter_content(chunk_size=64):
        buf += chunk
        while len(buf) >= 5:
            n = struct.unpack('>I', buf[1:5])[0]
            if len(buf) < 5+n: break
            flag=buf[0]; frame=buf[5:5+n]; buf=buf[5+n:]
            if flag != 0x80:
                try:
                    parsed = json.loads(frame)
                    frame_n += 1
                    walk_for_strings(parsed)
                except: pass
        if time.time()-t0 > 12: break
except Exception as e:
    pass

print(f"Collected {len(all_strings)} strings from {frame_n} frames")
print()

# Filter for AI-generated response (exclude known infrastructure strings)
SKIP = {'MODEL_', 'grpc-', 'http', 'windsurf', 'D:\\', 'exa.', 'proto',
        'tool_calling', 'Prefer minimal', 'IMPORTANT', 'Never use', 'Be terse'}
SKIP_LONG = {  # Skip system prompt excerpts
    'You are Cascade', 'The USER is interacting', 'communication_style',
    'Before each tool call', 'You have the ability to call tools',
    'If you intend to call multiple', 'Keep dependent commands',
    'making_code_changes', 'Prefer minimal', 'EXTREMELY IMPORTANT',
    'citation_guidelines', 'You MUST use the following',
    'tool_calling', 'Use only the available tools',
}

print("=== Filtered AI response strings ===")
seen = set()
response_parts = []
for s in all_strings:
    if len(s) < 5 or len(s) > 1000: continue
    if any(skip in s for skip in SKIP): continue
    if any(skip in s for skip in SKIP_LONG): continue
    if s in seen: continue
    # Look for actual response-like content
    if any(x in s for x in ['Backend', 'connected', '1+1', '2', 'Hello', 'Say', 'Opus',
                              'responding', 'fully', 'permission_denied', 'error',
                              'internal', 'Claude', 'Model']):
        seen.add(s)
        response_parts.append(s)
        print(f"  >> {s[:200]}")

print()
if not response_parts:
    print("No filtered response found. Last 20 unique strings:")
    shown = set()
    for s in reversed(all_strings):
        if s not in shown and 5 < len(s) < 300:
            shown.add(s)
            if len(shown) <= 20:
                print(f"  {repr(s[:150])}")
