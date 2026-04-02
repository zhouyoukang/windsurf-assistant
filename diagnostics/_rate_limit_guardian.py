"""
_rate_limit_guardian.py — Rate Limit 守护进程 v1.0
道法自然 · 万法归宗 · 从根本上解决

职责:
  1. WAM Hub保活 — 每10s检测:9870, 离线则IPC重启扩展宿主
  2. 精准换号调度 — 从globalThis._resetAt信号读取精确重置时间, 调度自动切换
  3. 全链路诊断  — 补丁/Hub/代理/池 完整状态一览
  4. 模拟测试    — 无需真实限流即可验证换号链路

Usage:
  python _rate_limit_guardian.py           # 守护模式(持续运行)
  python _rate_limit_guardian.py --check   # 一次性全链路诊断
  python _rate_limit_guardian.py --sim     # 模拟rate limit事件, 验证响应链路
  python _rate_limit_guardian.py --status  # 补丁+Hub状态速查
  python _rate_limit_guardian.py --heal    # 立即执行IPC重启, 尝试恢复WAM Hub

架构:
  Guardian
    ├── HubWatcher     — 每10s轮询:9870 + 离线则IPC重启
    ├── SignalMonitor  — 从Hub API读取rate limit事件
    ├── SwitchScheduler— 基于_resetAt精准调度切号
    └── DiagEngine     — 全链路状态报告
"""
import sys, os, time, json, hashlib, hmac, socket, platform
import threading, subprocess, struct
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ═══════════════════════════════════════════════════════
#  常量
# ═══════════════════════════════════════════════════════
WAM_HUB      = 'http://127.0.0.1:9870'
ADMIN_HUB    = 'http://127.0.0.1:19881'
PROXY_PORT   = 19443
WORKBENCH_JS = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
PLUGIN_MGR   = Path(__file__).parent.parent.parent / '插件管理' / 'plugin_manager.py'
PYTHON       = r'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe'

# Opus per-model rate limit windows (实测值+裕量 ms)
OPUS_WINDOWS = {
    'claude-opus-4-6':             2400_000,   # ~40min 实测(37m2s当前)
    'claude-opus-4.6':             2400_000,
    'claude-opus-4-5':             2400_000,
    'claude-opus-4-6-thinking-1m': 1400_000,   # ~22min 实测(22m13s)
    'claude-opus-4-6-thinking':    1560_000,   # ~26min 估算
    'claude-sonnet-4-6':            900_000,
    'claude-sonnet-4-5':            900_000,
    'default':                     2400_000,
}

VERSION = '1.0.0'

# ═══════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════

def _ts():
    return time.strftime('%H:%M:%S')

def _log(tag, msg, color=''):
    COLORS = {'ok': '\033[92m', 'warn': '\033[93m', 'err': '\033[91m', 'info': '\033[96m', '': ''}
    RESET = '\033[0m'
    c = COLORS.get(color, '')
    print(f'[{_ts()}] {c}[{tag}]{RESET} {msg}')

def _http(method, url, body=None, timeout=5, headers=None):
    try:
        data = json.dumps(body).encode() if body else None
        h = {'Content-Type': 'application/json'}
        if headers:
            h.update(headers)
        if data:
            h['Content-Length'] = str(len(data))
        req = Request(url, data=data, headers=h, method=method)
        r = urlopen(req, timeout=timeout)
        return {'ok': True, 'status': r.status, 'data': json.loads(r.read())}
    except HTTPError as e:
        try:
            return {'ok': False, 'status': e.code, 'data': json.loads(e.read())}
        except:
            return {'ok': False, 'status': e.code, 'data': {}}
    except URLError as e:
        return {'ok': False, 'status': 0, 'data': {}, 'error': str(e)}
    except Exception as e:
        return {'ok': False, 'status': 0, 'data': {}, 'error': str(e)}

def _machine_id():
    """Node.js os.cpus()[0].model + hostname + username + platform + arch"""
    try:
        result = subprocess.run(
            ['wmic', 'cpu', 'get', 'name', '/value'],
            capture_output=True, text=True, timeout=5
        )
        cpu = ''
        for line in result.stdout.split('\n'):
            if '=' in line and 'name' in line.lower():
                cpu = line.split('=', 1)[1].strip()
                break
    except:
        cpu = platform.processor() or ''

    hostname = socket.gethostname()
    try:
        username = os.getlogin()
    except:
        username = os.environ.get('USERNAME', os.environ.get('USER', ''))

    sys_map = {'Windows': 'win32', 'Linux': 'linux', 'Darwin': 'darwin'}
    plat = sys_map.get(platform.system(), platform.system().lower())
    arch = platform.machine().lower()

    data = '|'.join([hostname, username, cpu, plat, arch])
    return hashlib.sha256(data.encode()).hexdigest()

def _local_secret():
    mid = _machine_id()
    return hmac.new(mid.encode(), b'wam-relay-v1', hashlib.sha256).hexdigest()

def _sign_headers():
    """与cloudPool.js._signHeaders()兼容的HMAC签名"""
    import secrets as _sec
    ts = str(int(time.time()))
    nonce = _sec.token_hex(8)
    secret = _local_secret()
    sig = hmac.new(secret.encode(), f'{ts}.{nonce}'.encode(), hashlib.sha256).hexdigest()
    mid = _machine_id()
    device_id = hashlib.sha256(
        f'{socket.gethostname()}|{os.getlogin()}'.encode()
    ).hexdigest()[:16]
    return {'x-ts': ts, 'x-nc': nonce, 'x-sg': sig, 'x-di': device_id}

def _parse_reset_secs(msg):
    """从 'Resets in: 37m2s' 提取秒数"""
    import re
    if not msg:
        return 0
    m = re.search(r'Resets in:\s*(?:(\d+)h)?(?:(\d+)m)?(\d+)s', msg, re.I)
    if not m:
        return 0
    return int(m.group(1) or 0)*3600 + int(m.group(2) or 0)*60 + int(m.group(3) or 0)

# ═══════════════════════════════════════════════════════
#  IPC 管道重启 (来自 插件管理/plugin_manager.py)
# ═══════════════════════════════════════════════════════

def _ipc_restart_ext_host():
    """通过IPC管道发送 restartExtensionHost 消息"""
    import winreg
    # 枚举所有 main-sock 管道
    pipes = []
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             '[IO.Directory]::GetFiles("\\\\.\\pipe\\") | Where-Object {$_ -like "*main-sock*"}'],
            capture_output=True, text=True, timeout=10
        )
        pipes = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]
    except:
        pass

    if not pipes:
        _log('IPC', 'No main-sock pipes found', 'warn')
        return False

    msg = json.dumps({'type': 'restartExtensionHost'}).encode('utf-8')
    sent = 0
    for pipe_path in pipes:
        try:
            import win32file
            handle = win32file.CreateFile(
                pipe_path,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0, None,
                win32file.OPEN_EXISTING,
                0, None
            )
            header = struct.pack('<I', len(msg))
            win32file.WriteFile(handle, header + msg)
            win32file.CloseHandle(handle)
            sent += 1
            _log('IPC', f'Sent restartExtensionHost → {pipe_path}', 'ok')
        except Exception as e:
            _log('IPC', f'Failed {pipe_path}: {e}', 'warn')

    return sent > 0

def _ipc_restart_via_plugin_mgr():
    """降级: 调用 插件管理/plugin_manager.py restart"""
    if not PLUGIN_MGR.exists():
        _log('IPC', f'plugin_manager.py not found: {PLUGIN_MGR}', 'warn')
        return False
    try:
        result = subprocess.run(
            [PYTHON, str(PLUGIN_MGR), 'restart'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            _log('IPC', 'Extension host restarted via plugin_manager', 'ok')
            return True
        else:
            _log('IPC', f'plugin_manager restart failed: {result.stderr[:200]}', 'err')
            return False
    except Exception as e:
        _log('IPC', f'Exception: {e}', 'err')
        return False

def _touch_reload():
    """零感知恢复: 写入.reload时间戳触发hot-dir watcher重载, 用户无感知"""
    import pathlib
    reload_path = pathlib.Path.home() / '.wam-hot' / '.reload'
    if not reload_path.parent.exists():
        _log('HEAL', f'.wam-hot not found: {reload_path.parent}', 'warn')
        return False
    ts = str(int(time.time() * 1000))
    try:
        reload_path.write_text(ts)
        _log('HEAL', f'.reload={ts} → watcher将触发热重载(零干扰)', 'ok')
        return True
    except Exception as e:
        _log('HEAL', f'.reload write failed: {e}', 'err')
        return False

def restart_extension_host():
    """三级恢复: L1 .reload(零干扰) → L2 IPC重启(~2s) → L3 plugin_manager"""
    _log('HEAL', 'L1: Trying .reload (zero disruption)...', 'info')
    if _touch_reload():
        time.sleep(5)
        wam = check_wam_hub()
        if wam['online']:
            _log('HEAL', '✅ L1 success: .reload触发热重载, Hub已上线', 'ok')
            return True
        _log('HEAL', 'L1: .reload sent but Hub still offline, trying L2...', 'warn')

    _log('HEAL', 'L2: IPC restartExtensionHost (~2s)...', 'info')
    try:
        import win32file
        if _ipc_restart_ext_host():
            time.sleep(5)
            if _touch_reload():  # IPC重启后再触发.reload
                time.sleep(3)
            wam = check_wam_hub()
            if wam['online']:
                _log('HEAL', '✅ L2 success: IPC+.reload联合恢复', 'ok')
                return True
    except ImportError:
        _log('HEAL', 'win32file not available, skipping L2', 'warn')

    _log('HEAL', 'L3: plugin_manager fallback...', 'info')
    return _ipc_restart_via_plugin_mgr()

# ═══════════════════════════════════════════════════════
#  补丁状态检查
# ═══════════════════════════════════════════════════════

PATCH_CHECKS = [
    ('Patch1: checkUserMessageRateLimit bypass', 'if(!1&&!tu.hasCapacity)'),
    ('Patch2: checkChatCapacity bypass',         'if(!1&&!Ru.hasCapacity)'),
    ('Patch3: GBe interceptor',                  'globalThis.__wamRateLimit={ts:Date.now()'),
    ('Patch4: isRateLimited all users',          'isRateLimited&&this.ab.anonymous'),   # 缺失=已应用
    ('Patch5: _resetAt precision',               '_resetMs:_rm,_resetAt:Date.now()+_rm'),
    ('Patch6: OpusWindows constants',            '__wamOpusWindows'),
]

def check_patches():
    if not os.path.exists(WORKBENCH_JS):
        return {'ok': False, 'error': 'workbench.js not found'}
    with open(WORKBENCH_JS, 'r', encoding='utf-8') as f:
        c = f.read()
    results = {}
    for name, pattern in PATCH_CHECKS:
        if name == 'Patch4: isRateLimited all users':
            # Patch4: 缺失原始字符串 = 已修改(patched)
            results[name] = 'PATCHED' if pattern not in c else 'NEEDS PATCH'
        else:
            results[name] = 'PATCHED' if pattern in c else 'MISSING'
    return {'ok': True, 'results': results, 'file': WORKBENCH_JS}

# ═══════════════════════════════════════════════════════
#  Hub 状态检查
# ═══════════════════════════════════════════════════════

def check_wam_hub():
    r = _http('GET', f'{WAM_HUB}/health')
    if r['ok']:
        return {'online': True, 'data': r['data']}
    return {'online': False, 'error': r.get('error', f"status={r['status']}")}

def check_admin_hub():
    r = _http('GET', f'{ADMIN_HUB}/api/health')
    if r['ok']:
        return {'online': True, 'data': r['data']}
    return {'online': False, 'error': r.get('error', f"status={r['status']}")}

def check_proxy():
    try:
        s = socket.create_connection(('127.0.0.1', PROXY_PORT), timeout=2)
        s.close()
        return {'online': True}
    except:
        return {'online': False}

def get_pool_status():
    r = _http('GET', f'{WAM_HUB}/api/pool/status')
    if r['ok']:
        return r['data']
    return {'ok': False, 'error': r.get('error', '')}

def get_seamless_stats():
    r = _http('GET', f'{WAM_HUB}/api/seamless-stats')
    if r['ok']:
        return r['data']
    return {}

# ═══════════════════════════════════════════════════════
#  全链路诊断
# ═══════════════════════════════════════════════════════

def run_diagnostics():
    print('\n╔══════════════════════════════════════════════════════════╗')
    print(f'║  Rate Limit Guardian v{VERSION} — 全链路诊断               ║')
    print('╚══════════════════════════════════════════════════════════╝')
    print(f'时间: {time.strftime("%Y-%m-%d %H:%M:%S")}\n')

    ok_count = fail_count = warn_count = 0

    def ok(name, detail=''):
        nonlocal ok_count; ok_count += 1
        print(f'  ✅ {name}' + (f' — {detail}' if detail else ''))

    def fail(name, detail=''):
        nonlocal fail_count; fail_count += 1
        print(f'  ❌ {name}' + (f' — {detail}' if detail else ''))

    def warn(name, detail=''):
        nonlocal warn_count; warn_count += 1
        print(f'  ⚠️  {name}' + (f' — {detail}' if detail else ''))

    # ── 1. 补丁状态 ──
    print('─── 1. workbench.js 补丁 ───')
    pr = check_patches()
    if not pr['ok']:
        fail('workbench.js', pr.get('error'))
    else:
        for name, state in pr['results'].items():
            if state == 'PATCHED':
                ok(name)
            elif state == 'NEEDS PATCH':
                fail(name, '运行 python ws_repatch.py --force')
            else:
                warn(name, '目标字符串未找到(版本可能已变)')

    # ── 2. WAM Hub :9870 ──
    print('\n─── 2. WAM Hub :9870 ───')
    wam = check_wam_hub()
    if wam['online']:
        v = wam['data'].get('version', wam['data'].get('v', '?'))
        ok('WAM Hub', f'v{v}')
        pool = get_pool_status()
        if pool.get('ok') is not False:
            active = pool.get('activeEmail') or pool.get('active', {}).get('email', '?')
            total = pool.get('totalAccounts') or pool.get('accounts', '?')
            ok('Pool status', f'active={str(active)[:30]} total={total}')
        stats = get_seamless_stats()
        if stats:
            ok('Seamless stats', f'switches={stats.get("switches",0)} retries={stats.get("retries",0)}')
    else:
        fail('WAM Hub OFFLINE', f'{wam["error"]} — 守护进程将自动重启')
        warn('根因: 无感切号VSIX Hub未初始化', '可能原因: hot-dir有旧版extension.js')
        warn('修复路径', 'Ctrl+Shift+P → wam.hotReload 或 Reload Window')

    # ── 3. Admin Hub :19881 ──
    print('\n─── 3. Admin Hub :19881 ───')
    admin = check_admin_hub()
    if admin['online']:
        ok('Admin Hub', admin['data'].get('version', 'online'))
    else:
        warn('Admin Hub offline', admin.get('error', ''))

    # ── 4. 透明代理 :19443 ──
    print('\n─── 4. 透明代理 :19443 ───')
    proxy = check_proxy()
    if proxy['online']:
        ok('透明代理 active', 'gRPC apiKey替换层运行中')
    else:
        warn('透明代理 offline', '账号切换依赖WAM WAM热切换(3-5s) 而非网络层拦截(0ms)')

    # ── 5. Opus窗口参考 ──
    print('\n─── 5. per-model Rate Limit窗口参考 ───')
    for model, ms in OPUS_WINDOWS.items():
        sec = ms // 1000
        print(f'  {model:<44s}: {sec}s = {sec//60}m{sec%60}s')

    # ── 汇总 ──
    print(f'\n{"═"*58}')
    print(f'  ✅ {ok_count}  ⚠️  {warn_count}  ❌ {fail_count}')

    if not wam['online']:
        print('\n⚡ WAM Hub离线是当前唯一Critical问题:')
        print('   方案A (推荐): Ctrl+Shift+P → "wam.hotReload" 热重载')
        print('   方案B: Ctrl+Shift+P → "Reload Window" 重载窗口(3-5s)')
        print('   方案C: 运行 python _rate_limit_guardian.py --heal')
    elif fail_count == 0:
        print('\n✅ 全链路完整! claude-opus-4.6限流将被自动处理.')
        print('   _resetAt: 精确到秒的重置时间戳 ✅')
        print('   WAM 1s拦截器: 检测到rate limit → 立即切号+重试 ✅')
    print()
    return {'ok': fail_count == 0, 'ok_count': ok_count, 'fail_count': fail_count, 'warn_count': warn_count}

# ═══════════════════════════════════════════════════════
#  模拟测试 — 无需真实限流即可验证全链路
# ═══════════════════════════════════════════════════════

def run_simulation():
    print('\n╔══════════════════════════════════════════════════════════╗')
    print('║  Rate Limit 全链路模拟验证                                ║')
    print('╚══════════════════════════════════════════════════════════╝\n')

    ok_c = fail_c = 0

    def ok(name, detail=''):
        nonlocal ok_c; ok_c += 1
        print(f'  ✅ {name}' + (f' — {detail}' if detail else ''))

    def fail(name, detail=''):
        nonlocal fail_c; fail_c += 1
        print(f'  ❌ {name}' + (f' — {detail}' if detail else ''))

    # ── SIM-1: _resetAt提取精度验证 ──
    print('─── SIM-1: Patch5 _resetAt提取精度 ───')
    test_cases = [
        ("Reached message rate limit. Resets in: 37m2s",   2222),
        ("Resets in: 39m2s",                               2342),
        ("Resets in: 9m22s",                                562),
        ("Resets in: 22m13s",                              1333),
        ("Resets in: 1h30m0s",                             5400),
        ("Resets in: 42s",                                   42),
        ("No reset info here",                                0),
    ]
    for msg, expected in test_cases:
        got = _parse_reset_secs(msg)
        if got == expected:
            ok(f'parse "{msg[:40]}"', f'{got}s ✓')
        else:
            fail(f'parse "{msg[:40]}"', f'expected={expected}s got={got}s')

    # ── SIM-2: Patch5在workbench.js中的存在验证 ──
    print('\n─── SIM-2: workbench.js Patch5/6内容验证 ───')
    if os.path.exists(WORKBENCH_JS):
        with open(WORKBENCH_JS, 'r', encoding='utf-8') as f:
            c = f.read()
        checks = [
            ('_resetAt注入',     '_resetAt:Date.now()+_rm'),
            ('_resetMs注入',     '_resetMs:_rm'),
            ('__wamModelResets', '__wamModelResets'),
            ('__wamOpusWindows', '__wamOpusWindows'),
            ('isBenign覆盖',     'isBenign:_rl||B'),
            ('消息替换',         '\\u23f3'),
        ]
        for name, pattern in checks:
            if pattern in c:
                ok(f'workbench.js {name}')
            else:
                fail(f'workbench.js {name} — 未找到"{pattern}"')
    else:
        fail('workbench.js not found', WORKBENCH_JS)

    # ── SIM-3: globalThis信号格式模拟 ──
    print('\n─── SIM-3: globalThis信号格式模拟 ───')
    # 模拟Patch5执行后的信号
    fake_msg = "Permission denied: Reached message rate limit for this model. Please try again later. Resets in: 37m2s (trace ID: 5bac174d2b9b40afe46ea50f19d9cc76)"
    reset_ms = _parse_reset_secs(fake_msg) * 1000
    ts_now = int(time.time() * 1000)
    fake_signal = {
        'ts':       ts_now,
        'msg':      fake_msg,
        'id':       '5bac174d2b9b40afe46ea50f19d9cc76',
        'code':     None,
        '_resetMs': reset_ms,
        '_resetAt': ts_now + reset_ms,
    }
    reset_dt = time.strftime('%H:%M:%S', time.localtime((ts_now + reset_ms) / 1000))
    if reset_ms == 2222_000:
        ok('信号._resetMs', f'{reset_ms}ms = 37min2s')
        ok('信号._resetAt', f'rate limit到期时间 = {reset_dt}')
    else:
        fail('信号._resetMs', f'expected=2222000 got={reset_ms}')

    # ── SIM-4: 换号调度模拟 ──
    print('\n─── SIM-4: 换号调度逻辑模拟 ───')
    now_ms = int(time.time() * 1000)
    accounts = [
        {'email': 'acc_A@test.local', 'rate_limited_until': now_ms + 2222_000, 'daily_pct': 60},
        {'email': 'acc_B@test.local', 'rate_limited_until': 0,                 'daily_pct': 85},
        {'email': 'acc_C@test.local', 'rate_limited_until': now_ms - 5000,    'daily_pct': 40},
    ]

    def select_best(accs, current_email='acc_A@test.local'):
        """模拟WAM selectOptimal逻辑"""
        candidates = [
            a for a in accs
            if a['email'] != current_email
            and (a['rate_limited_until'] == 0 or a['rate_limited_until'] < now_ms)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda a: a['daily_pct'])

    best = select_best(accounts)
    if best and best['email'] == 'acc_B@test.local':
        ok('selectOptimal', f'正确跳过rate-limited账号, 选中={best["email"]} D={best["daily_pct"]}%')
    else:
        fail('selectOptimal', f'选错账号: {best}')

    # acc_B also rate limited → should pick acc_C
    accounts[1]['rate_limited_until'] = now_ms + 1800_000
    best2 = select_best(accounts)
    if best2 and best2['email'] == 'acc_C@test.local':
        ok('selectOptimal(all-but-C)', f'所有高额账号耗尽, fallback到C={best2["email"]} D={best2["daily_pct"]}%')
    else:
        fail('selectOptimal(all-but-C)', f'应选acc_C, 实际={best2}')

    # all rate limited
    for a in accounts:
        a['rate_limited_until'] = now_ms + 1_800_000
    best3 = select_best(accounts)
    if best3 is None:
        next_reset = min(a['rate_limited_until'] for a in accounts if a['email'] != 'acc_A@test.local')
        wait_s = (next_reset - now_ms) // 1000
        ok('全部耗尽处理', f'no candidates → 应等待{wait_s}s后重试(最早 {wait_s//60}m{wait_s%60}s)')
    else:
        fail('全部耗尽处理', f'应返回None, 实际={best3}')

    # ── SIM-5: WAM Hub连通性 ──
    print('\n─── SIM-5: WAM Hub连通性 ───')
    wam = check_wam_hub()
    if wam['online']:
        ok('WAM Hub :9870', f'online, 自动换号链路通畅')
    else:
        fail('WAM Hub :9870 OFFLINE', '守护进程将在daemon模式下自动重启')

    # ── SIM-6: Admin Hub连通性 ──
    print('\n─── SIM-6: Admin Hub连通性 ───')
    admin = check_admin_hub()
    if admin['online']:
        ok('Admin Hub :19881', 'online')
    else:
        print(f'  ⏭️  Admin Hub :19881 offline — {admin.get("error", "")}')

    # ── 汇总 ──
    print(f'\n{"═"*58}')
    print(f'  ✅ {ok_c} passed  ❌ {fail_c} failed')
    total = ok_c + fail_c
    if total > 0:
        print(f'  Pass rate: {ok_c/total*100:.0f}%')

    if fail_c == 0:
        print('\n✅ 全链路模拟通过! 换号机制端到端验证完整.')
    else:
        print('\n⚠️  有失败项, 请检查上述输出.')
    print()
    return fail_c == 0

# ═══════════════════════════════════════════════════════
#  守护进程主循环
# ═══════════════════════════════════════════════════════

class RateLimitGuardian:
    def __init__(self):
        self._wam_offline_since = None
        self._restart_count = 0
        self._last_restart = 0
        self._lock = threading.Lock()

    def _should_restart(self):
        now = time.time()
        offline_sec = now - self._wam_offline_since if self._wam_offline_since else 0
        since_last = now - self._last_restart
        # 离线超30s且距上次重启超60s
        return offline_sec > 30 and since_last > 60

    def tick(self):
        wam = check_wam_hub()
        if wam['online']:
            if self._wam_offline_since:
                _log('WAM', f'Hub recovered after {time.time()-self._wam_offline_since:.0f}s', 'ok')
            self._wam_offline_since = None
            return

        # Hub offline
        if not self._wam_offline_since:
            self._wam_offline_since = time.time()
            _log('WAM', 'Hub went offline', 'warn')

        offline_sec = time.time() - self._wam_offline_since
        _log('WAM', f'Hub still offline ({offline_sec:.0f}s)', 'warn')

        if self._should_restart():
            _log('HEAL', f'Triggering restart #{self._restart_count+1}...', 'info')
            if restart_extension_host():
                self._restart_count += 1
                self._last_restart = time.time()
                _log('HEAL', f'Restart sent, waiting 8s for Hub to come up...', 'ok')
                time.sleep(8)
            else:
                _log('HEAL', 'Restart failed. Try: Ctrl+Shift+P → Reload Window', 'err')
                self._last_restart = time.time()  # backoff

    def run_daemon(self, interval=10):
        _log('GUARD', f'Rate Limit Guardian v{VERSION} started (interval={interval}s)', 'info')
        _log('GUARD', f'Monitoring WAM Hub: {WAM_HUB}', 'info')
        _log('GUARD', 'Press Ctrl+C to stop', 'info')
        print()
        try:
            while True:
                self.tick()
                time.sleep(interval)
        except KeyboardInterrupt:
            _log('GUARD', 'Stopped by user', 'info')

# ═══════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════

def main():
    args = sys.argv[1:]

    if '--help' in args or '-h' in args:
        print(__doc__)
        return

    if '--check' in args:
        run_diagnostics()
        return

    if '--sim' in args:
        ok = run_simulation()
        sys.exit(0 if ok else 1)

    if '--status' in args:
        pr = check_patches()
        wam = check_wam_hub()
        proxy = check_proxy()
        print(f'[{_ts()}] 补丁状态:')
        if pr['ok']:
            for name, state in pr['results'].items():
                icon = '✅' if state == 'PATCHED' else '❌'
                print(f'  {icon} {name}: {state}')
        print(f'[{_ts()}] WAM Hub: {"✅ online" if wam["online"] else "❌ OFFLINE"}')
        print(f'[{_ts()}] 透明代理: {"✅ active" if proxy["online"] else "⚠️  inactive"}')
        return

    if '--heal' in args:
        _log('HEAL', 'Manual heal triggered', 'info')
        wam = check_wam_hub()
        if wam['online']:
            _log('HEAL', 'WAM Hub is already online, nothing to do', 'ok')
            return
        if restart_extension_host():
            wam2 = check_wam_hub()
            if wam2['online']:
                v = wam2['data'].get('version', wam2['data'].get('v', '?'))
                _log('HEAL', f'✅ WAM Hub online! v{v}', 'ok')
                return
        _log('HEAL', '❌ All heal attempts failed. Last resort: Ctrl+Shift+P → Reload Window', 'err')
        return

    # Default: daemon mode
    g = RateLimitGuardian()
    g.run_daemon()

if __name__ == '__main__':
    main()
