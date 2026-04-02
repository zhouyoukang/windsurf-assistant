# -*- coding: utf-8 -*-
"""
注入zhouyoukang账号 v2 - 先写本地文件，远端读取
避免命令行长度限制
"""
import subprocess, json, os, sys, tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SNAPSHOT_FILE = SCRIPT_DIR.parent / '010-道引擎_DaoEngine' / '_wam_snapshots.json'
TARGET_IP   = '192.168.31.179'
TARGET_USER = 'zhouyoukang'
TARGET_PASS = 'wsy057066wsy'
SKIP_EMAILS = {'ehhs619938345@yahoo.com', 'fpzgcmcdaqbq152@yahoo.com'}

# 共享临时目录 (system-level, all users can access)
SHARED_TMP = Path('C:/ctemp/ws_inject_shared')

def run_winrm_ps(ps_cmd, timeout=45):
    ps = f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -ErrorAction SilentlyContinue
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock {{ {ps_cmd} }} 2>&1
'''
    r = subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps],
        capture_output=True, text=True, timeout=timeout,
        encoding='utf-8', errors='replace'
    )
    return (r.stdout + r.stderr).strip(), r.returncode

# Step 1: Load snapshot
print("[1] Loading best account...")
with open(SNAPSHOT_FILE, 'r', encoding='utf-8') as f:
    snap_data = json.load(f)

candidates = []
for email, snap in snap_data.get('snapshots', {}).items():
    if email in SKIP_EMAILS:
        continue
    blob = snap.get('blobs', {}).get('windsurfAuthStatus', '')
    if not blob:
        continue
    try:
        auth = json.loads(blob)
        if len(auth.get('apiKey', '')) > 20:
            candidates.append({
                'email': email,
                'auth_blob': blob,
                'conf_blob': snap.get('blobs', {}).get('windsurfConfigurations', '') or '',
                'apiKey': auth['apiKey'],
                'harvested_at': snap.get('harvested_at', ''),
            })
    except Exception:
        pass

candidates.sort(key=lambda x: x['harvested_at'], reverse=True)
chosen = candidates[0]
print(f"  account: {chosen['email']}  key: {chosen['apiKey'][:40]}...")

# Step 2: Write data to shared path (accessible to all local users)
print(f"\n[2] Writing auth data to shared temp {SHARED_TMP}...")
SHARED_TMP.mkdir(parents=True, exist_ok=True)

payload = {
    'auth_blob': chosen['auth_blob'],
    'conf_blob': chosen['conf_blob'],
}
payload_path = SHARED_TMP / 'payload.json'
with open(payload_path, 'w', encoding='utf-8') as f:
    json.dump(payload, f)
print(f"  payload written: {payload_path} ({payload_path.stat().st_size} bytes)")

# Step 3: Write injection script to shared path
inject_py = '''
import sqlite3, json, os, sys
from pathlib import Path

user = os.environ.get("USERNAME", "zhouyoukang")
db_dir = Path(f"C:/Users/{user}/AppData/Roaming/Windsurf/User/globalStorage")
db_dir.mkdir(parents=True, exist_ok=True)
db = db_dir / "state.vscdb"

with open("C:/ctemp/ws_inject_shared/payload.json", "r", encoding="utf-8") as f:
    payload = json.load(f)

auth_val = payload["auth_blob"]
conf_val = payload["conf_blob"]

c = sqlite3.connect(str(db), timeout=10)
c.execute("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value TEXT)")
c.execute("INSERT OR REPLACE INTO ItemTable (key,value) VALUES (?,?)", ("windsurfAuthStatus", auth_val))
if conf_val.strip() and conf_val.strip() != "null":
    c.execute("INSERT OR REPLACE INTO ItemTable (key,value) VALUES (?,?)", ("windsurfConfigurations", conf_val))
c.execute("DELETE FROM ItemTable WHERE key=?", ("cachedPlanInfo",))
c.execute("DELETE FROM ItemTable WHERE key=?", ("windsurfMachineId",))
c.commit()

r = c.execute("SELECT value FROM ItemTable WHERE key=?", ("windsurfAuthStatus",)).fetchone()
if r:
    a = json.loads(r[0])
    ak = a.get("apiKey","")
    print(f"INJECT_OK user={user} key={ak[:40]} len={len(ak)}")
else:
    print("INJECT_FAIL: no row found")
c.close()
'''

inject_path = SHARED_TMP / 'do_inject.py'
with open(inject_path, 'w', encoding='utf-8') as f:
    f.write(inject_py)
print(f"  inject script: {inject_path}")

# Step 4: Run via WinRM (zhouyoukang reads from C:\ctemp\)
print(f"\n[3] Running injection via WinRM as {TARGET_USER}...")
out, rc = run_winrm_ps('python "C:\\ctemp\\ws_inject_shared\\do_inject.py" 2>&1', timeout=45)
print(f"  {out}")

if 'INJECT_OK' in out:
    print("\n  SUCCESS: account injected!")
else:
    print(f"\n  WARNING: result: {out[:200]}")
    # Try with full python path
    print("  Retrying with Program Files Python path...")
    out2, rc2 = run_winrm_ps(
        '"C:\\\\Program Files\\\\Python311\\\\python.exe" "C:\\\\ctemp\\\\ws_inject_shared\\\\do_inject.py" 2>&1',
        timeout=45
    )
    print(f"  {out2}")
    if 'INJECT_OK' in out2:
        print("  SUCCESS (retry)!")

# Step 5: Restart Windsurf
print("\n[4] Restarting Windsurf...")
restart = '''
Stop-Process -Name Windsurf -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
$exe = @("D:\\Windsurf\\Windsurf.exe","C:\\Users\\zhouyoukang\\AppData\\Local\\Programs\\Windsurf\\Windsurf.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($exe) { $shell = New-Object -ComObject Shell.Application; $shell.Open($exe); Write-Host "STARTED:$exe" }
else { Write-Host "EXE_NOT_FOUND" }
Start-Sleep -Seconds 10
$cnt = (Get-Process Windsurf -ErrorAction SilentlyContinue).Count
Write-Host "WS_PROCS:$cnt"
'''
out, rc = run_winrm_ps(restart, timeout=60)
print(f"  {out}")

print("\n=== Complete ===")
print(f"Account: {chosen['email']}")
print(f"APIKey:  {chosen['apiKey'][:50]}...")
print("On zhouyoukang session: Ctrl+Shift+P -> Reload Window")
