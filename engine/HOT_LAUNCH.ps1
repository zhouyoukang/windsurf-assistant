#!/usr/bin/env pwsh
# HOT_LAUNCH.ps1 — 一键热启动 v2 (单入口)
# ============================================================
# 道法自然: 一个守护进程管理一切
#
# hot_guardian.py 负责:
#   - 端口强制 (:19877/:19876 先杀后启)
#   - pool_engine + pool_proxy 崩溃自动重启
#   - extension.js 被覆盖自动重补丁
#   - _pool_apikey.txt 持续更新
#   - 守护状态 API :19875/status
#
# Usage: .\HOT_LAUNCH.ps1
# ============================================================

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python    = "python"

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "  HOT LAUNCH v2 — 一个守护进程管理一切热运行时" -ForegroundColor Cyan
Write-Host "  道法自然: 道生一，一生二，二生三，三生万物" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

# 1. Stop any existing guardian
Write-Host "`n[1] Stopping existing guardian (if any)..." -ForegroundColor Yellow
try { Invoke-WebRequest "http://127.0.0.1:19875/stop" -TimeoutSec 2 -ErrorAction SilentlyContinue | Out-Null } catch {}
Start-Sleep -Seconds 2

# 2. Launch hot_guardian in a new visible window
Write-Host "`n[2] Launching Hot Guardian (全热化总守护进程)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$ScriptDir'; python hot_guardian.py"
) -WindowStyle Normal

Start-Sleep -Seconds 8

# 3. Quick hot-test via guardian API
Write-Host "`n[3] Hot-test results:" -ForegroundColor Yellow
& $Python "$ScriptDir\hot_guardian.py" test

# 4. Also start dao_engine sentinel (predictive switching)
Write-Host "`n[4] Starting Sentinel (预测哨兵)..." -ForegroundColor Yellow
if (Test-Path "$ScriptDir\dao_engine.py") {
    Start-Process powershell -ArgumentList @(
        "-NoExit", "-Command",
        "Set-Location '$ScriptDir'; python dao_engine.py sentinel"
    ) -WindowStyle Minimized
}

Write-Host "`n=================================================================" -ForegroundColor Green
Write-Host "  HOT LAUNCH COMPLETE" -ForegroundColor Green
Write-Host ""
Write-Host "  Guardian API  : http://127.0.0.1:19875/status" -ForegroundColor Cyan
Write-Host "  Pool Engine   : http://127.0.0.1:19877/dashboard" -ForegroundColor Cyan
Write-Host "  Pool Proxy    : http://127.0.0.1:19876/pool/status" -ForegroundColor Cyan
Write-Host "  Key File      : $env:APPDATA\Windsurf\_pool_apikey.txt" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Quick commands:" -ForegroundColor White
Write-Host "    python hot_guardian.py status   # full status" -ForegroundColor Gray
Write-Host "    python hot_guardian.py test     # quick hot-test" -ForegroundColor Gray
Write-Host "    python _e2e_full_test.py        # complete E2E suite" -ForegroundColor Gray
Write-Host ""
Write-Host "  NEXT STEP: Restart Windsurf ONCE to activate the patch." -ForegroundColor Yellow
Write-Host "  AFTER THAT: Zero restarts. Hot switch = file update = <100ms." -ForegroundColor Green
Write-Host "=================================================================" -ForegroundColor Green
