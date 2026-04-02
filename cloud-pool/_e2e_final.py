#!/usr/bin/env python3
"""Final E2E smoke test — 万法归宗"""
import urllib.request, json, hmac as _hmac, hashlib, time, secrets

BASE = 'http://127.0.0.1:19880'
AKEY = 'd7e895be64192470b373eb8664fd80bc442c38817adc99e9'
HMAC_SEC = '78fa04cbfdf260a242dfeda5a9c4898aeb9bb6536c1d3bf4636447041a5f091c'

def _sign(body_bytes=b''):
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    msg = f'{ts}.{nonce}.'.encode() + body_bytes
    sig = _hmac.new(HMAC_SEC.encode(), msg, hashlib.sha256).hexdigest()
    return ts, nonce, sig

def admin(method, path, body=None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(f'{BASE}{path}', data=data, method=method,
          headers={'Content-Type':'application/json','X-Admin-Key': AKEY})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
    except Exception as e:
        return {'ok': False, 'error': str(e)}

def ext(method, path, body=None, device_id='DEV-E2ETEST01'):
    data = json.dumps(body).encode() if body else b''
    ts, nonce, sig = _sign(data or b'')
    req = urllib.request.Request(f'{BASE}{path}', data=data or None, method=method,
          headers={'Content-Type':'application/json',
                   'X-Signature': sig, 'X-Timestamp': ts, 'X-Nonce': nonce,
                   'X-Device-Id': device_id})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
    except Exception as e:
        return {'ok': False, 'error': str(e)}

print('=== CLOUD POOL v3 · 万法归宗 E2E ===\n')

# 1. health
r = admin('GET', '/api/health')
assert r.get('status') == 'ok', f'health fail: {r}'
print(f'[OK] health: v={r["version"]} accounts={r["accounts"]}')

# 2. ensure clean state
r = admin('GET', '/api/admin/push')
assert r.get('ok'), f'push list fail: {r}'
for d in r.get('directives', []):
    if d.get('active'):
        admin('POST', '/api/admin/push/revoke', {'directive_id': d['id']})
print(f'[OK] cleaned {r.get("active_count",0)} old directives')

# 3. create 3 directives (normal, high, critical)
for dtype, priority in [('announcement','normal'),('config_update','high'),('security_patch','critical')]:
    r = admin('POST', '/api/admin/push', {
        'type': dtype, 'payload': {'msg': f'{dtype} test'}, 'priority': priority, 'ttl_hours': 2
    })
    assert r.get('ok'), f'create {dtype} fail: {r}'
    print(f'[OK] push create: {r["directive_id"]} type={dtype} priority={priority}')

# 4. list — should be active=3
r = admin('GET', '/api/admin/push')
assert r.get('ok') and r.get('active_count') == 3, f'active != 3: {r}'
print(f'[OK] push list active_count=3')

# 5. ext/directives — should get all 3, critical first
r = ext('GET', '/api/ext/directives?v=1.0.0')
assert r.get('ok'), f'ext directives fail: {r}'
assert r.get('count') == 3, f'ext directives count: {r}'
assert r['directives'][0]['priority'] == 'critical', f'not sorted: {r["directives"][0]}'
print(f'[OK] ext/directives: {r["count"]} directives, first priority={r["directives"][0]["priority"]}')

# 6. heartbeat delivers directives
body = {'device_id': 'DEV-HB01', 'email': '', 'daily': 80, 'weekly': 70, 'version': '1.0.0'}
r = ext('POST', '/api/ext/heartbeat', body, device_id='DEV-HB01')
assert r.get('ok'), f'heartbeat fail: {r}'
assert 'directives' in r and r.get('directives_count', 0) == 3, f'heartbeat directives missing: {r}'
print(f'[OK] heartbeat delivers directives: count={r["directives_count"]}')

# 7. acked_count incremented (called twice)
r = admin('GET', '/api/admin/push')
acked = [d['acked_count'] for d in r.get('directives',[]) if d.get('active')]
assert all(c >= 2 for c in acked), f'acked_count not incremented: {acked}'
print(f'[OK] acked_count incremented: {acked}')

# 8. revoke critical directive
dids = [d['id'] for d in r['directives'] if d.get('active') and d['priority']=='critical']
assert dids, 'no critical to revoke'
r2 = admin('POST', '/api/admin/push/revoke', {'directive_id': dids[0]})
assert r2.get('ok'), f'revoke fail: {r2}'
print(f'[OK] revoke critical: {dids[0]}')

# 9. after revoke: 2 active
r = admin('GET', '/api/admin/push')
assert r.get('active_count') == 2, f'active after revoke != 2: {r}'
print(f'[OK] active after revoke: {r["active_count"]}')

# 10. security events + IP block
r = admin('GET', '/api/admin/security-events?limit=5')
assert r.get('ok') and 'stats' in r, f'security events: {r}'
print(f'[OK] security stats: {r["stats"]}')

r = admin('POST', '/api/admin/ip-block', {'ip': '10.0.0.99', 'action': 'block'})
assert r.get('ok'), f'ip block: {r}'
r = admin('GET', '/api/admin/security-events?limit=5')
blocked = [x for x in r.get('bad_ips',[]) if x['ip']=='10.0.0.99']
assert blocked, f'ip not in bad_ips: {r["bad_ips"]}'
print(f'[OK] ip block+verify: score={blocked[0]["score"]}')

r = admin('POST', '/api/admin/ip-block', {'ip': '10.0.0.99', 'action': 'unblock'})
assert r.get('ok'), f'ip unblock: {r}'
print(f'[OK] ip unblock: ok')

print('\n' + '='*40)
print('=== ALL E2E TESTS PASSED ✓ ===')
print('=== 云端推送 + 安全防护 · 万法归宗 ===')
print('='*40)
