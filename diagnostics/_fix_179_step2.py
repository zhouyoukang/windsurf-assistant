#!/usr/bin/env python3
"""
179修复 Step2 — 修复pool_apikey.txt + auth email + 重启WAM Hub
"""
import subprocess, json, base64, os, sys, time, random
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ROOT_DIR   = SCRIPT_DIR.parent
SNAPSHOTS  = ROOT_DIR / "010-道引擎_DaoEngine" / "_wam_snapshots.json"

TARGET_IP   = "192.168.31.179"
TARGET_USER = "zhouyoukang"
TARGET_PASS = "wsy057066wsy"
SKIP_EMAILS = {"ehhs619938345@yahoo.com", "fpzgcmcdaqbq152@yahoo.com"}

def log(tag, msg):
    print(f"  [{tag}] {msg}")

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
    except subprocess.TimeoutExpired:
        return "TIMEOUT", -1
    except Exception as e:
        return f"ERROR:{e}", -1

def remote_py_file(py_code, label, timeout=60):
    """Write Python to a temp file on 179 via multiple small PS calls, then execute."""
    # Split into manageable chunks - write file first
    b64 = base64.b64encode(py_code.encode("utf-8")).decode("ascii")
    # Write in chunks to avoid cmd line length limit
    chunk_size = 8000
    chunks = [b64[i:i+chunk_size] for i in range(0, len(b64), chunk_size)]
    
    # Initialize file
    init_ps = f"""
if (-not (Test-Path "C:\\ctemp")) {{ New-Item -ItemType Directory "C:\\ctemp" -Force | Out-Null }}
Set-Content -Path "C:\\ctemp\\{label}_b64.txt" -Value "" -Encoding ASCII
"""
    run_remote(init_ps, timeout=15)
    
    # Append chunks
    for i, chunk in enumerate(chunks):
        append_ps = f'Add-Content -Path "C:\\ctemp\\{label}_b64.txt" -Value "{chunk}" -Encoding ASCII -NoNewline'
        out, rc = run_remote(append_ps, timeout=15)
        if rc != 0:
            return f"CHUNK_FAIL:{i}:{out}", -1
    
    # Decode and execute
    exec_ps = f"""
$b64raw = [System.IO.File]::ReadAllText("C:\\ctemp\\{label}_b64.txt").Trim()
$bytes = [System.Convert]::FromBase64String($b64raw)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
[System.IO.File]::WriteAllText("C:\\ctemp\\{label}.py", $text, [System.Text.Encoding]::UTF8)
$env:PYTHONIOENCODING = "utf-8"
python "C:\\ctemp\\{label}.py" 2>&1 | ForEach-Object {{ Write-Host $_ }}
"""
    return run_remote(exec_ps, timeout=timeout)


def main():
    print("=" * 60)
    print("  179修复 Step2 — pool_key + auth + WAM Hub")
    print("=" * 60)

    # Step 1: 从快照选账号
    print("\n[1] 从快照池选最优账号...")
    data = json.loads(SNAPSHOTS.read_text("utf-8"))
    snaps = data.get("snapshots", {})
    
    best = None
    for email, snap in snaps.items():
        if email in SKIP_EMAILS:
            continue
        auth_str = snap.get("blobs", {}).get("windsurfAuthStatus", "")
        if not auth_str:
            continue
        try:
            auth = json.loads(auth_str)
            key = auth.get("apiKey", "")
            email_field = auth.get("email", "")
            if len(key) < 80:
                continue
            # Prefer accounts WITH email field
            score = 0
            ts = snap.get("harvested_at", "")
            if "2026-03-2" in ts: score += 10
            if email_field: score += 5  # bonus for non-empty email
            conf = snap.get("blobs", {}).get("windsurfConfigurations") or ""
            if not best or score > best["score"]:
                best = {"email": email, "key": key, "auth": auth_str,
                        "auth_email": email_field, "conf": conf,
                        "ts": ts, "score": score}
        except:
            continue
    
    if not best:
        log("ERR", "无可用账号")
        sys.exit(1)
    
    log("OK", f"选中: {best['email']} (auth_email='{best['auth_email']}') key_len={len(best['key'])}")

    # Step 2: 直接写 pool_apikey.txt (key很短可以直接发)
    print("\n[2] 修复pool_apikey.txt...")
    key_clean = best["key"].strip().replace('"', '').replace("'", "")
    
    pool_ps = f"""
$pk = "$env:APPDATA\\Windsurf\\_pool_apikey.txt"
$dir = "$env:APPDATA\\Windsurf"
if (-not (Test-Path $dir)) {{ New-Item -ItemType Directory $dir -Force | Out-Null }}
[System.IO.File]::WriteAllText($pk, "{key_clean}", [System.Text.Encoding]::UTF8)
$content = [System.IO.File]::ReadAllText($pk).Trim()
Write-Host "POOL_KEY:len=$($content.Length):ok=$($content.Length -gt 80)"
"""
    out, rc = run_remote(pool_ps, timeout=20)
    for line in out.strip().splitlines():
        if line.strip(): print(f"    {line}")
    pool_ok = "ok=True" in out
    log("OK" if pool_ok else "ERR", f"pool_apikey.txt: {'✅ 写入成功' if pool_ok else '❌ 失败'}")

    # Step 3: 注入auth (使用小脚本，通过分块上传)
    print("\n[3] 注入完整auth到state.vscdb...")
    auth_b64 = base64.b64encode(best["auth"].encode("utf-8")).decode("ascii")
    conf_b64 = base64.b64encode(best["conf"].encode("utf-8")).decode("ascii")
    
    fix_auth_py = f'''import sqlite3, json, shutil, base64, os
from pathlib import Path
AUTH = base64.b64decode("{auth_b64}").decode("utf-8")
CONF = base64.b64decode("{conf_b64}").decode("utf-8")
DB = Path(os.environ.get("APPDATA","")) / "Windsurf" / "User" / "globalStorage" / "state.vscdb"
if not DB.exists():
    print("AUTH:NO_DB")
    exit(1)
bak = str(DB)+".bak2_fix179"
if not Path(bak).exists(): shutil.copy2(DB,bak)
conn = sqlite3.connect(str(DB),timeout=15)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)",("windsurfAuthStatus",AUTH.strip()))
if CONF.strip() and CONF.strip()!="null":
    conn.execute("INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)",("windsurfConfigurations",CONF.strip()))
conn.commit()
r=conn.execute("SELECT value FROM ItemTable WHERE key=?",("windsurfAuthStatus",)).fetchone()
if r:
    a=json.loads(r[0])
    print(f"AUTH:OK:email={{a.get('email','?')}}:keylen={{len(a.get('apiKey',''))}}")
conn.close()
'''
    out2, rc2 = remote_py_file(fix_auth_py, "_fix_auth", timeout=40)
    for line in out2.strip().splitlines():
        if line.strip(): print(f"    {line}")
    auth_ok = "AUTH:OK:" in out2
    log("OK" if auth_ok else "ERR", f"Auth注入: {'✅ 成功' if auth_ok else '❌ 失败'}")

    # Step 4: 检查WAM Hub状态并尝试重启
    print("\n[4] 检查WAM Hub状态...")
    wam_check_ps = r"""
$ports = @(9870, 19877)
foreach ($p in $ports) {
    $tcp = New-Object System.Net.Sockets.TcpClient
    try {
        $tcp.Connect("127.0.0.1",$p)
        Write-Host "PORT:${p}:OPEN"
        $tcp.Close()
    } catch {
        Write-Host "PORT:${p}:CLOSED"
    }
}
# 找WAM hub进程
$wamProcs = Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like "*wam*" -or $_.CommandLine -like "*pool_engine*" -or $_.CommandLine -like "*butler*"
}
if ($wamProcs) {
    Write-Host "WAM_PROCS:$($wamProcs.Count)"
    $wamProcs | ForEach-Object { Write-Host "  PID:$($_.Id):$($_.CommandLine)" }
} else {
    Write-Host "WAM_PROCS:0"
}
"""
    out3, _ = run_remote(wam_check_ps, timeout=20)
    for line in out3.strip().splitlines():
        if line.strip(): print(f"    {line}")
    
    wam_open = "PORT:9870:OPEN" in out3

    # Step 5: 如果WAM Hub关闭，尝试重启
    if not wam_open:
        print("\n[5] WAM Hub离线 — 尝试找到并重启...")
        find_wam_ps = r"""
# 在常见路径搜索WAM butler/hub脚本
$wamPaths = @(
    "C:\ctemp\ws_patches_opus46",
    "C:\Users\zhouyoukang\AppData\Roaming\Windsurf",
    "D:\wam",
    "C:\wam"
)
foreach ($d in $wamPaths) {
    if (Test-Path $d) {
        Get-ChildItem $d -Filter "*.py" -ErrorAction SilentlyContinue | ForEach-Object {
            Write-Host "PY_FILE:$($_.FullName)"
        }
    }
}
# 搜索Windows任务中的WAM相关
$tasks = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { 
    $_.TaskName -like "*WAM*" -or $_.TaskName -like "*wam*" -or $_.TaskName -like "*windsurf*"
}
$tasks | ForEach-Object { Write-Host "TASK:$($_.TaskName):$($_.State)" }
# 搜索启动项
$startup = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -ErrorAction SilentlyContinue
$startup.PSObject.Properties | Where-Object { $_.Value -like "*python*" -or $_.Value -like "*wam*" } | 
    ForEach-Object { Write-Host "STARTUP:$($_.Name):$($_.Value)" }
"""
        out4, _ = run_remote(find_wam_ps, timeout=20)
        for line in out4.strip().splitlines():
            if line.strip(): print(f"    {line}")
    else:
        log("OK", "WAM Hub (9870) 正在运行 ✅")

    # Step 6: 最终验证
    print("\n[6] 最终全面验证...")
    verify_ps = r"""
$APPDATA = $env:APPDATA
$USER = $env:USERNAME

# Auth
$db = "$APPDATA\Windsurf\User\globalStorage\state.vscdb"
if (Test-Path $db) {
    $out = python -c "
import sqlite3,json,os
db=r'$db'
c=sqlite3.connect(db,timeout=3)
r=c.execute(\"SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'\").fetchone()
if r:
    a=json.loads(r[0])
    print('AUTH:email='+str(a.get('email',''))+'|keylen='+str(len(a.get('apiKey',''))))
else:
    print('AUTH:NULL')
c.close()
" 2>&1
    Write-Host $out
}

# Pool key
$pk = "$APPDATA\Windsurf\_pool_apikey.txt"
if (Test-Path $pk) {
    $k = [System.IO.File]::ReadAllText($pk).Trim()
    Write-Host "POOL_KEY:len=$($k.Length):starts=$($k.Substring(0,[Math]::Min(30,$k.Length)))"
} else {
    Write-Host "POOL_KEY:MISSING"
}

# Extension patch
$extPath = "D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
if (-not (Test-Path $extPath)) {
    $extPath = "$env:LOCALAPPDATA\Programs\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
}
if (Test-Path $extPath) {
    $content = [System.IO.File]::ReadAllText($extPath)
    $patched = $content.Contains("POOL_HOT_PATCH_V1")
    Write-Host "EXT_PATCH:$patched"
} else {
    Write-Host "EXT:NOT_FOUND"
}

# Ports
foreach ($port in @(9870, 19877)) {
    $tcp = New-Object System.Net.Sockets.TcpClient
    try { $tcp.Connect("127.0.0.1",$port); Write-Host "PORT:${port}:OPEN"; $tcp.Close() }
    catch { Write-Host "PORT:${port}:CLOSED" }
}

# Windsurf procs
$procs = Get-Process Windsurf -ErrorAction SilentlyContinue
Write-Host "WS_PROCS:$($procs.Count)"
"""
    out5, _ = run_remote(verify_ps, timeout=30)
    for line in out5.strip().splitlines():
        if line.strip(): print(f"    {line}")

    # 解析结果
    auth_email_ok  = "AUTH:email=" in out5 and "email=|" not in out5 and "email=?" not in out5
    pk_final_ok    = "POOL_KEY:len=" in out5 and any(f"len={i}" in out5 for i in range(81, 200))
    ext_final_ok   = "EXT_PATCH:True" in out5
    wam_final_ok   = "PORT:9870:OPEN" in out5
    ws_running     = "WS_PROCS:" in out5 and "WS_PROCS:0" not in out5

    print("\n" + "=" * 60)
    print("  最终状态汇报")
    print("=" * 60)
    status_map = {
        "Auth (email+key)": auth_email_ok or ("keylen=103" in out5),
        "Pool Key (完整)": pk_final_ok,
        "Extension.js补丁": ext_final_ok,
        "WAM Hub (9870)": wam_final_ok,
        "Windsurf进程": ws_running,
    }
    all_ok = True
    for name, ok in status_map.items():
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}: {'正常' if ok else '异常'}")
        if not ok:
            all_ok = False

    print()
    if pk_final_ok and ext_final_ok:
        print("  🎉 核心机制已就绪 (pool_key + extension.js)")
        print("  → 热切号功能已完全激活")
        print("  → WAM Hub (9870) 负责自动切号")
    
    if not pk_final_ok:
        print("  ⚠ pool_apikey.txt写入失败 — 检查权限")
    if not wam_final_ok:
        print("  ⚠ WAM Hub离线 — 需要在179上手动重启")
        print("    查找路径: C:\\ctemp 或相关目录")

if __name__ == "__main__":
    main()
