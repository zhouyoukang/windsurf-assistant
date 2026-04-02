"""get_cascade_models.py — 调 GetCascadeModelConfigs 找 cascade 可用模型"""
import json, sqlite3, struct, requests, re, base64

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
        frames.append((flag,raw[pos:pos+n])); pos+=n
    return frames

print("=== GetCascadeModelConfigs ===")
f = call("GetCascadeModelConfigs", {"metadata": META})
for flag, data in f:
    if flag == 0x80:
        print(f"Trailer: {data.decode('utf-8','replace')[:100]}")
    else:
        text = data.decode('utf-8','replace')
        try:
            parsed = json.loads(text)
            print(f"Keys: {list(parsed.keys())}")
            # Look for model configs
            for key, val in parsed.items():
                print(f"  {key}: {str(val)[:400]}")
        except:
            # Binary proto - extract text
            texts = re.findall(rb'[\x20-\x7e]{5,}', data)
            print("Text strings:")
            for t in texts[:30]:
                s = t.decode('utf-8','replace')
                if any(x in s for x in ['claude','gpt','model','Claude','GPT','uid','Model','Opus','opus']):
                    print(f"  {s}")

print()
print("=== windsurfConfigurations cascade model info ===")
wsc = rows.get('windsurfConfigurations','')
if wsc:
    try:
        raw = base64.b64decode(wsc + '==')
        texts = re.findall(rb'[\x20-\x7e]{4,}', raw)
        print("Strings:")
        for t in texts[:40]:
            s = t.decode('utf-8','replace')
            print(f"  {repr(s)}")
    except Exception as e:
        print(f"Decode error: {e}")

print()
print("=== Check cached_cascade_model_configs in state ===")
for key in rows:
    if 'cascade' in key.lower() and 'model' in key.lower():
        print(f"  {key}: {rows[key][:200]}")
