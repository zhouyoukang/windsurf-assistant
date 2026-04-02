"""find_session.py — 找 initCascadeId + 已有session，修复 failed_precondition"""
import re, json, sqlite3, struct, http.client, uuid

EXT_JS = r"D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
PORT = 57407; CSRF = '18e67ec6-8a9b-4781-bcea-ac61a722a640'

# === 1. Find initCascadeId in extension.js ===
print("=== 1. initCascadeId in extension.js ===")
with open(EXT_JS, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

for kw in ['initCascadeId', 'cascadeInitPrompt', 'impersonateTier']:
    for m in re.finditer(re.escape(kw), content):
        ctx = content[max(0, m.start()-100):m.start()+200]
        print(f"\n  {kw} @{m.start()}:")
        print(f"  {ctx[:250]}")

# === 2. Look for cascade sessions in state.vscdb ===
print("\n=== 2. Cascade sessions in state.vscdb ===")
conn = sqlite3.connect(DB); cur = conn.cursor()
cur.execute("SELECT key, value FROM ItemTable WHERE key LIKE '%cascade%' OR key LIKE '%session%'")
for k, v in cur.fetchall():
    print(f"  {k}: {str(v)[:200]}")
conn.close()

# === 3. Find active cascade conversation IDs ===
print("\n=== 3. Active cascade state ===")
conn2 = sqlite3.connect(DB); cur2 = conn2.cursor()
cur2.execute("SELECT key, value FROM ItemTable")
for k, v in cur2.fetchall():
    if 'windsurf' in k.lower() and len(str(v)) > 10:
        v_str = str(v)[:300]
        if any(x in v_str for x in ['cascade', 'conversationId', 'trajectoryId', 'cascadeId']):
            print(f"  {k}: {v_str}")
conn2.close()

# === 4. Try with IDs from active Windsurf session ===
print("\n=== 4. Test with cascadeId/workspaceId context ===")
conn3 = sqlite3.connect(DB); cur3 = conn3.cursor()
cur3.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
row = cur3.fetchone(); conn3.close()
api_key = json.loads(row[0]).get('apiKey', '')

def raw_chat(extra_fields=None, model='claude-sonnet-4-5', msg='Reply: OK'):
    """Test RawGetChatMessage with extra fields"""
    conv_id = str(uuid.uuid4())
    payload = {
        'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43',
                     'extensionVersion':'1.9577.43','apiKey':api_key},
        'chatMessages': [{
            'messageId': str(uuid.uuid4()), 'role': 1, 'content': msg,
            'timestamp': '2026-03-30T21:22:00Z', 'conversationId': conv_id,
        }],
        'model': model,
    }
    if extra_fields:
        payload.update(extra_fields)
    body = json.dumps(payload).encode()
    framed = b'\x00' + struct.pack('>I', len(body)) + body
    h = {'Content-Type':'application/connect+json','Accept':'application/connect+json',
         'Connect-Protocol-Version':'1','x-codeium-csrf-token':CSRF}
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=20)
    c.request('POST', '/exa.language_server_pb.LanguageServerService/RawGetChatMessage', framed, h)
    r = c.getresponse(); data = r.read(4096)
    texts = []
    pos = 0
    while pos < len(data):
        if pos + 5 > len(data): break
        flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]; pos += 5 + length
        try:
            obj = json.loads(chunk); dm = obj.get('deltaMessage', {})
            text = dm.get('text', '')
            if text: texts.append(('err' if dm.get('isError') else 'ok', text[:100]))
        except: pass
    return texts

# Test with various extra context fields
for extra, label in [
    ({'workspaceRootPath': 'e:/道/道生一/一生二'}, 'workspace_path'),
    ({'projectPath': 'e:/道/道生一/一生二'}, 'project_path'),
    ({'cascadeId': str(uuid.uuid4())}, 'new_cascadeId'),
    ({'workspaceId': str(uuid.uuid4())}, 'workspace_id'),
    ({}, 'baseline'),
]:
    results = raw_chat(extra)
    print(f"  [{label}]: {results}")
