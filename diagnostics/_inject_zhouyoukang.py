# -*- coding: utf-8 -*-
"""
直接注入zhouyoukang用户Windsurf账号
- 从snapshots.json选最新账号
- 写入state.vscdb (创建表如果不存在)
- 通过WinRM (PowerShell) 在zhouyoukang session执行
"""
import subprocess, json, base64, os, sys, random
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SNAPSHOT_FILE = SCRIPT_DIR.parent / '010-道引擎_DaoEngine' / '_wam_snapshots.json'
TARGET_IP   = '192.168.31.179'
TARGET_USER = 'zhouyoukang'
TARGET_PASS = 'wsy057066wsy'
SKIP_EMAILS = {'ehhs619938345@yahoo.com', 'fpzgcmcdaqbq152@yahoo.com'}

def run_winrm(py_code, timeout=60):
    b64 = base64.b64encode(py_code.encode('utf-8')).decode('ascii')
    ps = f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -ErrorAction SilentlyContinue
$b64 = "{b64}"
$bytes = [System.Convert]::FromBase64String($b64)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
$tmp = "C:\\ctemp\\ws_inject_zy"
if (-not (Test-Path $tmp)) {{ New-Item -ItemType Directory $tmp -Force | Out-Null }}
$p = "$tmp\\run.py"
[System.IO.File]::WriteAllText($p, $text, [System.Text.Encoding]::UTF8)
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock {{
    param($pyfile)
    python $pyfile 2>&1
}} -ArgumentList $p
'''
    r = subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps],
        capture_output=True, text=True, timeout=timeout,
        encoding='utf-8', errors='replace'
    )
    return (r.stdout + r.stderr).strip(), r.returncode

def run_winrm_ps(ps_cmd, timeout=30):
    ps = f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -ErrorAction SilentlyContinue
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock {{ {ps_cmd} }}
'''
    r = subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps],
        capture_output=True, text=True, timeout=timeout,
        encoding='utf-8', errors='replace'
    )
    return (r.stdout + r.stderr).strip(), r.returncode

# Step 1: Load snapshot pool
print("[1] Loading snapshot pool...")
if not SNAPSHOT_FILE.exists():
    print(f"  ERROR: {SNAPSHOT_FILE} not found")
    sys.exit(1)

with open(SNAPSHOT_FILE, 'r', encoding='utf-8') as f:
    snap_data = json.load(f)

snaps = snap_data.get('snapshots', {})
candidates = []
for email, snap in snaps.items():
    if email in SKIP_EMAILS:
        continue
    blob = snap.get('blobs', {}).get('windsurfAuthStatus', '')
    if not blob:
        continue
    try:
        auth = json.loads(blob)
        ak = auth.get('apiKey', '')
        if len(ak) > 20:
            candidates.append({
                'email': email,
                'blob': blob,
                'conf_blob': snap.get('blobs', {}).get('windsurfConfigurations', ''),
                'apiKey': ak,
                'harvested_at': snap.get('harvested_at', ''),
            })
    except Exception:
        pass

print(f"  total_valid_accounts: {len(candidates)}")
if not candidates:
    print("  ERROR: No valid accounts!")
    sys.exit(1)

# Pick most recent
candidates.sort(key=lambda x: x['harvested_at'], reverse=True)
chosen = candidates[0]
print(f"  chosen: {chosen['email']}")
print(f"  harvested_at: {chosen['harvested_at']}")
print(f"  apiKey: {chosen['apiKey'][:50]}...")

# Step 2: Test WinRM connectivity
print("\n[2] Testing WinRM connectivity...")
out, rc = run_winrm_ps('$env:COMPUTERNAME + ":" + $env:USERNAME')
print(f"  result: {out[:80]}")
if rc != 0 and 'zhouyoukang' not in out.lower() and 'desktop' not in out.lower():
    print(f"  WARNING: WinRM might not be working (rc={rc})")

# Step 3: Check current state.vscdb
print("\n[3] Checking current state.vscdb...")
check_code = '''
import sqlite3, json, os
from pathlib import Path

user = os.environ.get("USERNAME", "zhouyoukang")
db = Path(f"C:/Users/{user}/AppData/Roaming/Windsurf/User/globalStorage/state.vscdb")
print(f"DB_PATH:{db}")
print(f"DB_EXISTS:{db.exists()}")
if db.exists():
    c = sqlite3.connect(str(db), timeout=5)
    row = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
    if row:
        a = json.loads(row[0])
        print(f"AUTH_EXISTS:True")
        print(f"API_KEY_LEN:{len(a.get('apiKey',''))}")
    else:
        print("AUTH_EXISTS:False")
    c.close()
else:
    print("AUTH_EXISTS:False")
'''
out, rc = run_winrm(check_code)
print(f"  {out}")
needs_create = 'DB_EXISTS:False' in out or 'AUTH_EXISTS:False' in out

# Step 4: Inject account
print("\n[4] Injecting account...")
auth_b64 = base64.b64encode(chosen['blob'].encode('utf-8')).decode('ascii')
conf_b64 = base64.b64encode(chosen['conf_blob'].encode('utf-8')).decode('ascii') if chosen['conf_blob'] else ''

inject_code = f'''
import sqlite3, json, os, base64
from pathlib import Path

user = os.environ.get("USERNAME", "zhouyoukang")
db_dir = Path(f"C:/Users/{{user}}/AppData/Roaming/Windsurf/User/globalStorage")
db_dir.mkdir(parents=True, exist_ok=True)
db = db_dir / "state.vscdb"

auth_b64 = "{auth_b64}"
conf_b64 = "{conf_b64}"
status_val = base64.b64decode(auth_b64).decode("utf-8")
conf_val = base64.b64decode(conf_b64).decode("utf-8") if conf_b64 else ""

c = sqlite3.connect(str(db), timeout=10)
c.execute("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value TEXT)")
c.execute("INSERT OR REPLACE INTO ItemTable (key,value) VALUES (?,?)", ("windsurfAuthStatus", status_val))
if conf_val.strip() and conf_val.strip() != "null":
    c.execute("INSERT OR REPLACE INTO ItemTable (key,value) VALUES (?,?)", ("windsurfConfigurations", conf_val))
c.execute("DELETE FROM ItemTable WHERE key=?", ("cachedPlanInfo",))
c.execute("DELETE FROM ItemTable WHERE key=?", ("windsurfMachineId",))
c.commit()

r = c.execute("SELECT value FROM ItemTable WHERE key=?", ("windsurfAuthStatus",)).fetchone()
if r:
    a = json.loads(r[0])
    ak = a.get("apiKey","")
    print(f"INJECT_OK apiKey={{ak[:40]}} len={{len(ak)}}")
else:
    print("INJECT_FAIL")
c.close()
'''

out, rc = run_winrm(inject_code, timeout=90)
print(f"  {out}")

if 'INJECT_OK' in out:
    print("\n  [OK] Account injected successfully!")
else:
    print(f"\n  [WARN] Injection result unclear: {out[:200]}")

# Step 5: Restart Windsurf
print("\n[5] Restarting Windsurf for zhouyoukang...")
restart_ps = '''
Stop-Process -Name Windsurf -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$exe = @("D:\\Windsurf\\Windsurf.exe","C:\\Users\\zhouyoukang\\AppData\\Local\\Programs\\Windsurf\\Windsurf.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($exe) { Start-Process $exe; Write-Host "STARTED:$exe" } else { Write-Host "EXE_NOT_FOUND" }
Start-Sleep -Seconds 8
$cnt = (Get-Process Windsurf -ErrorAction SilentlyContinue).Count
Write-Host "WS_PROCS:$cnt"
'''
out, rc = run_winrm_ps(restart_ps, timeout=60)
print(f"  {out}")

print("\n=== Done ===")
print("zhouyoukang Windsurf should now be authenticated.")
print("On that session: Ctrl+Shift+P -> Reload Window (if needed)")
