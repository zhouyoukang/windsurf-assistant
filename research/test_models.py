"""test_models.py — 测试不同模型，确定 failed_precondition 根因"""
import struct, http.client, json, sqlite3, uuid

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
PORT = 57407; CSRF = '18e67ec6-8a9b-4781-bcea-ac61a722a640'
PATH = '/exa.language_server_pb.LanguageServerService/RawGetChatMessage'

conn = sqlite3.connect(DB); cur = conn.cursor()
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
row = cur.fetchone(); conn.close()
api_key = json.loads(row[0]).get('apiKey', '')
print(f"api_key: {api_key[:20]}...\n")

def send(model, conv_id=None, extra_msg_fields=None):
    cid = conv_id or str(uuid.uuid4())
    msg = {
        'messageId': str(uuid.uuid4()),
        'role': 1,
        'content': 'Reply with exactly: OK',
        'timestamp': '2026-03-30T21:22:00Z',
        'conversationId': cid,
    }
    if extra_msg_fields:
        msg.update(extra_msg_fields)
    payload = {
        'metadata': {
            'ideName': 'windsurf',
            'ideVersion': '1.9577.43',
            'extensionVersion': '1.9577.43',
            'apiKey': api_key,
        },
        'chatMessages': [msg],
    }
    if model:
        payload['model'] = model
    body = json.dumps(payload).encode()
    framed = b'\x00' + struct.pack('>I', len(body)) + body
    h = {'Content-Type': 'application/connect+json', 'Accept': 'application/connect+json',
         'Connect-Protocol-Version': '1', 'x-codeium-csrf-token': CSRF}
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=30)
    c.request('POST', PATH, framed, h)
    r = c.getresponse()
    data = r.read(8192)
    # Parse all chunks
    results = []
    pos = 0
    while pos < len(data):
        if pos + 5 > len(data): break
        flag = data[pos]
        length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]
        pos += 5 + length
        try: results.append((flag, json.loads(chunk)))
        except: results.append((flag, chunk))
    return results

# Test 1: No model (server chooses)
print("=== T1: No model ===")
for flag, obj in send(None):
    if isinstance(obj, dict):
        dm = obj.get('deltaMessage', {})
        text = dm.get('text', '')
        is_err = dm.get('isError', False)
        if text: print(f"  [{flag}] {'ERROR' if is_err else 'text'}: {text[:150]}")

print()

# Test 2: claude-sonnet-4-5 (should be available)
print("=== T2: claude-sonnet-4-5 ===")
for flag, obj in send('claude-sonnet-4-5'):
    if isinstance(obj, dict):
        dm = obj.get('deltaMessage', {})
        text = dm.get('text', '')
        is_err = dm.get('isError', False)
        if text: print(f"  [{flag}] {'ERROR' if is_err else 'text'}: {text[:200]}")

print()

# Test 3: claude-opus-4-6 with different request fields
print("=== T3: claude-opus-4-6 ===")
for flag, obj in send('claude-opus-4-6'):
    if isinstance(obj, dict):
        dm = obj.get('deltaMessage', {})
        text = dm.get('text', '')
        is_err = dm.get('isError', False)
        if text: print(f"  [{flag}] {'ERROR' if is_err else 'text'}: {text[:200]}")
        if 'error' in obj:
            print(f"  [{flag}] err: {obj['error']}")

print()

# Test 4: Try to get a REAL response by rotating to a fresh account via WAM
print("=== T4: Check WAM pool for available accounts ===")
try:
    import urllib.request
    r = urllib.request.urlopen('http://127.0.0.1:19876/pool/status', timeout=5)
    d = json.loads(r.read())
    pool = d.get('pool', {})
    print(f"  Pool: {pool.get('total', 0)} total, {pool.get('available', 0)} avail")
    print(f"  Daily: {pool.get('total_daily_available', 0)}, Weekly: {pool.get('total_weekly_available', 0)}")
except Exception as e:
    print(f"  WAM pool: {e}")
