###############################################################################
# 179笔记本 Windsurf自动轮转守护 — 永久解决切号问题
# 道法自然·无为而无不为
#
# 部署方式 (在141台式机上运行一次):
#   powershell -ExecutionPolicy Bypass -File "_auto_rotate_179.ps1" -Install
#
# 手动切号:
#   powershell -ExecutionPolicy Bypass -File "_auto_rotate_179.ps1"
#
# 逻辑:
#   1. 检查179上Windsurf的当前账号状态
#   2. 如果需要轮转(quota低或强制), 调用gen_inject_179.py执行切号
#   3. 每3天自动运行一次(计划任务)
###############################################################################
param(
    [switch]$Install,      # 安装为计划任务
    [switch]$Force,        # 强制切号(不检查状态)
    [switch]$Check         # 仅检查状态
)

$ErrorActionPreference = "Continue"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$GEN_SCRIPT       = Join-Path $SCRIPT_DIR "_gen_inject_179.py"
$DIRECT_INJECT    = Join-Path $SCRIPT_DIR "..\040-诊断工具_Diagnostics\direct_inject_179.py"
if (-not (Test-Path $DIRECT_INJECT)) { $DIRECT_INJECT = "C:\Temp\direct_inject_179.py" }
$TARGET_IP  = "192.168.31.179"
$TARGET_USER = "zhouyoukang"
$TARGET_PASS = "wsy057066wsy"
$TASK_NAME  = "WS179AutoRotate"

function Log($msg) { Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $msg" }

# ── 安装计划任务 ──
if ($Install) {
    $thisScript = $MyInvocation.MyCommand.Path
    $pythonExe  = (Get-Command python -ErrorAction SilentlyContinue)?.Source
    $trigger = New-ScheduledTaskTrigger -Daily -At "03:00" -DaysInterval 3
    $action  = New-ScheduledTaskAction -Execute "powershell" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$thisScript`"" `
        -WorkingDirectory $SCRIPT_DIR
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1) -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName $TASK_NAME -Trigger $trigger -Action $action `
        -Settings $settings -Principal $principal -Force | Out-Null
    Log "计划任务已安装: $TASK_NAME (每3天03:00执行)"
    Log "手动触发: schtasks /run /tn `"$TASK_NAME`""
    exit 0
}

# ── 建立到179的PS会话 ──
$sp = New-Object System.Security.SecureString
$TARGET_PASS.ToCharArray() | ForEach-Object { $sp.AppendChar($_) }
$cr = New-Object System.Management.Automation.PSCredential($TARGET_USER, $sp)

function Get179Status {
    try {
        $result = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ScriptBlock {
            python -c "
import sqlite3, json, sys
db = r'C:\Users\zhouyoukang\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
try:
    c = sqlite3.connect(db, timeout=3)
    r = c.execute('SELECT value FROM ItemTable WHERE key=?', ('windsurfAuthStatus',)).fetchone()
    if r:
        a = json.loads(r[0])
        ak = a.get('apiKey','')
        print(ak[:60])
    else:
        print('NULL')
    c.close()
except:
    print('ERROR')
" 2>&1
        } -ErrorAction Stop
        return $result.Trim()
    } catch {
        return "UNREACHABLE"
    }
}

# ── 检查状态 ──
if ($Check) {
    Log "检查179 Windsurf状态..."
    $apiKey = Get179Status
    Log "当前apiKey: $($apiKey.Substring(0, [Math]::Min(50, $apiKey.Length)))..."
    exit 0
}

# ── 执行轮转 ──
Log "=== 179 Windsurf账号自动轮转 ==="

if (-not $Force) {
    Log "检查当前状态..."
    $apiKey = Get179Status
    if ($apiKey -eq "UNREACHABLE") {
        Log "SKIP: 179不可达"
        exit 0
    }
    Log "当前apiKey: $($apiKey.Substring(0, [Math]::Min(40, $apiKey.Length)))..."
    # 这里可以加更智能的判断(比如查询quota%), 暂时每次都轮转
}

Log "执行账号轮转..."
Set-Item WSMan:\localhost\Client\TrustedHosts -Value $TARGET_IP -Force -ErrorAction SilentlyContinue

# Strategy 1: Use 179 butler hub /api/pool/rotate (最佳 — butler S-DIRECT自动注入)
$hubRotated = $false
try {
    $sp2 = New-Object System.Security.SecureString
    $TARGET_PASS.ToCharArray() | ForEach-Object { $sp2.AppendChar($_) }
    $cr2 = New-Object System.Management.Automation.PSCredential($TARGET_USER, $sp2)
    $hubResult = Invoke-Command -ComputerName $TARGET_IP -Credential $cr2 -ScriptBlock {
        try {
            $r = Invoke-WebRequest "http://127.0.0.1:9870/api/pool/rotate" -Method POST `
                -Body "{}" -ContentType "application/json" -UseBasicParsing -TimeoutSec 30
            return ($r.Content | ConvertFrom-Json)
        } catch { return $null }
    } -ErrorAction Stop
    if ($hubResult -and $hubResult.ok) {
        Log "Strategy1 Hub rotate OK: method=$($hubResult.method)"
        $hubRotated = $true
    } else {
        Log "Strategy1 Hub rotate failed: $($hubResult.error)"
    }
} catch {
    Log "Strategy1 unreachable: $_"
}

# Strategy 2: direct_inject_179.py from 141 pool DB (降级 — 绕过hub直接注入)
if (-not $hubRotated) {
    Log "Strategy2: direct inject from 141 pool..."
    if (Test-Path $DIRECT_INJECT) {
        python $DIRECT_INJECT
        if ($LASTEXITCODE -eq 0) {
            Log "Strategy2 direct inject OK"
            $hubRotated = $true
        } else {
            Log "Strategy2 direct inject failed"
        }
    } else {
        Log "Strategy2 script not found: $DIRECT_INJECT"
    }
}

# Strategy 3: legacy _gen_inject_179.py (最后降级)
if (-not $hubRotated -and (Test-Path $GEN_SCRIPT)) {
    Log "Strategy3: legacy gen_inject..."
    python $GEN_SCRIPT
    if ($LASTEXITCODE -eq 0) { Log "Strategy3 OK" } else { Log "Strategy3 FAILED" }
}

if ($hubRotated) {
    Log "轮转成功!"
} else {
    Log "轮转失败 — 所有策略均失败"
}
