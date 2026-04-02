"""find_opus46_enum.py — 找 claude-opus-4-6 对应的 model enum + 完整响应测试"""
import re, json, sqlite3, struct, time, requests, base64

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# 1. Find all OPUS model enums
print("=== All OPUS model enum values ===")
for m in re.finditer(r'MODEL_CLAUDE_\d+.*?OPUS.*?=(\d+)', content):
    ctx = content[max(0,m.start()-5):m.start()+80]
    print(f"  {repr(ctx[:80])}")

print()

# 2. Find all model enum entries containing "4_6" or "46"
print("=== Models with 4_6 or 46 ===")
for m in re.finditer(r'MODEL_\w*(?:4_6|46)\w*[="\']', content):
    ctx = content[max(0,m.start()-5):m.start()+100]
    print(f"  {repr(ctx[:90])}")

print()

# 3. Find model enum entries near 391 (MODEL_CLAUDE_4_5_OPUS)
print("=== Model enum values 385-420 (near 391) ===")
for m in re.finditer(r'A\[A\.(\w+)=(\d+)\]', content):
    val = int(m.group(2))
    if 385 <= val <= 420 and 'MODEL' in m.group(1):
        print(f"  {m.group(1)} = {val}")

print()

# 4. Check commandModelConfigs for claude-opus-4-6 style UID
print("=== commandModelConfigs with 'opus' ===")
DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
con = sqlite3.connect(DB); cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable")
rows = dict(cur.fetchall()); con.close()

auth = json.loads(rows.get('windsurfAuthStatus', '{}'))
for b64 in auth.get('allowedCommandModelConfigsProtoBinaryBase64', []):
    try:
        data = base64.b64decode(b64 + '==')
        if b'opus' in data.lower() or b'Opus' in data:
            texts = re.findall(rb'[\x20-\x7e]{4,}', data)
            print(f"  Config: {[t.decode() for t in texts[:8]]}")
    except: pass

# 5. Check if modelUid 'claude-opus-4-6' appears anywhere in extension.js
print()
print("=== 'claude-opus-4-6' in extension.js ===")
hits = list(re.finditer(r'claude.opus.4.6|opus.4.6', content, re.I))
print(f"Found {len(hits)} hits")
for h in hits[:5]:
    ctx = content[max(0,h.start()-30):h.start()+100]
    print(f"  @{h.start()}: {repr(ctx[:120])}")

# 6. Check GetCommandModelConfigs endpoint
print()
print("=== GetCommandModelConfigs response (live) ===")
API_KEY = auth.get('apiKey', '')
CSRF = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
META = {
    "ideName": "Windsurf", "ideVersion": "1.108.2",
    "extensionVersion": "3.14.2", "extensionName": "Windsurf",
    "extensionPath": r"D:\Windsurf\resources\app\extensions\windsurf",
    "apiKey": API_KEY, "locale": "en-US", "os": "win32",
    "url": "https://server.codeium.com",
}
HDR = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
       'x-codeium-csrf-token':CSRF,'x-grpc-web':'1'}
b = json.dumps({"metadata": META}).encode()
try:
    r = requests.post('http://127.0.0.1:64958/exa.language_server_pb.LanguageServerService/GetCommandModelConfigs',
                      data=b'\x00'+struct.pack('>I',len(b))+b, headers=HDR, timeout=8, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    # Parse frames
    pos = 0
    while pos+5 <= len(raw):
        flag = raw[pos]; n = struct.unpack('>I', raw[pos+1:pos+5])[0]; pos += 5
        frame = raw[pos:pos+n]; pos += n
        if flag != 0x80:
            try:
                d = json.loads(frame)
                # Show model labels and UIDs
                for cfg in d.get('commandModelConfigs', []):
                    label = cfg.get('label','?')
                    uid = cfg.get('modelUid', cfg.get('model_uid','?'))
                    enum_val = str(cfg.get('model', cfg.get('modelEnum','?')))[:30]
                    print(f"  label={label}, uid={uid}, enum={enum_val}")
            except:
                texts = re.findall(rb'[\x20-\x7e]{4,}', frame)
                for t in texts[:15]:
                    s = t.decode('utf-8','replace')
                    if any(x in s.lower() for x in ['claude','gpt','opus','sonnet','haiku','model','uid']):
                        print(f"  text: {s}")
        else:
            trailer = frame.decode('utf-8','replace')
            print(f"  Trailer: {trailer[:100]}")
except Exception as e:
    print(f"Error: {e}")
