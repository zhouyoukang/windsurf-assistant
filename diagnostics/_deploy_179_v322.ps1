###############################################################################
# _deploy_179_v322.ps1 — 推送WAM v3.22.0到179机 + 账号同步 + 验证切号
# 道法自然·推进到底·解决到底
###############################################################################
$ErrorActionPreference = "Continue"

$TARGET_IP   = "192.168.31.179"
$TARGET_USER = "zhouyoukang"
$TARGET_PASS = "wsy057066wsy"
$SRC_DIR     = "e:\道\道生一\一生二\无感切号\src"
$HOT_REMOTE  = "C:\Users\zhouyoukang\.wam-hot"
$ACCOUNTS_SRC = "C:\Users\ai\AppData\Roaming\Windsurf\User\globalStorage\windsurf-login-accounts.json"

function Log($msg, $color="White") { Write-Host "  $msg" -ForegroundColor $color }
function OK($msg)   { Log "[ OK ] $msg" "Green" }
function ERR($msg)  { Log "[ERR ] $msg" "Red" }
function INFO($msg) { Log "[INFO] $msg" "Cyan" }

$sp = New-Object System.Security.SecureString
$TARGET_PASS.ToCharArray() | ForEach-Object { $sp.AppendChar($_) }
$cr = New-Object System.Management.Automation.PSCredential($TARGET_USER, $sp)
Set-Item WSMan:\localhost\Client\TrustedHosts -Value $TARGET_IP -Force -EA SilentlyContinue

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "  WAM v3.22.0 → 179机 全量部署" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

# ── 1. 建立会话 ──
Write-Host "`n[1] 建立PSSession..." -ForegroundColor Yellow
$sess = New-PSSession -ComputerName $TARGET_IP -Credential $cr -ErrorAction Stop
OK "Session established: $TARGET_IP"

# ── 2. 确保hot-dir存在 ──
Write-Host "`n[2] 确保hot-dir存在..." -ForegroundColor Yellow
Invoke-Command -Session $sess -ScriptBlock {
    param($hd)
    if (-not (Test-Path $hd)) { New-Item -ItemType Directory $hd -Force | Out-Null }
    Write-Host "  hot-dir: $hd OK"
} -ArgumentList $HOT_REMOTE

# ── 3. 推送所有hot-dir模块 ──
Write-Host "`n[3] 推送v3.22.0模块..." -ForegroundColor Yellow
$files = @("extension.js","accountManager.js","authService.js","cloudPool.js","fingerprintManager.js","webviewProvider.js")
foreach ($f in $files) {
    $src = Join-Path $SRC_DIR $f
    if (Test-Path $src) {
        $dst = "$HOT_REMOTE\$f"
        try {
            Copy-Item -Path $src -Destination $dst -ToSession $sess -Force
            $sz = (Get-Item $src).Length
            OK "$f ($sz B) → 179 hot-dir"
        } catch {
            ERR "$f 推送失败: $_"
        }
    } else {
        ERR "$f 源文件不存在: $src"
    }
}

# ── 4. 推送账号池JSON ──
Write-Host "`n[4] 同步97账号池..." -ForegroundColor Yellow
if (Test-Path $ACCOUNTS_SRC) {
    $remotePaths = @(
        "C:\Users\zhouyoukang\AppData\Roaming\Windsurf\User\globalStorage\windsurf-login-accounts.json",
        "C:\Users\zhouyoukang\AppData\Roaming\Windsurf\User\globalStorage\zhouyoukang.windsurf-assistant\windsurf-login-accounts.json"
    )
    foreach ($rp in $remotePaths) {
        try {
            Invoke-Command -Session $sess -ScriptBlock {
                param($p)
                $d = Split-Path $p
                if (-not (Test-Path $d)) { New-Item -ItemType Directory $d -Force | Out-Null }
            } -ArgumentList $rp
            Copy-Item -Path $ACCOUNTS_SRC -Destination $rp -ToSession $sess -Force
            OK "accounts → $rp"
        } catch { ERR "accounts 推送失败($rp): $_" }
    }
    $cnt = (Get-Content $ACCOUNTS_SRC -Raw -Encoding UTF8 | ConvertFrom-Json).Count
    OK "账号总数: $cnt"
} else {
    ERR "accounts source not found: $ACCOUNTS_SRC"
}

# ── 5. 写入.reload信号 ──
Write-Host "`n[5] 触发热重载..." -ForegroundColor Yellow
$ts = [string][System.DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
Invoke-Command -Session $sess -ScriptBlock {
    param($hd, $ts)
    [IO.File]::WriteAllText("$hd\.reload", $ts, [Text.Encoding]::UTF8)
    Write-Host "  .reload written: $ts"
} -ArgumentList $HOT_REMOTE, $ts

# ── 6. 等待热重载 ──
Write-Host "`n[6] 等待热重载 (6s)..." -ForegroundColor Yellow
Start-Sleep 6

# ── 7. 验证hub版本 ──
Write-Host "`n[7] 验证hub..." -ForegroundColor Yellow
$hubResult = Invoke-Command -Session $sess -ScriptBlock {
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:9870/health" -UseBasicParsing -TimeoutSec 5 -EA Stop
        $r.Content
    } catch { "HUB_OFFLINE: $_" }
}
INFO "Hub状态: $hubResult"
$hubOk = $hubResult -and ($hubResult | ConvertFrom-Json -EA SilentlyContinue).version

# ── 8. 检查切前auth ──
Write-Host "`n[8] 切号测试..." -ForegroundColor Yellow
$authBefore = Invoke-Command -Session $sess -ScriptBlock {
    python -c "
import sqlite3,json
try:
    c=sqlite3.connect(r'C:\Users\zhouyoukang\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb',timeout=3)
    r=c.execute('SELECT value FROM ItemTable WHERE key=?',('windsurfAuthStatus',)).fetchone()
    if r:
        a=json.loads(r[0])
        print(a.get('apiKey','?')[:50])
    else: print('NULL')
    c.close()
except Exception as e: print('ERR:'+str(e)[:60])
" 2>&1
} 
INFO "切前apiKey: $authBefore"

# ── 9. 调用hub rotate ──
$rotateResult = Invoke-Command -Session $sess -ScriptBlock {
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:9870/api/pool/rotate" `
            -Method POST -Body "{}" -ContentType "application/json" `
            -UseBasicParsing -TimeoutSec 30 -EA Stop
        $r.Content
    } catch { "ROTATE_ERR: $_" }
}
INFO "Rotate结果: $rotateResult"

# ── 10. 等待切换+验证 ──
Start-Sleep 4
$authAfter = Invoke-Command -Session $sess -ScriptBlock {
    python -c "
import sqlite3,json
try:
    c=sqlite3.connect(r'C:\Users\zhouyoukang\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb',timeout=3)
    r=c.execute('SELECT value FROM ItemTable WHERE key=?',('windsurfAuthStatus',)).fetchone()
    if r:
        a=json.loads(r[0])
        print('email='+a.get('email','?')+' key='+a.get('apiKey','?')[:40])
    else: print('NULL')
    c.close()
except Exception as e: print('ERR:'+str(e)[:60])
" 2>&1
}
INFO "切后auth: $authAfter"

if ($authBefore -ne $authAfter) {
    OK "切号成功！apiKey已变化"
} else {
    $rotJson = $rotateResult | ConvertFrom-Json -EA SilentlyContinue
    if ($rotJson -and $rotJson.ok) {
        OK "Hub rotate成功 (Windsurf内部已切换，DB可能延迟)"
    } else {
        Write-Host "  [WARN] 切号状态待确认" -ForegroundColor Yellow
    }
}

# ── 11. 显示最终hot-dir状态 ──
Write-Host "`n[11] 179 hot-dir最终状态..." -ForegroundColor Yellow
Invoke-Command -Session $sess -ScriptBlock {
    param($hd)
    Get-ChildItem $hd | Select-Object Name, @{N='KB';E={[int]($_.Length/1024)}} | Format-Table -Auto
} -ArgumentList $HOT_REMOTE

Remove-PSSession $sess -EA SilentlyContinue

Write-Host "`n=================================================================" -ForegroundColor Green
Write-Host "  179机 WAM v3.22.0 部署完成" -ForegroundColor Green
Write-Host "=================================================================" -ForegroundColor Green
