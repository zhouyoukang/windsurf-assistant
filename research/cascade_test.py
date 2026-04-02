"""cascade_test.py — 快速测试 SendUserCascadeMessage (无阻塞)"""
import json, sqlite3, os, re, struct, time, requests

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
con = sqlite3.connect(DB); cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable")
rows = dict(cur.fetchall()); con.close()

auth_status = json.loads(rows.get('windsurfAuthStatus', '{}'))
API_KEY = auth_status.get('apiKey', '')
CSRF_TOKEN = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
LS_PORT = 64958

META = {
    "ideName": "Windsurf", "ideVersion": "1.108.2",
    "extensionVersion": "3.14.2", "extensionName": "Windsurf",
    "extensionPath": r"D:\Windsurf\resources\app\extensions\windsurf",
    "apiKey": API_KEY, "locale": "en-US", "os": "win32",
    "url": "https://server.codeium.com",
}

def call(method, body, timeout=10):
    url = f'http://127.0.0.1:{LS_PORT}/exa.language_server_pb.LanguageServerService/{method}'
    h = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
         'x-codeium-csrf-token':CSRF_TOKEN,'x-grpc-web':'1'}
    data = b'\x00' + struct.pack('>I', len(body)) + body
    r = requests.post(url, data=data, headers=h, timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    # Parse all frames
    frames = []; pos = 0
    while pos+5 <= len(raw):
        flag = raw[pos]; n = struct.unpack('>I',raw[pos+1:pos+5])[0]; pos += 5
        frames.append((flag, raw[pos:pos+n])); pos += n
    return r.status_code, dict(r.headers), frames

def print_frames(frames):
    for flag, data in frames:
        if flag == 0x80:
            print(f"  Trailer: {data.decode('utf-8','replace')[:200]}")
        else:
            try: print(f"  Data: {json.dumps(json.loads(data), ensure_ascii=False)[:300]}")
            except: print(f"  Raw: {data.decode('utf-8','replace')[:200]}")

# 0. InitializeCascadePanelState with workspace_trusted
print("=== InitializeCascadePanelState ===")
body0 = json.dumps({"metadata": META, "workspaceTrusted": True}).encode()
s0, h0, f0 = call("InitializeCascadePanelState", body0)
print(f"Status: {s0} {h0.get('Grpc-Message','')}")

# 0b. UpdateWorkspaceTrust
body0b = json.dumps({"metadata": META, "workspaceTrusted": True}).encode()
s0b, h0b, f0b = call("UpdateWorkspaceTrust", body0b)
print(f"UpdateWorkspaceTrust: {s0b} {h0b.get('Grpc-Message','')}")
print()

# 1. StartCascade
print("=== StartCascade ===")
body1 = json.dumps({"metadata": META, "source": "CORTEX_TRAJECTORY_SOURCE_USER"}).encode()
s1, h1, f1 = call("StartCascade", body1)
print(f"Status: {s1}")
print_frames(f1)

cascade_id = None
for flag, data in f1:
    if flag == 0:
        try:
            d = json.loads(data)
            cascade_id = d.get('cascadeId') or d.get('cascade_id')
        except:
            m = re.search(rb'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', data)
            if m: cascade_id = m.group(0).decode()

print(f"cascade_id: {cascade_id}\n")
if not cascade_id:
    print("No cascade_id. Stop."); exit(1)

# 2. SendUserCascadeMessage
print("=== SendUserCascadeMessage ===")
send_body = json.dumps({
    "metadata": META,
    "cascadeId": cascade_id,
    "items": [{"text": "Say: BACKEND CONNECTED"}],
    "cascadeConfig": {
        "plannerConfig": {
            "requestedModelUid": "MODEL_CLAUDE_4_5_OPUS",
            "conversational": {}
        }
    },
}).encode()

s2, h2, f2 = call("SendUserCascadeMessage", send_body, timeout=10)
print(f"Status: {s2}, Headers: {h2.get('Grpc-Status','?')} {h2.get('Grpc-Message','')[:100]}")
print_frames(f2)
print()

# 3. StreamCascadeReactiveUpdates (short peek)
print("=== StreamCascadeReactiveUpdates (8s peek) ===")
# StreamReactiveUpdatesRequest: id=cascade_id, protocol_version=1
stream_body = json.dumps({
    "id": cascade_id,
    "protocolVersion": 1,
}).encode()

url3 = f'http://127.0.0.1:{LS_PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates'
h3 = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
      'x-codeium-csrf-token':CSRF_TOKEN,'x-grpc-web':'1'}
data3 = b'\x00' + struct.pack('>I', len(stream_body)) + stream_body

def extract_text(obj, depth=0):
    """Recursively find text/content in nested dict"""
    if depth > 8: return []
    results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ('text', 'content', 'output', 'message') and isinstance(v, str) and len(v) > 2:
                results.append(f"[{k}] {v[:300]}")
            elif k == 'step' and isinstance(v, dict):
                results.extend(extract_text(v, depth+1))
            else:
                results.extend(extract_text(v, depth+1))
    elif isinstance(obj, list):
        for item in obj[:3]:
            results.extend(extract_text(item, depth+1))
    return results

try:
    r3 = requests.post(url3, data=data3, headers=h3, timeout=15, stream=True)
    print(f"Stream status: {r3.status_code}")
    deadline = time.time() + 13
    buf = b''; frame_count = 0
    for chunk in r3.iter_content(chunk_size=64):
        buf += chunk
        while len(buf) >= 5:
            n = struct.unpack('>I', buf[1:5])[0]
            if len(buf) < 5+n: break
            flag = buf[0]; frame = buf[5:5+n]; buf = buf[5+n:]
            if flag == 0x80:
                print(f"  Trailer: {frame.decode('utf-8','replace')[:200]}")
                break
            try:
                parsed = json.loads(frame)
                frame_count += 1
                keys = list(parsed.keys())
                texts = extract_text(parsed)
                if texts:
                    for t in texts[:2]:
                        print(f"  Frame#{frame_count} {t}")
                else:
                    # Print compact JSON for structure inspection
                    compact = json.dumps(parsed, ensure_ascii=False)
                    print(f"  Frame#{frame_count} keys={keys}: {compact[:250]}")
            except:
                print(f"  Raw: {frame.decode('utf-8','replace')[:150]}")
        if time.time() > deadline:
            print(f"  [timeout after {frame_count} frames]")
            break
except Exception as e:
    print(f"Stream error: {e}")

print("\nDone.")
