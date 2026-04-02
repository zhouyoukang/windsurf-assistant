"""find_best_account.py — 从 WAM 快照找有效账号，测试哪个能通过 Cascade"""
import json, os, struct, http.client, uuid, sqlite3

SNAP = r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\_wam_snapshots.json'
PORT = 57407; CSRF = '18e67ec6-8a9b-4781-bcea-ac61a722a640'
PATH = '/exa.language_server_pb.LanguageServerService/RawGetChatMessage'

def send(api_key, model='claude-opus-4-6'):
    payload = {
        'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43',
                     'extensionVersion':'1.9577.43','apiKey':api_key},
        'chatMessages': [{'messageId':str(uuid.uuid4()),'role':1,
                          'content':'Reply: OK','timestamp':'2026-03-30T21:22:00Z',
                          'conversationId':str(uuid.uuid4())}],
        'model': model,
    }
    body = json.dumps(payload).encode()
    framed = b'\x00' + struct.pack('>I', len(body)) + body
    h = {'Content-Type':'application/connect+json','Accept':'application/connect+json',
         'Connect-Protocol-Version':'1','x-codeium-csrf-token':CSRF}
    try:
        c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=15)
        c.request('POST', PATH, framed, h)
        r = c.getresponse()
        data = r.read(4096)
        # Parse first non-status chunk
        pos = 0
        results = []
        while pos < len(data):
            if pos + 5 > len(data): break
            flag = data[pos]
            length = struct.unpack('>I', data[pos+1:pos+5])[0]
            chunk = data[pos+5:pos+5+length]
            pos += 5 + length
            try:
                obj = json.loads(chunk)
                dm = obj.get('deltaMessage', {})
                text = dm.get('text', '')
                is_err = dm.get('isError', False)
                if text:
                    results.append(('error' if is_err else 'text', text[:100]))
            except: pass
        return results
    except Exception as e:
        return [('exception', str(e)[:80])]

# Load WAM snapshots
print("Loading WAM snapshots...")
try:
    data = json.loads(open(SNAP, encoding='utf-8', errors='replace').read())
    snaps = data.get('snapshots', [])
    print(f"Total snapshots: {len(snaps)}")
    # Sort by freshness (most recently used)
    snaps_sorted = sorted(snaps, key=lambda x: x.get('last_used', 0), reverse=True)
    print(f"\nTop accounts by last_used:")
    for s in snaps_sorted[:5]:
        key = s.get('api_key', '')[:20]
        lu = s.get('last_used', 0)
        avail = s.get('available', s.get('is_available', '?'))
        dc = s.get('daily_credits_used', s.get('daily_used', '?'))
        wc = s.get('weekly_credits_used', s.get('weekly_used', '?'))
        email = s.get('email', s.get('username', ''))[:30]
        print(f"  {key}... avail={avail} dc={dc} wc={wc} email={email} lu={lu}")
except Exception as e:
    print(f"Snapshot load error: {e}")
    snaps_sorted = []

# Also check state.vscdb for current key
DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
conn = sqlite3.connect(DB); cur = conn.cursor()
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
row = cur.fetchone(); conn.close()
current_key = json.loads(row[0]).get('apiKey', '')
print(f"\nCurrent state.vscdb key: {current_key[:25]}...")

# Test current key first
print(f"\n=== Testing current key ===")
results = send(current_key)
for kind, text in results:
    print(f"  [{kind}]: {text}")

# Test top WAM accounts
print(f"\n=== Testing WAM accounts ===")
tested = {current_key}
success_key = None

for snap in snaps_sorted[:20]:
    key = snap.get('api_key', '')
    if not key or key in tested:
        continue
    tested.add(key)
    results = send(key)
    result_str = ' | '.join(f"[{k}] {v}" for k, v in results)
    print(f"  {key[:20]}...: {result_str[:120]}")
    # Check for success (non-error text)
    for kind, text in results:
        if kind == 'text' and 'error' not in text.lower() and 'fail' not in text.lower():
            success_key = key
            print(f"  *** SUCCESS! Key: {key[:25]}...")
            break
    if success_key:
        break

if success_key:
    print(f"\n✅ Working key found: {success_key[:25]}...")
    print(f"\nFull test with claude-opus-4-6:")
    results = send(success_key, 'claude-opus-4-6')
    for kind, text in results:
        print(f"  [{kind}]: {text}")
else:
    print(f"\nNo working key found in top {len(tested)} accounts")
    print("Checking if the issue is about cascade session context vs account type...")
