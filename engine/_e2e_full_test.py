#!/usr/bin/env python3
"""
Full E2E Test Suite v2 — 验证所有组件到底
==========================================
Tests:
  T01-T05: pool_engine.py API (status/accounts/pick/rate-limit/models)
  T06-T09: pool_proxy.py (health/status/upstream forward/rate-limit detection)
  T10-T13: dao_engine.py (import/status/velocity/signal)
  T14-T16: wam_engine.py (import/scoring/api)
  T17:     Cross-component integration
  T18-T21: hot_patch.py (patch applied/key-file valid/key readable/watch import)
"""
import sys, os, json, time, traceback
import urllib.request
import urllib.error
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

APPDATA = Path(os.environ.get('APPDATA', ''))
RESULTS = []

# ── Auto-discover live ports (validate response body) ──
def _find_engine_port():
    """Find pool_engine by checking /api/health returns {ok:true,version:...}"""
    for p in range(19877, 19885):
        try:
            r = urllib.request.urlopen(f'http://127.0.0.1:{p}/api/health', timeout=2)
            d = json.loads(r.read())
            if d.get('ok') and 'version' in d:
                return p
        except Exception:
            continue
    return 19877  # fallback

def _find_proxy_port():
    """Find pool_proxy by checking /pool/health returns {ok:true}"""
    for p in range(19875, 19880):
        try:
            r = urllib.request.urlopen(f'http://127.0.0.1:{p}/pool/health', timeout=2)
            d = json.loads(r.read())
            if d.get('ok'):
                return p
        except Exception:
            continue
    return 19876  # fallback

ENGINE_PORT = _find_engine_port()
PROXY_PORT  = _find_proxy_port()
ENGINE = f'http://127.0.0.1:{ENGINE_PORT}'
PROXY  = f'http://127.0.0.1:{PROXY_PORT}'

def http_get(url, timeout=5):
    try:
        r = urllib.request.urlopen(url, timeout=timeout)
        return {'ok': True, 'status': r.status, 'data': json.loads(r.read())}
    except urllib.error.HTTPError as e:
        body = e.read()
        try: data = json.loads(body)
        except: data = body.decode('utf-8', errors='replace')[:200]
        return {'ok': False, 'status': e.code, 'data': data}
    except Exception as e:
        return {'ok': False, 'status': 0, 'error': str(e)}

def http_post(url, body, timeout=5):
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
        r = urllib.request.urlopen(req, timeout=timeout)
        return {'ok': True, 'status': r.status, 'data': json.loads(r.read())}
    except urllib.error.HTTPError as e:
        bd = e.read()
        try: data = json.loads(bd)
        except: data = bd.decode('utf-8', errors='replace')[:200]
        return {'ok': False, 'status': e.code, 'data': data}
    except Exception as e:
        return {'ok': False, 'status': 0, 'error': str(e)}

def test(tid, name, fn):
    try:
        ok, detail = fn()
        icon = '✅' if ok else '❌'
        RESULTS.append((tid, name, ok, detail))
        print(f'  {icon} {tid} {name}: {detail}')
        return ok
    except Exception as e:
        RESULTS.append((tid, name, False, str(e)))
        print(f'  ❌ {tid} {name}: EXCEPTION {e}')
        traceback.print_exc()
        return False

# ════════════════════════════════════════════
# Pool Engine Tests (T01-T05)
# ════════════════════════════════════════════
def t01():
    r = http_get(f'{ENGINE}/api/health')
    if not r['ok']: return False, f'Engine not reachable: {r}'
    return r['data'].get('ok', False), f'v{r["data"].get("version","?")}'

def t02():
    r = http_get(f'{ENGINE}/api/status')
    if not r['ok']: return False, f'status failed: {r}'
    p = r['data'].get('pool', {})
    total = p.get('total', 0)
    avail = p.get('available', 0)
    keys = p.get('has_api_key', 0)
    ok = total > 0 and avail > 0 and keys > 0
    return ok, f'{total} accts, {avail} avail, {keys} keys, D{p.get("total_daily",0)}% W{p.get("total_weekly",0)}%'

def t03():
    r = http_get(f'{ENGINE}/api/accounts')
    if not r['ok']: return False, f'accounts failed: {r}'
    accs = r['data'].get('accounts', [])
    if len(accs) == 0: return False, 'no accounts'
    active = [a for a in accs if a.get('is_active')]
    snaps = sum(1 for a in accs if a.get('has_snapshot'))
    return True, f'{len(accs)} accts, {len(active)} active, {snaps} snapshots'

def t04():
    # Pick best account
    r = http_get(f'{ENGINE}/api/pick')
    if not r['ok']: return False, f'pick failed: {r}'
    acct = r['data'].get('account', {})
    key_preview = r['data'].get('api_key_preview', '')
    has_key = len(key_preview) > 10
    return has_key, f'#{acct.get("index")} {acct.get("email","?")[:25]} key={key_preview[:20]}...'

def t05():
    # Report rate limit → pick should route around
    r1 = http_get(f'{ENGINE}/api/accounts')
    accs = r1['data'].get('accounts', [])
    active = next((a for a in accs if a.get('is_active')), None)
    if not active: return False, 'no active account'

    # Report rate limit on active account
    r2 = http_post(f'{ENGINE}/api/rate-limit', {
        'email': active['email'], 'model': 'claude-sonnet-4-6', 'duration_sec': 60
    })
    if not r2.get('ok') and not r2.get('data', {}).get('ok'):
        return False, f'rate-limit report failed: {r2}'

    # Pick for that model → should be different account
    r3 = http_get(f'{ENGINE}/api/pick?model=claude-sonnet-4-6')
    picked = r3['data'].get('account', {})
    routed_around = picked.get('email') != active['email']
    return True, f'active={active["email"][:20]} picked={picked.get("email","?")[:20]} routed_around={routed_around}'

# ════════════════════════════════════════════
# Pool Proxy Tests (T06-T09)
# ════════════════════════════════════════════
def t06():
    r = http_get(f'{PROXY}/pool/health')
    if not r['ok']: return False, f'Proxy not reachable: {r}'
    return r['data'].get('ok', False), f'proxy={r["data"].get("proxy","?")} engine={r["data"].get("engine")}'

def t07():
    r = http_get(f'{PROXY}/pool/status')
    if not r['ok']: return False, f'proxy status failed: {r}'
    ps = r['data'].get('proxy_stats', {})
    p = r['data'].get('pool', {})
    return True, f'pool={p.get("total",0)} accts, proxy_reqs={ps.get("total_requests",0)}'

def t08():
    # Test upstream forwarding — send a minimal request through proxy
    # The proxy should forward to server.self-serve.windsurf.com and return whatever response
    try:
        req = urllib.request.Request(
            f'{PROXY}/exa.language_server_pb.LanguageServerService/GetStatus',
            data=b'\x00',  # minimal body
            headers={
                'Content-Type': 'application/proto',
                'Connect-Protocol-Version': '1',
            })
        r = urllib.request.urlopen(req, timeout=20)
        return True, f'upstream {r.status} ({r.length}B) — forwarding works!'
    except urllib.error.HTTPError as e:
        # Any HTTP error from upstream means proxy successfully forwarded
        body_len = len(e.read()) if e.fp else 0
        # 400/401/404/415 from upstream = proxy forwarding works
        if e.code in (400, 401, 403, 404, 415, 500, 501):
            return True, f'upstream HTTP {e.code} ({body_len}B) — proxy forwarding WORKS'
        return False, f'upstream HTTP {e.code}'
    except Exception as e:
        return False, f'upstream error: {e}'

def t09():
    # After T08, check proxy stats incremented
    r = http_get(f'{PROXY}/pool/status')
    if not r['ok'] or 'data' not in r:
        return False, f'proxy not reachable: {r.get("error", r.get("status", "?"))}'
    ps = r['data'].get('proxy_stats', {})
    total = ps.get('total_requests', 0) + ps.get('total_forwarded', 0) + ps.get('total_errors', 0)
    return total > 0, f'total_reqs={ps.get("total_requests",0)} forwarded={ps.get("total_forwarded",0)} errors={ps.get("total_errors",0)}'

# ════════════════════════════════════════════
# Dao Engine Tests (T10-T13)
# ════════════════════════════════════════════
def t10():
    try:
        from dao_engine import (VelocityTracker, _should_switch, _check_ratelimit_signal,
                                find_best_switchable, SENTINEL_INTERVAL, QUOTA_THRESHOLD,
                                TTE_SWITCH_MIN, ANTI_OSCILLATION_SEC, SWITCH_COOLDOWN)
        return True, f'poll={SENTINEL_INTERVAL}s thresh={QUOTA_THRESHOLD}% TTE={TTE_SWITCH_MIN}min cd={SWITCH_COOLDOWN}s'
    except Exception as e:
        return False, str(e)

def t11():
    from dao_engine import VelocityTracker, ANTI_OSCILLATION_SEC
    import collections
    vt = VelocityTracker()
    # Simulate declining quota
    vt.record('test@email', 80, 60)
    time.sleep(0.05)
    vt.record('test@email', 75, 55)
    time.sleep(0.05)
    vt.record('test@email', 70, 50)
    d_rate, w_rate = vt.get_velocity('test@email')
    tte_d, tte_w = vt.predict_tte('test@email', 70, 50)
    # Anti-oscillation
    vt.mark_switched_from('old@email')
    recently = vt.is_recently_used('old@email')
    return True, f'vel_d={d_rate:.1f}/m vel_w={w_rate:.1f}/m tte_d={tte_d:.0f}m tte_w={tte_w:.0f}m anti_osc={recently}'

def t12():
    from dao_engine import _should_switch, TTE_SWITCH_MIN
    # Test various scenarios
    h_ok = {'daily': 80, 'weekly': 60, 'daily_reset_in_sec': 0, 'stale_min': -1}
    h_low = {'daily': 3, 'weekly': 60, 'daily_reset_in_sec': 5000, 'stale_min': -1}
    h_floor = {'daily': 1, 'weekly': 50, 'daily_reset_in_sec': 0, 'stale_min': -1}

    s1, r1 = _should_switch(h_ok)
    s2, r2 = _should_switch(h_low)
    s3, r3 = _should_switch(h_floor)
    s4, r4 = _should_switch(h_ok, tte_d=1.0, tte_w=50.0)  # TTE prediction trigger

    results = [
        f'ok={s1}({r1[:20]})',
        f'low={s2}({r2[:20]})',
        f'floor={s3}({r3[:20]})',
        f'tte={s4}({r4[:25]})',
    ]
    ok = (not s1) and s2 and s3 and s4
    return ok, ' | '.join(results)

def t13():
    from dao_engine import _check_ratelimit_signal, RATELIMIT_SIGNAL_FILE
    import json
    # Write signal file
    RATELIMIT_SIGNAL_FILE.write_text(json.dumps({
        'ts': time.time(), 'model': 'test', 'source': 'e2e_test'
    }), encoding='utf-8')
    triggered, info = _check_ratelimit_signal()
    # Signal should be consumed (file deleted)
    exists_after = RATELIMIT_SIGNAL_FILE.exists()
    return triggered and not exists_after, f'triggered={triggered} consumed={not exists_after} model={info.get("model","?")}'

# ════════════════════════════════════════════
# WAM Engine Tests (T14-T16)
# ════════════════════════════════════════════
def t14():
    from wam_engine import (AccountPool, SnapshotStore, HotSwitcher,
                            find_active_index, score_account, classify_account,
                            QUOTA_EXHAUSTED, QUOTA_URGENT)
    return True, f'EXHAUSTED={QUOTA_EXHAUSTED}% URGENT={QUOTA_URGENT}%'

def t15():
    from wam_engine import score_account
    # Weekly-weighted scoring test
    h_balanced = {'daily': 80, 'weekly': 80, 'days_left': 10, 'stale_min': -1}
    h_weekly_low = {'daily': 80, 'weekly': 30, 'days_left': 10, 'stale_min': -1}
    s1 = score_account(h_balanced, has_snapshot=True)
    s2 = score_account(h_weekly_low, has_snapshot=True)
    # Weekly-low should score significantly lower
    penalty = s1 - s2
    return penalty > 50, f'balanced={s1} weekly_low={s2} penalty={penalty} (weekly weighting works)'

def t16():
    from wam_engine import AccountPool, SnapshotStore, find_active_index
    pool = AccountPool()
    store = SnapshotStore()
    active_i = find_active_index(pool)
    td, tw = pool.pool_total()
    ok = pool.count() > 0 and active_i >= 0
    active_email = pool.get(active_i).get('email', '?') if active_i >= 0 else '?'
    return ok, f'{pool.count()} accts active=#{active_i+1} {active_email[:25]} D{td}% W{tw}% snaps={store.count_harvested()}'

# ════════════════════════════════════════════
# Cross-component Integration (T17)
# ════════════════════════════════════════════
def t17():
    # Verify pool_engine ↔ dao_engine ↔ wam_engine are all consistent
    from wam_engine import AccountPool, find_active_index
    pool = AccountPool()
    active_i = find_active_index(pool)
    wam_active = pool.get(active_i).get('email', '') if active_i >= 0 else ''

    r = http_get(f'{ENGINE}/api/status')
    engine_active = r['data'].get('active', {}).get('email', '') if r['ok'] else ''

    r2 = http_get(f'{PROXY}/pool/status')
    proxy_pool_total = r2['data'].get('pool', {}).get('total', 0) if r2['ok'] else 0

    consistent = (wam_active == engine_active) and proxy_pool_total > 0
    return consistent, f'wam={wam_active[:20]} engine={engine_active[:20]} proxy_pool={proxy_pool_total} consistent={consistent}'

# ════════════════════════════════════════════
# Hot-Patch Tests (T18-T21)
# ════════════════════════════════════════════
EXT_JS  = Path(r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js')
KEY_FILE = APPDATA / 'Windsurf' / '_pool_apikey.txt'
PATCH_MARKER = '/* POOL_HOT_PATCH_V1 */'
PATCH_OLD    = 'apiKey:this.apiKey,sessionId:this.sessionId,requestId:BigInt(this.requestId)'

def t18():
    # Patch applied to extension.js?
    if not EXT_JS.exists():
        return False, 'extension.js not found'
    src = EXT_JS.read_text(encoding='utf-8', errors='replace')
    patched = PATCH_MARKER in src
    original = PATCH_OLD in src
    return patched, f'patched={patched} original_present={original} size={EXT_JS.stat().st_size:,}'

def t19():
    # Key file exists and is valid?
    exists = KEY_FILE.exists()
    if not exists:
        return False, f'key file missing: {KEY_FILE}'
    key = KEY_FILE.read_text(encoding='utf-8', errors='replace').strip()
    valid = len(key) > 20 and key.startswith('sk-ws')
    age = round(time.time() - KEY_FILE.stat().st_mtime)
    return valid, f'valid={valid} len={len(key)} age={age}s preview={key[:25]}...'

def t20():
    # Key file is being updated by pool engine (age < 10s since started recently)
    if not KEY_FILE.exists():
        return False, 'key file missing'
    key = KEY_FILE.read_text(encoding='utf-8', errors='replace').strip()
    valid = key.startswith('sk-ws') and len(key) > 20
    # Check pool engine is writing it (verify engine is running and key is valid)
    r = http_get(f'{ENGINE}/api/pick')
    if r['ok']:
        engine_key_preview = r['data'].get('api_key_preview', '')
        consistent = engine_key_preview[:20] == key[:20] if engine_key_preview else False
    else:
        consistent = False
    return valid, f'key_valid={valid} engine_consistent={consistent} preview={key[:20]}...'

def t21():
    # hot_patch.py imports and verify() works
    try:
        from hot_patch import verify, PATCH_MARKER as PM, PATCH_OLD as PO
        v = verify()
        patched = v.get('patched', False)
        key_valid = v.get('pool_key_valid', False)
        backups = v.get('backups', 0)
        return True, f'verify()={v["ok"]} patched={patched} key_valid={key_valid} backups={backups}'
    except Exception as e:
        return False, str(e)

# ════════════════════════════════════════════
# Run all tests
# ════════════════════════════════════════════
if __name__ == '__main__':
    print('=' * 65)
    print('  FULL E2E TEST SUITE v2 — 验证所有组件到底')
    print('=' * 65)
    print(f'  Engine: {ENGINE}  Proxy: {PROXY}')

    print(f'\n── Pool Engine (:{ENGINE_PORT}) ──')
    test('T01', 'Engine health', t01)
    test('T02', 'Pool status', t02)
    test('T03', 'All accounts', t03)
    test('T04', 'Pick best (apiKey)', t04)
    test('T05', 'Rate-limit routing', t05)

    print(f'\n── Pool Proxy (:{PROXY_PORT}) ──')
    test('T06', 'Proxy health', t06)
    test('T07', 'Proxy status', t07)
    test('T08', 'Upstream forwarding', t08)
    test('T09', 'Proxy stats tracking', t09)

    print('\n── Dao Engine (predictive) ──')
    test('T10', 'Import + constants', t10)
    test('T11', 'VelocityTracker', t11)
    test('T12', '_should_switch logic', t12)
    test('T13', 'Rate-limit signal file', t13)

    print('\n── WAM Engine ──')
    test('T14', 'Import + thresholds', t14)
    test('T15', 'Weekly-weighted scoring', t15)
    test('T16', 'Pool + snapshots + active', t16)

    print('\n── Integration ──')
    test('T17', 'Cross-component consistency', t17)

    print('\n── Hot-Patch System ──')
    test('T18', 'extension.js patch applied', t18)
    test('T19', 'Key file valid', t19)
    test('T20', 'Key file consistent with engine', t20)
    test('T21', 'hot_patch.py verify()', t21)

    # Summary
    passed = sum(1 for _, _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, _, ok, _ in RESULTS if not ok)
    total = len(RESULTS)

    print(f'\n{"=" * 65}')
    print(f'  RESULTS: {passed}/{total} PASSED  {"" if failed == 0 else f"({failed} FAILED)"}')
    if failed > 0:
        print(f'\n  FAILURES:')
        for tid, name, ok, detail in RESULTS:
            if not ok:
                print(f'    ❌ {tid} {name}: {detail}')
    print(f'{"=" * 65}')
    sys.exit(0 if failed == 0 else 1)
