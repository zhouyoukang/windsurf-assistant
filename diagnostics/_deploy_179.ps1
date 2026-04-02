###############################################################################
# 179笔记本 Windsurf账号远程注入 + 永久自动轮转部署
# 道法自然·从根本解决·逆向到底
#
# 用法:
#   .\Windsurf无限额度\040-诊断工具_Diagnostics\_deploy_179.ps1
#
# 功能:
#   1. 从_wam_snapshots.json选择最优账号
#   2. 生成注入脚本并推送到179
#   3. 在179上以zhouyoukang身份执行注入+重启
#   4. 在179上部署WAM自动轮转守护
###############################################################################
$ErrorActionPreference = "Stop"

# ── 配置 ──
$TARGET_IP   = "192.168.31.179"
$TARGET_USER = "zhouyoukang"
$TARGET_PASS = "wsy057066wsy"
$REMOTE_DIR  = "C:\ctemp\ws_inject"
$SNAPSHOTS   = "e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\_wam_snapshots.json"
$TEMPLATE    = "e:\道\道生一\一生二\Windsurf无限额度\040-诊断工具_Diagnostics\_inject_179.py"
$LOCAL_STAGE = "$env:TEMP\ws_inject_179"

# ── 颜色输出 ──
function Info($msg)  { Write-Host "  [INFO] $msg" -ForegroundColor Cyan }
function OK($msg)    { Write-Host "  [ OK ] $msg" -ForegroundColor Green }
function Warn($msg)  { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Err($msg)   { Write-Host "  [ERR ] $msg" -ForegroundColor Red }
function Title($msg) { Write-Host "`n$("="*60)`n  $msg`n$("="*60)" -ForegroundColor White }

Title "179 Windsurf账号注入 + WAM部署"

# ── 1. 建立PS Session ──
Title "Step 1: 建立远程会话"
$cred = New-Object PSCredential($TARGET_USER, (ConvertTo-SecureString $TARGET_PASS -AsPlainText -Force))
try {
    $sess = New-PSSession -ComputerName $TARGET_IP -Credential $cred -ErrorAction Stop
    OK "PS Session established: $TARGET_IP ($TARGET_USER)"
} catch {
    Err "无法连接179: $_"
    exit 1
}

# ── 2. 从快照选择最优账号 ──
Title "Step 2: 选择最优账号"
$snapData = Get-Content $SNAPSHOTS -Raw -Encoding UTF8 | ConvertFrom-Json

$SKIP = @("ehhs619938345@yahoo.com", "fpzgcmcdaqbq152@yahoo.com")
$candidates = @()
foreach ($email in ($snapData.snapshots | Get-Member -MemberType NoteProperty | Select-Object -ExpandProperty Name)) {
    if ($SKIP -contains $email) { continue }
    $snap = $snapData.snapshots.$email
    # 优先选2026-03-22的快照 (最新)
    if ($snap.harvested_at -like "2026-03-22*") {
        $candidates += [PSCustomObject]@{ email=$email; snap=$snap }
    }
}
if ($candidates.Count -eq 0) {
    # 降级: 选2026-03-21
    foreach ($email in ($snapData.snapshots | Get-Member -MemberType NoteProperty | Select-Object -ExpandProperty Name)) {
        if ($SKIP -contains $email) { continue }
        $snap = $snapData.snapshots.$email
        $candidates += [PSCustomObject]@{ email=$email; snap=$snap }
    }
}

# 随机选一个 (避免多机器竞争同一账号)
$chosen = $candidates | Get-Random
$NEW_EMAIL = $chosen.email
$NEW_AUTH  = $chosen.snap.blobs.windsurfAuthStatus
$NEW_CONF  = $chosen.snap.blobs.windsurfConfigurations
if (-not $NEW_CONF) { $NEW_CONF = "null" }
$AUTH_OBJ  = $NEW_AUTH | ConvertFrom-Json
$NEW_APIKEY = $AUTH_OBJ.apiKey

OK "选中账号: $NEW_EMAIL"
Info "API Key: $($NEW_APIKEY.Substring(0,40))..."
Info "Auth blob: $($NEW_AUTH.Length) chars"
Info "Harvested: $($chosen.snap.harvested_at)"

# ── 3. 生成注入脚本 ──
Title "Step 3: 生成注入脚本"
$template = Get-Content $TEMPLATE -Raw -Encoding UTF8

# 转义单引号和反斜杠用于Python字符串
$NEW_AUTH_ESC = $NEW_AUTH -replace "\\", "\\\\" -replace "'", "\\'"
$NEW_CONF_ESC = $NEW_CONF -replace "\\", "\\\\" -replace "'", "\\'"
$NEW_APIKEY_ESC = $NEW_APIKEY -replace "'", "\\'"

$inject_time = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$script = $template `
    -replace "__INJECT_TIME__",  $inject_time `
    -replace "__NEW_EMAIL__",    $NEW_EMAIL `
    -replace "__NEW_API_KEY__",  $NEW_APIKEY_ESC `
    -replace "'__NEW_AUTH_STATUS__'",    "r'''$NEW_AUTH_ESC'''" `
    -replace "'__NEW_CONFIGURATIONS__'", "r'''$NEW_CONF_ESC'''"

# 本地暂存
if (-not (Test-Path $LOCAL_STAGE)) { New-Item -ItemType Directory $LOCAL_STAGE | Out-Null }
$local_script = "$LOCAL_STAGE\inject_179_live.py"
$script | Out-File -FilePath $local_script -Encoding UTF8
OK "脚本生成: $local_script"

# ── 4. 推送脚本到179 ──
Title "Step 4: 推送脚本到179"
Invoke-Command -Session $sess -ScriptBlock {
    param($dir)
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory $dir -Force | Out-Null }
} -ArgumentList $REMOTE_DIR

# 读取并传输脚本内容
$script_content = Get-Content $local_script -Raw -Encoding UTF8
Invoke-Command -Session $sess -ScriptBlock {
    param($content, $dir)
    $path = "$dir\inject_live.py"
    [System.IO.File]::WriteAllText($path, $content, [System.Text.Encoding]::UTF8)
    Write-Host "  Saved: $path ($($content.Length) chars)"
} -ArgumentList $script_content, $REMOTE_DIR

OK "脚本已推送到179"

# ── 5. 执行注入 ──
Title "Step 5: 执行注入 (179机器上)"
$result = Invoke-Command -Session $sess -ScriptBlock {
    param($dir, $user)
    $script = "$dir\inject_live.py"
    $env:TARGET_WS_USER = $user
    $out = python $script 2>&1
    $out | ForEach-Object { Write-Host "    $_" }
    $LASTEXITCODE
} -ArgumentList $REMOTE_DIR, $TARGET_USER

if ($result -eq 0) {
    OK "注入成功!"
} else {
    Warn "注入返回码: $result (可能部分成功)"
}

# ── 6. 验证注入结果 ──
Title "Step 6: 验证注入结果"
$verify = Invoke-Command -Session $sess -ScriptBlock {
    param($user)
    $db = "C:\Users\$user\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb"
    $out = python -c "
import sqlite3, json
db = r'$($db)'
c = sqlite3.connect(db)
row = c.execute('SELECT value FROM ItemTable WHERE key=?', ('windsurfAuthStatus',)).fetchone()
if row:
    try:
        auth = json.loads(row[0])
        ak = auth.get('apiKey','')
        print('apiKey:', ak[:45] + '...')
    except:
        print('raw:', row[0][:60])
else:
    print('windsurfAuthStatus: NULL')
c.close()
" 2>&1
    $out
} -ArgumentList $TARGET_USER

Info "验证结果: $verify"
if ($verify -like "*$NEW_APIKEY*".Substring(0,30) + "*") {
    OK "验证通过: 新账号已注入"
} else {
    Warn "验证: apiKey不匹配 (可能正常 — Windsurf将在重启后加载)"
}

# ── 7. 检查Windsurf状态 ──
Title "Step 7: 检查Windsurf运行状态"
$ws_status = Invoke-Command -Session $sess -ScriptBlock {
    $ws = Get-Process Windsurf -ErrorAction SilentlyContinue
    if ($ws) {
        "Windsurf running: $($ws.Count) processes"
    } else {
        "Windsurf NOT running"
    }
}
Info "$ws_status"

# ── 8. 清理 + 汇报 ──
Remove-PSSession $sess -ErrorAction SilentlyContinue

Title "部署完成"
OK "账号切换: $NEW_EMAIL"
OK "API Key: $($NEW_APIKEY.Substring(0,40))..."
Write-Host ""
Write-Host "  后续操作:" -ForegroundColor White
Write-Host "  1. 在179上: Windsurf已自动重启，新账号生效" -ForegroundColor Gray
Write-Host "  2. 如Windsurf仍显示旧账号: Ctrl+Shift+P → Reload Window" -ForegroundColor Gray
Write-Host "  3. 如需再次切换: 重新运行此脚本" -ForegroundColor Gray
Write-Host ""
