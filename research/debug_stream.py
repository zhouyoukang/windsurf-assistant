"""debug_stream.py — 打印完整原始流帧内容"""
import json, sqlite3, struct, time, requests, re

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

call("InitializeCascadePanelState", {"metadata":META,"workspaceTrusted":True})
call("UpdateWorkspaceTrust", {"metadata":META,"workspaceTrusted":True})

f1 = call("StartCascade", {"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
cascade_id = None
for flag, data in f1:
    if flag == 0:
        try: cascade_id = json.loads(data).get('cascadeId')
        except:
            m = re.search(rb'[0-9a-f-]{36}', data)
            if m: cascade_id = m.group(0).decode()
print(f"cascade_id: {cascade_id}")

f2 = call("SendUserCascadeMessage", {
    "metadata": META,
    "cascadeId": cascade_id,
    "items": [{"text": "1+1=?"}],
    "cascadeConfig": {"plannerConfig": {
        "requestedModelUid": "MODEL_CLAUDE_4_5_OPUS",
        "conversational": {}
    }},
}, timeout=8)
for flag, data in f2:
    d = data.decode('utf-8','replace')
    if flag == 0x80:
        print(f"Send trailer: {d[:100]}")
    else:
        print(f"Send data: {d[:100]}")

# Stream - save ALL raw content
stream_b = json.dumps({"id":cascade_id,"protocolVersion":1}).encode()
stream_d = b'\x00'+struct.pack('>I',len(stream_b))+stream_b

print("\nRaw stream frames:")
raw_frames = []
try:
    r3 = requests.post(
        f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
        data=stream_d, headers=HDR, timeout=13, stream=True)
    buf=b''; t0=time.time()
    for chunk in r3.iter_content(chunk_size=64):
        buf += chunk
        while len(buf) >= 5:
            n = struct.unpack('>I', buf[1:5])[0]
            if len(buf) < 5+n: break
            flag=buf[0]; frame=buf[5:5+n]; buf=buf[5+n:]
            raw_frames.append((flag, frame))
            if flag == 0x80:
                print(f"TRAILER: {frame.decode('utf-8','replace')[:200]}")
            else:
                # Print first 500 chars of each frame
                text = frame.decode('utf-8','replace')
                print(f"FRAME {len(raw_frames)} ({len(frame)}b): {text[:400]}")
        if time.time()-t0 > 11: break
except Exception as e:
    print(f"Stream end: {e}")

# Save to file
with open(r'e:\道\道生一\一生二\Windsurf无限额度\raw_frames.json', 'w') as f:
    json.dump([(flag, data.decode('utf-8','replace')) for flag, data in raw_frames], f, ensure_ascii=False, indent=2)
print(f"\nSaved {len(raw_frames)} frames")
