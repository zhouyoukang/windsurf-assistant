"""stream_capture.py — 捕获完整 stream 帧到文件，分析 AI 响应"""
import json, sqlite3, struct, time, requests, base64, re, os

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
con = sqlite3.connect(DB); cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable")
rows = dict(cur.fetchall()); con.close()
auth_status = json.loads(rows.get('windsurfAuthStatus', '{}'))
API_KEY = auth_status.get('apiKey', '')
CSRF = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
PORT = 64958

META = {
    "ideName": "Windsurf", "ideVersion": "1.108.2",
    "extensionVersion": "3.14.2", "extensionName": "Windsurf",
    "extensionPath": r"D:\Windsurf\resources\app\extensions\windsurf",
    "apiKey": API_KEY, "locale": "en-US", "os": "win32",
    "url": "https://server.codeium.com",
}
HDR = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
       'x-codeium-csrf-token':CSRF,'x-grpc-web':'1'}

def post(method, body_dict, timeout=10):
    b = json.dumps(body_dict).encode()
    d = b'\x00' + struct.pack('>I',len(b)) + b
    r = requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/{method}',
                      data=d, headers=HDR, timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames = []; pos = 0
    while pos+5 <= len(raw):
        flag=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        frames.append({'flag':flag,'data':raw[pos:pos+n].decode('utf-8','replace')}); pos+=n
    return r.status_code, frames

# Init
post("InitializeCascadePanelState", {"metadata":META,"workspaceTrusted":True})
post("UpdateWorkspaceTrust", {"metadata":META,"workspaceTrusted":True})

# Start cascade
_, f1 = post("StartCascade", {"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
cascade_id = None
for f in f1:
    if f['flag']==0:
        try:
            d = json.loads(f['data'])
            cascade_id = d.get('cascadeId') or d.get('cascade_id')
        except:
            m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', f['data'])
            if m: cascade_id = m.group(0)

if not cascade_id:
    print("No cascade_id"); exit(1)
print(f"cascade_id: {cascade_id}")

# Send message
_, f2 = post("SendUserCascadeMessage", {
    "metadata": META,
    "cascadeId": cascade_id,
    "items": [{"text": "Say exactly: BACKEND_CONNECTED. What is 1+1?"}],
    "cascadeConfig": {"plannerConfig": {"requestedModelUid": "MODEL_CLAUDE_4_5_OPUS", "conversational": {}}},
})
print(f"SendUserCascadeMessage: {[x['data'][:80] for x in f2]}")

# Stream - save all frames
OUT = r'e:\道\道生一\一生二\Windsurf无限额度\stream_frames.json'
stream_b = json.dumps({"id":cascade_id,"protocolVersion":1}).encode()
stream_d = b'\x00'+struct.pack('>I',len(stream_b))+stream_b

all_frames = []
print("Streaming...")
try:
    r3 = requests.post(
        f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
        data=stream_d, headers=HDR, timeout=12, stream=True)
    buf = b''; t0=time.time()
    for chunk in r3.iter_content(chunk_size=64):
        buf += chunk
        while len(buf)>=5:
            n=struct.unpack('>I',buf[1:5])[0]
            if len(buf)<5+n: break
            flag=buf[0]; frame=buf[5:5+n]; buf=buf[5+n:]
            try:
                parsed = json.loads(frame)
                all_frames.append(parsed)
                print(f"  frame {len(all_frames)}: {list(parsed.keys())}")
            except:
                all_frames.append({'raw': frame.decode('utf-8','replace')})
        if time.time()-t0 > 10:
            print("  [10s reached]"); break
except Exception as e:
    print(f"Stream ended: {e}")

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(all_frames, f, ensure_ascii=False, indent=2, default=str)
print(f"\nSaved {len(all_frames)} frames to {OUT}")

# Quick analysis of fullState
if all_frames and 'fullState' in all_frames[0]:
    fs = all_frames[0]['fullState']
    print(f"\nfullState length: {len(fs)}")
    # Decode base64
    try:
        raw_proto = base64.b64decode(fs + '==')
        print(f"Decoded {len(raw_proto)} bytes")
        # Look for text strings in proto
        texts = re.findall(rb'[\x20-\x7e]{8,}', raw_proto)
        for t in texts[:20]:
            print(f"  text: {t.decode('utf-8','replace')}")
    except Exception as e:
        print(f"Decode error: {e}")
