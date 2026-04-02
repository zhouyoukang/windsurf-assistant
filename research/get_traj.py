"""get_traj.py — 读取已有 cascade 轨迹中的 AI 响应"""
import json, sqlite3, struct, time, requests, re, base64

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
con = sqlite3.connect(DB); cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable"); rows = dict(cur.fetchall()); con.close()
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
        frames.append((flag, raw[pos:pos+n])); pos+=n
    return frames

# Get all trajectories
print("=== GetAllCascadeTrajectories ===")
f1 = call("GetAllCascadeTrajectories", {"metadata": META, "includeUserInputs": True})
for flag, data in f1:
    if flag == 0x80:
        print(f"Trailer: {data.decode('utf-8','replace')[:100]}")
        continue
    try:
        parsed = json.loads(data)
        summaries = parsed.get('trajectorySummaries', {})
        print(f"Trajectories: {len(summaries)} entries")
        for cid, summary in list(summaries.items())[:3]:
            print(f"\n  CascadeID: {cid}")
            print(f"  Summary: {str(summary)[:300]}")
    except:
        # Try to find text in raw
        texts = re.findall(rb'[\x20-\x7e]{10,}', data)
        for t in texts[:20]:
            s = t.decode('utf-8','replace')
            if any(x in s for x in ['Reply', 'E2E', 'BACKEND', 'connected', 'error', 'human', 'assistant']):
                print(f"  text: {s[:200]}")

print()

# Also try GetCascadeTrajectory for one of the cascade IDs we used
KNOWN_IDS = [
    '1ff8d78f-f24a-4017-820c-5388305244bd',  # from e2e_test.py
    'cce566c7-01b5-498e-be2d-81c720e35b20',  # from run_cascade_bg.py
]

for cid in KNOWN_IDS:
    print(f"=== GetCascadeTrajectory {cid[:12]}... ===")
    f2 = call("GetCascadeTrajectory", {
        "metadata": META,
        "cascadeId": cid,
    })
    for flag, data in f2:
        if flag == 0x80:
            print(f"  Trailer: {data.decode('utf-8','replace')[:100]}")
        else:
            text = data.decode('utf-8', 'replace')
            try:
                parsed = json.loads(text)
                # Walk for text
                def find_text(obj, d=0):
                    if d > 15: return []
                    r = []
                    if isinstance(obj, str) and 5 < len(obj) < 500:
                        r.append(obj)
                    elif isinstance(obj, dict):
                        for v in obj.values(): r.extend(find_text(v, d+1))
                    elif isinstance(obj, list):
                        for item in obj: r.extend(find_text(item, d+1))
                    return r
                texts = find_text(parsed)
                SKIP = {'MODEL_', 'grpc-', 'D:\\', 'exa.', 'You are Cascade', 'The USER',
                        'communication', 'tool_calling', 'making_code', 'Before each tool'}
                for t in texts:
                    if not any(x in t for x in SKIP) and len(t) > 5:
                        print(f"  >> {t[:200]}")
            except:
                print(f"  raw: {text[:200]}")
    print()
