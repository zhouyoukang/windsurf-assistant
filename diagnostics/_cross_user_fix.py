#!/usr/bin/env python3
"""
跨用户Windsurf修复器 — 道法自然·逆向到底
==========================================
从根本上解决另一个Windows主账号(Administrator)无法正常登录和无感切号的问题。

根因: Administrator的state.vscdb中windsurfAuthStatus为null(4字节),
      cachedPlanInfo缺失, machineId不同, 无扩展安装。

修复策略(五步):
  1. 从WAM快照池注入有效auth到Administrator的state.vscdb
  2. 同步machineId到Administrator的storage.json  
  3. 安装Login Helper扩展到Administrator的extensions目录
  4. 修复cascade-auth.json(清除失效的ott$一次性令牌)
  5. 验证修复结果

用法:
  python _cross_user_fix.py                # 全修复
  python _cross_user_fix.py diagnose       # 仅诊断
  python _cross_user_fix.py inject         # 仅注入auth
  python _cross_user_fix.py sync-ids       # 仅同步machineId
  python _cross_user_fix.py install-ext    # 仅安装扩展
  python _cross_user_fix.py verify         # 验证修复
"""

import sqlite3, json, os, sys, shutil, time, base64, re
from pathlib import Path
from datetime import datetime, timezone

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = Path(__file__).parent
WAM_DIR = SCRIPT_DIR.parent / '010-道引擎_DaoEngine'
SNAPSHOT_FILE = WAM_DIR / '_wam_snapshots.json'

# User paths
USERS = {
    'ai': {
        'appdata': Path(r'C:\Users\ai\AppData\Roaming\Windsurf'),
        'localappdata': Path(r'C:\Users\ai\AppData\Local\Windsurf'),
    },
    'Administrator': {
        'appdata': Path(r'C:\Users\Administrator\AppData\Roaming\Windsurf'),
        'localappdata': Path(r'C:\Users\Administrator\AppData\Local\Windsurf'),
    },
}

SOURCE_USER = 'ai'           # Working user (auth source)
TARGET_USER = 'Administrator' # Broken user (fix target)

WS_INSTALL = Path(r'D:\Windsurf')

def get_db_path(user):
    return USERS[user]['appdata'] / 'User' / 'globalStorage' / 'state.vscdb'

def get_storage_json_path(user):
    return USERS[user]['appdata'] / 'User' / 'globalStorage' / 'storage.json'

def get_globalstore(user):
    return USERS[user]['appdata'] / 'User' / 'globalStorage'


# ============================================================
# Database helpers
# ============================================================
def db_read(db_path, key):
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path), timeout=10)
    row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
    conn.close()
    return row[0] if row else None

def db_write(db_path, key, value):
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (key, value))
    conn.commit()
    conn.close()
    return True

def db_write_multi(db_path, kv_pairs):
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    n = 0
    for k, v in kv_pairs.items():
        conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (k, v))
        n += 1
    conn.commit()
    conn.close()
    return n


# ============================================================
# Step 0: Diagnose
# ============================================================
def diagnose():
    """Full diagnostic of both users' Windsurf state"""
    print("\n" + "="*60)
    print("  DIAGNOSE — 望闻问切")
    print("="*60)
    
    for user in [SOURCE_USER, TARGET_USER]:
        db = get_db_path(user)
        sj = get_storage_json_path(user)
        print(f"\n  [{user}]")
        
        # Auth status
        raw = db_read(db, 'windsurfAuthStatus')
        if raw:
            try:
                d = json.loads(raw)
                if d is None:
                    print(f"    windsurfAuthStatus: null (BROKEN)")
                elif isinstance(d, dict):
                    ak = d.get('apiKey', '')
                    print(f"    windsurfAuthStatus: apiKey={ak[:25]}... ({len(ak)} chars)")
                    # Extract email
                    pb = d.get('userStatusProtoBinaryBase64', '')
                    if pb:
                        raw_pb = base64.b64decode(pb)
                        emails = re.findall(rb'[\w.-]+@[\w.-]+\.\w+', raw_pb[:500])
                        if emails:
                            print(f"    proto email: {emails[0].decode()}")
                else:
                    print(f"    windsurfAuthStatus: unexpected type {type(d).__name__}")
            except:
                print(f"    windsurfAuthStatus: parse error (raw len={len(str(raw))})")
        else:
            print(f"    windsurfAuthStatus: MISSING")
        
        # Plan
        plan_raw = db_read(db, 'windsurf.settings.cachedPlanInfo')
        if plan_raw:
            p = json.loads(plan_raw)
            qu = p.get('quotaUsage', {})
            print(f"    plan: {p.get('planName')} | D{qu.get('dailyRemainingPercent', '?')}% W{qu.get('weeklyRemainingPercent', '?')}%")
        else:
            print(f"    cachedPlanInfo: MISSING")
        
        # Configurations
        conf_raw = db_read(db, 'windsurfConfigurations')
        print(f"    windsurfConfigurations: {len(str(conf_raw)) if conf_raw else 0} bytes")
        
        # Machine IDs
        if sj.exists():
            sjd = json.loads(sj.read_text(encoding='utf-8'))
            mid = sjd.get('telemetry.machineId', 'NONE')
            did = sjd.get('telemetry.devDeviceId', 'NONE')
            sid = sjd.get('storage.serviceMachineId', 'NONE')
            print(f"    machineId: {mid[:20]}...")
            print(f"    devDeviceId: {did}")
            print(f"    serviceMachineId: {sid}")
        
        # Extensions  
        ext_dir = USERS[user]['appdata'] / 'extensions'
        if ext_dir.exists():
            exts = [d.name for d in ext_dir.iterdir() if d.is_dir()]
            ws_exts = [e for e in exts if 'windsurf' in e.lower() or 'assistant' in e.lower()]
            print(f"    extensions: {len(exts)} total, windsurf-related: {ws_exts or 'NONE'}")
        else:
            print(f"    extensions: directory MISSING")
        
        # cascade-auth.json
        ca = get_globalstore(user) / 'cascade-auth.json'
        if ca.exists():
            cad = json.loads(ca.read_text(encoding='utf-8'))
            tok = cad.get('authToken', '')
            prefix = tok[:10] if tok else 'NONE'
            print(f"    cascade-auth: token={prefix}... ({len(tok)} chars)")
    
    # WAM snapshots
    print(f"\n  [WAM Snapshots]")
    if SNAPSHOT_FILE.exists():
        snaps = json.loads(SNAPSHOT_FILE.read_text(encoding='utf-8'))
        emails = list(snaps.get('snapshots', {}).keys())
        print(f"    Total harvested: {len(emails)}")
        # Find ones with valid apiKey
        valid = 0
        for email, snap in snaps.get('snapshots', {}).items():
            blobs = snap.get('blobs', {})
            auth_raw = blobs.get('windsurfAuthStatus', '')
            try:
                ad = json.loads(auth_raw)
                if ad and ad.get('apiKey', ''):
                    valid += 1
            except:
                pass
        print(f"    With valid apiKey: {valid}")
    else:
        print(f"    SNAPSHOT FILE NOT FOUND")


# ============================================================
# Step 1: Inject Auth from WAM Snapshots
# ============================================================
def find_best_snapshot():
    """Find the best account snapshot to inject"""
    if not SNAPSHOT_FILE.exists():
        return None, None
    
    snaps = json.loads(SNAPSHOT_FILE.read_text(encoding='utf-8'))
    
    # Also check the login-helper accounts for quota info
    login_helper = get_globalstore(SOURCE_USER) / 'zhouyoukang.windsurf-assistant' / 'windsurf-login-accounts.json'
    accounts = {}
    if login_helper.exists():
        try:
            accs = json.loads(login_helper.read_text(encoding='utf-8'))
            for a in accs:
                accounts[a.get('email', '')] = a
        except:
            pass
    
    # Also check the flat login-accounts file
    flat_helper = get_globalstore(SOURCE_USER) / 'windsurf-login-accounts.json'
    if flat_helper.exists():
        try:
            accs = json.loads(flat_helper.read_text(encoding='utf-8'))
            for a in accs:
                if a.get('email') not in accounts:
                    accounts[a.get('email', '')] = a
        except:
            pass
    
    best_email = None
    best_score = -1
    best_snap = None
    
    for email, snap in snaps.get('snapshots', {}).items():
        blobs = snap.get('blobs', {})
        auth_raw = blobs.get('windsurfAuthStatus', '')
        try:
            ad = json.loads(auth_raw)
            if not ad or not ad.get('apiKey'):
                continue
        except:
            continue
        
        # Score based on quota from login-helper
        acc = accounts.get(email, {})
        usage = acc.get('usage', {})
        d = usage.get('daily', {})
        w = usage.get('weekly', {})
        dr = d.get('remaining', 0) if isinstance(d, dict) else 0
        wr = w.get('remaining', 0) if isinstance(w, dict) else 0
        eff = min(dr, wr)
        
        # Prefer accounts with high quota
        score = eff
        
        # Bonus for recent harvest
        harvested_at = snap.get('harvested_at', '')
        if harvested_at:
            try:
                ht = datetime.fromisoformat(harvested_at.replace('Z', '+00:00'))
                age_hours = (datetime.now(timezone.utc) - ht).total_seconds() / 3600
                if age_hours < 24:
                    score += 20
                elif age_hours < 72:
                    score += 10
            except:
                pass
        
        if score > best_score:
            best_score = score
            best_email = email
            best_snap = snap
    
    return best_email, best_snap


def inject_auth(email=None, snap=None):
    """Inject auth from WAM snapshot into target user's state.vscdb"""
    print("\n" + "="*60)
    print("  STEP 1: INJECT AUTH — 金·注入")
    print("="*60)
    
    if not email or not snap:
        email, snap = find_best_snapshot()
    
    if not email:
        print("  ❌ No valid snapshot found!")
        return False
    
    blobs = snap.get('blobs', {})
    auth_raw = blobs.get('windsurfAuthStatus', '')
    
    try:
        ad = json.loads(auth_raw)
        apikey = ad.get('apiKey', '')
        print(f"  Selected: {email}")
        print(f"  apiKey: {apikey[:25]}... ({len(apikey)} chars)")
    except:
        print(f"  ❌ Failed to parse snapshot for {email}")
        return False
    
    target_db = get_db_path(TARGET_USER)
    if not target_db.exists():
        print(f"  ❌ Target DB not found: {target_db}")
        return False
    
    # Backup first
    backup = target_db.parent / f'state.vscdb.bak_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    shutil.copy2(str(target_db), str(backup))
    print(f"  Backup: {backup.name}")
    
    # Inject all auth blobs
    kv = {}
    for key in ['windsurfAuthStatus', 'windsurfConfigurations']:
        if key in blobs:
            kv[key] = blobs[key]
    
    if not kv:
        print("  ❌ No auth blobs in snapshot")
        return False
    
    written = db_write_multi(target_db, kv)
    print(f"  ✅ Injected {written} auth keys to {TARGET_USER}'s state.vscdb")
    
    # Also inject cachedPlanInfo from source user if available
    source_db = get_db_path(SOURCE_USER)
    plan_raw = db_read(source_db, 'windsurf.settings.cachedPlanInfo')
    if plan_raw:
        db_write(target_db, 'windsurf.settings.cachedPlanInfo', plan_raw)
        print(f"  ✅ Injected cachedPlanInfo")
    
    # Update cascade-auth.json with valid apiKey
    ca_path = get_globalstore(TARGET_USER) / 'cascade-auth.json'
    wa_path = get_globalstore(TARGET_USER) / 'windsurf-auth.json'
    auth_data = {
        'authToken': apikey,
        'token': apikey,
        'api_key': apikey,
        'timestamp': int(time.time() * 1000),
    }
    for p in [ca_path, wa_path]:
        p.write_text(json.dumps(auth_data, indent=2), encoding='utf-8')
        print(f"  ✅ Updated {p.name}")
    
    return True


# ============================================================
# Step 2: Sync Machine IDs
# ============================================================
def sync_machine_ids():
    """Copy machine IDs from source user to target user"""
    print("\n" + "="*60)
    print("  STEP 2: SYNC MACHINE IDs — 水·同步")
    print("="*60)
    
    source_sj = get_storage_json_path(SOURCE_USER)
    target_sj = get_storage_json_path(TARGET_USER)
    
    if not source_sj.exists():
        print(f"  ❌ Source storage.json not found")
        return False
    if not target_sj.exists():
        print(f"  ❌ Target storage.json not found")
        return False
    
    source_data = json.loads(source_sj.read_text(encoding='utf-8'))
    target_data = json.loads(target_sj.read_text(encoding='utf-8'))
    
    # Backup target
    backup = target_sj.parent / f'storage.json.bak_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    shutil.copy2(str(target_sj), str(backup))
    print(f"  Backup: {backup.name}")
    
    # IDs to sync
    id_keys = [
        'telemetry.machineId',
        'telemetry.devDeviceId', 
        'telemetry.macMachineId',
        'telemetry.sqmId',
        'storage.serviceMachineId',
    ]
    
    synced = 0
    for key in id_keys:
        src_val = source_data.get(key)
        tgt_val = target_data.get(key)
        if src_val and src_val != tgt_val:
            target_data[key] = src_val
            synced += 1
            print(f"  {key}:")
            print(f"    {tgt_val} → {src_val}")
    
    if synced > 0:
        target_sj.write_text(json.dumps(target_data, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"  ✅ Synced {synced} machine IDs")
    else:
        print(f"  ⚡ All IDs already in sync")
    
    # Also sync in state.vscdb if present
    target_db = get_db_path(TARGET_USER)
    if target_db.exists():
        for key in id_keys:
            src_val = source_data.get(key)
            if src_val:
                db_write(target_db, key, src_val)
        print(f"  ✅ Also synced IDs in state.vscdb")
    
    return True


# ============================================================
# Step 3: Install Login Helper Extension
# ============================================================
def install_extension():
    """Copy Login Helper extension from source user to target user"""
    print("\n" + "="*60)
    print("  STEP 3: INSTALL EXTENSION — 木·生长")
    print("="*60)
    
    source_ext = USERS[SOURCE_USER]['appdata'] / 'extensions'
    target_ext = USERS[TARGET_USER]['appdata'] / 'extensions'
    
    if not source_ext.exists():
        print(f"  ❌ Source extensions dir not found")
        return False
    
    target_ext.mkdir(parents=True, exist_ok=True)
    
    # Find windsurf-related extensions in source
    copied = 0
    for ext_dir in source_ext.iterdir():
        if not ext_dir.is_dir():
            continue
        name = ext_dir.name.lower()
        if any(kw in name for kw in ['windsurf', 'assistant', 'login-helper', 'pool-admin']):
            target_path = target_ext / ext_dir.name
            if target_path.exists():
                print(f"  ⚡ Already exists: {ext_dir.name}")
            else:
                shutil.copytree(str(ext_dir), str(target_path))
                copied += 1
                print(f"  ✅ Copied: {ext_dir.name}")
    
    if copied == 0:
        print(f"  No new extensions to copy")
    
    # Also copy login accounts data
    source_gs = get_globalstore(SOURCE_USER)
    target_gs = get_globalstore(TARGET_USER)
    
    # Copy windsurf-assistant extension data
    for subdir in ['zhouyoukang.windsurf-assistant']:
        src = source_gs / subdir
        dst = target_gs / subdir
        if src.exists() and src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                if f.is_file():
                    target_f = dst / f.name
                    shutil.copy2(str(f), str(target_f))
                    print(f"  ✅ Synced data: {subdir}/{f.name}")
    
    # Copy flat account files
    for fname in ['windsurf-login-accounts.json', 'windsurf-assistant-accounts.json']:
        src = source_gs / fname
        dst = target_gs / fname
        if src.exists():
            shutil.copy2(str(src), str(dst))
            print(f"  ✅ Synced: {fname}")
    
    return True


# ============================================================
# Step 4: Fix Stale Auth Files
# ============================================================
def fix_stale_auth():
    """Clean up stale one-time tokens and auth inconsistencies"""
    print("\n" + "="*60)
    print("  STEP 4: FIX STALE AUTH — 火·净化")
    print("="*60)
    
    target_gs = get_globalstore(TARGET_USER)
    
    # Check if cascade-auth.json has ott$ token (one-time token = stale)
    for fname in ['cascade-auth.json', 'windsurf-auth.json']:
        fpath = target_gs / fname
        if fpath.exists():
            try:
                data = json.loads(fpath.read_text(encoding='utf-8'))
                token = data.get('authToken', '') or data.get('token', '')
                if token.startswith('ott$'):
                    print(f"  ⚠️  {fname}: one-time token detected (ott$)")
                    # This was already fixed in inject_auth, verify
                    if token.startswith('sk-ws'):
                        print(f"    ✅ Already replaced with valid apiKey")
                    else:
                        print(f"    ℹ️  Will be fixed by auth injection")
                elif token.startswith('sk-ws'):
                    print(f"  ✅ {fname}: valid apiKey present")
                else:
                    print(f"  ⚠️  {fname}: unknown token format: {token[:20]}...")
            except:
                print(f"  ⚠️  {fname}: parse error")
    
    # Clear token cache if stale
    tc = target_gs / 'windsurf-token-cache.json'
    if tc.exists():
        content = tc.read_text(encoding='utf-8').strip()
        if content in ['{}', '[]', '', '""']:
            print(f"  ✅ token-cache: empty (ok)")
        else:
            tc.write_text('{}', encoding='utf-8')
            print(f"  ✅ Cleared stale token cache")
    
    # Clean up WAL files (force checkpoint)
    target_db = get_db_path(TARGET_USER)
    if target_db.exists():
        try:
            conn = sqlite3.connect(str(target_db), timeout=10)
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            conn.close()
            print(f"  ✅ WAL checkpoint completed")
        except Exception as e:
            print(f"  ⚠️  WAL checkpoint failed: {e}")
    
    return True


# ============================================================
# Step 5: Verify
# ============================================================
def verify():
    """Verify the fix was applied correctly"""
    print("\n" + "="*60)
    print("  VERIFY — 验·证")
    print("="*60)
    
    target_db = get_db_path(TARGET_USER)
    all_good = True
    
    # 1. windsurfAuthStatus
    raw = db_read(target_db, 'windsurfAuthStatus')
    if raw:
        try:
            d = json.loads(raw)
            if d and isinstance(d, dict) and d.get('apiKey'):
                ak = d['apiKey']
                print(f"  ✅ windsurfAuthStatus: apiKey={ak[:25]}... ({len(ak)} chars)")
                # Extract email
                pb = d.get('userStatusProtoBinaryBase64', '')
                if pb:
                    raw_pb = base64.b64decode(pb)
                    emails = re.findall(rb'[\w.-]+@[\w.-]+\.\w+', raw_pb[:500])
                    if emails:
                        print(f"     email: {emails[0].decode()}")
            else:
                print(f"  ❌ windsurfAuthStatus: still null or no apiKey")
                all_good = False
        except:
            print(f"  ❌ windsurfAuthStatus: parse error")
            all_good = False
    else:
        print(f"  ❌ windsurfAuthStatus: MISSING")
        all_good = False
    
    # 2. cachedPlanInfo
    plan = db_read(target_db, 'windsurf.settings.cachedPlanInfo')
    if plan:
        try:
            p = json.loads(plan)
            print(f"  ✅ cachedPlanInfo: {p.get('planName')} ({p.get('billingStrategy')})")
        except:
            print(f"  ⚠️  cachedPlanInfo: present but parse error")
    else:
        print(f"  ⚠️  cachedPlanInfo: MISSING (will be populated on first server call)")
    
    # 3. windsurfConfigurations
    conf = db_read(target_db, 'windsurfConfigurations')
    if conf and len(str(conf)) > 100:
        print(f"  ✅ windsurfConfigurations: {len(str(conf))} bytes")
    else:
        print(f"  ⚠️  windsurfConfigurations: MISSING or small")
    
    # 4. Machine IDs
    source_sj = json.loads(get_storage_json_path(SOURCE_USER).read_text(encoding='utf-8'))
    target_sj = json.loads(get_storage_json_path(TARGET_USER).read_text(encoding='utf-8'))
    ids_match = True
    for key in ['telemetry.machineId', 'telemetry.devDeviceId', 'storage.serviceMachineId']:
        if source_sj.get(key) != target_sj.get(key):
            print(f"  ❌ {key}: MISMATCH")
            ids_match = False
    if ids_match:
        print(f"  ✅ Machine IDs: all synced")
    else:
        all_good = False
    
    # 5. Extensions
    target_ext = USERS[TARGET_USER]['appdata'] / 'extensions'
    if target_ext.exists():
        exts = [d.name for d in target_ext.iterdir() if d.is_dir()]
        ws_exts = [e for e in exts if 'windsurf' in e.lower() or 'assistant' in e.lower()]
        if ws_exts:
            print(f"  ✅ Extensions: {ws_exts}")
        else:
            print(f"  ⚠️  No windsurf extensions (may be inline in Windsurf install)")
    
    # 6. cascade-auth.json
    ca = get_globalstore(TARGET_USER) / 'cascade-auth.json'
    if ca.exists():
        cad = json.loads(ca.read_text(encoding='utf-8'))
        tok = cad.get('authToken', '')
        if tok.startswith('sk-ws'):
            print(f"  ✅ cascade-auth: valid apiKey")
        elif tok.startswith('ott$'):
            print(f"  ❌ cascade-auth: still has stale ott$ token")
            all_good = False
        else:
            print(f"  ⚠️  cascade-auth: token={tok[:15]}...")
    
    # 7. Login accounts
    target_gs = get_globalstore(TARGET_USER)
    for fname in ['windsurf-login-accounts.json', 'windsurf-assistant-accounts.json']:
        f = target_gs / fname
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding='utf-8'))
                count = len(data) if isinstance(data, list) else '?'
                print(f"  ✅ {fname}: {count} accounts")
            except:
                print(f"  ⚠️  {fname}: parse error")
        else:
            print(f"  ⚠️  {fname}: missing")
    
    print()
    if all_good:
        print("  🎉 ALL CHECKS PASSED — Administrator should now work!")
        print("  Next: Restart Windsurf on Administrator account to activate")
    else:
        print("  ⚠️  Some checks failed — review above and re-run fix")
    
    return all_good


# ============================================================
# Main
# ============================================================
def full_fix():
    """Execute all fix steps"""
    print("="*60)
    print("  Windsurf 跨用户修复器 — 道法自然·逆向到底")
    print(f"  {datetime.now().isoformat()}")
    print(f"  Source: {SOURCE_USER} → Target: {TARGET_USER}")
    print("="*60)
    
    # Pre-check: ensure Windsurf is not running on target account
    # (We can still write to DB while it's running via WAL mode,
    #  but machine ID changes in storage.json need a restart)
    
    diagnose()
    
    ok1 = inject_auth()
    ok2 = sync_machine_ids()
    ok3 = install_extension()
    ok4 = fix_stale_auth()
    
    print("\n" + "="*60)
    print("  RESULT SUMMARY")
    print("="*60)
    print(f"  Auth injection:    {'✅' if ok1 else '❌'}")
    print(f"  Machine ID sync:   {'✅' if ok2 else '❌'}")
    print(f"  Extension install: {'✅' if ok3 else '❌'}")
    print(f"  Stale auth fix:    {'✅' if ok4 else '❌'}")
    
    verify()


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'full'
    
    if cmd == 'diagnose':
        diagnose()
    elif cmd == 'inject':
        inject_auth()
    elif cmd == 'sync-ids':
        sync_machine_ids()
    elif cmd == 'install-ext':
        install_extension()
    elif cmd == 'verify':
        verify()
    elif cmd in ('full', 'fix'):
        full_fix()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python _cross_user_fix.py [diagnose|inject|sync-ids|install-ext|verify|full]")
