#!/usr/bin/env python3
"""
179永久守护部署 — WAMHub任务加固 + 验证全链路
"""
import subprocess, time
from pathlib import Path

TARGET_IP   = "192.168.31.179"
TARGET_USER = "zhouyoukang"
TARGET_PASS = "wsy057066wsy"

def run_remote_ps1(ps1_content, timeout=60):
    """Write PS1 to a temp file and execute it remotely via WinRM session."""
    import tempfile, os
    # Write PS1 to local temp
    tmp = Path(tempfile.mktemp(suffix=".ps1"))
    tmp.write_text(ps1_content, encoding="utf-8")
    
    full = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(tmp)
    ]
    try:
        proc = subprocess.run(full, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace")
        tmp.unlink(missing_ok=True)
        return proc.stdout + proc.stderr, proc.returncode
    except Exception as e:
        tmp.unlink(missing_ok=True)
        return f"ERROR:{e}", -1

def run_remote(ps_cmd, timeout=60):
    """Run PS command on 179 via WinRM inline."""
    ps1 = f"""
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -ErrorAction SilentlyContinue
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock {{
    {ps_cmd}
}} 2>&1 | ForEach-Object {{ Write-Host $_ }}
"""
    return run_remote_ps1(ps1, timeout=timeout)

def log(tag, msg):
    print(f"  [{tag}] {msg}")

def main():
    print("=" * 60)
    print("  179永久守护部署")
    print("=" * 60)

    # ── Step 1: 检查WAMHub任务详情 ──
    print("\n[1] WAMHub任务详情...")
    check_ps = r"""
$task = Get-ScheduledTask -TaskName "WAMHub" -ErrorAction SilentlyContinue
if ($task) {
    $a = $task.Actions[0]
    Write-Host "EXISTS:True"
    Write-Host "STATE:$($task.State)"
    Write-Host "EXE:$($a.Execute)"
    Write-Host "ARGS:$($a.Arguments)"
    Write-Host "CWD:$($a.WorkingDirectory)"
    $task.Triggers | ForEach-Object { Write-Host "TRIGGER:$($_.CimClass.CimClassName):En=$($_.Enabled)" }
} else {
    Write-Host "EXISTS:False"
}
"""
    out, _ = run_remote(check_ps, timeout=20)
    for line in out.strip().splitlines():
        if line.strip(): print(f"    {line}")
    
    task_exists = "EXISTS:True" in out
    task_exe = ""
    task_args = ""
    task_cwd = ""
    for line in out.strip().splitlines():
        line = line.strip()
        if line.startswith("EXE:"):    task_exe = line[4:]
        if line.startswith("ARGS:"):   task_args = line[5:]
        if line.startswith("CWD:"):    task_cwd = line[4:]

    log("OK" if task_exists else "WARN", f"WAMHub任务: {'存在' if task_exists else '不存在'}")
    if task_exe: log("INFO", f"命令: {task_exe} {task_args}")

    # ── Step 2: 加固WAMHub任务 (开机自启 + 失败重启) ──
    print("\n[2] 加固WAMHub任务...")
    
    if task_exists and task_exe:
        # Rebuild task with startup trigger + failure restart
        harden_ps = f"""
$exe  = "{task_exe}"
$args = "{task_args}"
$cwd  = "{task_cwd}"

$triggers = @(
    (New-ScheduledTaskTrigger -AtStartup),
    (New-ScheduledTaskTrigger -AtLogOn)
)
$action = New-ScheduledTaskAction -Execute $exe -Argument $args -WorkingDirectory $cwd
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Days 999) `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -RestartCount 10 `
    -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName "WAMHub" -Trigger $triggers -Action $action `
    -Settings $settings -Principal $principal -Force | Out-Null

Enable-ScheduledTask -TaskName "WAMHub" | Out-Null
$st = (Get-ScheduledTask -TaskName "WAMHub").State
Write-Host "HARDENED:$st"
"""
        out2, _ = run_remote(harden_ps, timeout=20)
        for line in out2.strip().splitlines():
            if line.strip(): print(f"    {line}")
        hardened = "HARDENED:" in out2
        log("OK" if hardened else "WARN", f"任务加固: {'成功 (开机自启+失败重启)' if hardened else '未能加固'}")
    else:
        log("WARN", "WAMHub任务不存在，跳过加固")

    # ── Step 3: 创建WAMHub看门狗 (每5分钟检查) ──
    print("\n[3] 部署WAMHub看门狗...")
    watchdog_ps = r"""
$wdName = "WAMHubWatchdog"
$existing = Get-ScheduledTask -TaskName $wdName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "WATCHDOG:EXISTS:$($existing.State)"
} else {
    # Create watchdog script on 179
    $scriptPath = "C:\ctemp\wam_watchdog.ps1"
    $scriptContent = '$tcp=New-Object Net.Sockets.TcpClient;try{$tcp.Connect("127.0.0.1",9870);$tcp.Close();exit 0}catch{};schtasks /run /tn WAMHub 2>$null'
    [System.IO.File]::WriteAllText($scriptPath, $scriptContent, [System.Text.Encoding]::UTF8)

    $action = New-ScheduledTaskAction -Execute "powershell" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
    $trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) -Once -At "00:00"
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 1) -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

    Register-ScheduledTask -TaskName $wdName -Trigger $trigger -Action $action `
        -Settings $settings -Principal $principal -Force | Out-Null
    Enable-ScheduledTask -TaskName $wdName | Out-Null
    Write-Host "WATCHDOG:CREATED:OK"
}
"""
    out3, _ = run_remote(watchdog_ps, timeout=20)
    for line in out3.strip().splitlines():
        if line.strip(): print(f"    {line}")
    wd_ok = "WATCHDOG:" in out3
    log("OK" if wd_ok else "WARN", "看门狗: 每5分钟自动检查9870")

    # ── Step 4: 确保Windsurf正在运行 ──
    print("\n[4] 确认Windsurf运行状态...")
    ws_check_ps = r"""
$procs = Get-Process Windsurf -ErrorAction SilentlyContinue
Write-Host "WS_PROCS:$($procs.Count)"
if ($procs.Count -eq 0) {
    $wsExe = "D:\Windsurf\Windsurf.exe"
    if (Test-Path $wsExe) {
        Start-Process $wsExe
        Start-Sleep -Seconds 6
        $p2 = Get-Process Windsurf -ErrorAction SilentlyContinue
        Write-Host "WS_AFTER:$($p2.Count)"
    }
}
"""
    out4, _ = run_remote(ws_check_ps, timeout=30)
    for line in out4.strip().splitlines():
        if line.strip(): print(f"    {line}")
    ws_running = any(f"WS_PROCS:{i}" in out4 or f"WS_AFTER:{i}" in out4
                     for i in range(1, 30))
    log("OK" if ws_running else "WARN", f"Windsurf: {'运行中' if ws_running else '未运行'}")

    # ── Step 5: 最终状态检查 ──
    print("\n[5] 最终完整状态...")
    time.sleep(3)
    final_ps = r"""
# WAM Hub
$tcp = New-Object Net.Sockets.TcpClient
try {
    $tcp.Connect("127.0.0.1",9870)
    $stream = $tcp.GetStream()
    $req = [System.Text.Encoding]::ASCII.GetBytes("GET /api/pool/status HTTP/1.0`r`nHost:127.0.0.1`r`n`r`n")
    $stream.Write($req,0,$req.Length)
    Start-Sleep -Milliseconds 800
    $buf = New-Object byte[] 4096
    $n = $stream.Read($buf,0,$buf.Length)
    $resp = [System.Text.Encoding]::ASCII.GetString($buf,0,$n)
    $body = ($resp -split "`r`n`r`n")[1]
    $d = $body | ConvertFrom-Json
    Write-Host "WAM:ONLINE:available=$($d.available):total=$($d.total)"
    $tcp.Close()
} catch {
    Write-Host "WAM:OFFLINE"
}

# Pool key
$pk = "$env:APPDATA\Windsurf\_pool_apikey.txt"
if (Test-Path $pk) {
    $k = [System.IO.File]::ReadAllText($pk).Trim()
    Write-Host "POOL_KEY:len=$($k.Length):valid=$($k.Length -gt 80 -and $k.StartsWith('sk-ws'))"
}

# Extension
$ep = "D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
if (Test-Path $ep) {
    $ec = [System.IO.File]::ReadAllText($ep)
    Write-Host "EXT_PATCH:$($ec.Contains('POOL_HOT_PATCH_V1'))"
}

# Windsurf
$procs = Get-Process Windsurf -ErrorAction SilentlyContinue
Write-Host "WS_PROCS:$($procs.Count)"

# Tasks
$t1 = Get-ScheduledTask -TaskName "WAMHub" -ErrorAction SilentlyContinue
$t2 = Get-ScheduledTask -TaskName "WAMHubWatchdog" -ErrorAction SilentlyContinue
Write-Host "TASK_WAMHUB:$($t1.State)"
Write-Host "TASK_WATCHDOG:$($t2.State)"

Write-Host "FINAL_CHECK_DONE"
"""
    out5, _ = run_remote(final_ps, timeout=30)
    for line in out5.strip().splitlines():
        if line.strip(): print(f"    {line}")

    # Parse
    wam_ok   = "WAM:ONLINE" in out5
    pk_ok    = "POOL_KEY:len=" in out5 and "valid=True" in out5
    ext_ok   = "EXT_PATCH:True" in out5
    ws_ok    = any(f"WS_PROCS:{i}" in out5 for i in range(1, 30))
    hub_task = "TASK_WAMHUB:Ready" in out5 or "TASK_WAMHUB:Running" in out5
    wd_task  = "TASK_WATCHDOG:Ready" in out5 or "TASK_WATCHDOG:Running" in out5

    print("\n" + "=" * 60)
    print("  179 Windsurf全链路状态")
    print("=" * 60)
    items = [
        ("WAM Hub (9870)", wam_ok),
        ("pool_apikey.txt (103字节)", pk_ok),
        ("extension.js热补丁", ext_ok),
        ("Windsurf进程", ws_ok),
        ("WAMHub计划任务", hub_task),
        ("WAMHubWatchdog看门狗", wd_task),
    ]
    for name, ok in items:
        print(f"  {'✅' if ok else '❌'} {name}")

    core_ok = wam_ok and pk_ok and ext_ok
    print()
    if core_ok:
        print("  🎉 179 Windsurf已完全就绪！")
        print()
        print("  用户使用体验:")
        print("  1. 打开Windsurf → Cascade自动使用有效账号")
        print("  2. 账号耗尽时 → WAM Hub自动切换 (无感知)")
        print("  3. 开机自动恢复 → WAMHub任务开机启动")
        print("  4. 断线保护 → 看门狗每5分钟检查，自动恢复")
        print()
        print("  手动切号: POST http://127.0.0.1:9870/api/pool/rotate")
    else:
        print("  部分功能异常，关键缺失:")
        if not wam_ok: print("    WAM Hub未运行 → 手动: schtasks /run /tn WAMHub")
        if not pk_ok:  print("    pool_apikey.txt异常 → 运行 _fix_179_step2.py")
        if not ext_ok: print("    extension.js未打补丁 → 需admin权限修复")

if __name__ == "__main__":
    main()
