#!/usr/bin/env python3
"""Debug individual redeem calls to find the failure point."""
import json
from urllib.request import Request, urlopen

BASE = 'http://127.0.0.1:19880'
AK = 'test_admin_key_2026'

def req(method, path, body=None):
    hdrs = {'Content-Type': 'application/json', 'X-Admin-Key': AK}
    data = json.dumps(body).encode() if body else None
    r = Request(BASE + path, data=data, headers=hdrs, method=method)
    with urlopen(r, timeout=15) as resp:
        return json.loads(resp.read())

# 1. Generate 1 pro code
d = req('POST', '/api/admin/codes/generate', {'product': 'windsurf_pro', 'count': 1, 'expires_days': 30})
print('Gen pro:', d.get('ok'), d.get('codes', []))
pro_code = d['codes'][0] if d.get('ok') else ''

# 2. Generate 1 wam code
d2 = req('POST', '/api/admin/codes/generate', {'product': 'wam_3day', 'count': 1, 'expires_days': 30})
print('Gen wam:', d2.get('ok'), d2.get('codes', []))
wam_code = d2['codes'][0] if d2.get('ok') else ''

# 3. Redeem pro code (no admin key — public endpoint)
print('\n--- Redeeming pro code:', pro_code, '---')
try:
    r = Request(BASE + '/api/redeem', json.dumps({'code': pro_code}).encode(),
                {'Content-Type': 'application/json'})
    with urlopen(r, timeout=15) as resp:
        d3 = json.loads(resp.read())
        print('Pro result:', json.dumps(d3, ensure_ascii=False)[:500])
except Exception as e:
    print('Pro ERROR:', e)

# 4. Redeem wam code
print('\n--- Redeeming wam code:', wam_code, '---')
try:
    r2 = Request(BASE + '/api/redeem', json.dumps({'code': wam_code}).encode(),
                 {'Content-Type': 'application/json'})
    with urlopen(r2, timeout=15) as resp:
        d4 = json.loads(resp.read())
        print('WAM result:', json.dumps(d4, ensure_ascii=False)[:500])
except Exception as e:
    print('WAM ERROR:', e)
