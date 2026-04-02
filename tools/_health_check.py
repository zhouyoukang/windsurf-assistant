#!/usr/bin/env python3
"""
_health_check.py — Windsurf 无限额度系统综合健康检查
一键验证所有关键组件状态，标记问题并给出修复建议
"""
import sys, os, json, sqlite3, base64, re, time, subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ENGINE_DIR = SCRIPT_DIR / '010-道引擎_DaoEngine'
USERS = {
    'ai':            Path(r'C:\Users\ai\AppData\Roaming\Windsurf'),
    'Administrator': Path(r'C:\Users\Administrator\AppData\Roaming\Windsurf'),
}
EXT_JS_PATH = Path(r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js')
EXHAUSTED_KEY_PREFIXES = ['sk-ws-01-ZjtRvwZ']  # known exhausted keys

results = []
def chk(name, ok, detail='', fix=''):
    icon = '✅' if ok else '❌'
    results.append((ok, name, detail, fix))
    print(f'  {icon} {name}')
    if detail:
        print(f'     {detail}')
    if not ok and fix:
        print(f'     → FIX: {fix}')

def db_read_key(appdata):
    db = appdata / 'User' / 'globalStorage' / 'state.vscdb'
    try:
        conn = sqlite3.connect(str(db), timeout=5)
        row = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        conn.close()
        if row:
            d = json.loads(row[0])
            if isinstance(d, dict):
                ak = d.get('apiKey', '')
                pb = d.get('userStatusProtoBinaryBase64', '')
                email = ''
                if pb:
                    raw_pb = base64.b64decode(pb)
                    emails = re.findall(rb'[\w.-]+@[\w.-]+\.\w+', raw_pb[:500])
                    if emails: email = emails[0].decode().rstrip('P')
                return ak, email
    except: pass
    return '', ''

def get_pool_key(appdata):
    pf = appdata / '_pool_apikey.txt'
    try:
        return pf.read_text(encoding='utf-8').strip() if pf.exists() else ''
    except: return ''

def check_login_helper_freshness(appdata):
    gs = appdata / 'User' / 'globalStorage'
    files = {
        'assistant': gs / 'zhouyoukang.windsurf-assistant' / 'windsurf-login-accounts.json',
        'main':      gs / 'windsurf-login-accounts.json',
    }
    result = {}
    for name, f in files.items():
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding='utf-8'))
                lcs = [a.get('usage',{}).get('lastChecked',0) for a in data if isinstance(a.get('usage'),dict)]
                max_lc = max(lcs) if lcs else 0
                age_min = (time.time()*1000 - max_lc)/60000 if max_lc else 9999
                result[name] = {'count': len(data), 'age_min': round(age_min, 1)}
            except:
                result[name] = {'count': 0, 'age_min': 9999}
        else:
            result[name] = None
    return result

print('=' * 62)
print('  Windsurf 无限额度 健康检查')
print(f'  {time.strftime("%Y-%m-%d %H:%M:%S")}')
print('=' * 62)

# ─── 1. extension.js hot_patch ───────────────────────────────
print('\n[1] extension.js Hot Patch')
if EXT_JS_PATH.exists():
    content = EXT_JS_PATH.read_text(encoding='utf-8', errors='replace')
    patched = 'POOL_HOT_PATCH_V1' in content
    m = re.search(r'var _pf=("C:[^"]+_pool_apikey\.txt")', content)
    path_str = m.group(1) if m else 'unknown'
    chk('extension.js patched', patched,
        f'reads from: {path_str}',
        'Run: python hot_patch.py apply')
    correct_path = r'"C:\\Users\\Administrator\\AppData\\Roaming\\Windsurf\\_pool_apikey.txt"'
    chk('patch reads Admin pool key', path_str == correct_path,
        f'actual: {path_str}')
else:
    chk('extension.js exists', False, str(EXT_JS_PATH), 'Check D:\\Windsurf installation')

# ─── 2. pool_apikey.txt 状态 ────────────────────────────────
print('\n[2] _pool_apikey.txt Keys')
keys = {}
for user, appdata in USERS.items():
    pk = get_pool_key(appdata)
    keys[user] = pk
    is_exhausted = any(pk.startswith(p) for p in EXHAUSTED_KEY_PREFIXES)
    valid = pk.startswith('sk-ws') and len(pk) > 50 and not is_exhausted
    chk(f'{user} pool_key valid', valid,
        f'{pk[:45]}...' if pk else 'MISSING',
        'Run: python _cross_user_bridge.py sync')

chk('Both users same pool_key', keys.get('ai') == keys.get('Administrator'),
    'keys differ' if keys.get('ai') != keys.get('Administrator') else 'in sync')

# ─── 3. state.vscdb auth 状态 ──────────────────────────────
print('\n[3] state.vscdb Auth')
db_keys = {}
for user, appdata in USERS.items():
    ak, email = db_read_key(appdata)
    db_keys[user] = ak
    valid = ak.startswith('sk-ws') and len(ak) > 50
    chk(f'{user} DB auth valid', valid, f'{email} | {ak[:40]}')

chk('DB keys in sync', db_keys.get('ai') == db_keys.get('Administrator'),
    'Run bridge sync to align' if db_keys.get('ai') != db_keys.get('Administrator') else 'in sync')

# ─── 4. pool_key == DB key (pool_engine正在使用正确key) ─────
print('\n[4] pool_engine Key Coherence')
for user, appdata in USERS.items():
    pk = keys.get(user, '')
    dk = db_keys.get(user, '')
    # pool key might differ from DB key (pool_engine picks best, not necessarily active)
    # what matters: pool key is fresh and not exhausted
    is_exhausted = any(pk.startswith(p) for p in EXHAUSTED_KEY_PREFIXES)
    chk(f'{user}: pool key is fresh', bool(pk) and not is_exhausted,
        f'pool={pk[:35]}')

# ─── 5. Login Helper 数据新鲜度 ────────────────────────────
print('\n[5] Login Helper Data Freshness')
for user, appdata in USERS.items():
    lh = check_login_helper_freshness(appdata)
    main = lh.get('main')
    asst = lh.get('assistant')
    if main:
        fresh = main['age_min'] < 120
        chk(f'{user} main ({main["count"]} accs)', fresh,
            f'{main["age_min"]:.0f} min old',
            'Login Helper extension needs to run in Windsurf')
    else:
        chk(f'{user} main file exists', False, 'MISSING')
    if asst:
        fresh = asst['age_min'] < 120
        chk(f'{user} assistant cache', fresh,
            f'{asst["count"]} accs, {asst["age_min"]:.0f} min old',
            'Run: python _cross_user_bridge.py sync  (refresh_assistant_cache)')

# ─── 6. pool_engine 进程 ───────────────────────────────────
print('\n[6] pool_engine Process')
try:
    r = subprocess.run(['powershell', '-Command',
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | " +
        "Where-Object { $_.CommandLine -match 'pool_engine' } | " +
        "ForEach-Object { $_.ProcessId.ToString() + '|' + (Invoke-CimMethod -InputObject $_ -MethodName GetOwner).User }"],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10)
    procs = [l.strip() for l in r.stdout.strip().splitlines() if '|' in l]
    def _fmt(p):
        parts = p.split('|')
        return f'PID={parts[0]} owner={parts[1] if len(parts)>1 else "?"}'
    chk('pool_engine running', bool(procs),
        ', '.join([_fmt(p) for p in procs]),
        'Run: python pool_engine.py serve')
    if procs:
        # Check API
        try:
            import urllib.request
            resp = urllib.request.urlopen('http://127.0.0.1:19877/api/health', timeout=3)
            d = json.loads(resp.read())
            chk('pool_engine API responding', d.get('ok', False),
                f'version={d.get("version","?")}')
        except:
            chk('pool_engine API responding', False, ':19877 not responding')
except Exception as e:
    chk('pool_engine check', False, str(e))

# ─── 7. dao_engine.log 最近巡逻 ────────────────────────────
print('\n[7] DaoEngineGuardian Recent Activity')
log_file = ENGINE_DIR / '_dao_engine.log'
if log_file.exists():
    lines = log_file.read_text(encoding='utf-8', errors='replace').splitlines()
    recent = [l for l in lines[-50:] if '巡逻' in l or 'No active' in l or 'Switched' in l]
    last_patrol = next((l for l in reversed(lines[-50:]) if '巡逻完成' in l), None)
    no_active = sum(1 for l in lines[-20:] if 'No active account' in l)
    chk('Recent patrol succeeded', last_patrol is not None,
        last_patrol[:60] if last_patrol else 'No recent successful patrol')
    chk('No "No active account" errors (last 20 lines)', no_active == 0,
        f'{no_active} occurrences' if no_active > 0 else 'clean',
        'Check double-patrol source (PID logging now active)')
else:
    chk('dao_engine.log exists', False)

# ─── 8. Bridge 配置 ────────────────────────────────────────
print('\n[8] Cross-User Bridge')
bridge_py = ENGINE_DIR / '_cross_user_bridge.py'
if bridge_py.exists():
    content = bridge_py.read_text(encoding='utf-8')
    chk('sync_pool_apikey in bridge', 'sync_pool_apikey' in content)
    chk('ping-pong fix in bridge', 'Priority 1' in content)
    chk('refresh_assistant_cache in bridge', 'refresh_assistant_cache' in content)
try:
    r2 = subprocess.run(['schtasks', '/query', '/TN', r'\WindsurfCrossUserBridge', '/fo', 'CSV', '/nh'],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
    active = r2.returncode == 0 and 'Disabled' not in r2.stdout
    chk('WindsurfCrossUserBridge task active', active, r2.stdout.strip()[:60])
except:
    chk('WindsurfCrossUserBridge task', False, 'schtasks query failed')

# ─── 9. wam_engine 修复 ────────────────────────────────────
print('\n[9] wam_engine.py Fixes')
wam_py = ENGINE_DIR / 'wam_engine.py'
if wam_py.exists():
    wam_content = wam_py.read_text(encoding='utf-8')
    chk('_find_login_helper_json freshness fix', 'best_score' in wam_content and 'freshness' in wam_content)
else:
    chk('wam_engine.py exists', False)

pool_py = ENGINE_DIR / 'pool_engine.py'
if pool_py.exists():
    pool_content = pool_py.read_text(encoding='utf-8')
    chk('pool_engine writes to all user pool keys', '_ALL_POOL_KEY_FILES' in pool_content)

# ─── Summary ─────────────────────────────────────────────
print('\n' + '=' * 62)
total = len(results)
passed = sum(1 for r in results if r[0])
failed = total - passed
print(f'  TOTAL: {passed}/{total} checks passed', end='')
if failed == 0:
    print('  ✅ ALL HEALTHY')
else:
    print(f'  ⚠️  {failed} issue(s) found')
    print()
    print('  FAILED CHECKS:')
    for ok, name, detail, fix in results:
        if not ok:
            print(f'    ❌ {name}')
            if fix:
                print(f'       → {fix}')
print('=' * 62)
sys.exit(0 if failed == 0 else 1)
