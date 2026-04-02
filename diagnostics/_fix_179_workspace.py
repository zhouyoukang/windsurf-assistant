#!/usr/bin/env python3
"""
修复179 storage.json中的v:驱动器引用，并用有效路径启动Windsurf
"""
import json, os, shutil, subprocess, time
from pathlib import Path

TARGET_IP   = '192.168.31.179'
TARGET_USER = 'zhouyoukang'
TARGET_PASS = 'wsy057066wsy'

def run_winrm(ps_block, timeout=30):
    full = [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -EA SilentlyContinue
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock {{
{ps_block}
}} -EA Stop
'''
    ]
    r = subprocess.run(full, capture_output=True, text=True, timeout=timeout,
                       encoding='utf-8', errors='replace')
    return r.stdout.strip(), r.returncode

def copy_to_179(local_path: Path, remote_path: str):
    full = [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -EA SilentlyContinue
$sess = New-PSSession -ComputerName {TARGET_IP} -Credential $cr -EA Stop
Copy-Item -Path "{local_path}" -Destination "{remote_path}" -ToSession $sess -Force
Remove-PSSession $sess
Write-Host "COPY_OK"
'''
    ]
    r = subprocess.run(full, capture_output=True, text=True, timeout=30,
                       encoding='utf-8', errors='replace')
    return 'COPY_OK' in r.stdout

FIX_SCRIPT = r'''
import json, os, shutil
from pathlib import Path

appdata = os.environ.get("APPDATA", "")
storage = Path(appdata) / "Windsurf" / "User" / "globalStorage" / "storage.json"

if not storage.exists():
    print("storage.json NOT FOUND")
    exit(1)

shutil.copy2(str(storage), str(storage) + ".bak_fix")

with open(str(storage), encoding="utf-8", errors="replace") as f:
    data = json.load(f)

def has_v_drive(val):
    s = str(val).lower()
    return "v:\\" in s or "v:/" in s or "%5cv" in s or "file:///v" in s

changes = 0

# Fix windowsState
if "windowsState" in data:
    ws = data["windowsState"]
    if isinstance(ws, dict):
        for key in ["lastActiveWindow", "openedWindows"]:
            if key in ws:
                items = ws[key] if isinstance(ws[key], list) else [ws[key]]
                for item in (items if isinstance(items, list) else [items]):
                    if isinstance(item, dict):
                        for wk in ["folderUri", "workspace", "remoteAuthority"]:
                            if wk in item and has_v_drive(item[wk]):
                                print(f"Clearing windowsState.{key}.{wk}: {item[wk]}")
                                del item[wk]
                                changes += 1
    print(f"windowsState keys: {list(ws.keys()) if isinstance(ws, dict) else type(ws)}")

# Fix backupWorkspaces
if "backupWorkspaces" in data:
    bw = data["backupWorkspaces"]
    if isinstance(bw, dict):
        for key in list(bw.keys()):
            val = bw[key]
            if isinstance(val, list):
                orig_len = len(val)
                bw[key] = [v for v in val if not has_v_drive(str(v))]
                removed = orig_len - len(bw[key])
                if removed:
                    print(f"backupWorkspaces.{key}: removed {removed} v: entries")
                    changes += 1
            elif has_v_drive(str(val)):
                del bw[key]
                changes += 1
                print(f"backupWorkspaces.{key}: removed v: entry")

# Also clear windowsState entirely if it has v: workspace as the only window
if "windowsState" in data:
    ws = data["windowsState"]
    if isinstance(ws, dict):
        opened = ws.get("openedWindows", [])
        last = ws.get("lastActiveWindow", {})
        last_folder = last.get("folderUri", "") if isinstance(last, dict) else ""
        if has_v_drive(last_folder) or all(has_v_drive(str(w.get("folderUri", ""))) for w in opened if isinstance(w, dict)):
            print("Clearing entire windowsState to prevent v: workspace restore")
            data["windowsState"] = {"openedWindows": []}
            changes += 1

with open(str(storage), "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"DONE: {changes} changes made to storage.json")
'''

import tempfile
tmp = Path(tempfile.gettempdir()) / '_fix_ws_storage.py'
tmp.write_text(FIX_SCRIPT, encoding='utf-8')
print(f'Fix script: {tmp}')

ok = copy_to_179(tmp, r'C:\ctemp\_fix_ws_storage.py')
print(f'Copy: {"OK" if ok else "FAILED"}')

if ok:
    out, rc = run_winrm(r'python C:\ctemp\_fix_ws_storage.py 2>&1')
    print(f'Fix output:\n{out}')
    
    # Kill Windsurf 
    out2, _ = run_winrm('Stop-Process -Name Windsurf -Force -EA SilentlyContinue; Write-Host "KILLED"')
    time.sleep(2)
    
    # Start Windsurf with new-window flag (no workspace restore)
    ps_start = r'''
$shell = New-Object -ComObject Shell.Application
$shell.ShellExecute("D:\Windsurf\Windsurf.exe", "--new-window", "", "open", 1)
Start-Sleep 12
$c = (Get-Process -Name Windsurf -EA SilentlyContinue).Count
Write-Host "WS_PROCS:$c"
'''
    out3, _ = run_winrm(ps_start, timeout=20)
    print(f'Start result: {out3}')
    
    # Wait and check stability
    time.sleep(20)
    out4, _ = run_winrm('$c = (Get-Process -Name Windsurf -EA SilentlyContinue).Count; Write-Host "WS_PROCS:$c"')
    print(f'Stability check: {out4}')
    
    # Final log check
    check_ps = r'''
$logPath = "C:\Users\zhouyoukang\AppData\Roaming\Windsurf\logs"
$f = Get-ChildItem $logPath -Recurse -Filter "main.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($f) {
    $lines = Get-Content $f.FullName -Tail 15
    $authErr = $lines | Where-Object { $_ -match "unauthenticated|API key not found" }
    Write-Host "LOG_TIME:$($f.LastWriteTime)"
    Write-Host "AUTH_ERRORS:$($authErr.Count)"
    $lines | Select-Object -Last 5
}
'''
    out5, _ = run_winrm(check_ps, timeout=20)
    print(f'Final check:\n{out5}')

if __name__ == '__main__':
    pass
