#!/usr/bin/env python3
"""
179根本修复 — 一键彻底解决所有Windsurf问题
道法自然·推进到底·从根本解决

修复内容:
  1. extension.js — POOL_HOT_PATCH_V1 (热切号核心)
  2. workbench.js — ws_repatch.py全量补丁
  3. state.vscdb  — 注入完整有效账号 (修复空email/截断key)
  4. pool_apikey.txt — 写入正确完整key
  5. Windsurf重启  — 激活所有补丁
"""
import subprocess, json, base64, os, sys, time, random
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
ROOT_DIR    = SCRIPT_DIR.parent
SNAPSHOTS   = ROOT_DIR / "010-道引擎_DaoEngine" / "_wam_snapshots.json"
WS_REPATCH  = ROOT_DIR / "ws_repatch.py"

TARGET_IP   = "192.168.31.179"
TARGET_USER = "zhouyoukang"
TARGET_PASS = "wsy057066wsy"
SKIP_EMAILS = {"ehhs619938345@yahoo.com", "fpzgcmcdaqbq152@yahoo.com"}

def c(tag, msg, color=""):
    colors = {"ok": "\033[92m", "warn": "\033[93m", "err": "\033[91m", "info": "\033[96m", "": ""}
    reset = "\033[0m"
    print(f"  [{tag}] {colors.get(color,'')}{msg}{reset}")

def run_remote(ps_cmd, timeout=90):
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

def remote_py(py_code, timeout=120, label="script"):
    """Push Python code to 179 and run it."""
    b64 = base64.b64encode(py_code.encode("utf-8")).decode("ascii")
    ps = f"""
$b64 = "{b64}"
$bytes = [System.Convert]::FromBase64String($b64)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
if (-not (Test-Path "C:\\ctemp")) {{ New-Item -ItemType Directory "C:\\ctemp" -Force | Out-Null }}
[System.IO.File]::WriteAllText("C:\\ctemp\\{label}.py", $text, [System.Text.Encoding]::UTF8)
python "C:\\ctemp\\{label}.py" 2>&1 | ForEach-Object {{ Write-Host $_ }}
"""
    return run_remote(ps, timeout=timeout)

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
def main():
    skip_restart = "--skip-restart" in sys.argv

    print("=" * 65)
    print("  179 Windsurf根本修复 — 道法自然·推进到底")
    print("=" * 65)

    # ── Step 0: 连接测试 ──
    print("\n── Step 0: WinRM连接测试 ──")
    out, rc = run_remote("$env:COMPUTERNAME", timeout=20)
    if rc != 0 or "ZHOUMAC" not in out:
        c("ERR", f"WinRM连接失败: {out[:200]}", "err")
        sys.exit(1)
    c("OK", "连接成功: ZHOUMAC", "ok")

    # ── Step 1: 从本地快照池选择最优账号 ──
    print("\n── Step 1: 从快照池选择最优账号 ──")
    data = json.loads(SNAPSHOTS.read_text("utf-8"))
    snaps = data.get("snapshots", {})

    candidates = []
    for email, snap in snaps.items():
        if email in SKIP_EMAILS:
            continue
        auth_str = snap.get("blobs", {}).get("windsurfAuthStatus", "")
        if not auth_str:
            continue
        try:
            auth = json.loads(auth_str)
            key = auth.get("apiKey", "")
            if len(key) < 80:
                continue
        except:
            continue
        score = 0
        ts = snap.get("harvested_at", "")
        if "2026-03-2" in ts:
            score += 10
        elif "2026-03-1" in ts:
            score += 5
        conf = snap.get("blobs", {}).get("windsurfConfigurations") or ""
        candidates.append({
            "email": email, "key": key, "auth": auth_str,
            "conf": conf, "ts": ts, "score": score
        })

    if not candidates:
        c("ERR", "快照池无可用账号 (key<80chars)", "err")
        sys.exit(1)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    top_score = candidates[0]["score"]
    top_group = [x for x in candidates if x["score"] >= top_score]
    chosen = random.choice(top_group)

    c("OK", f"选中账号: {chosen['email']}", "ok")
    c("INFO", f"API Key: {chosen['key'][:40]}... (len={len(chosen['key'])})", "info")
    c("INFO", f"快照时间: {chosen['ts']}", "info")

    # ── Step 2: 构建并执行修复脚本 ──
    print("\n── Step 2: 执行核心修复 (auth + pool_key + ext.js) ──")

    auth_b64  = base64.b64encode(chosen["auth"].encode("utf-8")).decode("ascii")
    conf_b64  = base64.b64encode(chosen["conf"].encode("utf-8")).decode("ascii")
    key_b64   = base64.b64encode(chosen["key"].encode("utf-8")).decode("ascii")

    fix_core_py = f'''#!/usr/bin/env python3
import sqlite3, json, shutil, base64, os, sys
from pathlib import Path

AUTH_B64 = "{auth_b64}"
CONF_B64 = "{conf_b64}"
KEY_B64  = "{key_b64}"

auth_str = base64.b64decode(AUTH_B64).decode("utf-8")
conf_str = base64.b64decode(CONF_B64).decode("utf-8")
key_str  = base64.b64decode(KEY_B64).decode("utf-8")

APPDATA  = os.environ.get("APPDATA", "")
USER     = os.environ.get("USERNAME", "zhouyoukang")
DB_PATH  = Path(APPDATA) / "Windsurf" / "User" / "globalStorage" / "state.vscdb"
POOL_KEY = Path(APPDATA) / "Windsurf" / "_pool_apikey.txt"

EXT_PATHS = [
    r"D:\\Windsurf\\resources\\app\\extensions\\windsurf\\dist\\extension.js",
    Path(os.environ.get("LOCALAPPDATA","")) / "Programs" / "Windsurf" / "resources" / "app" / "extensions" / "windsurf" / "dist" / "extension.js",
]
EXT_PATHS = [Path(p) for p in EXT_PATHS]

PATCH_OLD = "apiKey:this.apiKey,sessionId:this.sessionId,requestId:BigInt(this.requestId)"
PATCH_MARKER = "/* POOL_HOT_PATCH_V1 */"
PATCH_NEW = (
    "apiKey:(function(){{"
    "try{{"
    "var _fs=require(\\"fs\\"),_path=require(\\"path\\");"
    "var _pf=_path.join(process.env.APPDATA||\\"\\","
    "\\"Windsurf\\",\\"_pool_apikey.txt\\");"
    "var _k=_fs.readFileSync(_pf,\\"utf8\\").trim();"
    "if(_k&&_k.length>20&&_k.startsWith(\\"sk-ws\\"))return _k;"
    "}}"
    "catch(_e){{}}"
    "return this.apiKey;"
    "}}).call(this)" + PATCH_MARKER + ","
    "sessionId:this.sessionId,requestId:BigInt(this.requestId)"
)

results = {{}}

print("=" * 55)
print("  Fix Core: auth + pool_key + extension.js")
print("=" * 55)

# Fix A: state.vscdb
print("\\n[A] 注入auth到state.vscdb...")
if DB_PATH.exists():
    bak = str(DB_PATH) + ".bak_fix179"
    if not Path(bak).exists():
        shutil.copy2(DB_PATH, bak)
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=15)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)",
                     ("windsurfAuthStatus", auth_str.strip()))
        if conf_str.strip() and conf_str.strip() != "null":
            conn.execute("INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)",
                         ("windsurfConfigurations", conf_str.strip()))
        conn.commit()
        row = conn.execute("SELECT value FROM ItemTable WHERE key=?",("windsurfAuthStatus",)).fetchone()
        if row:
            a = json.loads(row[0])
            print(f"  AUTH:OK:email={{a.get('email','?')}}:keylen={{len(a.get('apiKey',''))}}")
            results["auth"] = "OK"
        conn.close()
    except Exception as e:
        print(f"  AUTH:ERROR:{{e}}")
        results["auth"] = f"ERROR"
else:
    print(f"  AUTH:NO_DB:{{DB_PATH}}")
    results["auth"] = "NO_DB"

# Fix B: pool_apikey.txt
print("\\n[B] 写入pool_apikey.txt...")
try:
    POOL_KEY.parent.mkdir(parents=True, exist_ok=True)
    POOL_KEY.write_text(key_str.strip(), encoding="utf-8")
    actual_len = len(POOL_KEY.read_text(encoding="utf-8").strip())
    print(f"  POOL_KEY:OK:len={{actual_len}}:{{key_str[:40]}}...")
    results["pool_key"] = "OK"
except Exception as e:
    print(f"  POOL_KEY:ERROR:{{e}}")
    results["pool_key"] = "ERROR"

# Fix C: extension.js
print("\\n[C] 修复extension.js (POOL_HOT_PATCH_V1)...")
ext_path = None
for p in EXT_PATHS:
    if p.exists():
        ext_path = p
        break

if not ext_path:
    print("  EXT:NOT_FOUND")
    results["ext"] = "NOT_FOUND"
else:
    src = ext_path.read_text(encoding="utf-8", errors="replace")
    if PATCH_MARKER in src:
        print(f"  EXT:ALREADY_PATCHED:{{ext_path.name}}")
        results["ext"] = "ALREADY"
    elif PATCH_OLD not in src:
        print("  EXT:TARGET_NOT_FOUND — version changed?")
        # Try to find the pattern
        idx = src.find("apiKey:this.apiKey")
        print(f"  EXT:SEARCH_NEARBY:{{src[max(0,idx-50):idx+100]}}")
        results["ext"] = "TARGET_MISSING"
    else:
        cnt = src.count(PATCH_OLD)
        if cnt != 1:
            print(f"  EXT:DANGER:target x{{cnt}}")
            results["ext"] = "DANGER"
        else:
            bak = str(ext_path) + ".bak_fix179"
            if not Path(bak).exists():
                shutil.copy2(ext_path, bak)
            new_src = src.replace(PATCH_OLD, PATCH_NEW, 1)
            ext_path.write_text(new_src, encoding="utf-8")
            verify = PATCH_MARKER in ext_path.read_text(encoding="utf-8", errors="replace")
            if verify:
                print(f"  EXT:PATCHED:OK:{{ext_path.stat().st_size//1024}}KB")
                results["ext"] = "OK"
            else:
                shutil.copy2(bak, ext_path)
                print("  EXT:WRITE_FAIL:restored")
                results["ext"] = "WRITE_FAIL"

# Summary
print("\\n" + "=" * 55)
print(f"  auth={{results.get('auth','?')}}  pool_key={{results.get('pool_key','?')}}  ext={{results.get('ext','?')}}")
all_ok = (results.get("auth") == "OK" and
          results.get("pool_key") == "OK" and
          results.get("ext") in ("OK","ALREADY"))
print("CORE_FIX:" + ("ALL_OK" if all_ok else f"PARTIAL:{{json.dumps(results)}}"))
'''

    out, rc = remote_py(fix_core_py, timeout=60, label="_fix_core")
    for line in out.strip().splitlines():
        print(f"    {line}")

    core_ok = "CORE_FIX:ALL_OK" in out
    if core_ok:
        c("OK", "核心修复完成: auth + pool_key + extension.js", "ok")
    else:
        c("WARN", "核心修复部分完成，继续执行后续步骤...", "warn")

    # ── Step 3: ws_repatch.py (workbench.js全量补丁) ──
    print("\n── Step 3: ws_repatch.py 全量补丁 ──")
    if WS_REPATCH.exists():
        ws_content = WS_REPATCH.read_text("utf-8", errors="replace")
        ws_b64 = base64.b64encode(ws_content.encode("utf-8")).decode("ascii")
        ps_ws = f"""
$b64 = "{ws_b64}"
$bytes = [System.Convert]::FromBase64String($b64)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
[System.IO.File]::WriteAllText("C:\\ctemp\\_ws_repatch.py", $text, [System.Text.Encoding]::UTF8)
$env:PYTHONIOENCODING = "utf-8"
python "C:\\ctemp\\_ws_repatch.py" --force 2>&1 | Select-Object -Last 25 | ForEach-Object {{ Write-Host $_ }}
"""
        out2, rc2 = run_remote(ps_ws, timeout=120)
        for line in out2.strip().splitlines()[-20:]:
            print(f"    {line}")
        if rc2 == 0 or "PATCHED" in out2 or "already" in out2.lower():
            c("OK", "ws_repatch.py 执行完成", "ok")
        else:
            c("WARN", "ws_repatch.py 返回非零，检查上方输出", "warn")
    else:
        c("WARN", f"ws_repatch.py 未找到: {WS_REPATCH}", "warn")

    # ── Step 4: 重启Windsurf ──
    if skip_restart:
        print("\n── Step 4: 跳过重启 (--skip-restart) ──")
    else:
        print("\n── Step 4: 重启Windsurf (激活补丁) ──")
        restart_ps = r"""
$wsPaths = @(
    "D:\Windsurf\Windsurf.exe",
    "$env:LOCALAPPDATA\Programs\Windsurf\Windsurf.exe"
)
$wsExe = $null
foreach ($p in $wsPaths) { if (Test-Path $p) { $wsExe = $p; break } }

$procs = Get-Process Windsurf -ErrorAction SilentlyContinue
if ($procs) {
    Write-Host "KILL:$($procs.Count)_procs"
    $procs | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 4
} else {
    Write-Host "KILL:none_running"
}

if ($wsExe) {
    Write-Host "START:$wsExe"
    Start-Process $wsExe
    Start-Sleep -Seconds 5
    $running = Get-Process Windsurf -ErrorAction SilentlyContinue
    Write-Host "RUNNING:$($running.Count)_procs"
} else {
    Write-Host "START:exe_not_found"
}
"""
        out3, rc3 = run_remote(restart_ps, timeout=40)
        for line in out3.strip().splitlines():
            print(f"    {line}")

    # ── Step 5: 最终验证 ──
    print("\n── Step 5: 最终验证 ──")
    time.sleep(4)

    verify_py = r"""
import sqlite3, json, os
from pathlib import Path

APPDATA = os.environ.get("APPDATA","")
USER    = os.environ.get("USERNAME","zhouyoukang")
DB      = Path(APPDATA) / "Windsurf" / "User" / "globalStorage" / "state.vscdb"
PK      = Path(APPDATA) / "Windsurf" / "_pool_apikey.txt"
EXT     = Path(r"D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js")
if not EXT.exists():
    EXT = Path(os.environ.get("LOCALAPPDATA","")) / "Programs" / "Windsurf" / "resources" / "app" / "extensions" / "windsurf" / "dist" / "extension.js"

print("=== VERIFY ===")
# auth
if DB.exists():
    try:
        c = sqlite3.connect(str(DB),timeout=3)
        r = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        if r:
            a = json.loads(r[0])
            print(f"AUTH:email={a.get('email','?')}:keylen={len(a.get('apiKey',''))}")
        else:
            print("AUTH:NULL")
        c.close()
    except Exception as e:
        print(f"AUTH:ERROR:{e}")
else:
    print("AUTH:NO_DB")

# pool key
if PK.exists():
    k = PK.read_text(encoding="utf-8").strip()
    print(f"POOL_KEY:len={len(k)}:ok={len(k)>80}")
else:
    print("POOL_KEY:MISSING")

# ext patch
if EXT.exists():
    patched = "POOL_HOT_PATCH_V1" in EXT.read_text(encoding="utf-8",errors="replace")
    print(f"EXT_PATCH:{patched}")
else:
    print("EXT:NOT_FOUND")

import subprocess
r2 = subprocess.run(["tasklist","/FI","IMAGENAME eq Windsurf.exe","/FO","CSV"],
                    capture_output=True,text=True,timeout=5)
lines = [l for l in r2.stdout.split("\n") if "Windsurf" in l]
print(f"WS_PROCS:{len(lines)}")

# WAM hub
try:
    import urllib.request
    r3 = urllib.request.urlopen("http://127.0.0.1:9870/api/pool/status",timeout=3)
    d = json.loads(r3.read())
    print(f"WAM_HUB:OK:available={d.get('available','?')}")
except Exception as e:
    print(f"WAM_HUB:OFFLINE:{e}")
"""
    out4, rc4 = remote_py(verify_py, timeout=30, label="_verify")
    for line in out4.strip().splitlines():
        print(f"    {line}")

    # ── 汇报 ──
    print("\n" + "=" * 65)
    print("  修复汇报")
    print("=" * 65)

    auth_ok  = "AUTH:email=" in out4 and "keylen=0" not in out4
    pk_ok    = "POOL_KEY:len=" in out4 and "ok=False" not in out4
    ext_ok   = "EXT_PATCH:True" in out4
    ws_ok    = "WS_PROCS:" in out4 and "WS_PROCS:0" not in out4

    c("OK" if auth_ok else "ERR",  f"Auth注入: {'✅ email+key正常' if auth_ok else '❌ 失败'}", "ok" if auth_ok else "err")
    c("OK" if pk_ok   else "ERR",  f"Pool Key: {'✅ 完整key写入' if pk_ok else '❌ 失败'}", "ok" if pk_ok else "err")
    c("OK" if ext_ok  else "ERR",  f"Extension补丁: {'✅ POOL_HOT_PATCH_V1已应用' if ext_ok else '❌ 未打补丁'}", "ok" if ext_ok else "err")
    c("OK" if ws_ok   else "WARN", f"Windsurf进程: {'✅ 运行中' if ws_ok else '⚠ 未运行'}", "ok" if ws_ok else "warn")

    all_fixed = auth_ok and pk_ok and ext_ok
    print()
    if all_fixed:
        c("OK", "🎉 179 Windsurf全面修复完成！", "ok")
        print()
        print("  现在179 Windsurf:")
        print("  • 账号已登录 (有效email+完整apiKey)")
        print("  • 热切号已激活 (extension.js POOL_HOT_PATCH_V1)")
        print("  • WAM Hub自动管理切号 (:9870)")
        print("  • 如需切号: 访问 http://127.0.0.1:9870")
    else:
        c("WARN", "部分修复完成，请检查上方输出", "warn")
        if not ext_ok:
            print("\n  ⚠ extension.js未打补丁，可能原因:")
            print("    1. Windsurf版本更新导致patch target变化")
            print("    2. 文件权限问题")
            print("    → 解决: 手动在179上运行 hot_patch.py apply")

if __name__ == "__main__":
    main()
