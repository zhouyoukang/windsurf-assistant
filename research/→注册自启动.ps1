# →注册自启动.ps1 — 无为守护 Windows自动启动注册
# 道法自然 · 开机自启 · 用户零感知
# Usage: 右键以管理员身份运行 (或直接运行)

$TaskName   = "WindsurfWuWeiGuard"
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$CmdFile    = Join-Path $ScriptDir "→无感启动.cmd"
$NodeExe    = (Get-Command node -ErrorAction SilentlyContinue)?.Source
$WatchdogJs = Join-Path $ScriptDir "040-诊断工具_Diagnostics\_watchdog_wuwei.js"

Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  无为守护 — Windows自动启动注册                      ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── 检查已有任务 ───────────────────────────────
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[注册] 已存在任务 $TaskName，先删除..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# ── 方式1: 任务计划器 (推荐，用户登录后自动运行) ──
try {
    if (-not $NodeExe) {
        # 尝试常见位置
        $NodeExe = @(
            "C:\Program Files\nodejs\node.exe",
            "C:\Program Files (x86)\nodejs\node.exe",
            "$env:APPDATA\nvm\current\node.exe"
        ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    }

    if (-not $NodeExe) {
        Write-Host "[注册] ❌ 未找到node.exe，回退到CMD方式" -ForegroundColor Red
        throw "no node"
    }

    # 任务: 登录后30秒启动看门狗 (等待Windsurf完成加载)
    $action  = New-ScheduledTaskAction -Execute $NodeExe -Argument "`"$WatchdogJs`"" -WorkingDirectory $ScriptDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $trigger.Delay = "PT30S"   # 登录后等30s

    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 2) `
        -MultipleInstances IgnoreNew `
        -Priority 7

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action   $action `
        -Trigger  $trigger `
        -Settings $settings `
        -Description "无为守护: 自动检测并处理Windsurf速率限制，用户零感知" `
        -RunLevel Highest `
        -Force | Out-Null

    Write-Host "[注册] ✅ 任务计划器注册成功: $TaskName" -ForegroundColor Green
    Write-Host "       触发: 用户登录后30秒自动启动" -ForegroundColor Green
    Write-Host "       进程: node $WatchdogJs" -ForegroundColor Green
    Write-Host "       策略: 崩溃后2分钟内自动重启(最多3次)" -ForegroundColor Green
} catch {
    # ── 方式2: 注册表启动项 (备用) ──────────────────
    Write-Host "[注册] 使用注册表启动项..." -ForegroundColor Yellow
    $regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $cmdLine = "cmd /c start /min `"`" cmd /c `"$CmdFile`""
    Set-ItemProperty -Path $regPath -Name $TaskName -Value $cmdLine
    Write-Host "[注册] ✅ 注册表启动项已设置" -ForegroundColor Green
}

Write-Host ""

# ── 立即启动看门狗 ─────────────────────────────
Write-Host "[启动] 立即启动看门狗..." -ForegroundColor Cyan
if ($NodeExe -and (Test-Path $WatchdogJs)) {
    Start-Process -FilePath $NodeExe -ArgumentList "`"$WatchdogJs`"" `
        -WorkingDirectory $ScriptDir -WindowStyle Minimized
    Write-Host "[启动] ✅ 看门狗已在后台运行" -ForegroundColor Green
} else {
    Write-Host "[启动] ⚠️  直接启动失败，请手动运行 →无感启动.cmd" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║  注册完成！下次开机将自动启动无为守护。              ║" -ForegroundColor Green
Write-Host "║  Rate Limit从此完全对用户透明。                      ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Green
