import json, io, sys, base64, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CACHE = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\zhouyoukang.windsurf-assistant\wam-token-cache.json'
ACCOUNTS = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\windsurf-assistant-accounts.json'

cache = json.load(open(CACHE, encoding='utf-8', errors='replace'))
accounts = json.load(open(ACCOUNTS, encoding='utf-8', errors='replace'))

# Build credits map
cred_map = {a.get('email',''):a.get('credits',0) for a in accounts}

print(f"Cache has {len(cache)} entries")
print()

# Find high-credit entries
high = [(email, v) for email, v in cache.items() if cred_map.get(email, 0) >= 50]
print(f"High-credit (>=50) entries in cache: {len(high)}")
print()

for email, v in high:
    cr = cred_map.get(email, 0)
    keys = list(v.keys())
    token = v.get('idToken', '')
    refresh = v.get('refreshToken', '')
    api_key = v.get('apiKey', v.get('api_key', ''))
    
    # Decode JWT exp
    exp_info = 'unknown'
    if token:
        parts = token.split('.')
        if len(parts) >= 2:
            try:
                pad = parts[1] + '==='
                payload = json.loads(base64.urlsafe_b64decode(pad[:len(pad)-(len(pad)%4)]))
                exp = payload.get('exp', 0)
                valid = exp > time.time()
                exp_info = f"exp={exp} valid={valid}"
            except:
                exp_info = 'decode_fail'
    
    print(f"[cr={cr:3d}] {email}")
    print(f"  keys={keys}")
    print(f"  idToken={token[:60]}... {exp_info}")
    if refresh: print(f"  refreshToken={refresh[:40]}...")
    if api_key: print(f"  apiKey={api_key[:40]}...")
    print()
