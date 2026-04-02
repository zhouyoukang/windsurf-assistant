#!/usr/bin/env python3
"""最终验证: 所有根本性修复的核查"""
import sqlite3, json, os, base64, re, hashlib, subprocess
from pathlib import Path

PASS = []
FAIL = []

def check(name, ok, detail=''):
    if ok:
        PASS.append(name)
        print(f'  PASS  {name}: {detail}')
    else:
        FAIL.append(name)
        print(f'  FAIL  {name}: {detail}')

print('=' * 70)
print('  WAM 跨用户切号修复 — 最终验证')
print('=' * 70)

# ===========================================================
# FIX 1: hot_guardian.py _ALL_POOL_KEYS = [POOL_KEY] only
# ===========================================================
print('\n[Fix 1] hot_guardian.py _ALL_POOL_KEYS 仅当前用户')
hg = Path(r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\hot_guardian.py')
if hg.exists():
    src = hg.read_text('utf-8', errors='replace')
    has_admin = 'Users\\\\Administrator' in src or "Users\\Administrator" in src
    has_fix = '_ALL_POOL_KEYS = [POOL_KEY]' in src
    check('hg_no_admin_hardcode', not has_admin, 'Administrator path removed')
    check('hg_single_pool_key', has_fix, '_ALL_POOL_KEYS = [POOL_KEY]')
else:
    check('hot_guardian_exists', False, 'file missing')

# ===========================================================
# FIX 2: hot_patch.py uses process.env.APPDATA dynamic path
# ===========================================================
print('\n[Fix 2] hot_patch.py process.env.APPDATA 动态路径')
hp = Path(r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\hot_patch.py')
if hp.exists():
    src = hp.read_text('utf-8', errors='replace')
    has_dynamic = 'process.env.APPDATA' in src
    has_hardcoded = 'Users\\\\ai' in src or "Users\\\\Administrator" in src
    check('hp_dynamic_appdata', has_dynamic, 'process.env.APPDATA found')
    check('hp_no_hardcode', not has_hardcoded, 'no hardcoded user path')
else:
    check('hot_patch_exists', False, 'file missing')

# ===========================================================
# FIX 3: D:/Windsurf extension.js uses dynamic path
# ===========================================================
print('\n[Fix 3] D:/Windsurf extension.js 动态 APPDATA 路径')
ext = Path('D:/Windsurf/resources/app/extensions/windsurf/dist/extension.js')
if ext.exists():
    data = ext.read_bytes()
    has_marker = b'POOL_HOT_PATCH_V1' in data
    has_dynamic = b'process.env.APPDATA' in data
    has_hardcoded_ai = b'Users\\\\ai' in data
    has_hardcoded_adm = b'Users\\\\Administrator' in data
    check('ext_patched', has_marker, 'POOL_HOT_PATCH_V1 present')
    check('ext_dynamic_path', has_dynamic, 'process.env.APPDATA')
    check('ext_no_hardcode', not has_hardcoded_ai and not has_hardcoded_adm, 'no hardcoded user')
else:
    check('ext_js_exists', False, 'extension.js missing')

# ===========================================================
# FIX 4: Administrator _pool_apikey.txt is empty
# ===========================================================
print('\n[Fix 4] Administrator _pool_apikey.txt 已清空')
adm_pk = Path('C:/Users/Administrator/AppData/Roaming/Windsurf/_pool_apikey.txt')
if adm_pk.exists():
    val = adm_pk.read_text('utf-8', errors='replace').strip()
    check('admin_pool_key_empty', val == '', f'value="{val[:30]}"' if val else 'empty OK')
else:
    check('admin_pool_key_file_exists', False, 'file missing')

# ===========================================================
# FIX 5: wam_engine.py MULTI_USER_DBS = []
# ===========================================================
print('\n[Fix 5] wam_engine.py MULTI_USER_DBS 禁用')
we = Path(r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\wam_engine.py')
if we.exists():
    src = we.read_text('utf-8', errors='replace')
    has_disabled = 'MULTI_USER_DBS = []' in src
    has_old_inject = ('Users\\\\ai' in src or 'Users\\\\Administrator' in src) and 'MULTI_USER_DBS' in src
    check('wam_multi_user_disabled', has_disabled, 'MULTI_USER_DBS = []')
else:
    check('wam_engine_exists', False, 'file missing')

# ===========================================================
# FIX 6: pool_engine.py _ALL_POOL_KEY_FILES = [POOL_KEY_FILE]
# ===========================================================
print('\n[Fix 6] pool_engine.py _ALL_POOL_KEY_FILES 禁用')
pe = Path(r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\pool_engine.py')
if pe.exists():
    src = pe.read_text('utf-8', errors='replace')
    has_fix = '_ALL_POOL_KEY_FILES = [POOL_KEY_FILE]' in src
    check('pool_engine_no_cross_write', has_fix, '_ALL_POOL_KEY_FILES single entry')
else:
    check('pool_engine_exists', False, 'file missing')

# ===========================================================
# FIX 7: D:/Windsurf workbench.js GBe v4.0 patches
# ===========================================================
print('\n[Fix 7] workbench.js GBe v4.0 补丁')
wb = Path('D:/Windsurf/resources/app/out/vs/workbench/workbench.desktop.main.js')
if wb.exists():
    data = wb.read_bytes()
    patches = {
        'GBe __wamRateLimit': b'__wamRateLimit',
        'GBe errorCodePrefix=""': b'errorCodePrefix=""',
        'GBe errorParts:[]': b'errorParts:[]',
        'GBe hasCapacity bypass': b'if(!1&&!',
    }
    for name, marker in patches.items():
        check(f'wb_{name.replace(" ","_")}', marker in data, name)
    # Checksum match
    digest = hashlib.sha256(data).digest()
    cs = base64.b64encode(digest).decode().rstrip('=')
    prod = Path('D:/Windsurf/resources/app/product.json')
    if prod.exists():
        pj = json.loads(prod.read_text('utf-8'))
        stored = pj.get('checksums', {}).get('vs/workbench/workbench.desktop.main.js', '')
        check('wb_checksum_match', stored == cs, 'product.json checksum updated')
else:
    check('workbench_exists', False, 'file missing')

# ===========================================================
# FIX 8: WindsurfAdminWAM scheduled task
# ===========================================================
print('\n[Fix 8] WindsurfAdminWAM 计划任务')
r = subprocess.run(['schtasks', '/Query', '/TN', 'WindsurfAdminWAM'],
    capture_output=True, timeout=10)
task_exists = r.returncode == 0
check('admin_task_registered', task_exists, 'WindsurfAdminWAM in scheduler')

# ===========================================================
# FIX 9: cross_user_bridge v2.0 (AUTH_KEYS=[])
# ===========================================================
print('\n[Fix 9] cross_user_bridge v2.0 AUTH_KEYS=[]')
bridge = Path(r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\_cross_user_bridge.py')
if bridge.exists():
    src = bridge.read_text('utf-8', errors='replace')
    has_empty = 'AUTH_KEYS = []' in src
    check('bridge_auth_keys_empty', has_empty, 'AUTH_KEYS = [] (v2.0)')
else:
    check('bridge_exists', False, 'file missing')

# ===========================================================
# State verification
# ===========================================================
print('\n[State] 当前auth状态')
for user in ['ai', 'Administrator']:
    db = Path(f'C:/Users/{user}/AppData/Roaming/Windsurf/User/globalStorage/state.vscdb')
    pk = Path(f'C:/Users/{user}/AppData/Roaming/Windsurf/_pool_apikey.txt')
    db_key = ''
    pk_val = pk.read_text('utf-8', errors='replace').strip() if pk.exists() else ''
    if db.exists():
        try:
            c = sqlite3.connect(str(db), timeout=3)
            r = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
            if r and r[0]:
                a = json.loads(r[0])
                db_key = a.get('apiKey', '') if a else ''
            c.close()
        except:
            pass
    print(f'  {user}:')
    print(f'    state.vscdb key: {db_key[:35]}... len={len(db_key)}')
    print(f'    _pool_apikey.txt: "{pk_val[:35]}..." len={len(pk_val)}')
    if user == 'Administrator':
        check('admin_pool_key_stays_empty', len(pk_val) == 0, 'empty = will fallback to state.vscdb')

# Summary
print('\n' + '=' * 70)
print(f'  PASS: {len(PASS)}  FAIL: {len(FAIL)}')
if FAIL:
    print('  Failed checks:')
    for f in FAIL:
        print(f'    - {f}')
else:
    print('  All checks PASSED - 跨用户切号根本性修复已全部生效')
print('=' * 70)

USERS = {
    'ai': Path(r'C:\Users\ai\AppData\Roaming\Windsurf\User\globalStorage'),
    'Administrator': Path(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage'),
}

ID_KEYS = ['telemetry.machineId', 'telemetry.devDeviceId', 'telemetry.macMachineId',
           'telemetry.sqmId', 'storage.serviceMachineId']

def read_storage_json(gs):
    p = gs / 'storage.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}

def read_db_val(gs, key):
    db = gs / 'state.vscdb'
    if not db.exists(): return None
    conn = sqlite3.connect(str(db), timeout=10)
    row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
    conn.close()
    return row[0] if row else None

print("=" * 60)
print("  FINAL VERIFICATION")
print("=" * 60)

# 1. Compare machine IDs between storage.json files
print("\n[Machine IDs — storage.json]")
ids = {}
for user, gs in USERS.items():
    sj = read_storage_json(gs)
    ids[user] = {k: sj.get(k, 'NONE') for k in ID_KEYS}

all_match = True
for k in ID_KEYS:
    ai_val = ids['ai'].get(k, 'NONE')
    admin_val = ids['Administrator'].get(k, 'NONE')
    match = ai_val == admin_val
    status = '✅' if match else '❌'
    if not match:
        all_match = False
    short_k = k.replace('telemetry.', 't.').replace('storage.', 's.')
    print(f"  {status} {short_k}: {'MATCH' if match else 'MISMATCH'}")
    if not match:
        print(f"       ai:    {ai_val[:40]}")
        print(f"       admin: {admin_val[:40]}")

# 2. Force re-sync if mismatched
if not all_match:
    print("\n  → Re-syncing IDs...")
    ai_sj_path = USERS['ai'] / 'storage.json'
    admin_sj_path = USERS['Administrator'] / 'storage.json'
    ai_sj = json.loads(ai_sj_path.read_text(encoding='utf-8'))
    admin_sj = json.loads(admin_sj_path.read_text(encoding='utf-8'))
    
    for k in ID_KEYS:
        src = ai_sj.get(k)
        if src:
            admin_sj[k] = src
    
    admin_sj_path.write_text(json.dumps(admin_sj, indent=2, ensure_ascii=False), encoding='utf-8')
    
    # Also sync in state.vscdb
    admin_db = USERS['Administrator'] / 'state.vscdb'
    if admin_db.exists():
        conn = sqlite3.connect(str(admin_db), timeout=10)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=5000')
        for k in ID_KEYS:
            src = ai_sj.get(k)
            if src:
                conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (k, src))
        conn.commit()
        conn.close()
    
    print("  ✅ Re-synced all machine IDs")

# 3. Verify auth
print("\n[Auth Status]")
for user, gs in USERS.items():
    raw = read_db_val(gs, 'windsurfAuthStatus')
    if raw:
        try:
            d = json.loads(raw)
            if d and isinstance(d, dict) and d.get('apiKey'):
                ak = d['apiKey']
                pb = d.get('userStatusProtoBinaryBase64', '')
                email = None
                if pb:
                    raw_pb = base64.b64decode(pb)
                    emails = re.findall(rb'[\w.-]+@[\w.-]+\.\w+', raw_pb[:500])
                    email = emails[0].decode() if emails else None
                print(f"  ✅ {user}: apiKey={ak[:25]}... email={email}")
            elif d is None:
                print(f"  ❌ {user}: null")
            else:
                print(f"  ❌ {user}: no apiKey")
        except:
            print(f"  ❌ {user}: parse error")
    else:
        print(f"  ❌ {user}: MISSING")

# 4. Verify both have same apiKey
ai_ak = None
admin_ak = None
for user, gs in USERS.items():
    raw = read_db_val(gs, 'windsurfAuthStatus')
    if raw:
        try:
            d = json.loads(raw)
            if d and isinstance(d, dict):
                if user == 'ai': ai_ak = d.get('apiKey', '')
                else: admin_ak = d.get('apiKey', '')
        except: pass

print(f"\n[Auth Sync Check]")
if ai_ak and admin_ak:
    if ai_ak == admin_ak:
        print(f"  ✅ Both users have SAME apiKey")
    else:
        print(f"  ⚠️  Different apiKeys (both valid, just different accounts)")
        print(f"     ai:    {ai_ak[:25]}...")
        print(f"     admin: {admin_ak[:25]}...")
elif admin_ak:
    print(f"  ✅ Administrator has valid apiKey")
else:
    print(f"  ❌ Administrator has no valid apiKey")

# 5. Verify cachedPlanInfo
print(f"\n[Plan Info]")
for user, gs in USERS.items():
    raw = read_db_val(gs, 'windsurf.settings.cachedPlanInfo')
    if raw:
        try:
            p = json.loads(raw)
            qu = p.get('quotaUsage', {})
            print(f"  ✅ {user}: {p.get('planName')} D{qu.get('dailyRemainingPercent', '?')}% W{qu.get('weeklyRemainingPercent', '?')}%")
        except:
            print(f"  ⚠️  {user}: present but parse error")
    else:
        print(f"  ⚠️  {user}: missing (will populate on first server call)")

# 6. Verify cascade-auth files
print(f"\n[Auth Files]")
for user, gs in USERS.items():
    for fname in ['cascade-auth.json', 'windsurf-auth.json']:
        f = gs / fname
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding='utf-8'))
                tok = data.get('authToken', '') or data.get('api_key', '')
                if tok.startswith('sk-ws'):
                    print(f"  ✅ {user}/{fname}: valid sk-ws key")
                elif tok.startswith('ott$'):
                    print(f"  ❌ {user}/{fname}: stale ott$ token")
                else:
                    print(f"  ⚠️  {user}/{fname}: {tok[:15]}...")
            except:
                pass

# 7. Account data
print(f"\n[Account Data]")
for user, gs in USERS.items():
    for fname in ['windsurf-login-accounts.json', 'windsurf-assistant-accounts.json']:
        f = gs / fname
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding='utf-8'))
                count = len(data) if isinstance(data, list) else '?'
                print(f"  ✅ {user}/{fname}: {count} accounts")
            except:
                print(f"  ⚠️  {user}/{fname}: parse error")

# 8. Summary
print(f"\n{'='*60}")
print(f"  SUMMARY")
print(f"{'='*60}")
issues = 0
if not admin_ak:
    print(f"  ❌ CRITICAL: Administrator has no valid apiKey")
    issues += 1
if ai_ak and admin_ak and ai_ak != admin_ak:
    print(f"  ℹ️  Users have different apiKeys (normal if recently switched)")

if issues == 0:
    print(f"  🎉 ALL CRITICAL CHECKS PASSED")
    print(f"")
    print(f"  Next steps:")
    print(f"  1. Switch to Administrator Windows account")
    print(f"  2. Start Windsurf → should auto-detect valid auth")
    print(f"  3. If Windsurf asks to login, the injected apiKey will be used")
    print(f"  4. WAM cross-sync will keep auth updated on every switch")
