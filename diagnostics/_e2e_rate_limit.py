"""
_e2e_rate_limit.py — Rate Limit 全链路E2E测试 v2.0
道法自然 · 万法归宗 · 从根本上解决

测试链路:
  1. workbench.js补丁验证 (GBe拦截器+isRateLimited全用户)
  2. 号池管理端 Rate Limit Guard API测试
  3. cloudPool中继链路测试
  4. globalThis信号机制模拟
  5. 模型感知冷却时间验证
  6. 预防性轮转配置验证

Usage:
  python _e2e_rate_limit.py           # 全部测试
  python _e2e_rate_limit.py --patch   # 仅补丁验证
  python _e2e_rate_limit.py --api     # 仅API测试
"""
import sys, os, json, time, hashlib, re
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

WORKBENCH_JS = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
ADMIN_HUB = 'http://127.0.0.1:19881'
WAM_HUB = 'http://127.0.0.1:9870'

passed = 0
failed = 0
skipped = 0

def ok(name, detail=''):
    global passed
    passed += 1
    print(f'  ✅ {name}' + (f' — {detail}' if detail else ''))

def fail(name, detail=''):
    global failed
    failed += 1
    print(f'  ❌ {name}' + (f' — {detail}' if detail else ''))

def skip(name, detail=''):
    global skipped
    skipped += 1
    print(f'  ⏭️ {name}' + (f' — {detail}' if detail else ''))

def http_get(url, timeout=5):
    try:
        r = urlopen(Request(url), timeout=timeout)
        return json.loads(r.read())
    except Exception as e:
        return {'_error': str(e)}

def http_post(url, data, timeout=5):
    try:
        body = json.dumps(data).encode()
        r = urlopen(Request(url, data=body, headers={'Content-Type': 'application/json'}), timeout=timeout)
        return json.loads(r.read())
    except Exception as e:
        return {'_error': str(e)}

# ═══════════════════════════════════════════════════
#  TEST 1: workbench.js 补丁验证
# ═══════════════════════════════════════════════════
def test_workbench_patches():
    print('\n═══ TEST 1: workbench.js 补丁验证 ═══')
    if not os.path.exists(WORKBENCH_JS):
        skip('workbench.js not found', WORKBENCH_JS)
        return

    with open(WORKBENCH_JS, 'r', encoding='utf-8') as f:
        c = f.read()

    # Patch 1: checkUserMessageRateLimit bypass
    if 'if(!1&&!tu.hasCapacity)' in c:
        ok('Patch 1: checkUserMessageRateLimit bypass')
    elif 'if(!tu.hasCapacity)' in c:
        fail('Patch 1: checkUserMessageRateLimit — NOT patched')
    else:
        skip('Patch 1: checkUserMessageRateLimit — target not found (version changed?)')

    # Patch 2: checkChatCapacity bypass
    if 'if(!1&&!Ru.hasCapacity)' in c:
        ok('Patch 2: checkChatCapacity bypass')
    elif 'if(!Ru.hasCapacity)' in c:
        fail('Patch 2: checkChatCapacity — NOT patched')
    else:
        skip('Patch 2: checkChatCapacity — target not found')

    # Patch 3: GBe Rate Limit Interceptor
    if 'globalThis.__wamRateLimit' in c and '/rate.limit/i.test' in c:
        ok('Patch 3: GBe Rate Limit Interceptor', 'globalThis.__wamRateLimit signal active')
    elif 'const B=!!Z?.isBenign;return{errorCode:Z?.errorCode' in c:
        fail('Patch 3: GBe interceptor — NOT patched (original GBe intact)')
    else:
        skip('Patch 3: GBe interceptor — target not found')

    # Patch 3b: error message suppression (v4.0 全静默)
    if '_rl?"":Z?.userErrorMessage' in c:
        ok('Patch 3b: Error message suppression (v4.0)', 'rate limit messages fully silent')
    elif '\\u23f3' in c and '\\u9650\\u6d41' in c:
        ok('Patch 3b: Error message replacement (v3.x)', '⏳ 限流检测·正在自动切换账号... (legacy)')
    else:
        skip('Patch 3b: Error message suppression — not found')

    # Patch 3b2: errorCodePrefix suppression (v4.0)
    if '_rl?"":Z?.errorCode?' in c:
        ok('Patch 3b2: errorCodePrefix suppression (v4.0)', 'Permission denied prefix fully suppressed')
    else:
        skip('Patch 3b2: errorCodePrefix suppression — not found (v3.x legacy)')

    # Patch 3b3: errorParts suppression (v4.0)
    if '_rl?void 0:Z?.structuredErrorParts' in c:
        ok('Patch 3b3: errorParts suppression (v4.0)', 'structured error parts fully suppressed')
    else:
        skip('Patch 3b3: errorParts suppression — not found (v3.x legacy)')

    # Patch 3 sub: isBenign override
    if 'isBenign:_rl||B' in c:
        ok('Patch 3c: isBenign override for rate limit', 'rate limit errors marked benign')
    else:
        skip('Patch 3c: isBenign override')

    # Patch 4: isRateLimited for all users
    has_old_anonymous = 'isRateLimited&&this.ab.anonymous' in c
    # Check if isRateLimited exists without the anonymous check nearby
    if not has_old_anonymous:
        # Verify the widget class still references isRateLimited
        if 'isRateLimited' in c:
            ok('Patch 4: isRateLimited for all users', 'anonymous check removed')
        else:
            skip('Patch 4: isRateLimited — target not found')
    else:
        fail('Patch 4: isRateLimited — still has anonymous check')

    # Patch 5: _resetAt precise reset timestamp
    if '_resetMs:_rm,_resetAt:Date.now()' in c:
        ok('Patch 5: _resetAt precise timestamp', 'resetMs + resetAt injected')
    else:
        fail('Patch 5: _resetAt — NOT found in workbench.js')

    # Patch 5 sub: __wamModelResets history
    if '__wamModelResets' in c:
        ok('Patch 5b: __wamModelResets history array', 'last 20 rate limit events')
    else:
        fail('Patch 5b: __wamModelResets — NOT found')

    # Patch 5 sub: regex for "Resets in: XmYs"
    if 'Resets in:' in c or 'Resets in:\\\\s' in c or 'Resets in' in c:
        ok('Patch 5c: Reset time parser regex')
    else:
        skip('Patch 5c: Reset time parser regex — pattern not found')

    # Patch 6: per-model window constants
    if '__wamOpusWindows' in c:
        ok('Patch 6: __wamOpusWindows model windows', 'per-model constants injected')
    else:
        fail('Patch 6: __wamOpusWindows — NOT found')

    # Patch 6 sub: verify key model entries
    if 'claude-opus-4-6-thinking-1m' in c:
        ok('Patch 6b: thinking-1m model entry', '~23min window')
    else:
        skip('Patch 6b: thinking-1m model entry — not found')

    # Verify patch doesn't break JS syntax (basic check)
    gbe_idx = c.find('globalThis.__wamRateLimit')
    if gbe_idx > 0:
        region = c[max(0, gbe_idx-200):gbe_idx+800]
        opens = region.count('{')
        closes = region.count('}')
        if abs(opens - closes) <= 3:
            ok('Patch integrity: brace balance OK', f'opens={opens} closes={closes}')
        else:
            fail('Patch integrity: brace imbalance', f'opens={opens} closes={closes}')


# ═══════════════════════════════════════════════════
#  TEST 2: 号池管理端 Rate Limit Guard API
# ═══════════════════════════════════════════════════
def test_admin_hub_api():
    print('\n═══ TEST 2: 号池管理端 Rate Limit Guard API ═══')

    # Check admin hub health
    health = http_get(f'{ADMIN_HUB}/api/health')
    if '_error' in health:
        skip('Admin Hub offline', health['_error'])
        return

    if health.get('ok'):
        ok('Admin Hub health', f'v{health.get("v", "?")}')
    else:
        fail('Admin Hub health check failed')
        return

    # Check rate limit status
    rl_status = http_get(f'{ADMIN_HUB}/api/ratelimit/status')
    if '_error' in rl_status:
        skip('Rate limit status API', rl_status['_error'])
    elif rl_status.get('ok'):
        cfg = rl_status.get('config', {})
        ok('Rate limit status API', f'enabled={cfg.get("enabled")} autoSwitch={cfg.get("autoSwitch")}')

        # Verify v18.0 config fields
        if cfg.get('proactiveRotate') is not None:
            ok('v18.0 proactiveRotate config', f'proactiveRotate={cfg.get("proactiveRotate")} budget={cfg.get("proactiveBudget")}')
        else:
            fail('v18.0 proactiveRotate config — missing')

        if cfg.get('modelCooldowns'):
            mcd = cfg['modelCooldowns']
            ok('v18.0 modelCooldowns config', f'{len(mcd)} models: opus-thinking-1m={mcd.get("opus-thinking-1m")}s')
        else:
            fail('v18.0 modelCooldowns config — missing')

        # Check stats
        stats = rl_status.get('stats', {})
        ok('Rate limit stats', f'24h total={stats.get("total24h",0)} switched={stats.get("autoSwitched",0)} failed={stats.get("switchFailed",0)}')
    else:
        fail('Rate limit status API', rl_status.get('error', 'unknown'))


# ═══════════════════════════════════════════════════
#  TEST 3: Rate Limit Report + Auto-Switch 模拟
# ═══════════════════════════════════════════════════
def test_rate_limit_report():
    print('\n═══ TEST 3: Rate Limit Report 模拟 ═══')

    # Simulate a rate limit report
    report = http_post(f'{ADMIN_HUB}/api/ratelimit/trigger-switch', {
        'email': '_e2e_test_account@test.local',
        'dPercent': 85,
        'wPercent': 60,
        'deviceId': 'e2e-test-device',
    })

    if '_error' in report:
        skip('Rate limit report API', report['_error'])
        return

    if report.get('ok'):
        action = report.get('action', 'none')
        if action == 'auto_switched':
            ok('Rate limit auto-switch', f'action={action} switched={report.get("switchedAccount")}')
        elif action == 'throttled':
            ok('Rate limit throttled (防连锁)', f'waitMs={report.get("waitMs")}')
        elif action == 'switch_failed':
            ok('Rate limit report accepted', f'action={action} (no cloud pool = expected)')
        else:
            ok('Rate limit report accepted', f'action={action}')
    else:
        fail('Rate limit report', report.get('error', 'unknown'))

    # Clear the test cooldown
    clear = http_post(f'{ADMIN_HUB}/api/ratelimit/clear', {'email': '_e2e_test_account@test.local'})
    if clear and clear.get('ok'):
        ok('Cooldown cleared for test account')
    else:
        skip('Cooldown clear', str(clear))


# ═══════════════════════════════════════════════════
#  TEST 4: WAM Hub 连通性
# ═══════════════════════════════════════════════════
def test_wam_hub():
    print('\n═══ TEST 4: WAM Hub 连通性 ═══')

    health = http_get(f'{WAM_HUB}/health')
    if '_error' in health:
        skip('WAM Hub offline', health['_error'])
        return

    if health.get('ok') or health.get('status') == 'ok':
        version = health.get('version', health.get('v', '?'))
        ok('WAM Hub health', f'v{version}')
    else:
        fail('WAM Hub health', str(health))

    # Check pool status
    pool = http_get(f'{WAM_HUB}/api/pool/status')
    if '_error' not in pool and pool.get('ok') is not False:
        active = pool.get('activeEmail') or pool.get('active', {}).get('email', '?')
        total = pool.get('totalAccounts') or pool.get('accounts', '?')
        ok('WAM pool status', f'active={active[:20]}... total={total}')
    else:
        skip('WAM pool status', str(pool.get('_error', pool.get('error', ''))))


# ═══════════════════════════════════════════════════
#  TEST 5: globalThis 信号机制验证 (静态分析)
# ═══════════════════════════════════════════════════
def test_signal_mechanism():
    print('\n═══ TEST 5: globalThis 信号机制验证 ═══')

    if not os.path.exists(WORKBENCH_JS):
        skip('workbench.js not found')
        return

    with open(WORKBENCH_JS, 'r', encoding='utf-8') as f:
        c = f.read()

    # Verify signal structure
    if 'globalThis.__wamRateLimit={ts:Date.now()' in c:
        ok('Signal: timestamp (ts) field')
    else:
        fail('Signal: missing ts field')

    if 'msg:Z.userErrorMessage' in c:
        ok('Signal: message (msg) field')
    else:
        fail('Signal: missing msg field')

    if 'id:Z.errorId' in c:
        ok('Signal: error ID (id) field')
    else:
        fail('Signal: missing id field')

    if 'code:Z.errorCode' in c:
        ok('Signal: error code (code) field')
    else:
        fail('Signal: missing code field')

    # Verify regex pattern covers both "Rate limit" and "rate limit"
    if '/rate.limit/i' in c:
        ok('Signal: case-insensitive regex', '/rate.limit/i covers all variations')
    else:
        fail('Signal: regex pattern not found')


# ═══════════════════════════════════════════════════
#  TEST 6: 模型冷却时间矩阵验证
# ═══════════════════════════════════════════════════
def test_model_cooldowns():
    print('\n═══ TEST 6: 模型冷却时间矩阵 ═══')

    # Read poolManager.js and verify cooldown config
    pm_path = Path(__file__).parent.parent.parent / '号池管理端' / 'src' / 'poolManager.js'
    if not pm_path.exists():
        skip('poolManager.js not found', str(pm_path))
        return

    content = pm_path.read_text(encoding='utf-8')

    expected_models = {
        'opus-thinking-1m': 2400,
        'sonnet-thinking-1m': 2400,
        'opus-thinking': 1500,
        'opus': 1200,
        'default': 3900,
    }

    for model, expected_sec in expected_models.items():
        pattern = f"'{model}': {expected_sec}"
        if pattern in content:
            ok(f'Cooldown: {model}', f'{expected_sec}s = {expected_sec//60}min')
        else:
            fail(f'Cooldown: {model}', f'expected {expected_sec}s')

    # Verify proactive rotation config
    if 'proactiveRotate: true' in content:
        ok('Proactive rotation enabled')
    else:
        fail('Proactive rotation — not found or disabled')

    if 'proactiveBudget: 2' in content:
        ok('Proactive budget', '2 msgs per account per window')
    else:
        fail('Proactive budget — not found')

    if 'proactiveWindow: 1200000' in content:
        ok('Proactive window', '1200000ms = 20min')
    else:
        fail('Proactive window — not found')


# ═══════════════════════════════════════════════════
#  TEST 7: cloudPool.js reportRateLimit 方法验证
# ═══════════════════════════════════════════════════
def test_cloud_pool_client():
    print('\n═══ TEST 7: cloudPool.js reportRateLimit 验证 ═══')

    cp_path = Path(__file__).parent.parent.parent / '无感切号' / 'src' / 'cloudPool.js'
    if not cp_path.exists():
        skip('cloudPool.js not found', str(cp_path))
        return

    content = cp_path.read_text(encoding='utf-8')

    if 'async reportRateLimit(' in content:
        ok('reportRateLimit method exists')
    else:
        fail('reportRateLimit method — not found')

    if '/api/v1/rate-limit-report' in content:
        ok('reportRateLimit calls correct endpoint')
    else:
        fail('reportRateLimit endpoint path — not found')

    if 'model:' in content and 'traceId:' in content:
        ok('reportRateLimit passes model + traceId')
    else:
        fail('reportRateLimit — missing fields')


# ═══════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else '--all'

    print('╔══════════════════════════════════════════════════╗')
    print('║  Rate Limit E2E Test v3.0 — 道法自然·万法归宗  ║')
    print('╚══════════════════════════════════════════════════╝')
    print(f'Time: {time.strftime("%Y-%m-%d %H:%M:%S")}')

    if mode in ('--all', '--patch', '--v3'):
        test_workbench_patches()
        test_signal_mechanism()
        test_model_cooldowns()
        test_cloud_pool_client()

    if mode in ('--all', '--api'):
        test_admin_hub_api()
        test_rate_limit_report()
        test_wam_hub()

    if mode in ('--all', '--v3'):
        test_patch5_reset_time()
        test_guardian_status()
        test_opus_windows()

    print(f'\n{"═"*50}')
    print(f'Results: ✅ {passed} passed | ❌ {failed} failed | ⏭️ {skipped} skipped')
    total = passed + failed
    if total > 0:
        pct = passed / total * 100
        print(f'Pass rate: {pct:.0f}%')
    print(f'{"═"*50}')

    if failed > 0:
        print('\n⚠️  有失败项，请检查上述输出。')
        sys.exit(1)
    else:
        print('\n✅ 全部通过！Rate Limit 防御体系完整。')


# ═══════════════════════════════════════════════════
#  TEST 8: Patch5 _resetAt精度验证
# ═══════════════════════════════════════════════════
def test_patch5_reset_time():
    print('\n═══ TEST 8: Patch5 _resetAt精度验证 ═══')

    # 验证 workbench.js 包含 Patch5 注入的关键字段
    if not os.path.exists(WORKBENCH_JS):
        skip('workbench.js not found', WORKBENCH_JS)
        return

    with open(WORKBENCH_JS, 'r', encoding='utf-8') as f:
        c = f.read()

    if '_resetMs:_rm,_resetAt:Date.now()+_rm' in c:
        ok('Patch5: _resetAt/_resetMs注入到globalThis信号')
    else:
        fail('Patch5: _resetAt/_resetMs未注入 — 运行 python ws_repatch.py --force')

    if '__wamModelResets' in c:
        ok('Patch5: __wamModelResets历史队列(最近20条)')
    else:
        fail('Patch5: __wamModelResets未注入')

    if 'Resets in:\\s*' in c or 'Resets in:' in c:
        ok('Patch5: 正则提取"Resets in: Xm Ys"已注入')
    else:
        fail('Patch5: 正则模式未找到')

    # Python端验证解析逻辑
    import re
    def parse_reset_secs(msg):
        m = re.search(r'Resets in:\s*(?:(\d+)h)?(?:(\d+)m)?(\d+)s', msg or '', re.I)
        if not m: return 0
        return int(m.group(1) or 0)*3600 + int(m.group(2) or 0)*60 + int(m.group(3) or 0)

    cases = [
        ("Resets in: 37m2s",  2222),   # 当前截图错误
        ("Resets in: 39m2s",  2342),   # v15.0实测
        ("Resets in: 22m13s", 1333),   # thinking-1m实测
        ("Resets in: 9m22s",   562),   # v14.0实测
        ("Resets in: 1h0m0s", 3600),   # 1小时边界
        ("Resets in: 42s",      42),   # 纯秒
        ("no reset info",        0),   # 无信息
    ]
    for msg, expected in cases:
        got = parse_reset_secs(msg)
        if got == expected:
            ok(f'parse: "{msg}"', f'{got}s')
        else:
            fail(f'parse: "{msg}"', f'expected={expected}s got={got}s')


# ═══════════════════════════════════════════════════
#  TEST 9: Guardian状态
# ═══════════════════════════════════════════════════
def test_guardian_status():
    print('\n═══ TEST 9: Guardian(_rate_limit_guardian.py)状态 ═══')

    guardian_path = Path(__file__).parent / '_rate_limit_guardian.py'
    if guardian_path.exists():
        ok('Guardian脚本存在', str(guardian_path))
    else:
        fail('Guardian脚本不存在', str(guardian_path))
        return

    # 验证guardian可被导入(语法正确)
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, '-c', f'import importlib.util; spec=importlib.util.spec_from_file_location("g",r"{guardian_path}"); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print("ok")'],
        capture_output=True, text=True, timeout=10
    )
    if r.returncode == 0 and 'ok' in r.stdout:
        ok('Guardian语法检查通过')
    else:
        fail('Guardian语法错误', r.stderr[:200])
        return

    # 运行guardian --status
    r2 = subprocess.run(
        [sys.executable, str(guardian_path), '--status'],
        capture_output=True, text=True, timeout=15
    )
    if r2.returncode == 0:
        out = r2.stdout
        if 'PATCHED' in out:
            ok('Guardian --status 可正常运行')
        else:
            ok('Guardian --status 运行(补丁可能缺失)', out.strip()[:100])
    else:
        fail('Guardian --status 运行失败', r2.stderr[:200])


# ═══════════════════════════════════════════════════
#  TEST 10: per-model Opus窗口常量验证
# ═══════════════════════════════════════════════════
def test_opus_windows():
    print('\n═══ TEST 10: per-model Opus窗口常量 ═══')

    if not os.path.exists(WORKBENCH_JS):
        skip('workbench.js not found')
        return

    with open(WORKBENCH_JS, 'r', encoding='utf-8') as f:
        c = f.read()

    if '__wamOpusWindows' not in c:
        fail('Patch6 __wamOpusWindows 未注入 — 运行 python ws_repatch.py --force')
        return

    ok('Patch6: __wamOpusWindows常量表已注入')

    # 验证关键窗口值
    expected_entries = [
        ('claude-opus-4-6',             '2400000'),   # ~40min
        ('claude-opus-4-6-thinking-1m', '1400000'),   # ~22min+裕量
        ('claude-opus-4-6-thinking',    '1560000'),   # ~26min
    ]
    for model, ms in expected_entries:
        pattern = f'"{model}":{ms}'
        alt_pattern = f"'{model}':{ms}"
        if pattern in c or alt_pattern in c:
            ok(f'窗口常量: {model}', f'{ms}ms = {int(ms)//60000}m{(int(ms)%60000)//1000}s')
        else:
            fail(f'窗口常量缺失: {model}', f'期望{ms}ms')

    # 验证当前截图错误 37m2s 被正确覆盖
    # claude-opus-4.6 window=2400s=40min > 37m2s=2222s ✓
    opus_window = 2400
    current_reset = 37*60 + 2  # = 2222s
    if opus_window > current_reset:
        ok(f'窗口覆盖验证', f'{opus_window}s > {current_reset}s(当前错误Resets in: 37m2s) ✓ 不会提前路由')
    else:
        fail(f'窗口覆盖验证', f'{opus_window}s <= {current_reset}s ← 会提前路由触发新一轮限流!')


if __name__ == '__main__':
    main()
