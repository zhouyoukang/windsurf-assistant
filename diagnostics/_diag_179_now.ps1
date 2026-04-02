###############################################################################
# 179实时诊断 — API key not found根因分析 + 自动修复
###############################################################################
param([switch]$FixOnly, [switch]$DiagOnly)

$ErrorActionPreference = "Continue"
$TARGET_IP   = "192.168.31.179"
$TARGET_USER = "zhouyoukang"
$TARGET_PASS = "wsy057066wsy"

$sp = New-Object System.Security.SecureString
$TARGET_PASS.ToCharArray() | ForEach-Object { $sp.AppendChar($_) }
$cr = New-Object System.Management.Automation.PSCredential($TARGET_USER, $sp)

Set-Item WSMan:\localhost\Client\TrustedHosts -Value $TARGET_IP -Force -ErrorAction SilentlyContinue

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  179 Windsurf诊断 — $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Step1: 连通性
Write-Host "`n[1] 测试WinRM连接..." -ForegroundColor Yellow
try {
    $ping = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ScriptBlock { $env:COMPUTERNAME } -ErrorAction Stop
    Write-Host "  连接成功: $ping" -ForegroundColor Green
} catch {
    Write-Host "  [ERR] WinRM连接失败: $_" -ForegroundColor Red
    exit 1
}

# Step2: 读取当前状态
Write-Host "`n[2] 读取179 state.vscdb..." -ForegroundColor Yellow

$diagScript = @'
import sqlite3, json, sys, os
db = r'C:\Users\zhouyoukang\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
if not __import__('os').path.exists(db):
    print("DB_EXISTS:False")
    sys.exit(0)
print("DB_EXISTS:True")
c = sqlite3.connect(db, timeout=5)
row = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
if not row:
    print("AUTH_STATUS:NULL")
else:
    try:
        a = json.loads(row[0])
        ak = a.get("apiKey","")
        em = a.get("email","")
        print("EMAIL:" + str(em))
        print("APIKEY_LEN:" + str(len(ak)))
        print("APIKEY_PREVIEW:" + str(ak[:60]))
        print("AUTH_STATUS:FOUND")
    except Exception as e:
        print("PARSE_ERR:" + str(e)[:100])
c.close()
'@

# 将诊断脚本写到临时文件
$diagScriptB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($diagScript))

$result = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ArgumentList $diagScriptB64 -ScriptBlock {
    param($b64)
    $tmp = "C:\ctemp\diag_ws.py"
    if (-not (Test-Path "C:\ctemp")) { New-Item -ItemType Directory "C:\ctemp" -Force | Out-Null }
    $bytes = [Convert]::FromBase64String($b64)
    [System.IO.File]::WriteAllBytes($tmp, $bytes)
    $out = python $tmp 2>&1
    $out
} -ErrorAction Stop

Write-Host "  $result" -ForegroundColor White

$apiKeyLen = ($result | Where-Object { $_ -like "APIKEY_LEN:*" }) -replace "APIKEY_LEN:",""
$apiKeyPreview = ($result | Where-Object { $_ -like "APIKEY_PREVIEW:*" }) -replace "APIKEY_PREVIEW:",""
$email = ($result | Where-Object { $_ -like "EMAIL:*" }) -replace "EMAIL:",""
$authFound = ($result | Where-Object { $_ -eq "AUTH_STATUS:FOUND" })

Write-Host ""
Write-Host "  当前账号: $email" -ForegroundColor White
Write-Host "  API Key长度: $apiKeyLen" -ForegroundColor White
Write-Host "  API Key预览: $apiKeyPreview" -ForegroundColor White

# Step3: 判断是否需要修复
$needFix = $false
if (-not $authFound) {
    Write-Host "`n  [!] windsurfAuthStatus为空 — 需要注入" -ForegroundColor Red
    $needFix = $true
} elseif ([int]$apiKeyLen -lt 10) {
    Write-Host "`n  [!] API Key为空或过短 ($apiKeyLen) — 需要注入" -ForegroundColor Red
    $needFix = $true
} else {
    Write-Host "`n  [OK] state.vscdb有效，API Key长度=$apiKeyLen" -ForegroundColor Green
    Write-Host "  [!] Windsurf报错可能是运行时缓存问题，尝试强制reload..." -ForegroundColor Yellow
    $needFix = $true  # 即使有key也尝试重新注入以确保新鲜度
}

if ($DiagOnly) {
    Write-Host "`n[诊断完成 — 跳过修复]" -ForegroundColor Yellow
    exit 0
}

# Step4: 从快照池选账号并注入
Write-Host "`n[3] 从WAM快照池选择最优账号..." -ForegroundColor Yellow
$SNAPSHOTS = "e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\_wam_snapshots.json"

if (-not (Test-Path $SNAPSHOTS)) {
    Write-Host "  [ERR] 快照文件不存在: $SNAPSHOTS" -ForegroundColor Red
    exit 1
}

$snapData = Get-Content $SNAPSHOTS -Raw -Encoding UTF8 | ConvertFrom-Json
$SKIP = @("ehhs619938345@yahoo.com", "fpzgcmcdaqbq152@yahoo.com")

$candidates = @()
$allEmails = $snapData.snapshots | Get-Member -MemberType NoteProperty | Select-Object -ExpandProperty Name
foreach ($em in $allEmails) {
    if ($SKIP -contains $em) { continue }
    $snap = $snapData.snapshots.$em
    $authBlob = $snap.blobs.windsurfAuthStatus
    if (-not $authBlob) { continue }
    try {
        $authObj = $authBlob | ConvertFrom-Json
        $ak = $authObj.apiKey
        if ($ak -and $ak.Length -gt 20) {
            $candidates += [PSCustomObject]@{
                email    = $em
                apiKey   = $ak
                authBlob = $authBlob
                confBlob = $snap.blobs.windsurfConfigurations
                harvestAt = $snap.harvested_at
            }
        }
    } catch {}
}

Write-Host "  可用账号数: $($candidates.Count)" -ForegroundColor White

if ($candidates.Count -eq 0) {
    Write-Host "  [ERR] 没有可用账号！" -ForegroundColor Red
    exit 1
}

# 优先选最新收割的
$chosen = $candidates | Sort-Object harvestAt -Descending | Select-Object -First 1
Write-Host "  选中: $($chosen.email)" -ForegroundColor Green
Write-Host "  收割时间: $($chosen.harvestAt)" -ForegroundColor Gray
Write-Host "  API Key: $($chosen.apiKey.Substring(0,[Math]::Min(50,$chosen.apiKey.Length)))..." -ForegroundColor Gray

# Step5: 构建注入脚本
Write-Host "`n[4] 注入到179 state.vscdb..." -ForegroundColor Yellow

$authBlobEsc  = $chosen.authBlob
$confBlobVal  = if ($chosen.confBlob) { $chosen.confBlob } else { "" }

# 通过base64传输避免引号冲突
$injectPy = @"
import sqlite3, json, sys
db = r'C:\Users\zhouyoukang\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
import base64
status_b64 = '$([Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($authBlobEsc)))'
conf_b64   = '$([Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($confBlobVal)))'
status_val = base64.b64decode(status_b64).decode('utf-8')
conf_val   = base64.b64decode(conf_b64).decode('utf-8')
c = sqlite3.connect(db, timeout=10)
c.execute("INSERT OR REPLACE INTO ItemTable (key,value) VALUES (?,?)", ('windsurfAuthStatus', status_val))
if conf_val.strip() and conf_val.strip() != 'null':
    c.execute("INSERT OR REPLACE INTO ItemTable (key,value) VALUES (?,?)", ('windsurfConfigurations', conf_val))
c.execute("DELETE FROM ItemTable WHERE key='cachedPlanInfo'")
c.execute("DELETE FROM ItemTable WHERE key='windsurfMachineId'")
c.commit()
# Verify
r = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
if r:
    a = json.loads(r[0])
    ak = a.get('apiKey','')
    print('INJECT_OK:email=' + a.get('email','?') + ' apiKey=' + ak[:40])
else:
    print('INJECT_FAIL:row not found')
c.close()
"@

$injectB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($injectPy))

$injectResult = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ArgumentList $injectB64 -ScriptBlock {
    param($b64)
    $tmp = "C:\ctemp\inject_ws_now.py"
    if (-not (Test-Path "C:\ctemp")) { New-Item -ItemType Directory "C:\ctemp" -Force | Out-Null }
    $bytes = [Convert]::FromBase64String($b64)
    [System.IO.File]::WriteAllBytes($tmp, $bytes)
    $out = python $tmp 2>&1
    $out
} -ErrorAction Stop

Write-Host "  $injectResult" -ForegroundColor White

$injOk = ($injectResult | Where-Object { $_ -like "INJECT_OK:*" })
if ($injOk) {
    Write-Host "`n  [OK] 注入成功: $injOk" -ForegroundColor Green
} else {
    Write-Host "`n  [ERR] 注入失败！输出: $injectResult" -ForegroundColor Red
    exit 1
}

# Step6: 重启Windsurf (kill + start)
Write-Host "`n[5] 重启Windsurf on 179..." -ForegroundColor Yellow
$restartResult = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ScriptBlock {
    # Kill all Windsurf
    $ws = Get-Process Windsurf -ErrorAction SilentlyContinue
    if ($ws) {
        $ws | Stop-Process -Force
        Start-Sleep -Seconds 2
        Write-Host "KILLED:" + $ws.Count + " processes"
    } else {
        Write-Host "NOT_RUNNING:no Windsurf process"
    }
    
    # Find Windsurf executable
    $wsCandidates = @(
        "D:\Windsurf\Windsurf.exe",
        "C:\Users\zhouyoukang\AppData\Local\Programs\Windsurf\Windsurf.exe"
    )
    $wsExe = $null
    foreach ($p in $wsCandidates) {
        if (Test-Path $p) { $wsExe = $p; break }
    }
    
    if ($wsExe) {
        Start-Process $wsExe
        Write-Host "STARTED:$wsExe"
    } else {
        Write-Host "NO_EXE:Windsurf executable not found"
    }
} -ErrorAction Stop

Write-Host "  $restartResult" -ForegroundColor White

# Step7: 最终验证
Start-Sleep -Seconds 3
Write-Host "`n[6] 最终验证..." -ForegroundColor Yellow
$finalVerify = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ScriptBlock {
    python -c "
import sqlite3, json
db = r'C:\Users\zhouyoukang\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
c = sqlite3.connect(db, timeout=3)
r = c.execute(\"SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'\").fetchone()
if r:
    a = json.loads(r[0])
    print('FINAL:email=' + a.get('email','?') + ' apiKey_len=' + str(len(a.get('apiKey',''))))
else:
    print('FINAL:NULL')
c.close()
" 2>&1
} -ErrorAction Stop

Write-Host "  $finalVerify" -ForegroundColor Cyan

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  完成！Windsurf已重启并注入新账号" -ForegroundColor Green
Write-Host "  账号: $($chosen.email)" -ForegroundColor Green
Write-Host "  在179上: Ctrl+Shift+P -> Reload Window" -ForegroundColor Yellow
Write-Host "========================================`n" -ForegroundColor Green
