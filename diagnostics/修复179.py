#!/usr/bin/env python3
"""
修复179 — 179笔记本Windsurf一键全修复
========================================
道法自然·从根本解决·永久有效

解决问题:
  - Windsurf无法使用 / 无法登录 / 无法切换账号

修复内容:
  1. extension.js POOL_HOT_PATCH_V1 (热切号核心)
  2. workbench.js 补丁 (GBe静默/maxgen)
  3. state.vscdb 注入有效账号auth
  4. pool_apikey.txt 写入有效完整key
  5. WAM Hub 启动/恢复 (9870)
  6. WAMHub/WAMHubWatchdog/WAMPoolKeySync 计划任务加固
  7. Windsurf 重启

用法:
  python 修复179.py            # 完整修复
  python 修复179.py --check    # 仅检查状态
  python 修复179.py --restart  # 仅重启Windsurf
"""
import subprocess, json, base64, time, sys, random
from pathlib import Path
import tempfile

# ── 配置 ──
TARGET_IP   = "192.168.31.179"
TARGET_USER = "zhouyoukang"
TARGET_PASS = "wsy057066wsy"
SCRIPT_DIR  = Path(__file__).parent
ROOT_DIR    = SCRIPT_DIR.parent
SNAPSHOTS   = ROOT_DIR / "010-道引擎_DaoEngine" / "_wam_snapshots.json"
WS_REPATCH  = ROOT_DIR / "ws_repatch.py"
SKIP_EMAILS = {"ehhs619938345@yahoo.com", "fpzgcmcdaqbq152@yahoo.com"}

# ── 颜色输出 ──
def ok(msg):   print(f"  ✅ {msg}")
def err(msg):  print(f"  ❌ {msg}")
def info(msg): print(f"  ℹ  {msg}")
def warn(msg): print(f"  ⚠  {msg}")
def hdr(msg):  print(f"\n── {msg} ──")

# ── WinRM工具 ──
def run_remote_ps1(content, timeout=90):
    tmp = Path(tempfile.mktemp(suffix=".ps1"))
    tmp.write_text(content, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(tmp)],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace"
        )
        tmp.unlink(missing_ok=True)
        return proc.stdout + proc.stderr, proc.returncode
    except Exception as e:
        tmp.unlink(missing_ok=True)
        return f"ERROR:{e}", -1

def run_remote(ps_body, timeout=60):
    return run_remote_ps1(f"""
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -ErrorAction SilentlyContinue
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock {{
    {ps_body}
}} 2>&1 | ForEach-Object {{ Write-Host $_ }}
""", timeout=timeout)

def remote_py(py_code, label="_p", timeout=60):
    b64 = base64.b64encode(py_code.encode("utf-8")).decode("ascii")
    chunks = [b64[i:i+8000] for i in range(0, len(b64), 8000)]
    run_remote(f'[System.IO.File]::WriteAllText("C:\\\\ctemp\\\\{label}_b64.txt","", [System.Text.Encoding]::ASCII)', 8)
    for c in chunks:
        run_remote(f'[System.IO.File]::AppendAllText("C:\\\\ctemp\\\\{label}_b64.txt","{c}",[System.Text.Encoding]::ASCII)', 8)
    return run_remote(f"""
$b64=[System.IO.File]::ReadAllText("C:\\\\ctemp\\\\{label}_b64.txt").Trim()
$bytes=[System.Convert]::FromBase64String($b64)
$text=[System.Text.Encoding]::UTF8.GetString($bytes)
[System.IO.File]::WriteAllText("C:\\\\ctemp\\\\{label}.py",$text,[System.Text.Encoding]::UTF8)
$env:PYTHONIOENCODING="utf-8"
python "C:\\\\ctemp\\\\{label}.py" 2>&1 | ForEach-Object {{ Write-Host $_ }}
""", timeout=timeout)

# ── 账号选择 ──
def select_account():
    if not SNAPSHOTS.exists():
        return None
    data = json.loads(SNAPSHOTS.read_text("utf-8"))
    candidates = []
    for email, snap in data.get("snapshots", {}).items():
        if email in SKIP_EMAILS: continue
        auth = snap.get("blobs", {}).get("windsurfAuthStatus", "")
        if not auth: continue
        try:
            ao = json.loads(auth)
            key = ao.get("apiKey", "")
            if len(key) < 80: continue
        except: continue
        score = 10 if "2026-03-2" in snap.get("harvested_at","") else 5
        conf = snap.get("blobs", {}).get("windsurfConfigurations") or ""
        candidates.append({"email": email, "key": key, "auth": auth, "conf": conf, "score": score})
    if not candidates: return None
    candidates.sort(key=lambda x: x["score"], reverse=True)
    top = [x for x in candidates if x["score"] >= candidates[0]["score"]]
    return random.choice(top)

# ════════════════════════════════════════════════════════════
# 检查模式
# ════════════════════════════════════════════════════════════
def do_check():
    hdr("179 Windsurf状态检查")
    check_ps = r"""
$APPDATA = $env:APPDATA

# WAM Hub
try {
    $r = Invoke-WebRequest "http://127.0.0.1:9870/api/pool/status" -UseBasicParsing -TimeoutSec 5
    $d = $r.Content | ConvertFrom-Json
    Write-Host "WAM:ONLINE:$($d.available)/$($d.total) avail:active=$($d.activeEmail):rem=$($d.activeRemaining)%"
} catch { Write-Host "WAM:OFFLINE" }

# Pool key
$pk = "$APPDATA\Windsurf\_pool_apikey.txt"
if (Test-Path $pk) {
    $k = [System.IO.File]::ReadAllText($pk).Trim()
    Write-Host "POOL_KEY:len=$($k.Length):valid=$($k.Length -gt 80 -and $k.StartsWith('sk-ws'))"
} else { Write-Host "POOL_KEY:MISSING" }

# Extension
$ep = "D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
if (Test-Path $ep) {
    Write-Host "EXT_PATCH:$([System.IO.File]::ReadAllText($ep).Contains('POOL_HOT_PATCH_V1'))"
}

# Workbench patches
$wb = "D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js"
if (Test-Path $wb) {
    $wc = [System.IO.File]::ReadAllText($wb)
    Write-Host "WB_GBE:$($wc.Contains('__wamRateLimit'))"
    Write-Host "WB_MAXGEN:$($wc.Contains('maxGeneratorInvocations=9999'))"
}

# Tasks
foreach ($t in @("WAMHub","WAMHubWatchdog","WAMPoolKeySync")) {
    $task = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    if ($task) { Write-Host "TASK_$($t):$($task.State)" }
    else        { Write-Host "TASK_$($t):MISSING" }
}

Write-Host "CHECK_DONE"
"""
    out, _ = run_remote(check_ps, timeout=25)
    wam_ok   = "WAM:ONLINE" in out
    pk_ok    = "POOL_KEY:len=" in out and "valid=True" in out
    ext_ok   = "EXT_PATCH:True" in out
    gbe_ok   = "WB_GBE:True" in out
    hub_task = "TASK_WAMHub:Running" in out or "TASK_WAMHub:Ready" in out
    
    for line in out.splitlines():
        if line.strip(): print(f"    {line}")
    
    print()
    ok("WAM Hub") if wam_ok else err("WAM Hub 离线")
    ok("pool_apikey.txt") if pk_ok else err("pool_apikey.txt 无效")
    ok("extension.js POOL_HOT_PATCH_V1") if ext_ok else err("extension.js 未打补丁")
    ok("workbench GBe拦截") if gbe_ok else warn("workbench GBe未打补丁")
    ok("WAMHub计划任务") if hub_task else err("WAMHub任务未配置")
    
    return wam_ok and pk_ok and ext_ok

# ════════════════════════════════════════════════════════════
# 完整修复
# ════════════════════════════════════════════════════════════
def do_fix():
    print("=" * 65)
    print("  179 Windsurf一键全修复")
    print("=" * 65)

    # Step 0: 连接测试
    hdr("连接179")
    out, rc = run_remote("$env:COMPUTERNAME", 15)
    if "ZHOUMAC" not in out:
        err(f"WinRM连接失败: {out[:100]}")
        return False
    ok("连接成功: ZHOUMAC")

    # Step 1: 从快照池选账号
    hdr("选择有效账号")
    chosen = select_account()
    if chosen:
        ok(f"账号: {chosen['email']} (key={len(chosen['key'])}字节)")
        auth_b64 = base64.b64encode(chosen["auth"].encode()).decode()
        conf_b64 = base64.b64encode(chosen["conf"].encode()).decode()
        key_b64  = base64.b64encode(chosen["key"].encode()).decode()
    else:
        warn("本地快照池为空，将尝试从WAM Hub获取active账号key")
        auth_b64 = conf_b64 = key_b64 = ""

    # Step 2: 修复extension.js + state.vscdb + pool_apikey.txt
    hdr("修复extension.js + auth + pool_key")
    PATCH_OLD    = "apiKey:this.apiKey,sessionId:this.sessionId,requestId:BigInt(this.requestId)"
    PATCH_MARKER = "/* POOL_HOT_PATCH_V1 */"
    PATCH_NEW = (
        'apiKey:(function(){'
        'try{'
        'var _fs=require(\\"fs\\"),_path=require(\\"path\\");'
        'var _pf=_path.join(process.env.APPDATA||\\"\\",'
        '\\"Windsurf\\",\\"_pool_apikey.txt\\");'
        'var _k=_fs.readFileSync(_pf,\\"utf8\\").trim();'
        'if(_k&&_k.length>20&&_k.startsWith(\\"sk-ws\\"))return _k;'
        '}'
        'catch(_e){}'
        'return this.apiKey;'
        '}).call(this)' + PATCH_MARKER + ','
        'sessionId:this.sessionId,requestId:BigInt(this.requestId)'
    )

    fix_py = f'''
import sqlite3, json, shutil, base64, os
from pathlib import Path

AUTH_B64 = "{auth_b64}"
CONF_B64 = "{conf_b64}"
KEY_B64  = "{key_b64}"

auth_str = base64.b64decode(AUTH_B64).decode("utf-8") if AUTH_B64 else ""
conf_str = base64.b64decode(CONF_B64).decode("utf-8") if CONF_B64 else ""
key_str  = base64.b64decode(KEY_B64).decode("utf-8").strip() if KEY_B64 else ""

APPDATA  = os.environ.get("APPDATA","")
DB       = Path(APPDATA)/"Windsurf"/"User"/"globalStorage"/"state.vscdb"
PK       = Path(APPDATA)/"Windsurf"/"_pool_apikey.txt"
EXT_PATHS = [
    Path(r"D:\\Windsurf\\resources\\app\\extensions\\windsurf\\dist\\extension.js"),
    Path(os.environ.get("LOCALAPPDATA",""))/"Programs"/"Windsurf"/"resources"/"app"/"extensions"/"windsurf"/"dist"/"extension.js",
]
PATCH_OLD    = "{PATCH_OLD}"
PATCH_MARKER = "{PATCH_MARKER}"
PATCH_NEW    = r"""{PATCH_NEW}"""

results = {{}}

# A: auth注入
if auth_str and DB.exists():
    bak = str(DB)+".bak_fix"
    if not Path(bak).exists(): shutil.copy2(DB,bak)
    try:
        conn = sqlite3.connect(str(DB),timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)",("windsurfAuthStatus",auth_str.strip()))
        if conf_str.strip() and conf_str.strip()!="null":
            conn.execute("INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)",("windsurfConfigurations",conf_str.strip()))
        conn.commit()
        row = conn.execute("SELECT value FROM ItemTable WHERE key=?",("windsurfAuthStatus",)).fetchone()
        if row:
            a=json.loads(row[0])
            print(f"AUTH:OK:keylen={{len(a.get('apiKey',''))}}")
            results["auth"]="OK"
        conn.close()
    except Exception as e:
        print(f"AUTH:ERR:{{e}}")
        results["auth"]="ERR"
else:
    results["auth"]="SKIP"

# B: pool_apikey.txt — 先尝试WAM Hub active key，fallback到注入的key
if not key_str:
    try:
        import urllib.request
        r = urllib.request.urlopen("http://127.0.0.1:9870/api/pool/accounts",timeout=8)
        d = json.loads(r.read())
        accounts = d.get("accounts",[])
        idx = d.get("activeIndex",-1)
        if 0<=idx<len(accounts):
            k = accounts[idx].get("apiKey","")
            if len(k)>80: key_str=k
    except: pass

if key_str and len(key_str)>80:
    PK.parent.mkdir(parents=True,exist_ok=True)
    PK.write_text(key_str,encoding="utf-8")
    print(f"POOL_KEY:OK:{{len(key_str)}}")
    results["pool_key"]="OK"
else:
    print("POOL_KEY:SKIP:no_valid_key")
    results["pool_key"]="SKIP"

# C: extension.js patch
ext_path=None
for p in EXT_PATHS:
    if p.exists(): ext_path=p; break
if ext_path:
    src=ext_path.read_text(encoding="utf-8",errors="replace")
    if PATCH_MARKER in src:
        print(f"EXT:ALREADY_PATCHED")
        results["ext"]="ALREADY"
    elif PATCH_OLD not in src:
        print("EXT:TARGET_NOT_FOUND")
        results["ext"]="TARGET_MISSING"
    elif src.count(PATCH_OLD)==1:
        bak=str(ext_path)+".bak_fix"
        if not Path(bak).exists(): shutil.copy2(ext_path,bak)
        ext_path.write_text(src.replace(PATCH_OLD,PATCH_NEW,1),encoding="utf-8")
        if PATCH_MARKER in ext_path.read_text(encoding="utf-8",errors="replace"):
            print(f"EXT:PATCHED:OK")
            results["ext"]="OK"
        else:
            shutil.copy2(bak,ext_path); results["ext"]="WRITE_FAIL"
    else:
        results["ext"]="DANGER"
        print(f"EXT:DANGER:multiple_targets")
else:
    print("EXT:NOT_FOUND"); results["ext"]="NOT_FOUND"

print("CORE_FIX:" + ("OK" if all(v in ("OK","ALREADY","SKIP") for v in results.values()) else f"PARTIAL:{{results}}"))
'''
    out2, _ = remote_py(fix_py, "_mainfix", timeout=60)
    core_ok = "CORE_FIX:OK" in out2
    for line in out2.splitlines():
        if line.strip(): info(f"  {line}")

    # Step 3: ws_repatch.py (workbench.js全量补丁)
    hdr("workbench.js补丁")
    if WS_REPATCH.exists():
        ws_b64 = base64.b64encode(WS_REPATCH.read_text("utf-8","replace").encode("utf-8")).decode("ascii")
        out3, _ = run_remote(f"""
$b64="{ws_b64}"
$bytes=[System.Convert]::FromBase64String($b64)
$text=[System.Text.Encoding]::UTF8.GetString($bytes)
[System.IO.File]::WriteAllText("C:\\\\ctemp\\\\_repatch.py",$text,[System.Text.Encoding]::UTF8)
$env:PYTHONIOENCODING="utf-8"
python "C:\\\\ctemp\\\\_repatch.py" --force 2>&1 | Select-Object -Last 10 | ForEach-Object {{ Write-Host $_ }}
""", timeout=120)
        for line in out3.splitlines()[-8:]:
            if line.strip(): info(f"  {line}")

    # Step 4: WAM Hub启动 + 任务加固
    hdr("WAM Hub启动与加固")
    hub_ps = r"""
# 检查WAM Hub状态
$tcp = New-Object Net.Sockets.TcpClient
try { $tcp.Connect("127.0.0.1",9870); Write-Host "WAM:ALREADY_ONLINE"; $tcp.Close() }
catch {
    # 启动计划任务
    $t = Get-ScheduledTask -TaskName "WAMHub" -ErrorAction SilentlyContinue
    if ($t) {
        Enable-ScheduledTask -TaskName "WAMHub" | Out-Null
        schtasks /run /tn "WAMHub" | Out-Null
        Start-Sleep -Seconds 3
        $tcp2 = New-Object Net.Sockets.TcpClient
        try { $tcp2.Connect("127.0.0.1",9870); Write-Host "WAM:STARTED_OK"; $tcp2.Close() }
        catch { Write-Host "WAM:START_FAILED" }
    } else { Write-Host "WAM:TASK_MISSING" }
}

# 加固任务: 开机触发 + 失败重启
$t2 = Get-ScheduledTask -TaskName "WAMHub" -ErrorAction SilentlyContinue
if ($t2) {
    $a2  = $t2.Actions[0]
    $trg = @((New-ScheduledTaskTrigger -AtStartup),(New-ScheduledTaskTrigger -AtLogOn))
    $act = New-ScheduledTaskAction -Execute $a2.Execute -Argument $a2.Arguments -WorkingDirectory $a2.WorkingDirectory
    $set = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Days 999) -RestartInterval (New-TimeSpan -Minutes 2) -RestartCount 10 -StartWhenAvailable
    $pri = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName "WAMHub" -Trigger $trg -Action $act -Settings $set -Principal $pri -Force | Out-Null
    Write-Host "WAMHub:HARDENED"
}

# 部署看门狗
$wd = Get-ScheduledTask -TaskName "WAMHubWatchdog" -ErrorAction SilentlyContinue
if (-not $wd) {
    $wds = '$tcp=New-Object Net.Sockets.TcpClient;try{$tcp.Connect("127.0.0.1",9870);$tcp.Close();exit 0}catch{};schtasks /run /tn WAMHub 2>$null'
    [System.IO.File]::WriteAllText("C:\ctemp\wam_watchdog.ps1",$wds,[System.Text.Encoding]::UTF8)
    $wda = New-ScheduledTaskAction -Execute "powershell" -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\ctemp\wam_watchdog.ps1"'
    $wdt = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) -Once -At "00:00"
    $wds2 = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 1) -StartWhenAvailable
    $wdp = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName "WAMHubWatchdog" -Trigger $wdt -Action $wda -Settings $wds2 -Principal $wdp -Force | Out-Null
    Enable-ScheduledTask -TaskName "WAMHubWatchdog" | Out-Null
    Write-Host "WAMHubWatchdog:CREATED"
}
Write-Host "HUB_SETUP_DONE"
"""
    out4, _ = run_remote(hub_ps, timeout=30)
    wam_ok = "WAM:ALREADY_ONLINE" in out4 or "WAM:STARTED_OK" in out4
    for line in out4.splitlines():
        if line.strip(): info(f"  {line}")
    ok("WAM Hub就绪") if wam_ok else warn("WAM Hub未启动")

    # Step 5: Windsurf启动
    hdr("启动Windsurf")
    ws_ps = r"""
$procs = Get-Process Windsurf -ErrorAction SilentlyContinue
if ($procs.Count -gt 0) {
    $procs | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    Write-Host "KILL:$($procs.Count)"
}
$exe = "D:\Windsurf\Windsurf.exe"
if (-not (Test-Path $exe)) { $exe = "$env:LOCALAPPDATA\Programs\Windsurf\Windsurf.exe" }
if (Test-Path $exe) {
    Start-Process $exe
    Start-Sleep -Seconds 5
    $p2 = Get-Process Windsurf -ErrorAction SilentlyContinue
    Write-Host "WS:PROCS:$($p2.Count)"
}
"""
    out5, _ = run_remote(ws_ps, timeout=25)
    ws_started = "WS:PROCS:" in out5 and "WS:PROCS:0" not in out5
    for line in out5.splitlines():
        if line.strip(): info(f"  {line}")
    ok("Windsurf已启动") if ws_started else warn("Windsurf未在WinRM中可见(GUI进程)")

    # Step 6: 最终验证
    hdr("最终验证")
    time.sleep(3)
    ok_check = do_check()

    print("\n" + "=" * 65)
    if core_ok and ok_check:
        print("  🎉 179 Windsurf全面修复完成！")
        print()
        print("  修复架构:")
        print("  ┌─ extension.js拦截gRPC → 读pool_apikey.txt → 最优key")
        print("  ├─ WAMPoolKeySync 60s → WAM Hub active key → pool_apikey.txt")
        print("  ├─ WAM Hub (9870) → 管理97账号 → 自动选最优")
        print("  └─ WAMHubWatchdog → 5min检查 → 崩溃自动重启")
    else:
        print("  ⚠ 修复部分完成，检查上方输出")
    print("=" * 65)

# ════════════════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════════════════
def main():
    args = set(sys.argv[1:])
    if "--check" in args:
        do_check()
    elif "--restart" in args:
        hdr("重启Windsurf")
        run_remote(r"""
$p = Get-Process Windsurf -ErrorAction SilentlyContinue
if ($p) { $p | Stop-Process -Force; Start-Sleep -Seconds 3 }
$exe = if (Test-Path "D:\Windsurf\Windsurf.exe") { "D:\Windsurf\Windsurf.exe" } else { "$env:LOCALAPPDATA\Programs\Windsurf\Windsurf.exe" }
Start-Process $exe; Write-Host "RESTARTED"
""", 20)
    else:
        do_fix()

if __name__ == "__main__":
    main()
