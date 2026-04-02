"""
init_cascade.py — 初始化 Cascade session，然后发 RawGetChatMessage
流程: InitializeCascadePanelState → 获取 cascadeId → RawGetChatMessage
"""
import struct, http.client, json, sqlite3, uuid, re

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
PORT = 57407; CSRF = '18e67ec6-8a9b-4781-bcea-ac61a722a640'

conn = sqlite3.connect(DB); cur = conn.cursor()
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
row = cur.fetchone(); conn.close()
api_key = json.loads(row[0]).get('apiKey', '')
print(f"api_key: {api_key[:20]}...\n")

def call_lsp(method, payload, timeout=20):
    path = f'/exa.language_server_pb.LanguageServerService/{method}'
    body = json.dumps(payload).encode()
    framed = b'\x00' + struct.pack('>I', len(body)) + body
    h = {'Content-Type':'application/connect+json','Accept':'application/connect+json',
         'Connect-Protocol-Version':'1','x-codeium-csrf-token':CSRF}
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
    c.request('POST', path, framed, h)
    r = c.getresponse()
    data = r.read(16384)
    chunks = []
    pos = 0
    while pos < len(data):
        if pos + 5 > len(data): break
        flag = data[pos]
        length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]
        pos += 5 + length
        try: chunks.append((flag, json.loads(chunk)))
        except: chunks.append((flag, chunk))
    return r.status, chunks

meta = {'ideName':'windsurf','ideVersion':'1.9577.43','extensionVersion':'1.9577.43','apiKey':api_key}

# === Step 1: InitializeCascadePanelState ===
print("=== Step 1: InitializeCascadePanelState ===")
init_payload = {
    'metadata': meta,
    'workspaceRootPath': 'e:/道/道生一/一生二',
    'workspaceName': '一生二',
}
s, chunks = call_lsp('InitializeCascadePanelState', init_payload, timeout=10)
print(f"HTTP {s}")
cascade_id = None
for flag, obj in chunks:
    print(f"  chunk (flag={flag}): {json.dumps(obj, ensure_ascii=False)[:300] if isinstance(obj, dict) else obj[:200]}")
    if isinstance(obj, dict):
        cascade_id = obj.get('cascadeId', obj.get('cascade_id', obj.get('sessionId', None)))

print(f"\ncascadeId from response: {cascade_id}")
print()

# === Step 2: Try RawGetChatMessage with cascade context ===
print("=== Step 2: RawGetChatMessage ===")
conv_id = str(uuid.uuid4())
chat_payload = {
    'metadata': meta,
    'chatMessages': [{
        'messageId': str(uuid.uuid4()),
        'role': 1,
        'content': 'Reply with exactly three words: OPUS FOUR SIX',
        'timestamp': '2026-03-30T21:22:00Z',
        'conversationId': conv_id,
    }],
    'model': 'claude-opus-4-6',
}
if cascade_id:
    chat_payload['cascadeId'] = cascade_id
    print(f"Using cascadeId: {cascade_id}")

s, chunks = call_lsp('RawGetChatMessage', chat_payload, timeout=60)
print(f"HTTP {s}")
for flag, obj in chunks:
    if isinstance(obj, dict):
        dm = obj.get('deltaMessage', {})
        text = dm.get('text', '')
        is_err = dm.get('isError', False)
        if text:
            print(f"  [{'ERROR' if is_err else 'text'}]: {text[:200]}")
        elif flag == 0 and obj:
            print(f"  [chunk flag={flag}]: {json.dumps(obj, ensure_ascii=False)[:200]}")
        if 'error' in obj:
            print(f"  [err]: {obj['error']}")

# === Step 3: Try StartCascade ===
print("\n=== Step 3: StartCascade ===")
start_payload = {
    'metadata': meta,
    'workspaceRootPath': 'e:/道/道生一/一生二',
}
s, chunks = call_lsp('StartCascade', start_payload, timeout=10)
print(f"HTTP {s}")
new_cascade_id = None
for flag, obj in chunks:
    print(f"  chunk (flag={flag}): {json.dumps(obj, ensure_ascii=False)[:300] if isinstance(obj,dict) else obj[:200]}")
    if isinstance(obj, dict):
        new_cascade_id = obj.get('cascadeId', obj.get('cascade_id', None))

if new_cascade_id:
    print(f"\n✅ Got cascadeId: {new_cascade_id}")
    print("Retrying RawGetChatMessage with cascadeId...")
    chat_payload['cascadeId'] = new_cascade_id
    s, chunks = call_lsp('RawGetChatMessage', chat_payload, timeout=60)
    print(f"HTTP {s}")
    for flag, obj in chunks:
        if isinstance(obj, dict):
            dm = obj.get('deltaMessage', {})
            text = dm.get('text', '')
            is_err = dm.get('isError', False)
            if text:
                print(f"  [{'ERROR' if is_err else ''}text]: {text[:300]}")
