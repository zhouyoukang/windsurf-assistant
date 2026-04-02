###############################################################################
# 179永久守护部署 — 确保WAM Hub + Windsurf永不失效
###############################################################################
$ErrorActionPreference = "Continue"
$TARGET_IP   = "192.168.31.179"
$TARGET_USER = "zhouyoukang"
$TARGET_PASS = "wsy057066wsy"

$sp = New-Object System.Security.SecureString
$TARGET_PASS.ToCharArray() | ForEach-Object { $sp.AppendChar($_) }
$cr = New-Object System.Management.Automation.PSCredential($TARGET_USER, $sp)
Set-Item WSMan:\localhost\Client\TrustedHosts -Value $TARGET_IP -Force -ErrorAction SilentlyContinue

Write-Host "=== 179永久守护部署 ===" -ForegroundColor Cyan

$result = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ScriptBlock {
    # 1. 检查WAMHub任务详细配置
    Write-Host "=== WAMHub任务详情 ===" -ForegroundColor Yellow
    $task = Get-ScheduledTask -TaskName "WAMHub" -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "TaskName: $($task.TaskName)"
        Write-Host "State: $($task.State)"
        Write-Host "Description: $($task.Description)"
        $action = $task.Actions[0]
        Write-Host "Action.Execute: $($action.Execute)"
        Write-Host "Action.Arguments: $($action.Arguments)"
        Write-Host "Action.WorkingDirectory: $($action.WorkingDirectory)"
        $triggers = $task.Triggers
        foreach ($t in $triggers) {
            Write-Host "Trigger: $($t.CimClass.CimClassName) Enabled=$($t.Enabled)"
        }
        $settings = $task.Settings
        Write-Host "RestartOnFailure: $($settings.RestartOnFailure)"
        Write-Host "RestartInterval: $($settings.RestartInterval)"
        Write-Host "RestartCount: $($settings.RestartCount)"
        Write-Host "ExecutionTimeLimit: $($settings.ExecutionTimeLimit)"
    } else {
        Write-Host "WAMHub任务不存在"
    }

    # 2. 检查当前WAM进程
    Write-Host "`n=== WAM相关进程 ===" -ForegroundColor Yellow
    $pythonProcs = Get-Process python -ErrorAction SilentlyContinue
    $pythonProcs | ForEach-Object {
        try {
            $cmdline = (Get-WmiObject Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine
            if ($cmdline -like "*wam*" -or $cmdline -like "*pool*" -or $cmdline -like "*9870*" -or $cmdline -like "*butler*") {
                Write-Host "PY_PROC:PID=$($_.Id):CMD=$cmdline"
            }
        } catch {}
    }
    # 检查9870端口对应进程
    $netstat = netstat -ano 2>&1 | Select-String ":9870"
    $netstat | ForEach-Object { Write-Host "NETSTAT:$_" }

    # 3. 加固WAMHub任务 — 设置失败重启 + 登录时触发
    Write-Host "`n=== 加固WAMHub计划任务 ===" -ForegroundColor Yellow
    $task = Get-ScheduledTask -TaskName "WAMHub" -ErrorAction SilentlyContinue
    if ($task) {
        # 获取任务详细信息
        $action = $task.Actions[0]
        $exe    = $action.Execute
        $args   = $action.Arguments
        $cwd    = $action.WorkingDirectory

        # 重新注册任务：添加系统启动触发器 + 失败自动重启
        $triggers = @(
            $(New-ScheduledTaskTrigger -AtStartup),         # 开机触发
            $(New-ScheduledTaskTrigger -AtLogOn)            # 登录触发
        )
        $newAction   = New-ScheduledTaskAction -Execute $exe -Argument $args -WorkingDirectory $cwd
        $settings = New-ScheduledTaskSettingsSet `
            -ExecutionTimeLimit (New-TimeSpan -Days 999) `
            -RestartInterval (New-TimeSpan -Minutes 2) `
            -RestartCount 10 `
            -StartWhenAvailable `
            -RunOnlyIfNetworkAvailable:$false
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

        Register-ScheduledTask -TaskName "WAMHub" -Trigger $triggers -Action $newAction `
            -Settings $settings -Principal $principal -Force | Out-Null
        Write-Host "WAMHub任务已加固: 开机自启 + 失败重启(2min间隔,最多10次)"

        # 确保任务已启用并运行
        Enable-ScheduledTask -TaskName "WAMHub" | Out-Null
        $status = (Get-ScheduledTask -TaskName "WAMHub").State
        Write-Host "WAMHub状态: $status"
    } else {
        Write-Host "WAMHub任务不存在，跳过加固"
    }

    # 4. 检查WAMHub守护是否需要单独的看门狗
    Write-Host "`n=== WAMHub看门狗检测 ===" -ForegroundColor Yellow
    $watchdogTask = Get-ScheduledTask -TaskName "WAMHubWatchdog" -ErrorAction SilentlyContinue
    if (-not $watchdogTask) {
        # 创建简单看门狗脚本 — 每5分钟检查9870是否在线
        $watchdogScript = @"
# WAMHub看门狗 — 自动重启
`$tcp = New-Object System.Net.Sockets.TcpClient
try { `$tcp.Connect("127.0.0.1",9870); `$tcp.Close(); exit 0 } catch {}
# 9870离线 — 运行WAMHub任务
schtasks /run /tn "WAMHub" 2>&1 | Out-Null
"@
        $wdPath = "C:\ctemp\wam_watchdog.ps1"
        [System.IO.File]::WriteAllText($wdPath, $watchdogScript, [System.Text.Encoding]::UTF8)

        $wdAction = New-ScheduledTaskAction `
            -Execute "powershell" `
            -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$wdPath`"" `
            -WorkingDirectory "C:\ctemp"
        $wdTrigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) -Once -At "00:00"
        $wdSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -StartWhenAvailable
        $wdPrincipal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

        Register-ScheduledTask -TaskName "WAMHubWatchdog" -Trigger $wdTrigger -Action $wdAction `
            -Settings $wdSettings -Principal $wdPrincipal -Force | Out-Null
        Enable-ScheduledTask -TaskName "WAMHubWatchdog" | Out-Null
        Write-Host "WAMHubWatchdog已创建: 每5分钟检查9870，离线则自动重启"
    } else {
        Write-Host "WAMHubWatchdog已存在: $($watchdogTask.State)"
    }

    # 5. 验证当前完整状态
    Write-Host "`n=== 当前完整状态 ===" -ForegroundColor Green
    
    # WAM Hub
    $tcp2 = New-Object System.Net.Sockets.TcpClient
    try {
        $tcp2.Connect("127.0.0.1",9870)
        $stream = $tcp2.GetStream()
        $req = "GET /api/pool/status HTTP/1.0`r`nHost: 127.0.0.1`r`n`r`n"
        $bytes = [System.Text.Encoding]::ASCII.GetBytes($req)
        $stream.Write($bytes, 0, $bytes.Length)
        Start-Sleep -Milliseconds 500
        $buf = New-Object byte[] 2048
        $n = $stream.Read($buf, 0, $buf.Length)
        $resp = [System.Text.Encoding]::ASCII.GetString($buf, 0, $n)
        $body = ($resp -split "`r`n`r`n")[1]
        $d = $body | ConvertFrom-Json
        Write-Host "WAM_HUB:ONLINE:available=$($d.available):total=$($d.total)"
        $tcp2.Close()
    } catch {
        Write-Host "WAM_HUB:OFFLINE:$_"
    }

    # Windsurf
    $ws = Get-Process Windsurf -ErrorAction SilentlyContinue
    Write-Host "WS_PROCS:$($ws.Count)"

    # Pool key
    $pk = "$env:APPDATA\Windsurf\_pool_apikey.txt"
    if (Test-Path $pk) {
        $k = [System.IO.File]::ReadAllText($pk).Trim()
        Write-Host "POOL_KEY:len=$($k.Length)"
    }

    # Extension patch
    $ep = "D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
    if (Test-Path $ep) {
        $ec = [System.IO.File]::ReadAllText($ep)
        Write-Host "EXT_HOTPATCH:$($ec.Contains('POOL_HOT_PATCH_V1'))"
    }

    Write-Host "`nDEPLOY_DONE"
} -ErrorAction Stop

$result | ForEach-Object { Write-Host "  $_" }
Write-Host "`n=== 守护部署完成 ===" -ForegroundColor Green
