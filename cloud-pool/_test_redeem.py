#!/usr/bin/env python3
"""E2E test for the redemption/card-key system (ldxp.cn integration)."""
import json, sys, secrets as sec
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

BASE = 'http://127.0.0.1:19880'
AK = 'test_admin_key_2026'
passed = failed = 0

def req(method, path, body=None, headers=None):
    hdrs = {'Content-Type': 'application/json'}
    if headers: hdrs.update(headers)
    data = json.dumps(body).encode() if body else None
    try:
        r = Request(BASE + path, data=data, headers=hdrs, method=method)
        with urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except HTTPError as e:
        try: return e.code, json.loads(e.read())
        except: return e.code, {'error': str(e)}
    except Exception as e:
        return 0, {'error': str(e)}

def test(name, ok, detail=''):
    global passed, failed
    if ok:
        passed += 1
        print(f'  PASS {name}' + (f' | {detail}' if detail else ''))
    else:
        failed += 1
        print(f'  FAIL {name} | {detail}')

ah = {'X-Admin-Key': AK}

print('=== Redemption System E2E Test ===\n')

# 1. Products catalog
c, d = req('GET', '/api/products')
pcount = len(d.get('products', {})) if c == 200 else 0
test('products', c == 200 and d.get('ok') and pcount >= 5, f'{pcount} products')

# 2. Generate windsurf_trial codes (batch of 5)
c, d = req('POST', '/api/admin/codes/generate',
           {'product': 'windsurf_trial', 'count': 5, 'expires_days': 30}, ah)
trial_codes = d.get('codes', []) if c == 200 and d.get('ok') else []
test('gen_trial_codes', len(trial_codes) == 5, f'batch={d.get("batch_id","")} count={len(trial_codes)}')

# 3. Generate windsurf_pro codes (batch of 3)
c, d = req('POST', '/api/admin/codes/generate',
           {'product': 'windsurf_pro', 'count': 3, 'expires_days': 30}, ah)
pro_codes = d.get('codes', []) if c == 200 and d.get('ok') else []
test('gen_pro_codes', len(pro_codes) == 3, f'count={len(pro_codes)}')

# 4. Generate WAM tool codes
c, d = req('POST', '/api/admin/codes/generate',
           {'product': 'wam_3day', 'count': 3, 'expires_days': 30}, ah)
wam_codes = d.get('codes', []) if c == 200 and d.get('ok') else []
test('gen_wam_codes', len(wam_codes) == 3, f'count={len(wam_codes)}')

# 5. List all codes
c, d = req('GET', '/api/admin/codes', headers=ah)
stats = d.get('stats', {}) if c == 200 else {}
test('list_codes', c == 200 and d.get('ok'), f'total={stats.get("total")} avail={stats.get("available")}')

# 6. Export codes in ldxp format
c, d = req('GET', '/api/admin/codes/export?product=windsurf_trial', headers=ah)
export_total = d.get('total', 0) if c == 200 else 0
test('export_ldxp', c == 200 and export_total > 0, f'total={export_total}')

# 7. Redeem trial code -> get account credentials
if trial_codes:
    code = trial_codes[0]
    c, d = req('POST', '/api/redeem', {'code': code})
    got_acct = c == 200 and d.get('ok') and d.get('type') == 'account'
    email = d.get('email', '?')[:30] if got_acct else '?'
    test('redeem_trial', got_acct, f'email={email} D{d.get("daily_pct")}% W{d.get("weekly_pct")}%')

    # 8. Try reuse same code (should fail)
    c2, d2 = req('POST', '/api/redeem', {'code': code})
    test('redeem_duplicate_blocked', not d2.get('ok') and 'already' in d2.get('error', ''), d2.get('error', ''))
else:
    test('redeem_trial', False, 'no codes')
    test('redeem_duplicate_blocked', False, 'skipped')

# 9. Redeem pro code -> get account with auth blob
if pro_codes:
    c, d = req('POST', '/api/redeem', {'code': pro_codes[0]})
    got_pro = c == 200 and d.get('ok') and d.get('type') == 'account'
    has_blob = 'auth_blob' in d if got_pro else False
    test('redeem_pro', got_pro, f'email={d.get("email","?")[:25]} has_blob={has_blob}')
else:
    test('redeem_pro', False, 'no codes')

# 10. Redeem WAM tool code -> get tool activation
if wam_codes:
    c, d = req('POST', '/api/redeem', {'code': wam_codes[0]})
    got_tool = c == 200 and d.get('ok') and d.get('type') == 'tool'
    test('redeem_wam_tool', got_tool, f'days={d.get("days")} msg={d.get("message","")}')
else:
    test('redeem_wam_tool', False, 'no codes')

# 11. Invalid code
c, d = req('POST', '/api/redeem', {'code': 'INVALID-CODE-HERE'})
test('redeem_invalid', not d.get('ok') and 'invalid' in d.get('error', ''), d.get('error', ''))

# 12. Concurrent redemption race (10 codes, 10 threads)
print('\n  --- Concurrent Redemption Race ---')
c, d = req('POST', '/api/admin/codes/generate',
           {'product': 'windsurf_trial', 'count': 20, 'expires_days': 30}, ah)
race_codes = d.get('codes', []) if c == 200 else []
redeemed_emails = []
race_errors = []
lock = threading.Lock()

def redeem_worker(code):
    c, d = req('POST', '/api/redeem', {'code': code})
    with lock:
        if c == 200 and d.get('ok') and d.get('type') == 'account':
            redeemed_emails.append(d.get('email', ''))
        elif d.get('error') and 'no accounts' not in d.get('error', ''):
            race_errors.append(d.get('error', ''))

with ThreadPoolExecutor(max_workers=20) as pool:
    futures = [pool.submit(redeem_worker, code) for code in race_codes]
    for f in as_completed(futures):
        try: f.result()
        except: pass

duplicates = [e for e in redeemed_emails if redeemed_emails.count(e) > 1]
test('concurrent_redeem_no_duplicates',
     len(duplicates) == 0,
     f'{len(redeemed_emails)} redeemed, {len(set(redeemed_emails))} unique, {len(duplicates)} dupes')

# 13. Final stats
c, d = req('GET', '/api/admin/codes', headers=ah)
stats = d.get('stats', {}) if c == 200 else {}
test('final_stats', stats.get('redeemed', 0) >= 3,
     f'total={stats.get("total")} avail={stats.get("available")} redeemed={stats.get("redeemed")}')

print(f'\n=== {passed}/{passed + failed} passed, {failed} failed ===')
sys.exit(0 if failed == 0 else 1)
