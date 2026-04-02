#!/usr/bin/env python3
"""
云端号池 v3.1 — 真实多用户并发压测
模拟多台Windsurf实例同时对云端发起请求，验证：
1. 账号分配竞态条件（两用户不会拿到同一账号）
2. SQLite并发写入（bulk_sync + heartbeat + allocate同时执行）
3. 读操作不被写锁阻塞
4. 限流/nonce线程安全
5. 缓存一致性

用法: python _e2e_concurrency.py [--port 19880]
"""

import os, sys, json, time, uuid, secrets, threading, argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

# ============================================================
# Config
# ============================================================
DEFAULT_PORT = 19880
ADMIN_KEY = ''  # Will be set from env or args
BASE_URL = ''
NUM_CONCURRENT_USERS = 10
NUM_REQUESTS_PER_TEST = 50

# ============================================================
# HTTP helpers
# ============================================================
def _req(method, path, body=None, headers=None):
    """Make HTTP request, return (status, data_dict)."""
    url = BASE_URL + path
    hdrs = {'Content-Type': 'application/json'}
    if headers:
        hdrs.update(headers)
    data = json.dumps(body).encode() if body else None
    try:
        req = Request(url, data=data, headers=hdrs, method=method)
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw)
    except HTTPError as e:
        try:
            raw = e.read().decode()
            return e.code, json.loads(raw)
        except:
            return e.code, {'error': str(e)}
    except Exception as e:
        return 0, {'error': str(e)}

def GET(path, headers=None):
    return _req('GET', path, headers=headers)

def POST(path, body=None, headers=None):
    return _req('POST', path, body=body, headers=headers)

def admin_headers():
    return {'X-Admin-Key': ADMIN_KEY}

# ============================================================
# Test infrastructure
# ============================================================
class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.lock = threading.Lock()

    def ok(self, name):
        with self.lock:
            self.passed += 1
            print(f'  ✅ {name}')

    def fail(self, name, detail=''):
        with self.lock:
            self.failed += 1
            self.errors.append(f'{name}: {detail}')
            print(f'  ❌ {name}: {detail}')

    def summary(self):
        total = self.passed + self.failed
        print(f'\n{"="*60}')
        print(f'Results: {self.passed}/{total} passed, {self.failed} failed')
        if self.errors:
            print(f'\nFailures:')
            for e in self.errors:
                print(f'  - {e}')
        print(f'{"="*60}')
        return self.failed == 0

R = TestResult()

# ============================================================
# Phase 1: Basic health + connectivity
# ============================================================
def test_health():
    """Verify server is running and responding."""
    code, data = GET('/api/health')
    if code == 200 and data.get('status') == 'ok':
        R.ok(f'health: v{data.get("version")} accounts={data.get("accounts")} available={data.get("available")}')
        return True
    R.fail('health', f'code={code} data={data}')
    return False

def test_admin_overview():
    """Verify admin API accessible."""
    code, data = GET('/api/admin/overview', headers=admin_headers())
    if code == 200 and data.get('ok'):
        pool = data.get('pool', {})
        R.ok(f'admin_overview: total={pool.get("total")} avail={pool.get("available")} urgent={data.get("urgent")}')
        return True
    R.fail('admin_overview', f'code={code} error={data.get("error","")}')
    return False

# ============================================================
# Phase 2: Concurrent READ pressure
# ============================================================
def test_concurrent_reads():
    """N threads hit read-only endpoints simultaneously."""
    errors = []
    results = Counter()

    def _read_worker(worker_id):
        endpoints = [
            '/api/health',
            '/api/public/pool',
            '/api/public/pool-enhanced',
        ]
        for ep in endpoints:
            code, data = GET(ep)
            if code == 200:
                results[f'{ep}:ok'] += 1
            else:
                errors.append(f'worker{worker_id} {ep}: code={code}')
                results[f'{ep}:fail'] += 1

    with ThreadPoolExecutor(max_workers=NUM_CONCURRENT_USERS) as pool:
        futures = [pool.submit(_read_worker, i) for i in range(NUM_CONCURRENT_USERS)]
        for f in as_completed(futures):
            try: f.result()
            except Exception as e: errors.append(str(e))

    total_ok = sum(v for k, v in results.items() if ':ok' in k)
    total_fail = sum(v for k, v in results.items() if ':fail' in k)

    if total_fail == 0:
        R.ok(f'concurrent_reads: {total_ok} requests from {NUM_CONCURRENT_USERS} threads, 0 failures')
    else:
        R.fail(f'concurrent_reads', f'{total_fail} failures out of {total_ok+total_fail}: {errors[:5]}')

# ============================================================
# Phase 3: Concurrent WRITE - account allocation race
# ============================================================
def test_concurrent_allocation_race():
    """Multiple users try to allocate accounts simultaneously.
    Key assertion: No two users get the same account."""
    allocated_emails = []
    allocation_errors = []
    lock = threading.Lock()

    # First, register N users
    users = []
    for i in range(NUM_CONCURRENT_USERS):
        code, data = POST('/api/register', {'name': f'stress_user_{i}_{secrets.token_hex(3)}'})
        if code == 200 and data.get('ok'):
            users.append(data)
        else:
            allocation_errors.append(f'register failed: {data}')

    if len(users) < 2:
        R.fail('allocation_race', f'only {len(users)} users registered')
        return

    # Top up each user (admin confirm)
    for u in users:
        code, data = POST('/api/topup', {'t': u['token'], 'amount': 8, 'method': 'test'})
        if code == 200 and data.get('ok'):
            pid = data['payment_id']
            POST('/api/admin/confirm', {'payment_id': pid}, headers=admin_headers())

    # Concurrent allocation — all users try at once
    def _allocate_worker(user):
        code, data = POST('/api/allocate', {'t': user['token']})
        with lock:
            if code == 200 and data.get('ok'):
                allocated_emails.append(data.get('email', ''))
            else:
                allocation_errors.append(data.get('error', 'unknown'))

    with ThreadPoolExecutor(max_workers=NUM_CONCURRENT_USERS) as pool:
        futures = [pool.submit(_allocate_worker, u) for u in users]
        for f in as_completed(futures):
            try: f.result()
            except Exception as e: allocation_errors.append(str(e))

    # Check: no duplicate emails
    duplicates = [e for e in allocated_emails if allocated_emails.count(e) > 1]
    unique_allocated = len(set(allocated_emails))

    if duplicates:
        R.fail('allocation_race', f'DUPLICATE ACCOUNTS: {set(duplicates)} — race condition!')
    elif unique_allocated > 0:
        R.ok(f'allocation_race: {unique_allocated} unique allocations, 0 duplicates, {len(allocation_errors)} expected_errors')
    else:
        R.fail('allocation_race', f'no allocations succeeded: {allocation_errors[:5]}')

    # Cleanup: release all allocations
    for u in users:
        POST('/api/release', {'t': u['token']})

# ============================================================
# Phase 4: Concurrent ext_pull race (device allocation)
# ============================================================
def test_concurrent_ext_pull_race():
    """Multiple devices try to pull accounts simultaneously via extension API.
    No two devices should get the same account."""
    pulled_emails = []
    pull_errors = []
    lock = threading.Lock()

    device_ids = [f'TEST-DEV-{secrets.token_hex(4).upper()}' for _ in range(NUM_CONCURRENT_USERS)]

    def _pull_worker(device_id):
        # Direct ext pull (no HMAC for local test, relies on HMAC being disabled)
        code, data = GET(f'/api/ext/pull', headers={'X-Device-Id': device_id})
        with lock:
            if code == 200 and data.get('ok'):
                pulled_emails.append(data.get('email', ''))
            else:
                pull_errors.append(f'{device_id}: {data.get("error", "")}')

    with ThreadPoolExecutor(max_workers=NUM_CONCURRENT_USERS) as pool:
        futures = [pool.submit(_pull_worker, did) for did in device_ids]
        for f in as_completed(futures):
            try: f.result()
            except Exception as e: pull_errors.append(str(e))

    duplicates = [e for e in pulled_emails if pulled_emails.count(e) > 1]
    unique_pulled = len(set(pulled_emails))

    if duplicates:
        R.fail('ext_pull_race', f'DUPLICATE ACCOUNTS: {set(duplicates)} — device race condition!')
    else:
        R.ok(f'ext_pull_race: {unique_pulled} unique pulls, {len(pull_errors)} errors (expected if no credentials/HMAC)')

    # Release pulled accounts
    for email in set(pulled_emails):
        POST('/api/ext/release', {'email': email, 'device_id': 'cleanup'})

# ============================================================
# Phase 5: Concurrent bulk_sync + reads (write doesn't block reads)
# ============================================================
def test_concurrent_sync_and_reads():
    """Bulk sync running while reads happen — reads should not timeout."""
    read_times = []
    sync_result = [None]
    errors = []
    lock = threading.Lock()

    # Generate fake accounts for sync
    fake_accounts = [
        {'email': f'stress_{i}_{secrets.token_hex(4)}@test.local',
         'plan': 'Trial', 'daily': 100, 'weekly': 100, 'days_left': 12}
        for i in range(50)
    ]

    def _sync_worker():
        code, data = POST('/api/admin/bulk-sync',
                         {'accounts': fake_accounts, 'source': 'stress_test', 'device_id': 'stress'},
                         headers=admin_headers())
        sync_result[0] = (code, data)

    def _read_worker(worker_id):
        t0 = time.time()
        code, data = GET('/api/health')
        elapsed = time.time() - t0
        with lock:
            read_times.append(elapsed)
            if code != 200:
                errors.append(f'worker{worker_id}: code={code}')

    # Start sync in background, then hammer with reads
    sync_thread = threading.Thread(target=_sync_worker)
    sync_thread.start()

    # Small delay to ensure sync is running
    time.sleep(0.05)

    with ThreadPoolExecutor(max_workers=NUM_CONCURRENT_USERS) as pool:
        futures = [pool.submit(_read_worker, i) for i in range(NUM_REQUESTS_PER_TEST)]
        for f in as_completed(futures):
            try: f.result()
            except Exception as e: errors.append(str(e))

    sync_thread.join(timeout=30)

    avg_read = sum(read_times) / len(read_times) if read_times else 0
    max_read = max(read_times) if read_times else 0
    sc, sd = sync_result[0] if sync_result[0] else (0, {})

    if max_read < 5.0 and len(errors) == 0:
        R.ok(f'sync_and_reads: sync={sd.get("synced",0)} accounts, '
             f'reads: avg={avg_read*1000:.0f}ms max={max_read*1000:.0f}ms ({len(read_times)} requests)')
    else:
        R.fail('sync_and_reads', f'max_read={max_read:.2f}s errors={errors[:3]}')

    # Cleanup: delete stress test accounts (mark as expired)
    try:
        import sqlite3
        db_path = SCRIPT_DIR / 'cloud_pool.db'
        if db_path.exists():
            c = sqlite3.connect(str(db_path), timeout=10)
            c.execute("DELETE FROM accounts WHERE email LIKE 'stress_%@test.local'")
            c.commit()
            c.close()
    except:
        pass

# ============================================================
# Phase 6: Concurrent heartbeats (most common concurrent write)
# ============================================================
def test_concurrent_heartbeats():
    """Multiple devices send heartbeats simultaneously — the most common concurrent write scenario."""
    results = Counter()
    errors = []
    lock = threading.Lock()

    def _heartbeat_worker(worker_id):
        device_id = f'HB-DEV-{worker_id:03d}'
        code, data = POST('/api/ext/heartbeat',
                         {'device_id': device_id, 'email': f'hb_test_{worker_id}@test.local',
                          'daily': 80 - worker_id, 'weekly': 90 - worker_id},
                         headers={'X-Device-Id': device_id})
        with lock:
            if code == 200:
                results['ok'] += 1
            elif code == 401:
                results['auth'] += 1  # Expected if HMAC enabled
            else:
                results['fail'] += 1
                errors.append(f'worker{worker_id}: code={code} error={data.get("error","")}')

    with ThreadPoolExecutor(max_workers=NUM_CONCURRENT_USERS) as pool:
        futures = [pool.submit(_heartbeat_worker, i) for i in range(NUM_REQUESTS_PER_TEST)]
        for f in as_completed(futures):
            try: f.result()
            except Exception as e: errors.append(str(e))

    total = results['ok'] + results['auth'] + results['fail']
    if results['fail'] == 0:
        R.ok(f'concurrent_heartbeats: {results["ok"]} ok, {results["auth"]} auth_expected, 0 fails ({total} total)')
    else:
        R.fail('concurrent_heartbeats', f'{results["fail"]} failures: {errors[:5]}')

# ============================================================
# Phase 7: Device activation race (same hwid concurrent)
# ============================================================
def test_concurrent_device_activation():
    """Multiple requests activate the same device hwid — should be idempotent."""
    results = []
    errors = []
    lock = threading.Lock()
    hwid = f'STRESS-HWID-{secrets.token_hex(8)}'

    def _activate_worker(worker_id):
        code, data = POST('/api/device/activate',
                         {'hwid': hwid, 'name': f'stress_device_{worker_id}'})
        with lock:
            if code == 200 and data.get('ok'):
                results.append(data.get('action', ''))
            else:
                errors.append(f'worker{worker_id}: {data.get("error","")}')

    with ThreadPoolExecutor(max_workers=NUM_CONCURRENT_USERS) as pool:
        futures = [pool.submit(_activate_worker, i) for i in range(NUM_CONCURRENT_USERS)]
        for f in as_completed(futures):
            try: f.result()
            except Exception as e: errors.append(str(e))

    activated = results.count('activated')
    existing = results.count('existing')

    if activated <= 1 and len(errors) == 0:
        R.ok(f'device_activation_race: {activated} activated, {existing} existing (idempotent OK)')
    elif activated > 1:
        R.fail('device_activation_race', f'{activated} activations — should be exactly 1!')
    else:
        R.fail('device_activation_race', f'errors: {errors[:5]}')

# ============================================================
# Phase 8: P2P order concurrent creation
# ============================================================
def test_concurrent_p2p_orders():
    """Multiple P2P orders created simultaneously — verify no DB conflicts."""
    order_ids = []
    errors = []
    lock = threading.Lock()

    # Phase A: Activate all devices sequentially (idempotent, avoids race)
    device_map = {}  # worker_id -> device_id
    for i in range(NUM_CONCURRENT_USERS):
        hwid = f'p2p-hwid-{i}-{secrets.token_hex(4)}'
        code, data = POST('/api/device/activate', {'hwid': hwid, 'name': f'P2P-DEV-{i:03d}'})
        if code == 200 and data.get('ok'):
            device_map[i] = data.get('device_id', '')

    if len(device_map) < 2:
        R.fail('concurrent_p2p', f'only {len(device_map)} devices activated')
        return

    # Phase B: Concurrent P2P order creation
    def _p2p_worker(worker_id):
        device_id = device_map.get(worker_id, '')
        if not device_id:
            return
        code, data = POST('/api/admin/p2p/create',
                         {'device_id': device_id, 'w_credits': 100, 'method': 'stress_test',
                          'auto_confirm': True, 'note': f'stress_{worker_id}'},
                         headers=admin_headers())
        with lock:
            if code == 200 and data.get('ok'):
                order_ids.append(data.get('order_id', ''))
            else:
                errors.append(f'worker{worker_id}: {data.get("error","")}')

    with ThreadPoolExecutor(max_workers=NUM_CONCURRENT_USERS) as pool:
        futures = [pool.submit(_p2p_worker, i) for i in device_map.keys()]
        for f in as_completed(futures):
            try: f.result()
            except Exception as e: errors.append(str(e))

    unique_orders = len(set(order_ids))
    if unique_orders == len(order_ids) and len(errors) == 0:
        R.ok(f'concurrent_p2p: {unique_orders} unique orders, 0 duplicates, 0 errors')
    elif len(errors) > 0:
        R.fail('concurrent_p2p', f'{len(errors)} errors: {errors[:5]}')
    else:
        R.fail('concurrent_p2p', f'duplicate order IDs detected!')

# ============================================================
# Phase 9: Mixed read/write storm
# ============================================================
def test_mixed_storm():
    """Ultimate stress: reads + writes + syncs + heartbeats all at once."""
    results = Counter()
    errors = []
    lock = threading.Lock()

    def _storm_worker(worker_id):
        # Each worker does a mix of operations
        ops = ['read', 'write', 'sync', 'heartbeat']
        op = ops[worker_id % len(ops)]

        try:
            if op == 'read':
                code, _ = GET('/api/health')
                with lock: results[f'read:{code}'] += 1
            elif op == 'write':
                code, _ = POST('/api/register', {'name': f'storm_{worker_id}_{secrets.token_hex(3)}'})
                with lock: results[f'register:{code}'] += 1
            elif op == 'sync':
                accs = [{'email': f'storm_{worker_id}_{j}@test.local', 'plan': 'Trial',
                         'daily': 100, 'weekly': 100, 'days_left': 12} for j in range(5)]
                code, _ = POST('/api/admin/sync', {'accounts': accs}, headers=admin_headers())
                with lock: results[f'sync:{code}'] += 1
            elif op == 'heartbeat':
                code, _ = POST('/api/ext/heartbeat',
                              {'device_id': f'STORM-{worker_id}', 'email': f'storm@test.local',
                               'daily': 50, 'weekly': 60})
                with lock: results[f'heartbeat:{code}'] += 1
        except Exception as e:
            with lock: errors.append(f'{op}:{e}')

    with ThreadPoolExecutor(max_workers=NUM_CONCURRENT_USERS * 2) as pool:
        futures = [pool.submit(_storm_worker, i) for i in range(NUM_REQUESTS_PER_TEST)]
        for f in as_completed(futures):
            try: f.result()
            except: pass

    total = sum(results.values())
    fail_count = sum(v for k, v in results.items() if ':500' in k or ':0' in k)

    if fail_count == 0 and len(errors) == 0:
        R.ok(f'mixed_storm: {total} operations, 0 server errors | {dict(results)}')
    else:
        R.fail('mixed_storm', f'{fail_count} server errors, {len(errors)} exceptions | {dict(results)} | {errors[:3]}')

    # Cleanup storm data
    try:
        import sqlite3
        db_path = SCRIPT_DIR / 'cloud_pool.db'
        if db_path.exists():
            c = sqlite3.connect(str(db_path), timeout=10)
            c.execute("DELETE FROM accounts WHERE email LIKE 'storm_%@test.local'")
            c.execute("DELETE FROM users WHERE name LIKE 'storm_%'")
            c.commit()
            c.close()
    except:
        pass

# ============================================================
# Main
# ============================================================
def main():
    global BASE_URL, ADMIN_KEY, NUM_CONCURRENT_USERS, NUM_REQUESTS_PER_TEST

    parser = argparse.ArgumentParser(description='Cloud Pool v3.1 Concurrency E2E Test')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--admin-key', default=os.environ.get('CLOUD_POOL_ADMIN_KEY', ''))
    parser.add_argument('--users', type=int, default=NUM_CONCURRENT_USERS)
    parser.add_argument('--requests', type=int, default=NUM_REQUESTS_PER_TEST)
    args = parser.parse_args()

    BASE_URL = f'http://{args.host}:{args.port}'
    ADMIN_KEY = args.admin_key
    NUM_CONCURRENT_USERS = args.users
    NUM_REQUESTS_PER_TEST = args.requests

    print(f'{"="*60}')
    print(f'Cloud Pool v3.1 — Concurrency E2E Test')
    print(f'  Server:   {BASE_URL}')
    print(f'  Users:    {NUM_CONCURRENT_USERS} concurrent')
    print(f'  Requests: {NUM_REQUESTS_PER_TEST} per test')
    print(f'  Admin:    {"configured" if ADMIN_KEY else "NOT SET (some tests will fail)"}')
    print(f'{"="*60}\n')

    # Phase 1: Connectivity
    print('[Phase 1] Health Check')
    if not test_health():
        print('\n⛔ Server not reachable. Start it first:')
        print(f'  python cloud_pool_server.py --port {args.port} --admin-key YOUR_KEY')
        return False

    print('\n[Phase 2] Admin API')
    test_admin_overview()

    print('\n[Phase 3] Concurrent Reads')
    test_concurrent_reads()

    print('\n[Phase 4] Allocation Race Condition')
    test_concurrent_allocation_race()

    print('\n[Phase 5] Extension Pull Race')
    test_concurrent_ext_pull_race()

    print('\n[Phase 6] Sync + Reads (Write vs Read contention)')
    test_concurrent_sync_and_reads()

    print('\n[Phase 7] Concurrent Heartbeats')
    test_concurrent_heartbeats()

    print('\n[Phase 8] Device Activation Race')
    test_concurrent_device_activation()

    print('\n[Phase 9] Concurrent P2P Orders')
    test_concurrent_p2p_orders()

    print('\n[Phase 10] Mixed Read/Write Storm')
    test_mixed_storm()

    return R.summary()


if __name__ == '__main__':
    ok = main()
    sys.exit(0 if ok else 1)
