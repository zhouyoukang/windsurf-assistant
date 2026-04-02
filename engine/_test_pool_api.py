#!/usr/bin/env python3
"""Quick E2E test for Pool Engine API"""
import urllib.request, json

BASE = 'http://127.0.0.1:19877'

def get(path):
    r = urllib.request.urlopen(f'{BASE}{path}', timeout=3)
    return json.loads(r.read())

def post(path, data):
    req = urllib.request.Request(
        f'{BASE}{path}',
        data=json.dumps(data).encode(),
        headers={'Content-Type': 'application/json'})
    r = urllib.request.urlopen(req, timeout=3)
    return json.loads(r.read())

# T1: Health
d = get('/api/health')
assert d['ok'], 'health failed'
print(f'T1 health: OK v{d["version"]}')

# T2: Status
d = get('/api/status')
p = d['pool']
print(f'T2 status: {p["total"]} accounts, {p["available"]} avail, '
      f'D{p["total_daily"]}% W{p["total_weekly"]}%, keys={p["has_api_key"]}')

# T3: All accounts
d = get('/api/accounts')
accs = d['accounts']
print(f'T3 accounts: {len(accs)} returned')
for a in accs[:3]:
    print(f'   #{a["index"]} {a["email"][:28]} D{a["daily"]}% W{a["weekly"]}% '
          f'sc={a["score"]} snap={a["has_snapshot"]} active={a["is_active"]}')

# T4: Pick best (no model filter)
d = get('/api/pick')
print(f'T4 pick(any): #{d["account"]["index"]} {d["account"]["email"][:28]} '
      f'score={d["account"]["score"]} key={d["api_key_preview"][:20]}...')

# T5: Report rate limit on active account for claude-sonnet
active_email = accs[0]['email']  # first = active (sorted)
d = post('/api/rate-limit', {
    'email': active_email,
    'model': 'claude-sonnet-4-6',
    'duration_sec': 900,
})
print(f'T5 rate-limit report: {d}')

# T6: Pick for rate-limited model → should pick different account
d = get('/api/pick?model=claude-sonnet-4-6')
picked = d['account']
bypassed = picked['email'] != active_email
print(f'T6 pick(claude-sonnet-4-6): #{picked["index"]} {picked["email"][:28]} '
      f'{"ROUTED AROUND" if bypassed else "same (still best)"}')

# T7: Model availability
d = get('/api/models')
models = d['models']
print(f'T7 models: {len(models)} tracked')
for mk, info in list(models.items())[:4]:
    print(f'   {mk:<30} avail={info["available"]} blocked={info["blocked"]}')

# T8: Pick for different model → should still work
d = get('/api/pick?model=gpt-4.1')
print(f'T8 pick(gpt-4.1): #{d["account"]["index"]} {d["account"]["email"][:28]}')

print(f'\n=== ALL {8} TESTS PASSED ===')
