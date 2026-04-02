#!/usr/bin/env python3
"""本地Windsurf全面诊断 — 账号/补丁/checksum状态"""
import sqlite3, json, os, hashlib, base64, subprocess
from pathlib import Path

user = os.environ.get('USERNAME', 'ai')
print(f"=== 本地诊断 | user={user} ===\n")

# 1. Auth state
db_path = Path(f'C:/Users/{user}/AppData/Roaming/Windsurf/User/globalStorage/state.vscdb')
print(f"[1] state.vscdb: {db_path}")
print(f"    exists: {db_path.exists()}")

if db_path.exists():
    c = sqlite3.connect(str(db_path), timeout=5)
    rows = c.execute("SELECT key, length(value) FROM ItemTable WHERE key LIKE 'windsurf%' OR key LIKE 'codeium%' OR key LIKE 'cached%'").fetchall()
    print(f"    keys ({len(rows)}):", [k for k,v in rows])
    
    row = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
    if row:
        a = json.loads(row[0])
        print(f"    keys in auth: {list(a.keys())}")
        print(f"    email: {a.get('email') or a.get('user_email') or a.get('username') or '?'}")
        print(f"    isSignedIn: {a.get('isSignedIn')}")
        ak = a.get('apiKey','')
        print(f"    apiKey: {ak[:50]}... ({len(ak)} chars)")
        print(f"    AUTH_STATE: {'VALID' if len(ak) > 20 else 'BROKEN'}")
    else:
        print("    AUTH_STATUS: NULL")
    
    row2 = c.execute("SELECT value FROM ItemTable WHERE key='cachedPlanInfo'").fetchone()
    if row2:
        try:
            p = json.loads(row2[0])
            print(f"    plan: {p.get('name') or p.get('planName') or str(p)[:80]}")
        except:
            print(f"    cachedPlanInfo: {str(row2[0])[:80]}")
    c.close()

# 2. Workbench patch status
print("\n[2] Workbench.js 补丁状态")
wb_candidates = [
    r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js',
    Path(f'C:/Users/{user}/AppData/Local/Programs/Windsurf/resources/app/out/vs/workbench/workbench.desktop.main.js'),
]
wb = None
for p in wb_candidates:
    if Path(p).exists():
        wb = Path(p)
        break

if wb:
    print(f"    path: {wb}")
    data = wb.read_bytes()
    print(f"    size: {len(data):,} bytes")
    
    patches = {
        '__wamRateLimit': b'__wamRateLimit',
        'errorCodePrefix=""': b'errorCodePrefix=""',
        'maxGenerationTokens=9999': b'maxGenerationTokens=9999',
        'GBe_patch_v4': b'errorParts:[]',
    }
    for name, marker in patches.items():
        found = marker in data
        print(f"    {name}: {'✓' if found else '✗'}")
    
    # Checksum
    digest = hashlib.sha256(data).digest()
    b64h = base64.b64encode(digest).decode().rstrip('=')
    prod = wb.parent.parent.parent.parent / 'product.json'
    if prod.exists():
        pj = json.loads(prod.read_text(encoding='utf-8'))
        stored = pj.get('checksums', {}).get('vs/workbench/workbench.desktop.main.js', 'MISSING')
        match = (stored == b64h)
        print(f"    checksum_match: {'✓' if match else '✗ NEEDS FIX'}")
else:
    print("    WB: NOT FOUND")

# 3. Windsurf process count
print("\n[3] Windsurf进程")
try:
    r = subprocess.run(['powershell','-NoProfile','-Command','(Get-Process Windsurf -EA SilentlyContinue).Count'],
                       capture_output=True, text=True, timeout=10)
    cnt = r.stdout.strip()
    print(f"    processes: {cnt}")
except Exception as e:
    print(f"    error: {e}")

print("\n=== 诊断完成 ===")
