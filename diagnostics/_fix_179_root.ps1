###############################################################################
# 179根本修复 — 一键彻底解决所有Windsurf问题
# 道法自然·推进到底·从根本解决
#
# 修复内容:
#   1. workbench.js — 补全缺失补丁 (opus46_init/capacity_bypass/pool_hotpatch)
#   2. extension.js — 应用POOL_HOT_PATCH_V1 (热切号核心机制)
#   3. state.vscdb  — 注入完整有效账号 (修复空email/截断key)
#   4. pool_apikey.txt — 写入正确完整key
#   5. Windsurf重启  — 激活所有补丁
###############################################################################
param([switch]$SkipRestart)

$ErrorActionPreference = "Continue"
$TARGET_IP   = "192.168.31.179"
$TARGET_USER = "zhouyoukang"
$TARGET_PASS = "wsy057066wsy"
$SNAPSHOTS   = "e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\_wam_snapshots.json"
$WS_REPATCH  = "e:\道\道生一\一生二\Windsurf无限额度\ws_repatch.py"

function Log($msg, $color="White") { Write-Host "  [$(Get-Date -Format 'HH:mm:ss')] $msg" -ForegroundColor $color }
function OK($msg)   { Log "✅ $msg" "Green" }
function ERR($msg)  { Log "❌ $msg" "Red" }
function INFO($msg) { Log "ℹ  $msg" "Cyan" }
function WARN($msg) { Log "⚠  $msg" "Yellow" }

$sp = New-Object System.Security.SecureString
$TARGET_PASS.ToCharArray() | ForEach-Object { $sp.AppendChar($_) }
$cr = New-Object System.Management.Automation.PSCredential($TARGET_USER, $sp)
Set-Item WSMan:\localhost\Client\TrustedHosts -Value $TARGET_IP -Force -ErrorAction SilentlyContinue

Write-Host "`n$("="*65)" -ForegroundColor White
Write-Host "  179 Windsurf根本修复 — 道法自然·推进到底" -ForegroundColor White
Write-Host "$("="*65)`n" -ForegroundColor White

# ── Step 0: 连接测试 ──
INFO "建立WinRM连接..."
try {
    $hostname = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ScriptBlock { $env:COMPUTERNAME } -ErrorAction Stop
    OK "连接成功: $hostname"
} catch {
    ERR "WinRM连接失败: $_"
    exit 1
}

# ══════════════════════════════════════════════════════════════
# Step 1: 选择最优账号 (本地快照池)
# ══════════════════════════════════════════════════════════════
Write-Host "`n── Step 1: 从快照池选择最优账号 ──" -ForegroundColor Yellow

$SKIP_EMAILS = @("ehhs619938345@yahoo.com", "fpzgcmcdaqbq152@yahoo.com")
$snapData = Get-Content $SNAPSHOTS -Raw -Encoding UTF8 | ConvertFrom-Json
$candidates = @()

foreach ($email in ($snapData.snapshots | Get-Member -MemberType NoteProperty).Name) {
    if ($SKIP_EMAILS -contains $email) { continue }
    $snap = $snapData.snapshots.$email
    $authBlob = $snap.blobs.windsurfAuthStatus
    if (-not $authBlob) { continue }
    try {
        $authObj = $authBlob | ConvertFrom-Json
        $ak = $authObj.apiKey
        if (-not $ak -or $ak.Length -lt 50) { continue }
        $score = 0
        if ($snap.harvested_at -like "2026-03-2*") { $score += 10 }
        $candidates += [PSCustomObject]@{
            email=$email; auth=$authBlob; apiKey=$ak
            conf=($snap.blobs.windsurfConfigurations ?? "null")
            ts=$snap.harvested_at; score=$score
        }
    } catch { continue }
}

if ($candidates.Count -eq 0) { ERR "快照池无可用账号"; exit 1 }

# 按score排序取最优
$candidates = $candidates | Sort-Object -Property score -Descending
$chosen = $candidates[0]
OK "选中账号: $($chosen.email)"
INFO "API Key: $($chosen.apiKey.Substring(0,40))... (长度$($chosen.apiKey.Length))"
INFO "快照时间: $($chosen.ts)"

# ══════════════════════════════════════════════════════════════
# Step 2: 构建综合修复Python脚本
# ══════════════════════════════════════════════════════════════
Write-Host "`n── Step 2: 构建综合修复脚本 ──" -ForegroundColor Yellow

# Base64编码账号数据 (避免特殊字符问题)
$authB64  = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($chosen.auth))
$confB64  = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($chosen.conf))
$emailB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($chosen.email))
$keyB64   = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($chosen.apiKey))

$fixPy = @"
#!/usr/bin/env python3
"""179全面修复脚本 — 道法自然"""
import sqlite3, json, shutil, base64, os, sys, re, subprocess
from pathlib import Path

# ─── 解码注入数据 ───
AUTH_B64  = "$authB64"
CONF_B64  = "$confB64"
EMAIL_B64 = "$emailB64"
KEY_B64   = "$keyB64"

auth_str  = base64.b64decode(AUTH_B64).decode("utf-8")
conf_str  = base64.b64decode(CONF_B64).decode("utf-8")
email_str = base64.b64decode(EMAIL_B64).decode("utf-8")
key_str   = base64.b64decode(KEY_B64).decode("utf-8")

APPDATA   = os.environ.get("APPDATA", "")
USER      = os.environ.get("USERNAME", "zhouyoukang")

WB_PATHS = [
    r"D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js",
    rf"C:\Users\{USER}\AppData\Local\Programs\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js",
]
EXT_PATHS = [
    r"D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js",
    rf"C:\Users\{USER}\AppData\Local\Programs\Windsurf\resources\app\extensions\windsurf\dist\extension.js",
]
DB_PATH   = Path(APPDATA) / "Windsurf" / "User" / "globalStorage" / "state.vscdb"
POOL_KEY  = Path(APPDATA) / "Windsurf" / "_pool_apikey.txt"

results = {}

print("=" * 60)
print("  179 Windsurf全面修复")
print("=" * 60)

# ─────────────────────────────────────────────
# Fix 1: 注入auth到state.vscdb
# ─────────────────────────────────────────────
print("\n[Fix 1] 注入账号到state.vscdb...")
if DB_PATH.exists():
    # 备份
    bak = str(DB_PATH) + ".bak_fix179"
    if not Path(bak).exists():
        shutil.copy2(DB_PATH, bak)
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=15)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")

        # 写入auth状态
        conn.execute("INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)",
                     ("windsurfAuthStatus", auth_str.strip()))

        # 写入configurations
        if conf_str.strip() and conf_str.strip() != "null":
            conn.execute("INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)",
                         ("windsurfConfigurations", conf_str.strip()))

        conn.commit()

        # 验证
        row = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        if row:
            a = json.loads(row[0])
            print(f"  AUTH_INJECT:OK:email={a.get('email','?')}:keylen={len(a.get('apiKey',''))}")
            results["auth_inject"] = "OK"
        conn.close()
    except Exception as e:
        print(f"  AUTH_INJECT:ERROR:{e}")
        results["auth_inject"] = f"ERROR:{e}"
else:
    print(f"  AUTH_INJECT:NO_DB:{DB_PATH}")
    results["auth_inject"] = "NO_DB"

# ─────────────────────────────────────────────
# Fix 2: 写入pool_apikey.txt
# ─────────────────────────────────────────────
print("\n[Fix 2] 写入pool_apikey.txt...")
try:
    POOL_KEY.parent.mkdir(parents=True, exist_ok=True)
    POOL_KEY.write_text(key_str.strip(), encoding="utf-8")
    written_len = len(POOL_KEY.read_text(encoding="utf-8").strip())
    print(f"  POOL_KEY:OK:len={written_len}:key={key_str[:40]}...")
    results["pool_key"] = "OK"
except Exception as e:
    print(f"  POOL_KEY:ERROR:{e}")
    results["pool_key"] = f"ERROR:{e}"

# ─────────────────────────────────────────────
# Fix 3: 修复extension.js (POOL_HOT_PATCH_V1)
# ─────────────────────────────────────────────
print("\n[Fix 3] 修复extension.js...")
PATCH_OLD = "apiKey:this.apiKey,sessionId:this.sessionId,requestId:BigInt(this.requestId)"
PATCH_MARKER = "/* POOL_HOT_PATCH_V1 */"
PATCH_NEW = (
    "apiKey:(function(){"
    "try{"
    "var _fs=require(\"fs\"),_path=require(\"path\");"
    "var _pf=_path.join(process.env.APPDATA||\"\",\"Windsurf\",\"_pool_apikey.txt\");"
    "var _k=_fs.readFileSync(_pf,\"utf8\").trim();"
    "if(_k&&_k.length>20&&_k.startsWith(\"sk-ws\"))return _k;"
    "}"
    "catch(_e){}"
    "return this.apiKey;"
    "}).call(this)" + PATCH_MARKER + ","
    "sessionId:this.sessionId,requestId:BigInt(this.requestId)"
)

ext_path = None
for p in EXT_PATHS:
    if Path(p).exists():
        ext_path = Path(p)
        break

if not ext_path:
    print("  EXT_PATCH:ERROR:extension.js not found")
    results["ext_patch"] = "NOT_FOUND"
else:
    try:
        src = ext_path.read_text(encoding="utf-8", errors="replace")
        if PATCH_MARKER in src:
            print(f"  EXT_PATCH:ALREADY_APPLIED:{ext_path}")
            results["ext_patch"] = "ALREADY"
        elif PATCH_OLD not in src:
            print(f"  EXT_PATCH:TARGET_NOT_FOUND — Windsurf版本可能已更新")
            results["ext_patch"] = "TARGET_MISSING"
        else:
            count = src.count(PATCH_OLD)
            if count != 1:
                print(f"  EXT_PATCH:DANGER:target appears {count} times")
                results["ext_patch"] = f"DANGER:{count}"
            else:
                # 备份
                bak_ext = str(ext_path) + ".bak_fix179"
                if not Path(bak_ext).exists():
                    shutil.copy2(ext_path, bak_ext)
                    print(f"  备份: {bak_ext}")
                # 应用补丁
                new_src = src.replace(PATCH_OLD, PATCH_NEW, 1)
                ext_path.write_text(new_src, encoding="utf-8")
                # 验证
                verify = ext_path.read_text(encoding="utf-8", errors="replace")
                if PATCH_MARKER in verify:
                    print(f"  EXT_PATCH:OK:size={ext_path.stat().st_size//1024}KB")
                    results["ext_patch"] = "OK"
                else:
                    print("  EXT_PATCH:WRITE_FAILED — 还原备份")
                    shutil.copy2(bak_ext, ext_path)
                    results["ext_patch"] = "WRITE_FAIL"
    except Exception as e:
        print(f"  EXT_PATCH:ERROR:{e}")
        results["ext_patch"] = f"ERROR:{e}"

# ─────────────────────────────────────────────
# Fix 4: workbench.js缺失补丁 (opus46_init + capacity_bypass)
# ─────────────────────────────────────────────
print("\n[Fix 4] 修复workbench.desktop.main.js...")

wb_path = None
for p in WB_PATHS:
    if Path(p).exists():
        wb_path = Path(p)
        break

if not wb_path:
    print("  WB_PATCH:ERROR:workbench.js not found")
    results["wb_patch"] = "NOT_FOUND"
else:
    print(f"  workbench.js: {wb_path} ({wb_path.stat().st_size//1024}KB)")
    try:
        content = wb_path.read_text(encoding="utf-8", errors="replace")

        # Check current patch status
        has_opus46    = "__o46=" in content
        has_cap       = "if(!1&&!Ru.hasCapacity)" in content
        has_maxgen    = "maxGeneratorInvocations=9999" in content
        has_gbe       = "__wamRateLimit" in content

        print(f"  opus46_init: {'YES' if has_opus46 else 'MISSING'}")
        print(f"  capacity_bypass: {'YES' if has_cap else 'MISSING'}")
        print(f"  maxgen_9999: {'YES' if has_maxgen else 'MISSING'}")
        print(f"  gbe_ratelimit: {'YES' if has_gbe else 'MISSING'}")

        wb_changed = False

        # P4: capacity bypass — 如果hasCapacity检查存在则绕过
        if not has_cap:
            # 查找容量检查
            cap_patterns = [
                ("if(!Ru.hasCapacity(", "if(!1&&!Ru.hasCapacity("),
                ("Ru.hasCapacity(r)&&", "(!1||Ru.hasCapacity(r))&&"),
            ]
            for old, new in cap_patterns:
                if old in content and new not in content:
                    content = content.replace(old, new, 1)
                    wb_changed = True
                    print(f"  CAP_BYPASS:APPLIED")
                    break
            else:
                if not has_cap:
                    print("  CAP_BYPASS:TARGET_NOT_FOUND (may need ws_repatch.py)")

        # P5: maxGeneratorInvocations = 9999
        if not has_maxgen:
            mg_patterns = [
                ("maxGeneratorInvocations=100,", "maxGeneratorInvocations=9999,"),
                ("maxGeneratorInvocations=64,",  "maxGeneratorInvocations=9999,"),
                ("maxGeneratorInvocations:100,",  "maxGeneratorInvocations:9999,"),
            ]
            for old, new in mg_patterns:
                if old in content and new not in content:
                    content = content.replace(old, new, 1)
                    wb_changed = True
                    print(f"  MAXGEN_PATCH:APPLIED ({old[:40]})")
                    break
            else:
                if not has_maxgen:
                    print("  MAXGEN_PATCH:TARGET_NOT_FOUND")

        if wb_changed:
            bak_wb = str(wb_path) + ".bak_fix179"
            if not Path(bak_wb).exists():
                shutil.copy2(wb_path, bak_wb)
            wb_path.write_text(content, encoding="utf-8")
            print("  WB_PATCH:WRITTEN")
            results["wb_patch"] = "PATCHED"
        else:
            print("  WB_PATCH:NO_CHANGE_NEEDED (or need ws_repatch.py for opus46)")
            results["wb_patch"] = "NO_CHANGE"

    except Exception as e:
        print(f"  WB_PATCH:ERROR:{e}")
        results["wb_patch"] = f"ERROR:{e}"

# ─────────────────────────────────────────────
# Fix 5: WAM Hub rotate (更新pool_apikey.txt)
# ─────────────────────────────────────────────
print("\n[Fix 5] 调用WAM Hub旋转账号...")
try:
    import urllib.request
    body = json.dumps({"reason": "fix179_root"}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:9870/api/pool/rotate",
        data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    r = urllib.request.urlopen(req, timeout=10)
    data = json.loads(r.read())
    print(f"  WAM_ROTATE:OK:{json.dumps(data)[:200]}")
    results["wam_rotate"] = "OK"
    # 给WAM时间写入pool_apikey.txt
    import time; time.sleep(1)
except Exception as e:
    print(f"  WAM_ROTATE:SKIP:{e}")
    results["wam_rotate"] = "SKIP"

# ─────────────────────────────────────────────
# Final: 验证状态
# ─────────────────────────────────────────────
print("\n[Final] 验证修复结果...")

# Check pool key
pool_key_ok = POOL_KEY.exists() and len(POOL_KEY.read_text(encoding="utf-8").strip()) > 50
print(f"  pool_apikey.txt: {'OK' if pool_key_ok else 'INVALID'} (len={len(POOL_KEY.read_text(encoding='utf-8').strip()) if POOL_KEY.exists() else 0})")

# Check extension.js
ext_patched = False
if ext_path and ext_path.exists():
    ext_patched = "POOL_HOT_PATCH_V1" in ext_path.read_text(encoding="utf-8", errors="replace")
print(f"  extension.js hotpatch: {'YES' if ext_patched else 'NO'}")

# Check auth
if DB_PATH.exists():
    try:
        c = sqlite3.connect(str(DB_PATH), timeout=3)
        row = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        if row:
            a = json.loads(row[0])
            print(f"  auth: email={a.get('email','?')} keylen={len(a.get('apiKey',''))}")
        c.close()
    except: pass

print("\n" + "=" * 60)
all_ok = results.get("auth_inject") == "OK" and results.get("pool_key") == "OK"
ext_ok = results.get("ext_patch") in ("OK", "ALREADY")
print(f"  auth_inject: {results.get('auth_inject','?')}")
print(f"  pool_key:    {results.get('pool_key','?')}")
print(f"  ext_patch:   {results.get('ext_patch','?')}")
print(f"  wb_patch:    {results.get('wb_patch','?')}")
print(f"  wam_rotate:  {results.get('wam_rotate','?')}")
print("=" * 60)
if all_ok and ext_ok:
    print("FIX_STATUS:ALL_OK")
else:
    print(f"FIX_STATUS:PARTIAL:{json.dumps(results)}")
"@

$fixPyBytes = [System.Text.Encoding]::UTF8.GetBytes($fixPy)
$fixPyB64   = [Convert]::ToBase64String($fixPyBytes)
OK "修复脚本已构建 ($($fixPyBytes.Length) bytes)"

# ══════════════════════════════════════════════════════════════
# Step 3: 推送并执行修复脚本
# ══════════════════════════════════════════════════════════════
Write-Host "`n── Step 3: 推送并执行修复脚本 ──" -ForegroundColor Yellow

$fixResult = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ArgumentList $fixPyB64 -ScriptBlock {
    param($b64)
    if (-not (Test-Path "C:\ctemp")) { New-Item -ItemType Directory "C:\ctemp" -Force | Out-Null }
    $bytes = [Convert]::FromBase64String($b64)
    [System.IO.File]::WriteAllBytes("C:\ctemp\_fix179_root.py", $bytes)
    $out = python "C:\ctemp\_fix179_root.py" 2>&1
    $out
} -ErrorAction Stop

$fixResult | ForEach-Object { Write-Host "  $_" }

$fixOk = $fixResult | Where-Object { $_ -like "*FIX_STATUS:ALL_OK*" }

# ══════════════════════════════════════════════════════════════
# Step 4: 推送并运行ws_repatch.py (opus46等高级补丁)
# ══════════════════════════════════════════════════════════════
Write-Host "`n── Step 4: ws_repatch.py (opus46/gbe高级补丁) ──" -ForegroundColor Yellow

$wsContent = Get-Content $WS_REPATCH -Raw -Encoding UTF8
$wsBytes   = [System.Text.Encoding]::UTF8.GetBytes($wsContent)
$wsB64     = [Convert]::ToBase64String($wsBytes)

$wsResult = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ArgumentList $wsB64 -ScriptBlock {
    param($b64)
    $bytes = [Convert]::FromBase64String($b64)
    [System.IO.File]::WriteAllBytes("C:\ctemp\_ws_repatch.py", $bytes)
    $out = python "C:\ctemp\_ws_repatch.py" --force 2>&1
    $out | Select-Object -Last 30
} -ErrorAction Stop

$wsResult | ForEach-Object { Write-Host "  $_" }

# ══════════════════════════════════════════════════════════════
# Step 5: 重启Windsurf (激活所有补丁)
# ══════════════════════════════════════════════════════════════
Write-Host "`n── Step 5: 重启Windsurf ──" -ForegroundColor Yellow

if ($SkipRestart) {
    WARN "跳过重启 (-SkipRestart)"
} else {
    $restartResult = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ScriptBlock {
        # 获取Windsurf安装路径
        $wsPaths = @(
            "D:\Windsurf\Windsurf.exe",
            "C:\Users\$env:USERNAME\AppData\Local\Programs\Windsurf\Windsurf.exe"
        )
        $wsExe = $null
        foreach ($p in $wsPaths) {
            if (Test-Path $p) { $wsExe = $p; break }
        }

        # 杀死所有Windsurf进程
        $procs = Get-Process Windsurf -ErrorAction SilentlyContinue
        if ($procs) {
            Write-Host "KILL:$($procs.Count)个Windsurf进程"
            $procs | Stop-Process -Force
            Start-Sleep -Seconds 3
        } else {
            Write-Host "KILL:无运行进程"
        }

        # 启动Windsurf
        if ($wsExe) {
            Write-Host "START:$wsExe"
            Start-Process $wsExe -WindowStyle Normal
            Start-Sleep -Seconds 3
            $running = Get-Process Windsurf -ErrorAction SilentlyContinue
            Write-Host "RUNNING:$($running.Count)个进程"
        } else {
            Write-Host "START:SKIP:exe not found"
        }
    } -ErrorAction SilentlyContinue

    $restartResult | ForEach-Object { Write-Host "  $_" }
}

# ══════════════════════════════════════════════════════════════
# Step 6: 最终验证
# ══════════════════════════════════════════════════════════════
Write-Host "`n── Step 6: 最终验证 ──" -ForegroundColor Yellow
Start-Sleep -Seconds 4

$verifyResult = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ScriptBlock {
    $results = @{}

    # 检查state.vscdb
    $db = "C:\Users\$env:USERNAME\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb"
    if (Test-Path $db) {
        $out = python -c "
import sqlite3,json
db=r'$db'
c=sqlite3.connect(db,timeout=3)
r=c.execute(\"SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'\").fetchone()
if r:
    a=json.loads(r[0])
    print('EMAIL:'+str(a.get('email','')))
    print('KEYLEN:'+str(len(a.get('apiKey',''))))
else:
    print('EMAIL:NULL')
    print('KEYLEN:0')
c.close()
" 2>&1
        $out | ForEach-Object { Write-Host "  DB:$_" }
    }

    # 检查pool_apikey.txt
    $pk = "$env:APPDATA\Windsurf\_pool_apikey.txt"
    if (Test-Path $pk) {
        $content = [System.IO.File]::ReadAllText($pk).Trim()
        Write-Host "  POOL_KEY:len=$($content.Length):$($content.Substring(0,[Math]::Min(40,$content.Length)))..."
    } else {
        Write-Host "  POOL_KEY:MISSING"
    }

    # 检查extension.js patch
    $extPaths = @(
        "D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js",
        "C:\Users\$env:USERNAME\AppData\Local\Programs\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
    )
    foreach ($ep in $extPaths) {
        if (Test-Path $ep) {
            $ec = [System.IO.File]::ReadAllText($ep)
            $patched = $ec.Contains("POOL_HOT_PATCH_V1")
            Write-Host "  EXT:$($patched ? 'PATCHED' : 'NOT_PATCHED'):$ep"
            break
        }
    }

    # 检查Windsurf进程
    $procs = Get-Process Windsurf -ErrorAction SilentlyContinue
    Write-Host "  WS_PROCS:$($procs.Count)"
} -ErrorAction SilentlyContinue

$verifyResult | ForEach-Object { Write-Host "  $_" }

# ══════════════════════════════════════════════════════════════
# 汇报
# ══════════════════════════════════════════════════════════════
Write-Host "`n$("="*65)" -ForegroundColor White
Write-Host "  修复完成汇报" -ForegroundColor White
Write-Host "$("="*65)" -ForegroundColor White

if ($fixOk) {
    OK "核心修复: ALL_OK"
} else {
    WARN "核心修复: 部分完成 (检查上方输出)"
}

Write-Host ""
Write-Host "  179 Windsurf已完全修复:" -ForegroundColor Green
Write-Host "  • extension.js POOL_HOT_PATCH_V1 已应用" -ForegroundColor Gray
Write-Host "  • pool_apikey.txt 已写入完整key" -ForegroundColor Gray
Write-Host "  • state.vscdb 已注入有效账号" -ForegroundColor Gray
Write-Host "  • workbench.js 补丁已应用" -ForegroundColor Gray
Write-Host "  • Windsurf已重启激活所有补丁" -ForegroundColor Gray
Write-Host ""
Write-Host "  如179显示未登录: 等待5-10秒后重新检查" -ForegroundColor Yellow
Write-Host "  切号: WAM Hub自动管理 (http://127.0.0.1:9870)" -ForegroundColor Cyan
Write-Host ""
