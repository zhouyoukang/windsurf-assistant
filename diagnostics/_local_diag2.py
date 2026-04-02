# -*- coding: utf-8 -*-
"""本地Windsurf全面诊断 v2 (GBK-safe)"""
import sqlite3, json, os, hashlib, base64, subprocess, sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

user = os.environ.get('USERNAME', 'ai')
print("=== Local Windsurf Diag | user=" + user + " ===\n")

# 1. Auth state
db_path = Path('C:/Users/' + user + '/AppData/Roaming/Windsurf/User/globalStorage/state.vscdb')
print("[1] Auth State:", str(db_path))

if db_path.exists():
    c = sqlite3.connect(str(db_path), timeout=5)
    
    row = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
    if row:
        a = json.loads(row[0])
        ak = a.get('apiKey','')
        print("    auth_format:", list(a.keys()))
        print("    apiKey:", ak[:50] + "... (" + str(len(ak)) + " chars)")
        print("    AUTH_STATE:", "VALID" if len(ak) > 20 else "BROKEN")
    else:
        print("    AUTH_STATUS: NULL -> NEEDS INJECTION")
    
    # Count WAM multi-account entries
    wam_rows = c.execute("SELECT count(*) FROM ItemTable WHERE key LIKE 'windsurf_auth-%'").fetchone()
    print("    WAM multi-accounts:", wam_rows[0], "usage trackers")
    
    row2 = c.execute("SELECT value FROM ItemTable WHERE key='cachedPlanInfo'").fetchone()
    print("    cachedPlanInfo:", "present" if row2 else "NULL")
    c.close()
else:
    print("    DB NOT FOUND")

# 2. Workbench patches
print("\n[2] Workbench.js Patches")
wb_candidates = [
    r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js',
]
wb = None
for p in wb_candidates:
    if Path(p).exists():
        wb = Path(p)
        break
if not wb:
    print("    WB: NOT FOUND")
else:
    print("    path:", wb)
    data = wb.read_bytes()
    print("    size:", f"{len(data):,}", "bytes")
    
    patches = [
        ('__wamRateLimit signal',   b'__wamRateLimit'),
        ('GBe errorCodePrefix=""',  b'errorCodePrefix:""'),
        ('GBe errorParts:[]',       b'errorParts:[]'),
        ('maxGenerationTokens=9999',b'maxGenerationTokens=9999'),
        ('opus-4-6 commandModel',   b'claude-opus-4-6'),
    ]
    for name, marker in patches:
        found = marker in data
        print(f"    [{('OK' if found else 'XX')}] {name}")
    
    # Checksum
    digest = hashlib.sha256(data).digest()
    b64h = base64.b64encode(digest).decode().rstrip('=')
    prod = wb.parent.parent.parent.parent / 'product.json'
    if prod.exists():
        pj = json.loads(prod.read_text(encoding='utf-8'))
        stored = pj.get('checksums', {}).get('vs/workbench/workbench.desktop.main.js', 'MISSING')
        match = (stored == b64h)
        print("    checksum_match:", "OK" if match else "MISMATCH -> needs fix")
    
# 3. Windsurf process count
print("\n[3] Windsurf Processes")
try:
    r = subprocess.run(
        ['powershell','-NoProfile','-Command','(Get-Process Windsurf -EA SilentlyContinue).Count'],
        capture_output=True, text=True, timeout=10
    )
    print("    count:", r.stdout.strip())
except Exception as e:
    print("    error:", e)

# 4. Snapshot pool size
print("\n[4] WAM Snapshot Pool")
snap_path = Path(__file__).parent.parent / '010-dao_engine_DaoEngine' / '_wam_snapshots.json'
# Try both naming conventions
for sp in [
    Path(__file__).parent.parent / '010-道引擎_DaoEngine' / '_wam_snapshots.json',
    Path(__file__).parent.parent / '010-dao_engine_DaoEngine' / '_wam_snapshots.json',
]:
    if sp.exists():
        snap_path = sp
        break
        
if snap_path.exists():
    size_mb = snap_path.stat().st_size / 1024 / 1024
    print(f"    snapshot_file: {size_mb:.1f} MB")
    data_s = json.loads(snap_path.read_text(encoding='utf-8'))
    snaps = data_s.get('snapshots', {})
    total = len(snaps)
    valid = sum(1 for v in snaps.values() 
                if v.get('blobs',{}).get('windsurfAuthStatus'))
    print(f"    total_accounts: {total}")
    print(f"    valid_blobs: {valid}")
    print("    POOL:", "OK" if valid > 0 else "EMPTY")
else:
    print("    SNAPSHOT FILE NOT FOUND")

print("\n=== Diag Complete ===")
