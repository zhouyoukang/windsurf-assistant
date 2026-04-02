#!/usr/bin/env python3
"""
179同步修复 — WAM Hub active账号 → pool_apikey.txt + state.vscdb 同步
"""
import subprocess, json, base64, time
from pathlib import Path
import tempfile

TARGET_IP   = "192.168.31.179"
TARGET_USER = "zhouyoukang"
TARGET_PASS = "wsy057066wsy"

def run_remote_ps1(content, timeout=90):
    tmp = Path(tempfile.mktemp(suffix=".ps1"))
    tmp.write_text(content, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(tmp)],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace"
        )
        tmp.unlink(missing_ok=True)
        return proc.stdout + proc.stderr, proc.returncode
    except Exception as e:
        tmp.unlink(missing_ok=True)
        return f"ERROR:{e}", -1

def run_remote(ps_body, timeout=60):
    ps1 = f"""
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -ErrorAction SilentlyContinue
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock {{
    {ps_body}
}} 2>&1 | ForEach-Object {{ Write-Host $_ }}
"""
    return run_remote_ps1(ps1, timeout=timeout)

def remote_py(py_code, label="_p", timeout=60):
    b64 = base64.b64encode(py_code.encode("utf-8")).decode("ascii")
    chunks = [b64[i:i+8000] for i in range(0, len(b64), 8000)]
    run_remote(f'[System.IO.File]::WriteAllText("C:\\\\ctemp\\\\{label}_b64.txt","", [System.Text.Encoding]::ASCII)', timeout=8)
    for chunk in chunks:
        run_remote(f'[System.IO.File]::AppendAllText("C:\\\\ctemp\\\\{label}_b64.txt","{chunk}",[System.Text.Encoding]::ASCII)', timeout=8)
    exec_ps = f"""
$b64=[System.IO.File]::ReadAllText("C:\\\\ctemp\\\\{label}_b64.txt").Trim()
$bytes=[System.Convert]::FromBase64String($b64)
$text=[System.Text.Encoding]::UTF8.GetString($bytes)
[System.IO.File]::WriteAllText("C:\\\\ctemp\\\\{label}.py",$text,[System.Text.Encoding]::UTF8)
$env:PYTHONIOENCODING="utf-8"
python "C:\\\\ctemp\\\\{label}.py" 2>&1 | ForEach-Object {{ Write-Host $_ }}
"""
    return run_remote(exec_ps, timeout=timeout)

def main():
    print("=" * 65)
    print("  179 WAM同步修复")
    print("=" * 65)

    # ── Step 1: 从WAM Hub获取active账号apiKey并同步 ──
    print("\n[1] 获取WAM active apiKey + 同步pool_apikey.txt...")
    sync_py = r'''
import urllib.request, json, os, sqlite3, shutil
from pathlib import Path

APPDATA = os.environ.get("APPDATA", "")
PK      = Path(APPDATA) / "Windsurf" / "_pool_apikey.txt"
DB      = Path(APPDATA) / "Windsurf" / "User" / "globalStorage" / "state.vscdb"

# 1. Get WAM active account apiKey
active_key  = ""
active_email = ""
try:
    r = urllib.request.urlopen("http://127.0.0.1:9870/api/pool/accounts", timeout=8)
    data = json.loads(r.read())
    accounts = data.get("accounts", [])
    idx = data.get("activeIndex", -1)
    print(f"WAM_ACCOUNTS:{len(accounts)}:activeIdx={idx}")
    if 0 <= idx < len(accounts):
        a = accounts[idx]
        active_key   = a.get("apiKey", a.get("api_key", ""))
        active_email = a.get("email", "")
        print(f"WAM_ACTIVE:email={active_email}:keylen={len(active_key)}")
        print(f"WAM_ACTIVE_KEY40:{active_key[:40]}")
except Exception as e:
    print(f"WAM_ACCOUNTS_FAIL:{e}")

# 2. If we got a valid key, sync pool_apikey.txt
if active_key and len(active_key) > 80:
    old_key = PK.read_text(encoding="utf-8").strip() if PK.exists() else ""
    if old_key != active_key:
        PK.write_text(active_key, encoding="utf-8")
        print(f"POOL_KEY_SYNCED:len={len(active_key)}")
    else:
        print(f"POOL_KEY_ALREADY_SYNC:len={len(active_key)}")
else:
    # fallback: read current pool_apikey.txt key
    if PK.exists():
        active_key = PK.read_text(encoding="utf-8").strip()
        print(f"POOL_KEY_FALLBACK:len={len(active_key)}")
    print("WAM_KEY_UNAVAILABLE:using_existing_pool_key")

# 3. Update state.vscdb apiKey if different
if DB.exists() and active_key and len(active_key) > 80:
    try:
        bak = str(DB) + ".bak_sync"
        if not Path(bak).exists():
            shutil.copy2(DB, bak)
        conn = sqlite3.connect(str(DB), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        row = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        if row:
            auth = json.loads(row[0])
            current_key = auth.get("apiKey", "")
            if current_key != active_key:
                auth["apiKey"] = active_key
                conn.execute("INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)",
                             ("windsurfAuthStatus", json.dumps(auth)))
                conn.commit()
                print(f"VSCDB_KEY_UPDATED:old={current_key[:20]}...:new={active_key[:20]}...")
            else:
                print("VSCDB_KEY_MATCH:no_update_needed")
        conn.close()
    except Exception as e:
        print(f"VSCDB_UPDATE_FAIL:{e}")

# 4. Final state check
pk_len = len(PK.read_text(encoding="utf-8").strip()) if PK.exists() else 0
print(f"FINAL_POOL_KEY_LEN:{pk_len}")
if DB.exists():
    try:
        c = sqlite3.connect(str(DB), timeout=3)
        row = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        if row:
            a = json.loads(row[0])
            print(f"FINAL_AUTH_KEYLEN:{len(a.get('apiKey',''))}")
        c.close()
    except: pass

print("SYNC_DONE")
'''
    out, _ = remote_py(sync_py, "_sync", timeout=40)
    sync_ok = "SYNC_DONE" in out
    for line in out.splitlines():
        if line.strip(): print(f"    {line}")
    
    if not sync_ok:
        print("  [WARN] 同步脚本未完成，检查上方输出")
    
    # ── Step 2: 部署永久pool_key同步守护任务 ──
    print("\n[2] 部署WAM-PoolKey同步计划任务...")
    
    sync_daemon_code = '''#!/usr/bin/env python3
"""WAM Hub pool_apikey.txt同步守护 — 保持pool_key与WAM active账号同步"""
import urllib.request, json, os, time, sys
from pathlib import Path

APPDATA  = os.environ.get("APPDATA", "")
PK       = Path(APPDATA) / "Windsurf" / "_pool_apikey.txt"
LOG      = Path(APPDATA) / "Windsurf" / "_pool_key_sync.log"
INTERVAL = 60  # 每60秒检查一次

def log(msg):
    import datetime
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\\n")
    except: pass

def sync_once():
    try:
        r = urllib.request.urlopen("http://127.0.0.1:9870/api/pool/accounts", timeout=8)
        data = json.loads(r.read())
        accounts = data.get("accounts", [])
        idx = data.get("activeIndex", -1)
        if 0 <= idx < len(accounts):
            ak = accounts[idx].get("apiKey", "")
            if len(ak) > 80 and ak.startswith("sk-ws"):
                current = PK.read_text(encoding="utf-8").strip() if PK.exists() else ""
                if current != ak:
                    PK.write_text(ak, encoding="utf-8")
                    log(f"SYNCED:{accounts[idx].get('email','?')}:{ak[:20]}...")
                return True
    except Exception as e:
        log(f"SYNC_ERR:{e}")
    return False

if "--once" in sys.argv:
    sync_once()
else:
    log("WAM-PoolKey同步守护启动")
    while True:
        sync_once()
        time.sleep(INTERVAL)
'''
    
    daemon_b64 = base64.b64encode(sync_daemon_code.encode("utf-8")).decode("ascii")
    
    deploy_ps = f"""
$b64 = "{daemon_b64}"
$bytes = [System.Convert]::FromBase64String($b64)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
$scriptPath = "C:\\ctemp\\wam_pool_sync.py"
[System.IO.File]::WriteAllText($scriptPath, $text, [System.Text.Encoding]::UTF8)
Write-Host "SCRIPT_WRITTEN:$scriptPath"

$taskName = "WAMPoolKeySync"
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {{
    Write-Host "TASK_ALREADY_EXISTS:$($existingTask.State)"
}} else {{
    $action = New-ScheduledTaskAction -Execute "python" -Argument $scriptPath
    $trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Seconds 60) -Once -At "00:00"
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName $taskName -Trigger $trigger -Action $action `
        -Settings $settings -Principal $principal -Force | Out-Null
    Enable-ScheduledTask -TaskName $taskName | Out-Null
    Write-Host "TASK_CREATED:$taskName"
}}

# Run once immediately
python $scriptPath --once 2>&1 | Select-Object -First 5 | ForEach-Object {{ Write-Host "SYNC_ONCE:$_" }}
"""
    out2, _ = run_remote(deploy_ps, timeout=30)
    for line in out2.splitlines():
        if line.strip(): print(f"    {line}")

    # ── Step 3: 重启Windsurf激活同步后的auth ──
    print("\n[3] 重启Windsurf (加载同步后的auth)...")
    restart_ps = r"""
$procs = Get-Process Windsurf -ErrorAction SilentlyContinue
if ($procs.Count -gt 0) {
    $procs | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    Write-Host "KILLED:$($procs.Count)"
}
$exe = "D:\Windsurf\Windsurf.exe"
if (Test-Path $exe) {
    Start-Process $exe
    Start-Sleep -Seconds 6
    $p2 = Get-Process Windsurf -ErrorAction SilentlyContinue
    Write-Host "STARTED:$($p2.Count)"
} else {
    Write-Host "EXE_NOT_FOUND"
}
"""
    out3, _ = run_remote(restart_ps, timeout=30)
    for line in out3.splitlines():
        if line.strip(): print(f"    {line}")

    # ── Step 4: 最终全面验证 ──
    print("\n[4] 最终验证...")
    time.sleep(5)
    
    final_verify_ps = r"""
# WAM Hub
try {
    $r = Invoke-WebRequest "http://127.0.0.1:9870/api/pool/status" -UseBasicParsing -TimeoutSec 5
    $d = $r.Content | ConvertFrom-Json
    Write-Host "WAM:ONLINE:available=$($d.available):active=$($d.activeEmail):remaining=$($d.activeRemaining)"
} catch {
    Write-Host "WAM:OFFLINE"
}

# Pool key
$pk = "$env:APPDATA\Windsurf\_pool_apikey.txt"
if (Test-Path $pk) {
    $k = [System.IO.File]::ReadAllText($pk).Trim()
    Write-Host "POOL_KEY:len=$($k.Length):valid=$($k.Length -gt 80 -and $k.StartsWith('sk-ws'))"
}

# Extension patch
$ep = "D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
if (Test-Path $ep) {
    $ec = [System.IO.File]::ReadAllText($ep)
    Write-Host "EXT_PATCH:$($ec.Contains('POOL_HOT_PATCH_V1'))"
}

# Tasks
$tasks = @("WAMHub","WAMHubWatchdog","WAMPoolKeySync")
foreach ($t in $tasks) {
    $task = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    if ($task) { Write-Host "TASK_$($t):$($task.State)" }
    else        { Write-Host "TASK_$($t):MISSING" }
}

# Windsurf via WMI
$wmi = Get-WmiObject Win32_Process -Filter "Name='Windsurf.exe'" -ErrorAction SilentlyContinue
Write-Host "WS_WMI:$(@($wmi).Count)"

Write-Host "FINAL_OK"
"""
    out4, _ = run_remote(final_verify_ps, timeout=25)
    for line in out4.splitlines():
        if line.strip(): print(f"    {line}")

    # ── 解析并汇报 ──
    wam_ok  = "WAM:ONLINE" in out4
    pk_ok   = "POOL_KEY:len=" in out4 and "valid=True" in out4
    ext_ok  = "EXT_PATCH:True" in out4
    hub_ok  = "TASK_WAMHub:Running" in out4 or "TASK_WAMHub:Ready" in out4
    wd_ok   = "TASK_WAMHubWatchdog:Ready" in out4 or "TASK_WAMHubWatchdog:Running" in out4
    sync_ok2 = "TASK_WAMPoolKeySync:Ready" in out4 or "TASK_WAMPoolKeySync:Running" in out4
    ws_ok   = "WS_WMI:" in out4 and "WS_WMI:0" not in out4

    print("\n" + "=" * 65)
    print("  🏁 179 Windsurf最终全链路状态")
    print("=" * 65)
    
    items = [
        ("WAM Hub (9870) — 账号池管理",      wam_ok),
        ("pool_apikey.txt — 103字节有效key", pk_ok),
        ("extension.js POOL_HOT_PATCH_V1",  ext_ok),
        ("WAMHub 计划任务 (开机自启)",        hub_ok),
        ("WAMHubWatchdog (5min检查)",        wd_ok),
        ("WAMPoolKeySync (60s同步)",         sync_ok2),
        ("Windsurf 进程运行",                ws_ok),
    ]
    
    all_ok = all(ok for _, ok in items[:6])  # core items
    for name, ok in items:
        print(f"  {'✅' if ok else '❌'} {name}")
    
    print()
    if all_ok:
        print("  🎉 179 Windsurf全面修复完成，所有机制就绪！")
        print()
        print("  架构说明:")
        print("  ┌─ extension.js 拦截每次gRPC → 读pool_apikey.txt → 用最优key")
        print("  ├─ WAMPoolKeySync 每60s → WAM Hub active key → pool_apikey.txt")  
        print("  ├─ WAM Hub (9870) → 管理97账号池 → 自动选最优")
        print("  └─ WAMHubWatchdog → 5min检查 → Hub崩溃自动重启")
        print()
        print("  用户体验: 打开Windsurf即可使用，账号切换完全无感知")
    else:
        print("  ⚠ 部分项目需要处理:")
        for name, ok in items:
            if not ok:
                print(f"    ❌ {name}")

if __name__ == "__main__":
    main()
