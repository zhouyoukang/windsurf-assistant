"""run_cascade_bg.py — 后台运行 30s，保存 AI 完整响应到文件"""
import json, sqlite3, struct, time, requests, re, sys

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
con = sqlite3.connect(DB); cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable")
rows = dict(cur.fetchall()); con.close()
API_KEY = json.loads(rows.get('windsurfAuthStatus','{}')).get('apiKey','')
CSRF = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
PORT = 64958
OUT = r'e:\道\道生一\一生二\Windsurf无限额度\cascade_response.txt'

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

def log(msg):
    print(msg, flush=True)
    with open(OUT, 'a', encoding='utf-8') as f:
        f.write(msg + '\n')

# Clear output
open(OUT, 'w').close()
log(f"=== Cascade Response Test {time.strftime('%H:%M:%S')} ===")

call("InitializeCascadePanelState", {"metadata":META,"workspaceTrusted":True})
call("UpdateWorkspaceTrust", {"metadata":META,"workspaceTrusted":True})

# StartCascade
f1 = call("StartCascade", {"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
cascade_id = None
for flag, data in f1:
    if flag == 0:
        try: cascade_id = json.loads(data).get('cascadeId')
        except:
            m = re.search(rb'[0-9a-f-]{36}', data)
            if m: cascade_id = m.group(0).decode()
log(f"cascade_id: {cascade_id}")

# SendUserCascadeMessage
USER_MSG = "Reply with exactly this text: 'BACKEND_CONNECTED via MODEL_CLAUDE_4_5_OPUS'. Then answer: 2+2=?"
f2 = call("SendUserCascadeMessage", {
    "metadata": META,
    "cascadeId": cascade_id,
    "items": [{"text": USER_MSG}],
    "cascadeConfig": {"plannerConfig": {
        "requestedModelUid": "MODEL_CLAUDE_4_5_OPUS",
        "conversational": {}
    }},
}, timeout=8)
sent_ok = any(b'grpc-status: 0' in d for flag, d in f2)
log(f"Message sent: {sent_ok}")

# Stream - 35 second window
stream_b = json.dumps({"id":cascade_id,"protocolVersion":1}).encode()
stream_d = b'\x00'+struct.pack('>I',len(stream_b))+stream_b

# Collect all string values
def walk(obj, depth=0):
    if depth > 15: return []
    r = []
    if isinstance(obj, str):
        r.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values(): r.extend(walk(v, depth+1))
    elif isinstance(obj, list):
        for item in obj: r.extend(walk(item, depth+1))
    return r

log("Streaming (35s)...")
frame_count = 0
all_unique_strings = set()
NEW_STRINGS = []  # strings we haven't seen that are likely AI responses

try:
    r3 = requests.post(
        f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
        data=stream_d, headers=HDR, timeout=37, stream=True)
    buf=b''; t0=time.time()
    for chunk in r3.iter_content(chunk_size=128):
        buf += chunk
        while len(buf) >= 5:
            n = struct.unpack('>I', buf[1:5])[0]
            if len(buf) < 5+n: break
            flag=buf[0]; frame=buf[5:5+n]; buf=buf[5+n:]
            if flag == 0x80:
                trailer = frame.decode('utf-8','replace')
                log(f"  STREAM TRAILER: {trailer[:100]}")
                break
            try:
                parsed = json.loads(frame)
                frame_count += 1
                strings = walk(parsed)
                for s in strings:
                    if s not in all_unique_strings:
                        all_unique_strings.add(s)
                        # Check if this looks like an AI response
                        if (len(s) > 5 and len(s) < 500 and
                                not any(x in s for x in ['MODEL_', 'grpc-', 'D:\\', 'c.\\', 
                                    'function', 'const ', 'import ', 'async ', '://'])):
                            NEW_STRINGS.append(s)
                            # If it looks like actual AI output:
                            if any(x in s for x in ['BACKEND', 'connected', '1+1', '2+2', 
                                                      'Claude', '4', 'answer', 'equals', 
                                                      'permission_denied', 'error', 'OK']):
                                log(f"  >> RESPONSE: {s[:300]}")
            except: pass
        elapsed = time.time()-t0
        if elapsed > 33:
            log(f"  [33s reached, {frame_count} frames]")
            break
except Exception as e:
    log(f"  Stream ended: {type(e).__name__}: {str(e)[:100]}")

log(f"\nTotal: {frame_count} frames, {len(all_unique_strings)} unique strings")
log("\nTop candidate response strings:")
for s in NEW_STRINGS[-30:]:
    if 5 < len(s) < 300:
        log(f"  {repr(s[:200])}")
