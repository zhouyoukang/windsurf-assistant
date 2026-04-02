#!/usr/bin/env python3
"""
跨用户同步桥接 — 道法自然
===========================
持续同步Windsurf认证数据到所有Windows用户账号。

核心原理:
  windsurfAuthStatus 是纯JSON存储在SQLite中（非DPAPI加密）
  → 可以直接跨用户读写
  → 每次ai用户切号后，自动同步到Administrator

用法:
  python _cross_user_bridge.py              # 单次同步
  python _cross_user_bridge.py daemon       # 持续监控同步
  python _cross_user_bridge.py install      # 安装Windows计划任务
"""

import sqlite3, json, os, sys, shutil, time
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent

# ============================================================
# User Configuration
# ============================================================
USERS = {
    'ai': {
        'appdata': Path(r'C:\Users\ai\AppData\Roaming\Windsurf'),
        'home': Path(r'C:\Users\ai'),
    },
    'Administrator': {
        'appdata': Path(r'C:\Users\Administrator\AppData\Roaming\Windsurf'),
        'home': Path(r'C:\Users\Administrator'),
    },
    'zhouyoukang': {
        'appdata': Path(r'C:\Users\zhouyoukang\AppData\Roaming\Windsurf'),
        'home': Path(r'C:\Users\zhouyoukang'),
    },
}

# Auth keys to sync between users
# v2.0 道之修正: 停止同步windsurfAuthStatus/windsurfConfigurations/cachedPlanInfo
# 根因: 这些key包含活跃apiKey, 每30s同步会覆盖WAM在Administrator上的切号结果
# 仅在null-auth恢复时才写入这些key (见recover_null_auth)
AUTH_KEYS = []  # 不再主动同步auth状态 — WAM各自独立管理

# Account data files to sync (account POOL only — credentials, not active session)
ACCOUNT_FILES = [
    'windsurf-login-accounts.json',
    'windsurf-assistant-accounts.json',
]

# Auth JSON files — 不再同步 (会覆盖WAM切号后写入的auth文件)
AUTH_FILES = []  # v2.0: 停止同步, WAM独立管理

SYNC_INTERVAL = 30  # seconds for daemon mode
RECOVERY_CHECK_INTERVAL = 10  # seconds for null-auth recovery check

# WAM switch lock file — WAM切号时写入, bridge检查后暂跳过auth sync
WAM_LOCK_TTL = 120  # seconds: if lock is newer than this, skip auth sync for that user


def is_wam_switching(user):
    """Check if WAM is actively switching accounts for this user.
    Returns True if ~/.wam-hot/.wam_switching is present and < WAM_LOCK_TTL seconds old."""
    try:
        lock_path = Path(USERS[user]['home']) / '.wam-hot' / '.wam_switching'
        if not lock_path.exists():
            return False
        age = time.time() - lock_path.stat().st_mtime
        return age < WAM_LOCK_TTL
    except:
        return False

# _pool_apikey.txt paths — extension.js hot_patch reads apiKey from here
POOL_KEY_FILES = {
    user: USERS[user]['appdata'] / '_pool_apikey.txt'
    for user in USERS
}
SNAPSHOT_FILE = SCRIPT_DIR / '_wam_snapshots.json'
LOG_FILE = SCRIPT_DIR / '_cross_user_bridge.log'


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except:
        pass


def get_db(user):
    return USERS[user]['appdata'] / 'User' / 'globalStorage' / 'state.vscdb'

def get_gs(user):
    return USERS[user]['appdata'] / 'User' / 'globalStorage'


def db_read(db_path, key):
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else None
    except:
        return None

def db_write(db_path, key, value):
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=5000')
        conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (key, value))
        conn.commit()
        conn.close()
        return True
    except:
        return False


def get_active_apikey(user):
    """Get the current apiKey from a user's state.vscdb"""
    raw = db_read(get_db(user), 'windsurfAuthStatus')
    if not raw:
        return None
    try:
        d = json.loads(raw)
        if d and isinstance(d, dict):
            return d.get('apiKey', '')
    except:
        pass
    return None


def sync_auth_to_user(source, target):
    """Sync auth DB keys from source user to target user. Returns count of synced keys.
    v2.0: AUTH_KEYS is now empty — no active auth sync.
    Only null-auth recovery (recover_null_auth) writes auth keys."""
    if not AUTH_KEYS:
        return 0  # v2.0: disabled — WAM manages auth independently per user
    src_db = get_db(source)
    tgt_db = get_db(target)
    if not src_db.exists() or not tgt_db.exists():
        return 0
    synced = 0
    for key in AUTH_KEYS:
        src_val = db_read(src_db, key)
        if not src_val:
            continue
        if key == 'windsurfAuthStatus':
            try:
                d = json.loads(src_val)
                if not d or not isinstance(d, dict) or not d.get('apiKey'):
                    continue
            except:
                continue
        tgt_val = db_read(tgt_db, key)
        if src_val != tgt_val:
            if db_write(tgt_db, key, src_val):
                synced += 1
    return synced


def sync_account_files(source, target):
    """Sync login-helper account files from source to target"""
    src_gs = get_gs(source)
    tgt_gs = get_gs(target)
    synced = 0
    
    for fname in ACCOUNT_FILES:
        src = src_gs / fname
        tgt = tgt_gs / fname
        if src.exists():
            try:
                src_data = src.read_bytes()
                tgt_data = tgt.read_bytes() if tgt.exists() else b''
                if src_data != tgt_data:
                    shutil.copy2(str(src), str(tgt))
                    synced += 1
            except:
                pass
    
    # Also sync the extension-specific account file
    src_ext = src_gs / 'zhouyoukang.windsurf-assistant'
    tgt_ext = tgt_gs / 'zhouyoukang.windsurf-assistant'
    if src_ext.exists():
        tgt_ext.mkdir(parents=True, exist_ok=True)
        for f in src_ext.iterdir():
            if f.is_file() and f.suffix == '.json':
                tgt_f = tgt_ext / f.name
                try:
                    src_data = f.read_bytes()
                    tgt_data = tgt_f.read_bytes() if tgt_f.exists() else b''
                    if src_data != tgt_data:
                        shutil.copy2(str(f), str(tgt_f))
                        synced += 1
                except:
                    pass
    
    return synced


def sync_auth_files(source, target):
    """Sync cascade-auth.json and windsurf-auth.json"""
    src_gs = get_gs(source)
    tgt_gs = get_gs(target)
    synced = 0
    
    for fname in AUTH_FILES:
        src = src_gs / fname
        tgt = tgt_gs / fname
        if src.exists():
            try:
                src_data = json.loads(src.read_text(encoding='utf-8'))
                src_token = src_data.get('authToken', '') or src_data.get('api_key', '')
                
                # Only sync if source has a valid sk-ws key (not ott$)
                if not src_token.startswith('sk-ws'):
                    continue
                
                tgt_data = json.loads(tgt.read_text(encoding='utf-8')) if tgt.exists() else {}
                tgt_token = tgt_data.get('authToken', '')
                
                if src_token != tgt_token:
                    tgt.write_text(json.dumps(src_data, indent=2), encoding='utf-8')
                    synced += 1
            except:
                pass
    
    return synced


def sync_pool_apikey(source, target):
    """[v2.0 DISABLED] Sync _pool_apikey.txt from source to target.
    Disabled: forcing same apiKey on all users defeats independent WAM switching.
    Each user's WAM manages its own pool_apikey.txt."""
    return 0  # v2.0: disabled
    # Original implementation preserved below for reference:
def _sync_pool_apikey_legacy(source, target):
    """Sync _pool_apikey.txt from source to target.
    Critical: extension.js hot_patch reads apiKey exclusively from this file.
    Without this sync, the target Windsurf uses stale/exhausted apiKey for all
    gRPC requests even when state.vscdb has fresh auth."""
    src_db = get_db(source)
    src_key = db_read(src_db, 'windsurfAuthStatus')
    if not src_key:
        return 0
    try:
        d = json.loads(src_key)
        if not d or not isinstance(d, dict):
            return 0
        apikey = d.get('apiKey', '')
        if not apikey or not apikey.startswith('sk-ws'):
            return 0
    except:
        return 0

    tgt_pf = POOL_KEY_FILES.get(target)
    if not tgt_pf:
        return 0

    # Read current target pool key
    try:
        current = tgt_pf.read_text(encoding='utf-8').strip() if tgt_pf.exists() else ''
    except:
        current = ''

    if apikey == current:
        return 0  # Already up to date

    try:
        tgt_pf.write_text(apikey, encoding='utf-8')
        # Also sync to all drive copies of the file (D: and E: use same path via APPDATA)
        return 1
    except Exception as e:
        log(f'  pool_apikey sync error: {e}')
        return 0


def sync_machine_ids(source, target):
    """[v2.0 DISABLED] Ensure machine IDs match between users.
    Disabled: WAM rotates fingerprints independently per-user before each switch.
    Syncing machine IDs overwrites WAM's rotation and breaks fingerprint isolation."""
    return 0  # v2.0: disabled
def _sync_machine_ids_legacy(source, target):
    """Ensure machine IDs match between users (legacy, disabled)"""
    src_sj = get_gs(source) / 'storage.json'
    tgt_sj = get_gs(target) / 'storage.json'
    
    if not src_sj.exists() or not tgt_sj.exists():
        return 0
    
    try:
        src_data = json.loads(src_sj.read_text(encoding='utf-8'))
        tgt_data = json.loads(tgt_sj.read_text(encoding='utf-8'))
    except:
        return 0
    
    id_keys = [
        'telemetry.machineId', 'telemetry.devDeviceId',
        'telemetry.macMachineId', 'telemetry.sqmId',
        'storage.serviceMachineId',
    ]
    
    changed = 0
    for key in id_keys:
        src_val = src_data.get(key)
        if src_val and src_val != tgt_data.get(key):
            tgt_data[key] = src_val
            changed += 1
    
    if changed > 0:
        tgt_sj.write_text(json.dumps(tgt_data, indent=2, ensure_ascii=False), encoding='utf-8')
    
    return changed


def find_freshest_source():
    """Determine which user has the canonical (authoritative) auth to sync from.

    Priority:
      1. User whose DB apiKey matches the pool_apikey.txt (pool engine's ground truth)
      2. User whose Windsurf process is currently running (active session)
      3. Fall back to newest DB mtime (original behaviour)
    This prevents ping-pong: after bridge writes to target, target's mtime becomes
    newest, causing it to be selected as source on the next cycle, overwriting source.
    """
    pool_keys = {}
    for user, pf in POOL_KEY_FILES.items():
        if pf.exists():
            try:
                pool_keys[user] = pf.read_text(encoding='utf-8').strip()
            except:
                pass

    user_keys = {}
    for user in USERS:
        raw = db_read(get_db(user), 'windsurfAuthStatus')
        if not raw:
            continue
        try:
            d = json.loads(raw)
            if d and isinstance(d, dict) and d.get('apiKey'):
                user_keys[user] = d['apiKey']
        except:
            continue

    # Priority 1: prefer user whose DB key == their own pool_apikey.txt
    # (pool_engine writes to pool_apikey.txt only for the active session user)
    for user, pk in pool_keys.items():
        if pk and user_keys.get(user) == pk:
            return user

    # Priority 2: prefer user whose DB key appears in ANY pool_apikey.txt
    for user, uk in user_keys.items():
        for pk in pool_keys.values():
            if uk and uk == pk:
                return user

    # Priority 3: fall back to DB mtime (original behaviour)
    best_user = None
    best_ts = 0
    for user in USERS:
        if user not in user_keys:
            continue
        db = get_db(user)
        if db.exists():
            mtime = db.stat().st_mtime
            if mtime > best_ts:
                best_ts = mtime
                best_user = user

    return best_user


def detect_null_auth():
    """Detect users whose windsurfAuthStatus is null (Windsurf cleared it on startup).
    Returns list of user names that need recovery.
    v2.0: Only checks users whose state.vscdb EXISTS — skips non-Windsurf users."""
    need_recovery = []
    for user in USERS:
        db = get_db(user)
        if not db.exists():
            continue  # v2.0: skip — user doesn't have Windsurf installed
        raw = db_read(db, 'windsurfAuthStatus')
        if not raw:
            need_recovery.append(user)
            continue
        try:
            d = json.loads(raw)
            if d is None or (isinstance(d, dict) and not d.get('apiKey')):
                need_recovery.append(user)
        except:
            need_recovery.append(user)
    return need_recovery


def recover_null_auth(user):
    """Recover a user's null auth by injecting from WAM snapshots.
    This handles the case where Windsurf nulls-out windsurfAuthStatus
    on startup due to DPAPI session failure."""
    if not SNAPSHOT_FILE.exists():
        log(f'  Recovery failed: no snapshot file')
        return False
    
    try:
        snaps = json.loads(SNAPSHOT_FILE.read_text(encoding='utf-8'))
    except:
        return False
    
    # Find any snapshot with a valid apiKey
    for email, snap in snaps.get('snapshots', {}).items():
        blobs = snap.get('blobs', {})
        auth_raw = blobs.get('windsurfAuthStatus', '')
        try:
            ad = json.loads(auth_raw)
            if ad and isinstance(ad, dict) and ad.get('apiKey'):
                # Inject this auth into the broken user's DB
                target_db = get_db(user)
                if not target_db.exists():
                    continue
                
                conn = sqlite3.connect(str(target_db), timeout=10)
                conn.execute('PRAGMA journal_mode=WAL')
                conn.execute('PRAGMA busy_timeout=5000')
                for k, v in blobs.items():
                    conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (k, v))
                conn.commit()
                conn.close()
                
                # Also update auth files
                gs = get_gs(user)
                apikey = ad['apiKey']
                auth_data = json.dumps({
                    'authToken': apikey, 'token': apikey,
                    'api_key': apikey, 'timestamp': int(time.time() * 1000),
                }, indent=2)
                for fname in AUTH_FILES:
                    (gs / fname).write_text(auth_data, encoding='utf-8')
                
                log(f'  ✅ Recovered {user} auth from snapshot ({email[:25]})')
                return True
        except:
            continue
    
    log(f'  ❌ No valid snapshot for recovery')
    return False


def refresh_assistant_cache():
    """Per-user: refresh the stale zhouyoukang.windsurf-assistant/windsurf-login-accounts.json
    from the user's own fresh windsurf-login-accounts.json.

    Root cause fix: pool_engine (and dao_engine patrol) used to pick the assistant-extension
    file first via _find_login_helper_json(), which had 7000+ min stale data, causing it to
    pick an exhausted account. By keeping the assistant file in sync with the fresh file,
    we ensure ANY fallback path also sees current quota data.
    """
    import time as _t
    STALE_THRESHOLD_MIN = 120  # refresh if more than 2 hours stale
    synced = 0
    for user, info in USERS.items():
        gs = info['appdata'] / 'User' / 'globalStorage'
        fresh_f = gs / 'windsurf-login-accounts.json'
        stale_f = gs / 'zhouyoukang.windsurf-assistant' / 'windsurf-login-accounts.json'
        if not fresh_f.exists():
            continue
        try:
            fresh_data = json.loads(fresh_f.read_text(encoding='utf-8'))
            if not isinstance(fresh_data, list) or not fresh_data:
                continue
            # Check freshness of fresh file
            lcs = [a.get('usage', {}).get('lastChecked', 0) for a in fresh_data
                   if isinstance(a.get('usage'), dict)]
            max_lc = max(lcs) if lcs else 0
            age_min = (_t.time() * 1000 - max_lc) / 60000 if max_lc else 9999
            if age_min > STALE_THRESHOLD_MIN:
                continue  # fresh file itself is stale, don't copy stale→stale

            # Check if assistant file needs update
            if stale_f.exists():
                try:
                    stale_data = json.loads(stale_f.read_text(encoding='utf-8'))
                    stale_lcs = [a.get('usage', {}).get('lastChecked', 0)
                                 for a in stale_data if isinstance(a.get('usage'), dict)]
                    stale_age = (_t.time() * 1000 - max(stale_lcs)) / 60000 if stale_lcs else 9999
                    if stale_age <= STALE_THRESHOLD_MIN:
                        continue  # already fresh enough
                except Exception:
                    pass  # re-write if unreadable

            # Overwrite stale file with fresh data
            stale_f.parent.mkdir(parents=True, exist_ok=True)
            stale_f.write_bytes(fresh_f.read_bytes())
            synced += 1
        except Exception:
            pass
    if synced > 0:
        log(f'  assistant cache refreshed for {synced} user(s)')
    return synced


# ============================================================
# One-shot sync
# ============================================================
def sync_once():
    """Run one sync cycle: find freshest source, sync to all others"""
    source = find_freshest_source()
    if not source:
        log('⚠️  No user has valid auth — cannot sync')
        return False
    
    src_ak = get_active_apikey(source)
    log(f'Source: {source} (apiKey={src_ak[:20]}...)')
    
    # Refresh stale assistant cache files (per-user, independently of source/target)
    refresh_assistant_cache()

    total_synced = 0
    for target in USERS:
        if target == source:
            continue

        # v2.0: Skip if WAM is actively switching on target user
        if is_wam_switching(target):
            log(f'  → {target}: WAM switching in progress — skipping auth sync (lock < {WAM_LOCK_TTL}s)')
            continue

        # v2.0: Only sync account pool files (credentials list)
        # auth/fingerprint/pool_apikey sync removed — WAM manages these independently
        n_auth = 0  # disabled
        n_files = sync_account_files(source, target)
        n_auth_files = 0  # disabled
        n_ids = 0  # disabled
        n_pool_key = 0  # disabled

        total = n_auth + n_files + n_auth_files + n_ids + n_pool_key
        if total > 0:
            log(f'  → {target}: accounts={n_files} (auth/ids/pool_key sync disabled in v2.0)')
            total_synced += total
        else:
            log(f'  → {target}: accounts in sync ✅')

    return total_synced > 0


# ============================================================
# Daemon mode
# ============================================================
def daemon():
    """Persistent sync daemon — poll, sync, and auto-recover
    v2.0: auth/fingerprint/pool_apikey sync disabled — WAM manages these independently per user.
    Only syncs account pool JSON files + null-auth recovery."""
    log(f'Bridge daemon v2.0 started (sync={SYNC_INTERVAL}s, recovery={RECOVERY_CHECK_INTERVAL}s)')
    log(f'v2.0 mode: account pool sync only — auth/fingerprint/pool_apikey sync DISABLED')
    last_recovery_check = 0
    last_pool_sync = 0

    while True:
        try:
            now = time.time()

            # 1. Account pool sync (periodic, not triggered by auth change)
            if now - last_pool_sync >= SYNC_INTERVAL:
                sync_once()  # only syncs account pool files now
                last_pool_sync = now

            # 2. Null-auth recovery (more frequent check)
            if now - last_recovery_check >= RECOVERY_CHECK_INTERVAL:
                broken = detect_null_auth()
                if broken:
                    for user in broken:
                        # Skip recovery if WAM is actively switching
                        if is_wam_switching(user):
                            log(f'  ⚡ Null auth on {user} but WAM switching — will retry next cycle')
                            continue
                        log(f'⚡ Null auth detected on {user} — auto-recovering...')
                        recover_null_auth(user)
                last_recovery_check = now

            time.sleep(min(SYNC_INTERVAL, RECOVERY_CHECK_INTERVAL))
        except KeyboardInterrupt:
            log('Daemon stopped')
            break
        except Exception as e:
            log(f'Error: {e}')
            time.sleep(SYNC_INTERVAL)


# ============================================================
# Install as scheduled task
# ============================================================
def install_task():
    """Install Windows Scheduled Task for periodic sync"""
    import subprocess
    
    pythonw = Path(sys.executable).parent / 'pythonw.exe'
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    
    script = Path(__file__).resolve()
    task_name = "WindsurfCrossUserBridge"
    
    task_xml = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Windsurf Cross-User Auth Bridge — 跨用户认证同步</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled></LogonTrigger>
    <TimeTrigger>
      <Repetition>
        <Interval>PT3M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>2026-01-01T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT1M</ExecutionTimeLimit>
    <Hidden>true</Hidden>
  </Settings>
  <Actions>
    <Exec>
      <Command>{pythonw}</Command>
      <Arguments>"{script}"</Arguments>
      <WorkingDirectory>{SCRIPT_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>'''
    
    task_file = SCRIPT_DIR / '_cross_user_bridge_task.xml'
    task_file.write_text(task_xml, encoding='utf-16')
    
    r = subprocess.run(
        ["schtasks", "/Create", "/TN", task_name, "/XML", str(task_file), "/F"],
        capture_output=True, encoding='gbk', errors='replace',
    )
    task_file.unlink(missing_ok=True)
    
    if r.returncode == 0:
        log(f'✅ Task installed: {task_name} (every 3 min + logon)')
    else:
        log(f'⚠️  Task install failed: {r.stderr.strip()}')
    
    return r.returncode == 0


# ============================================================
# Main
# ============================================================
if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'sync'
    
    if cmd == 'daemon':
        daemon()
    elif cmd == 'install':
        install_task()
    elif cmd in ('sync', 'once'):
        sync_once()
    else:
        print(f"Usage: python _cross_user_bridge.py [sync|daemon|install]")
