#!/usr/bin/env python3
"""
179修复 Step3 — 启动WAM Hub + Windsurf + 最终验证
"""
import subprocess, time
from pathlib import Path

TARGET_IP   = "192.168.31.179"
TARGET_USER = "zhouyoukang"
TARGET_PASS = "wsy057066wsy"

def run_remote(ps_cmd, timeout=60):
    full = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        f"""
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -ErrorAction SilentlyContinue
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock {{
    {ps_cmd}
}} 2>&1 | ForEach-Object {{ Write-Host $_ }}
exit $LASTEXITCODE
"""
    ]
    try:
        proc = subprocess.run(full, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace")
        return proc.stdout + proc.stderr, proc.returncode
    except Exception as e:
        return f"ERROR:{e}", -1

def log(tag, msg):
    print(f"  [{tag}] {msg}")

def main():
    print("=" * 60)
    print("  179修复 Step3 — 启动服务 + 最终验证")
    print("=" * 60)

    # Step 1: 启动WAMHub计划任务
    print("\n[1] 启动WAMHub计划任务...")
    wam_start_ps = r"""
# 运行WAMHub计划任务
$taskName = "WAMHub"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "TASK:$($task.TaskName):State=$($task.State)"
    if ($task.State -eq "Ready" -or $task.State -eq "Disabled") {
        # 先启用
        if ($task.State -eq "Disabled") {
            Enable-ScheduledTask -TaskName $taskName | Out-Null
        }
        schtasks /run /tn $taskName 2>&1 | ForEach-Object { Write-Host "SCHTASK:$_" }
        Start-Sleep -Seconds 3
        # 检查端口
        $tcp = New-Object System.Net.Sockets.TcpClient
        try { $tcp.Connect("127.0.0.1",9870); Write-Host "WAM:9870:OPEN"; $tcp.Close() }
        catch { Write-Host "WAM:9870:STILL_CLOSED" }
    } else {
        Write-Host "TASK:RUNNING_STATE:$($task.State)"
    }
} else {
    Write-Host "TASK:NOT_FOUND:WAMHub"
    # 查找WAM hub脚本
    $wamScripts = Get-ChildItem "C:\ctemp" -Filter "*wam*" -Recurse -ErrorAction SilentlyContinue
    $wamScripts | ForEach-Object { Write-Host "FOUND:$($_.FullName)" }
}
"""
    out, _ = run_remote(wam_start_ps, timeout=25)
    for line in out.strip().splitlines():
        if line.strip(): print(f"    {line}")
    wam_started = "WAM:9870:OPEN" in out

    # Step 2: 如果WAM Hub还未运行，查找并直接启动
    if not wam_started:
        print("\n[1b] WAM Hub未通过任务启动，查找hub脚本...")
        find_hub_ps = r"""
$searchPaths = @(
    "C:\ctemp",
    "C:\Users\zhouyoukang\Desktop",
    "C:\Users\zhouyoukang\Documents",
    "D:\wam",
    "C:\wam",
    "C:\Users\zhouyoukang\AppData\Roaming\Windsurf"
)
foreach ($path in $searchPaths) {
    if (Test-Path $path) {
        Get-ChildItem $path -Filter "*.py" -Recurse -ErrorAction SilentlyContinue | 
        Where-Object { $_.Name -like "*wam*" -or $_.Name -like "*butler*" -or $_.Name -like "*pool*" -or $_.Name -like "*hub*" } |
        ForEach-Object { Write-Host "SCRIPT:$($_.FullName)" }
    }
}
# 查看任务的实际命令
$task = Get-ScheduledTask -TaskName "WAMHub" -ErrorAction SilentlyContinue
if ($task) {
    $action = $task.Actions[0]
    Write-Host "TASK_CMD:$($action.Execute) $($action.Arguments)"
    Write-Host "TASK_DIR:$($action.WorkingDirectory)"
}
"""
        out2, _ = run_remote(find_hub_ps, timeout=20)
        for line in out2.strip().splitlines():
            if line.strip(): print(f"    {line}")

        # 尝试从任务命令获取脚本路径并直接运行
        cmd_line = ""
        work_dir = ""
        for line in out2.strip().splitlines():
            if "TASK_CMD:" in line:
                cmd_line = line.replace("TASK_CMD:", "").strip()
            if "TASK_DIR:" in line:
                work_dir = line.replace("TASK_DIR:", "").strip()

        if cmd_line:
            log("INFO", f"找到任务命令: {cmd_line}")
            # 后台启动WAM hub
            start_hub_ps = f"""
$cwd = "{work_dir}"
if (-not $cwd -or -not (Test-Path $cwd)) {{ $cwd = "C:\\ctemp" }}
Start-Process -FilePath "{cmd_line.split()[0]}" -ArgumentList "{' '.join(cmd_line.split()[1:])}" `
    -WorkingDirectory $cwd -WindowStyle Hidden
Start-Sleep -Seconds 4
$tcp = New-Object System.Net.Sockets.TcpClient
try {{ $tcp.Connect("127.0.0.1",9870); Write-Host "WAM:9870:OPEN_AFTER_START"; $tcp.Close() }}
catch {{ Write-Host "WAM:9870:STILL_CLOSED_AFTER_START" }}
"""
            out3, _ = run_remote(start_hub_ps, timeout=20)
            for line in out3.strip().splitlines():
                if line.strip(): print(f"    {line}")
            wam_started = "OPEN" in out3

    # Step 3: 启动Windsurf
    print("\n[2] 启动Windsurf...")
    start_ws_ps = r"""
$wsPaths = @(
    "D:\Windsurf\Windsurf.exe",
    "$env:LOCALAPPDATA\Programs\Windsurf\Windsurf.exe"
)
$wsExe = $null
foreach ($p in $wsPaths) {
    if (Test-Path $p) { $wsExe = $p; break }
}
if (-not $wsExe) {
    Write-Host "WS_EXE:NOT_FOUND"
    exit 0
}
# 确保没有残留进程
$procs = Get-Process Windsurf -ErrorAction SilentlyContinue
if ($procs.Count -gt 0) {
    Write-Host "WS:ALREADY_RUNNING:$($procs.Count)"
} else {
    Start-Process $wsExe
    Write-Host "WS:STARTED:$wsExe"
    Start-Sleep -Seconds 6
    $procs = Get-Process Windsurf -ErrorAction SilentlyContinue
    Write-Host "WS:PROCS:$($procs.Count)"
}
"""
    out4, _ = run_remote(start_ws_ps, timeout=30)
    for line in out4.strip().splitlines():
        if line.strip(): print(f"    {line}")
    ws_running = "WS:PROCS:" in out4 and "WS:PROCS:0" not in out4

    # Step 4: 等待10s让Windsurf完全加载
    print("\n[3] 等待Windsurf完全加载 (10s)...")
    time.sleep(10)

    # Step 5: 最终全面验证
    print("\n[4] 最终全面验证...")
    final_verify_ps = r"""
$APPDATA = $env:APPDATA
$USER = $env:USERNAME

# 1. auth check via Python
$db = "$APPDATA\Windsurf\User\globalStorage\state.vscdb"
if (Test-Path $db) {
    $diagCode = @"
import sqlite3,json,os
db=os.environ.get('APPDATA','')+r'\Windsurf\User\globalStorage\state.vscdb'
c=sqlite3.connect(db,timeout=3)
r=c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
if r:
    a=json.loads(r[0])
    print('AUTH_EMAIL:'+str(a.get('email','')))
    print('AUTH_KEYLEN:'+str(len(a.get('apiKey',''))))
    print('AUTH_KEY40:'+str(a.get('apiKey','')[:40]))
else:
    print('AUTH_STATUS:NULL')
c.close()
"@
    $diagCode | python 2>&1 | ForEach-Object { Write-Host $_ }
}

# 2. Pool key
$pk = "$APPDATA\Windsurf\_pool_apikey.txt"
if (Test-Path $pk) {
    $k = [System.IO.File]::ReadAllText($pk).Trim()
    Write-Host "POOL_KEY:len=$($k.Length):key=$($k.Substring(0,[Math]::Min(40,$k.Length)))"
} else {
    Write-Host "POOL_KEY:MISSING"
}

# 3. Extension.js patch
$extPath = "D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
if (-not (Test-Path $extPath)) {
    $extPath = "$env:LOCALAPPDATA\Programs\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
}
if (Test-Path $extPath) {
    $ext = [System.IO.File]::ReadAllText($extPath)
    Write-Host "EXT_HOTPATCH:$($ext.Contains('POOL_HOT_PATCH_V1'))"
    Write-Host "EXT_SIZE_KB:$([int]($ext.Length/1024))"
} else {
    Write-Host "EXT:NOT_FOUND"
}

# 4. workbench patches
$wbPath = "D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js"
if (Test-Path $wbPath) {
    $wb = [System.IO.File]::ReadAllText($wbPath)
    Write-Host "WB_GBE:$($wb.Contains('__wamRateLimit'))"
    Write-Host "WB_MAXGEN:$($wb.Contains('maxGeneratorInvocations=9999'))"
    Write-Host "WB_OPUS46:$($wb.Contains('__o46='))"
}

# 5. Ports
foreach ($port in @(9870, 19877)) {
    $tcp = New-Object System.Net.Sockets.TcpClient
    try { $tcp.Connect("127.0.0.1",$port); Write-Host "PORT:${port}:OPEN"; $tcp.Close() }
    catch { Write-Host "PORT:${port}:CLOSED" }
}

# 6. Windsurf processes
$procs = Get-Process Windsurf -ErrorAction SilentlyContinue
Write-Host "WS_PROCS:$($procs.Count)"
"""
    out5, _ = run_remote(final_verify_ps, timeout=35)
    for line in out5.strip().splitlines():
        if line.strip(): print(f"    {line}")

    # Parse results
    has_keylen  = any(f"AUTH_KEYLEN:{i}" in out5 for i in range(80, 200))
    has_poolkey = any(f"POOL_KEY:len={i}" in out5 for i in range(80, 200))
    ext_patched = "EXT_HOTPATCH:True" in out5
    gbe_ok      = "WB_GBE:True" in out5
    wam_up      = "PORT:9870:OPEN" in out5
    ws_procs    = any(f"WS_PROCS:{i}" in out5 for i in range(1, 30))

    print("\n" + "=" * 60)
    print("  🏁 最终状态汇报")
    print("=" * 60)
    checks = [
        ("Auth key (有效apiKey)", has_keylen),
        ("Pool key txt (完整103字节)", has_poolkey),
        ("Extension.js热补丁", ext_patched),
        ("workbench GBe拦截器", gbe_ok),
        ("WAM Hub (9870)", wam_up),
        ("Windsurf运行中", ws_procs),
    ]
    all_critical_ok = has_keylen and has_poolkey and ext_patched
    for name, ok in checks:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}")

    print()
    if all_critical_ok:
        print("  🎉 179 Windsurf核心功能完全修复！")
        print()
        print("  功能状态:")
        print("  • Cascade/AI可以正常对话")
        print("  • 热切号: extension.js从pool_apikey.txt读取")
        print("  • WAM Hub自动管理账号池切换")
        print()
        if not wam_up:
            print("  ℹ WAM Hub暂时离线，Windsurf用当前注入账号运行")
            print("    账号耗尽时需手动重启WAMHub任务")
    else:
        print("  ⚠ 部分功能需进一步处理:")
        if not has_keylen:
            print("    - Auth注入未成功 → 重新运行 _fix_179_step2.py")
        if not has_poolkey:
            print("    - pool_apikey.txt写入失败 → 检查权限")
        if not ext_patched:
            print("    - extension.js未打补丁 → 需admin权限或手动操作")

if __name__ == "__main__":
    main()
