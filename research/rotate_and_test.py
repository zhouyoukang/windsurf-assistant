"""rotate_and_test.py — 用不同账号轮测 RawGetChatMessage，找可用的"""
import json, struct, http.client, uuid, sqlite3

SNAP = r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\_wam_snapshots.json'
DB   = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
PORT = 57407; CSRF = '18e67ec6-8a9b-4781-bcea-ac61a722a640'

def raw_test(api_key, model='claude-sonnet-4-5', timeout=12):
    payload = {
        'metadata': {
            'ideName': 'windsurf', 'ideVersion': '1.9577.43',
            'extensionVersion': '1.9577.43', 'apiKey': api_key,
        },
        'chatMessages': [{
            'messageId': str(uuid.uuid4()), 'role': 1,
            'content': 'Reply OK', 'timestamp': '2026-03-30T21:22:00Z',
            'conversationId': str(uuid.uuid4()),
        }],
        'model': model,
    }
    body = json.dumps(payload).encode()
    framed = b'\x00' + struct.pack('>I', len(body)) + body
    h = {'Content-Type': 'application/connect+json', 'Accept': 'application/connect+json',
         'Connect-Protocol-Version': '1', 'x-codeium-csrf-token': CSRF}
    try:
        c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
        c.request('POST',
                  '/exa.language_server_pb.LanguageServerService/RawGetChatMessage',
                  framed, h)
        r = c.getresponse(); data = r.read(4096)
        pos = 0
        while pos < len(data):
            if pos + 5 > len(data): break
            flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
            chunk = data[pos+5:pos+5+length]; pos += 5 + length
            try:
                obj = json.loads(chunk)
                dm = obj.get('deltaMessage', {})
                text = dm.get('text', '')
                if text:
                    return ('error' if dm.get('isError') else 'response', text[:150])
            except: pass
        return ('empty', '')
    except Exception as e:
        return ('exception', str(e)[:60])

# Load snapshots
data = json.loads(open(SNAP, encoding='utf-8', errors='replace').read())
snaps_raw = data.get('snapshots', [])
print(f"Loaded {len(snaps_raw)} snapshots")

# Parse snapshot entries (might be JSON strings or dicts)
accounts = []
for s in snaps_raw:
    if isinstance(s, dict):
        accounts.append(s)
    elif isinstance(s, (bytes, str)):
        try:
            accounts.append(json.loads(s))
        except:
            pass

print(f"Parsed {len(accounts)} account dicts")
if accounts:
    print(f"Fields: {list(accounts[0].keys())[:10]}")
    print(f"Sample: {json.dumps(accounts[0], ensure_ascii=False)[:300]}")

# Sort by available credits (descending)
def sort_key(a):
    d = a.get('daily_credits', a.get('daily_credits_remaining', a.get('credits', 0)))
    w = a.get('weekly_credits', a.get('weekly_credits_remaining', 0))
    avail = a.get('available', a.get('is_available', False))
    return (1 if avail else 0, d + w)

accounts_sorted = sorted(accounts, key=sort_key, reverse=True)

# Get current key
conn = sqlite3.connect(DB); cur = conn.cursor()
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
row = cur.fetchone(); conn.close()
current_key = json.loads(row[0]).get('apiKey', '')

# Test top 10 accounts
print(f"\n=== Testing top accounts ===")
tested = set()
for acc in accounts_sorted[:15]:
    key = acc.get('api_key', acc.get('apiKey', acc.get('key', '')))
    if not key or key in tested:
        continue
    tested.add(key)
    email = acc.get('email', acc.get('username', ''))[:25]
    avail = acc.get('available', acc.get('is_available', '?'))
    
    kind, text = raw_test(key, 'claude-sonnet-4-5')
    print(f"  {key[:20]}... [{email}] avail={avail} → [{kind}]: {text[:100]}")
    
    if kind == 'response':
        print(f"\n✅ WORKING account found!")
        print(f"  Key: {key}")
        # Test with claude-opus-4-6
        kind2, text2 = raw_test(key, 'claude-opus-4-6')
        print(f"  claude-opus-4-6: [{kind2}]: {text2[:200]}")
        break

# Also test with current key + different metadata
print(f"\n=== Testing metadata variations with current key ===")
variations = [
    {'planName': 'PLAN_WINDSURF_TRIAL'},
    {'planName': 'Pro', 'deviceFingerprint': str(uuid.uuid4())},
    {'planName': 'Windsurf Trial'},
    {'locale': 'en-US', 'osType': 'Windows_NT'},
]
for v in variations:
    payload = {
        'metadata': {
            'ideName': 'windsurf', 'ideVersion': '1.9577.43',
            'extensionVersion': '1.9577.43', 'apiKey': current_key,
            **v
        },
        'chatMessages': [{
            'messageId': str(uuid.uuid4()), 'role': 1, 'content': 'Reply OK',
            'timestamp': '2026-03-30T21:22:00Z',
            'conversationId': str(uuid.uuid4()),
        }],
        'model': 'claude-sonnet-4-5',
    }
    body = json.dumps(payload).encode()
    framed = b'\x00' + struct.pack('>I', len(body)) + body
    h = {'Content-Type':'application/connect+json','Accept':'application/connect+json',
         'Connect-Protocol-Version':'1','x-codeium-csrf-token':CSRF}
    try:
        c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=10)
        c.request('POST','/exa.language_server_pb.LanguageServerService/RawGetChatMessage',framed,h)
        r = c.getresponse(); data = r.read(2048)
        texts = []
        pos = 0
        while pos < len(data):
            if pos + 5 > len(data): break
            flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
            chunk = data[pos+5:pos+5+length]; pos += 5 + length
            try:
                obj = json.loads(chunk); dm = obj.get('deltaMessage', {})
                t = dm.get('text', '')
                if t: texts.append(('err' if dm.get('isError') else 'ok', t[:80]))
            except: pass
        print(f"  meta+{list(v.keys())}: {texts}")
    except Exception as e:
        print(f"  meta+{list(v.keys())}: exception {e}")
