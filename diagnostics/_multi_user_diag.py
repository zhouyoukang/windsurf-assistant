#!/usr/bin/env python3
"""
Multi-User Windsurf Diagnostics — 逆向到底
诊断两个Windows账户(ai / Administrator)的Windsurf配置差异
"""

import sqlite3, json, os, sys, subprocess, base64, re
from pathlib import Path
from datetime import datetime

USERS = {
    'ai': Path(r'C:\Users\ai\AppData\Roaming\Windsurf'),
    'Administrator': Path(r'C:\Users\Administrator\AppData\Roaming\Windsurf'),
}

WS_INSTALL = Path(r'D:\Windsurf')

def read_db_keys(db_path, pattern_keywords):
    """Read keys from state.vscdb matching keywords"""
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(str(db_path), timeout=5)
    result = {}
    for kw in pattern_keywords:
        rows = conn.execute(
            "SELECT key FROM ItemTable WHERE key LIKE ?", (f'%{kw}%',)
        ).fetchall()
        for r in rows:
            result[r[0]] = True
    conn.close()
    return sorted(result.keys())

def read_db_value(db_path, key):
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else None
    except:
        return None

def read_all_windsurf_keys(db_path):
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path), timeout=5)
    rows = conn.execute(
        "SELECT key FROM ItemTable WHERE key LIKE '%windsurf%' OR key LIKE '%auth%' "
        "OR key LIKE '%machine%' OR key LIKE '%device%' OR key LIKE '%fingerprint%' "
        "OR key LIKE '%telemetry%' OR key LIKE '%credential%' OR key LIKE '%token%' "
        "OR key LIKE '%codeium%' OR key LIKE '%cascade%'"
    ).fetchall()
    conn.close()
    return sorted(set(r[0] for r in rows))

def check_credential_manager(user_label):
    """Check Windows Credential Manager for Windsurf entries"""
    try:
        r = subprocess.run(
            ['cmdkey', '/list'],
            capture_output=True, text=True, timeout=10, encoding='gbk', errors='replace'
        )
        lines = r.stdout.split('\n')
        ws_entries = [l.strip() for l in lines if 'windsurf' in l.lower() or 'codeium' in l.lower()]
        return ws_entries
    except:
        return []

def check_extensions(ws_appdata):
    """Check installed extensions"""
    ext_dir = ws_appdata / 'extensions'
    if not ext_dir.exists():
        return []
    return sorted([d.name for d in ext_dir.iterdir() if d.is_dir()])

def check_storage_json(ws_appdata):
    """Read storage.json for key config"""
    p = ws_appdata / 'User' / 'globalStorage' / 'storage.json'
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except:
        return None

def check_cascade_auth(ws_appdata):
    """Check cascade-auth.json"""
    p = ws_appdata / 'User' / 'globalStorage' / 'cascade-auth.json'
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except:
        return None

def check_windsurf_auth_json(ws_appdata):
    """Check windsurf-auth.json"""
    p = ws_appdata / 'User' / 'globalStorage' / 'windsurf-auth.json'
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except:
        return None

def check_login_helper_accounts(ws_appdata):
    """Check login helper account files"""
    gs = ws_appdata / 'User' / 'globalStorage'
    files = [
        gs / 'zhouyoukang.windsurf-assistant' / 'windsurf-login-accounts.json',
        gs / 'windsurf-login-accounts.json',
        gs / 'windsurf-assistant-accounts.json',
    ]
    result = {}
    for f in files:
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding='utf-8'))
                count = len(data) if isinstance(data, list) else 'non-list'
                result[f.name] = {'exists': True, 'count': count, 'size': f.stat().st_size}
            except:
                result[f.name] = {'exists': True, 'error': 'parse_failed'}
        else:
            result[f.name] = {'exists': False}
    return result

def extract_auth_status(db_path):
    """Extract windsurfAuthStatus summary"""
    raw = read_db_value(db_path, 'windsurfAuthStatus')
    if not raw:
        return None
    try:
        d = json.loads(raw)
        api_key = d.get('apiKey', '')
        proto_b64 = d.get('userStatusProtoBinaryBase64', '')
        # Extract email from proto
        email = None
        if proto_b64:
            proto_raw = base64.b64decode(proto_b64)
            emails = re.findall(rb'[\w.-]+@[\w.-]+\.\w+', proto_raw[:500])
            if emails:
                email = emails[0].decode()
        return {
            'apiKey_prefix': api_key[:20] + '...' if api_key else 'NONE',
            'apiKey_length': len(api_key),
            'has_proto': bool(proto_b64),
            'proto_size': len(proto_b64) if proto_b64 else 0,
            'email': email,
            'num_command_models': len(d.get('allowedCommandModelConfigsProtoBinaryBase64', [])),
        }
    except Exception as e:
        return {'error': str(e)}

def extract_cached_plan(db_path):
    """Extract cached plan info"""
    raw = read_db_value(db_path, 'windsurf.settings.cachedPlanInfo')
    if not raw:
        return None
    try:
        return json.loads(raw)
    except:
        return None

def check_machine_id(db_path):
    """Check machine/device identifiers"""
    keys = [
        'telemetry.machineId',
        'telemetry.macMachineId', 
        'telemetry.devDeviceId',
        'telemetry.sqmId',
        'storage.serviceMachineId',
    ]
    result = {}
    for k in keys:
        v = read_db_value(db_path, k)
        if v:
            result[k] = v[:40] + ('...' if len(str(v)) > 40 else '')
    return result

def check_electron_safe_storage():
    """Check if Electron safeStorage (DPAPI) is accessible"""
    # This is per-Windows-user - DPAPI keys are tied to user SID
    return "DPAPI is per-Windows-user: credentials encrypted by one user CANNOT be decrypted by another"

# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    print("=" * 70)
    print("Windsurf Multi-User Diagnostics — 逆向到底")
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Current User: {os.environ.get('USERNAME', '?')}")
    print("=" * 70)
    
    report = {'_meta': {'timestamp': datetime.now().isoformat(), 'current_user': os.environ.get('USERNAME')}}
    
    # 1. Per-user analysis
    for user, ws_path in USERS.items():
        print(f"\n{'='*50}")
        print(f"  USER: {user}")
        print(f"  Path: {ws_path}")
        print(f"{'='*50}")
        
        user_report = {}
        db = ws_path / 'User' / 'globalStorage' / 'state.vscdb'
        
        # 1a. Basic structure
        gs = ws_path / 'User' / 'globalStorage'
        if gs.exists():
            items = list(gs.iterdir())
            print(f"\n  [GlobalStorage] {len(items)} items")
        else:
            print(f"\n  [GlobalStorage] DOES NOT EXIST")
            continue
        
        # 1b. All windsurf-related DB keys
        print(f"\n  [DB Keys]")
        all_keys = read_all_windsurf_keys(db)
        for k in all_keys:
            print(f"    {k}")
        user_report['db_keys'] = all_keys
        
        # 1c. Auth status
        print(f"\n  [Auth Status]")
        auth = extract_auth_status(db)
        if auth:
            for k, v in auth.items():
                print(f"    {k}: {v}")
        else:
            print("    NO AUTH STATUS!")
        user_report['auth_status'] = auth
        
        # 1d. Cached plan
        print(f"\n  [Cached Plan]")
        plan = extract_cached_plan(db)
        if plan:
            print(f"    planName: {plan.get('planName', '?')}")
            print(f"    billingStrategy: {plan.get('billingStrategy', '?')}")
            usage = plan.get('usage', {})
            print(f"    remaining: {usage.get('remainingMessages', '?')}")
            quota = plan.get('quotaUsage', {})
            if quota:
                print(f"    dailyRemaining: {quota.get('dailyRemainingPercent', '?')}%")
                print(f"    weeklyRemaining: {quota.get('weeklyRemainingPercent', '?')}%")
        else:
            print("    NO CACHED PLAN!")
        user_report['cached_plan'] = plan
        
        # 1e. Machine IDs
        print(f"\n  [Machine IDs]")
        mids = check_machine_id(db)
        for k, v in mids.items():
            print(f"    {k}: {v}")
        user_report['machine_ids'] = mids
        
        # 1f. storage.json
        print(f"\n  [storage.json]")
        sj = check_storage_json(ws_path)
        if sj:
            interesting = {k: v for k, v in sj.items() 
                         if any(x in k.lower() for x in ['machine', 'telemetry', 'auth', 'windsurf', 'device'])}
            for k, v in interesting.items():
                val = str(v)[:60]
                print(f"    {k}: {val}")
        user_report['storage_json_keys'] = list(sj.keys()) if sj else None
        
        # 1g. cascade-auth.json
        print(f"\n  [cascade-auth.json]")
        ca = check_cascade_auth(ws_path)
        if ca:
            for k, v in ca.items():
                print(f"    {k}: {str(v)[:60]}")
        else:
            print("    NOT FOUND or empty")
        user_report['cascade_auth'] = ca
        
        # 1h. windsurf-auth.json
        print(f"\n  [windsurf-auth.json]")
        wa = check_windsurf_auth_json(ws_path)
        if wa:
            for k, v in wa.items():
                print(f"    {k}: {str(v)[:60]}")
        else:
            print("    NOT FOUND or empty")
        user_report['windsurf_auth'] = wa
        
        # 1i. Login Helper accounts
        print(f"\n  [Login Helper Accounts]")
        lha = check_login_helper_accounts(ws_path)
        for fname, info in lha.items():
            print(f"    {fname}: {info}")
        user_report['login_helper'] = lha
        
        # 1j. Extensions
        print(f"\n  [Extensions]")
        exts = check_extensions(ws_path)
        ws_exts = [e for e in exts if 'windsurf' in e.lower() or 'assistant' in e.lower() or 'login' in e.lower()]
        for e in ws_exts:
            print(f"    {e}")
        print(f"    (total extensions: {len(exts)})")
        user_report['extensions'] = ws_exts
        
        report[user] = user_report
    
    # 2. Cross-user comparison
    print(f"\n{'='*70}")
    print("  CROSS-USER COMPARISON")
    print(f"{'='*70}")
    
    # 2a. Machine ID comparison
    print(f"\n  [Machine ID Comparison]")
    for key in ['telemetry.machineId', 'telemetry.devDeviceId', 'storage.serviceMachineId']:
        vals = {}
        for user, ws_path in USERS.items():
            db = ws_path / 'User' / 'globalStorage' / 'state.vscdb'
            v = read_db_value(db, key)
            vals[user] = str(v)[:40] if v else 'NONE'
        same = vals.get('ai') == vals.get('Administrator') and vals.get('ai') != 'NONE'
        print(f"    {key}:")
        for u, v in vals.items():
            print(f"      {u}: {v}")
        print(f"      SAME: {same}")
    
    # 2b. DPAPI / Credential isolation
    print(f"\n  [DPAPI / Credential Isolation]")
    print(f"    {check_electron_safe_storage()}")
    
    # 2c. Credential Manager
    print(f"\n  [Windows Credential Manager (current user: {os.environ.get('USERNAME')})]")
    creds = check_credential_manager(os.environ.get('USERNAME'))
    if creds:
        for c in creds:
            print(f"    {c}")
    else:
        print("    No Windsurf/Codeium entries found")
    
    # 3. Root cause analysis
    print(f"\n{'='*70}")
    print("  ROOT CAUSE ANALYSIS")
    print(f"{'='*70}")
    
    issues = []
    
    # Check auth status for both users
    for user, ws_path in USERS.items():
        db = ws_path / 'User' / 'globalStorage' / 'state.vscdb'
        auth = extract_auth_status(db)
        if not auth or auth.get('error'):
            issues.append(f"[{user}] NO AUTH: windsurfAuthStatus missing or corrupted")
        elif auth.get('apiKey_length', 0) < 10:
            issues.append(f"[{user}] EMPTY API KEY: apiKey too short ({auth.get('apiKey_length')})")
        
        plan = extract_cached_plan(db)
        if not plan:
            issues.append(f"[{user}] NO PLAN: cachedPlanInfo missing")
    
    # Check if snapshot file is accessible
    snap_file = Path(r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\_wam_snapshots.json')
    if snap_file.exists():
        print(f"\n  [Snapshot File] {snap_file} EXISTS ({snap_file.stat().st_size} bytes)")
        try:
            snaps = json.loads(snap_file.read_text(encoding='utf-8'))
            emails = list(snaps.get('snapshots', {}).keys())
            print(f"    Harvested accounts: {len(emails)}")
            for e in emails[:10]:
                print(f"      {e}")
        except:
            print("    Parse error")
    else:
        issues.append("SNAPSHOT FILE NOT FOUND")
    
    if issues:
        print(f"\n  [Issues Found]")
        for i, issue in enumerate(issues):
            print(f"    {i+1}. {issue}")
    else:
        print(f"\n  No critical issues found in DB state")
    
    # 4. Key insight
    print(f"\n{'='*70}")
    print("  KEY INSIGHTS — 道法自然")
    print(f"{'='*70}")
    print("""
  Windsurf auth chain (per Windows user):
    1. Electron safeStorage (DPAPI) → encrypts refresh token
       → DPAPI master key is per-Windows-user SID
       → Token encrypted by 'ai' CANNOT be decrypted by 'Administrator'
    
    2. state.vscdb → stores windsurfAuthStatus (apiKey, protobuf)
       → Per-user at %APPDATA%\\Windsurf\\...
       → WAM can write to it, but apiKey validity depends on server
    
    3. Windows Credential Manager → may store OAuth tokens
       → Also per-user (DPAPI encrypted)
    
    4. storage.json → machine telemetry IDs
       → Per-user but IDs may differ → fingerprint mismatch
    
  ROOT CAUSE HYPOTHESIS:
    When 'Administrator' starts Windsurf:
    a) Electron tries to read safeStorage → DPAPI decryption fails silently
    b) No valid refresh token → can't auto-login
    c) Manual login may work but token storage fails again
    d) Machine IDs may differ → server sees different device
    e) Login Helper extension may not be installed/configured
    """)
    
    # Save report
    out = Path(__file__).parent / '_multi_user_diag_report.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Report saved to: {out}")
