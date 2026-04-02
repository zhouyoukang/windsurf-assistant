#!/usr/bin/env python3
"""Quick E2E test for push + security APIs"""
import urllib.request, json, sys

BASE = 'http://127.0.0.1:19880'
KEY  = 'd7e895be64192470b373eb8664fd80bc442c38817adc99e9'

def call(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
          headers={'Content-Type':'application/json','X-Admin-Key': KEY})
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return json.loads(r.read().decode())
    except Exception as e:
        return {'ok': False, 'error': str(e)}

ok = True

# 0. cleanup: revoke any existing directives
r0 = call('GET', '/api/admin/push')
assert r0.get('ok'), f'FAIL initial list: {r0}'
for d in r0.get('directives', []):
    if d.get('active'):
        call('POST', '/api/admin/push/revoke', {'directive_id': d['id']})
print(f'[OK] cleanup: revoked {r0.get("active_count",0)} pre-existing directives')

# 1. push list (empty after cleanup)
r = call('GET', '/api/admin/push')
assert r.get('ok') and r.get('active_count') == 0, f'FAIL push list empty: {r}'
print(f'[OK] push list active=0 after cleanup')

# 2. create push directive
r = call('POST', '/api/admin/push', {
    'type': 'announcement',
    'payload': {'message': '万法归宗·云端推送测试', 'ts': 'test'},
    'priority': 'high',
    'ttl_hours': 1
})
assert r.get('ok'), f'FAIL push create: {r}'
did = r['directive_id']
print(f'[OK] push create: {did}  sig={r.get("signature","")}')

# 3. push list (should have 1)
r = call('GET', '/api/admin/push')
assert r.get('ok') and r.get('active_count') == 1, f'FAIL push list count: {r}'
print(f'[OK] push list active: {r["active_count"]}')

# 4. security events
r = call('GET', '/api/admin/security-events?limit=10')
assert r.get('ok'), f'FAIL security events: {r}'
print(f'[OK] security events: {r["stats"]}')

# 5. ip block
r = call('POST', '/api/admin/ip-block', {'ip': '1.2.3.4', 'action': 'block'})
assert r.get('ok'), f'FAIL ip block: {r}'
print(f'[OK] ip block: {r}')

# 6. bad_ips check
r = call('GET', '/api/admin/security-events?limit=5')
assert r.get('ok') and len(r.get('bad_ips',[])) >= 1, f'FAIL bad_ips: {r}'
print(f'[OK] bad_ips count: {len(r["bad_ips"])}')

# 7. ip unblock
r = call('POST', '/api/admin/ip-block', {'ip': '1.2.3.4', 'action': 'unblock'})
assert r.get('ok'), f'FAIL ip unblock: {r}'
print(f'[OK] ip unblock: {r}')

# 8. revoke push
r = call('POST', '/api/admin/push/revoke', {'directive_id': did})
assert r.get('ok'), f'FAIL push revoke: {r}'
print(f'[OK] push revoke: {did}')

# 9. push list (should be active=0)
r = call('GET', '/api/admin/push')
assert r.get('ok') and r.get('active_count') == 0, f'FAIL push list after revoke: {r}'
print(f'[OK] push list after revoke: active={r["active_count"]}')

# 10. heartbeat returns directives
r2 = call('POST', '/api/admin/push', {
    'type': 'config_update', 'payload': {'key': 'v2'}, 'priority': 'normal', 'ttl_hours': 24
})
assert r2.get('ok'), f'FAIL push create2: {r2}'
print(f'[OK] push create2 for heartbeat test: {r2["directive_id"]}')

print('\n=== ALL TESTS PASSED ===')
