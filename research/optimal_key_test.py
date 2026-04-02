"""optimal_key_test.py — 用 WAM pool 的最优 key 测试 RawGetChatMessage"""
import urllib.request, json, struct, http.client, uuid, os

PROXY = 'http://127.0.0.1:19876'
PORT  = 57407; CSRF = '18e67ec6-8a9b-4781-bcea-ac61a722a640'
SVC   = '/exa.language_server_pb.LanguageServerService/'

def frm(d): return b'\x00' + struct.pack('>I', len(d)) + d

def json_call(api_key, model='claude-opus-4-6', msg='Reply: OPUS46_OK', timeout=30):
    payload = {
        'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43',
                     'extensionVersion':'1.9577.43','apiKey':api_key},
        'chatMessages': [{'messageId':str(uuid.uuid4()),'role':1,'content':msg,
                          'timestamp':'2026-03-30T22:30:00Z',
                          'conversationId':str(uuid.uuid4())}],
        'model': model,
    }
    body = json.dumps(payload).encode(); framed = frm(body)
    h = {'Content-Type':'application/connect+json','Accept':'application/connect+json',
         'Connect-Protocol-Version':'1','x-codeium-csrf-token':CSRF}
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
    c.request('POST', SVC + 'RawGetChatMessage', framed, h)
    r = c.getresponse(); data = r.read(32768)
    pos = 0; results = []
    while pos < len(data):
        if pos+5 > len(data): break
        flag = data[pos]; length = struct.unpack('>I', data[pos+1:pos+5])[0]
        chunk = data[pos+5:pos+5+length]; pos += 5+length
        try: results.append((flag, json.loads(chunk)))
        except: results.append((flag, chunk))
    return results

def analyze(results):
    for flag, obj in results:
        if isinstance(obj, dict):
            dm = obj.get('deltaMessage', {})
            text = dm.get('text', '')
            if text:
                return ('err' if dm.get('isError') else 'ok', text[:200])
            if 'error' in obj:
                return ('json_err', obj['error'].get('message','')[:150])
    return ('empty', '')

# 1. Get optimal key from pool proxy
print("=== Getting optimal key from WAM pool ===")
try:
    r = urllib.request.urlopen(PROXY + '/pool/status', timeout=5)
    status = json.loads(r.read())
    pool = status.get('pool', {})
    print(f"Pool: total={pool.get('total',0)} available={pool.get('available',0)}")
    print(f"Daily: {pool.get('total_daily',0)} Weekly: {pool.get('total_weekly',0)}")
except Exception as e:
    print(f"Pool status error: {e}")

# Get accounts
optimal_key = None
try:
    r2 = urllib.request.urlopen(PROXY + '/pool/accounts', timeout=5)
    accounts = json.loads(r2.read()).get('accounts', [])
    print(f"\nAccounts: {len(accounts)}")
    # Sort by available daily credits descending
    accounts_sorted = sorted(accounts, key=lambda a: (
        a.get('available', False),
        -(a.get('daily_used', a.get('daily_credits_used', 0))),
    ), reverse=True)
    for acc in accounts_sorted[:5]:
        key = acc.get('api_key', '')[:25]
        avail = acc.get('available', '?')
        du = acc.get('daily_used', acc.get('daily_credits_used', '?'))
        print(f"  {key}... avail={avail} daily_used={du}")
    if accounts_sorted:
        optimal_key = accounts_sorted[0].get('api_key', '')
        print(f"\nOptimal key: {optimal_key[:25]}...")
except Exception as e:
    print(f"Accounts error: {e}")

# Also check _optimal_key.txt
key_file = r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\_optimal_key.txt'
if os.path.exists(key_file):
    file_key = open(key_file).read().strip()
    print(f"File optimal key: {file_key[:25]}...")
    if not optimal_key:
        optimal_key = file_key

if not optimal_key:
    print("No optimal key found, using current state.vscdb key")
    import sqlite3
    DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    row = cur.fetchone(); conn.close()
    optimal_key = json.loads(row[0]).get('apiKey', '')

print(f"\nUsing key: {optimal_key[:25]}...")

# 2. Test with optimal key
print("\n=== Test RawGetChatMessage with optimal key ===")
for model in ['claude-opus-4-6', 'claude-sonnet-4-5']:
    results = json_call(optimal_key, model=model,
                        msg=f'Reply with exactly: {model.upper().replace("-","_")}_WORKS')
    kind, text = analyze(results)
    print(f"  {model}: [{kind}] {text[:150]}")
    if kind == 'ok':
        print(f"  ✅ SUCCESS! Model {model} works!")

# 3. Get all accounts and find one with valid cascade session
print("\n=== Testing multiple accounts ===")
try:
    r3 = urllib.request.urlopen(PROXY + '/pool/accounts', timeout=5)
    all_accs = json.loads(r3.read()).get('accounts', [])
    tested = 0
    for acc in all_accs[:20]:
        key = acc.get('api_key', '')
        if not key: continue
        results = json_call(key, model='claude-sonnet-4-5', 
                           msg='Reply: OK', timeout=8)
        kind, text = analyze(results)
        tested += 1
        if kind == 'ok':
            print(f"  ✅ WORKING: {key[:25]}... [{kind}]: {text[:100]}")
            # Now test with claude-opus-4-6
            r2 = json_call(key, model='claude-opus-4-6', msg='Reply: OPUS46_FINAL', timeout=15)
            k2, t2 = analyze(r2)
            print(f"    opus-4-6: [{k2}]: {t2[:150]}")
            break
        elif 'cascade session' not in text.lower():
            print(f"  DIFF: {key[:20]}... [{kind}]: {text[:80]}")
    print(f"Tested {tested} accounts")
except Exception as e:
    print(f"Multi-account test error: {e}")
