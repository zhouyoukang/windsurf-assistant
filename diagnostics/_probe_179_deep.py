#!/usr/bin/env python3
"""
179深度探测 — WAM Hub机制 + auth链路 + wam_hub.py源码读取
"""
import subprocess, json, base64, time
from pathlib import Path

TARGET_IP   = "192.168.31.179"
TARGET_USER = "zhouyoukang"
TARGET_PASS = "wsy057066wsy"

def run_remote_ps1(content, timeout=60):
    import tempfile
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
    ps1 = f"""
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -ErrorAction SilentlyContinue
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock {{
    {ps_body}
}} 2>&1 | ForEach-Object {{ Write-Host $_ }}
"""
    return run_remote_ps1(ps1, timeout=timeout)

def remote_py(py_code, label="_probe", timeout=60):
    """Chunk-upload Python to 179 and execute."""
    b64 = base64.b64encode(py_code.encode("utf-8")).decode("ascii")
    chunks = [b64[i:i+8000] for i in range(0, len(b64), 8000)]

    init_ps = f"""
if (-not (Test-Path "C:\\ctemp")) {{ New-Item -ItemType Directory "C:\\ctemp" -Force | Out-Null }}
[System.IO.File]::WriteAllText("C:\\ctemp\\{label}_b64.txt", "", [System.Text.Encoding]::ASCII)
"""
    run_remote(init_ps, timeout=10)

    for chunk in chunks:
        append_ps = f'[System.IO.File]::AppendAllText("C:\\ctemp\\{label}_b64.txt", "{chunk}", [System.Text.Encoding]::ASCII)'
        run_remote(append_ps, timeout=10)

    exec_ps = f"""
$b64 = [System.IO.File]::ReadAllText("C:\\ctemp\\{label}_b64.txt").Trim()
$bytes = [System.Convert]::FromBase64String($b64)
$text  = [System.Text.Encoding]::UTF8.GetString($bytes)
[System.IO.File]::WriteAllText("C:\\ctemp\\{label}.py", $text, [System.Text.Encoding]::UTF8)
$env:PYTHONIOENCODING = "utf-8"
python "C:\\ctemp\\{label}.py" 2>&1 | ForEach-Object {{ Write-Host $_ }}
"""
    return run_remote(exec_ps, timeout=timeout)

def main():
    print("=" * 65)
    print("  179深度探测 — WAM Hub + Auth链路")
    print("=" * 65)

    # ── Step 1: WAM Hub API + 活跃账号 ──
    print("\n[1] WAM Hub API状态...")
    wam_ps = r"""
try {
    $r = Invoke-WebRequest "http://127.0.0.1:9870/api/pool/status" -UseBasicParsing -TimeoutSec 5
    Write-Host "WAM_STATUS:" + $r.Content
} catch { Write-Host "WAM_STATUS:FAIL" }
"""
    out, _ = run_remote(wam_ps, timeout=15)
    wam_line = [l for l in out.splitlines() if "WAM_STATUS:" in l]
    if wam_line:
        try:
            d = json.loads(wam_line[0].replace("WAM_STATUS:", ""))
            print(f"  active: {d.get('activeEmail','?')} | remaining={d.get('activeRemaining','?')}%")
            print(f"  pool: total={d.get('total','?')} available={d.get('available','?')}")
            print(f"  switches: {d.get('switchCount','?')} | proxyMode={d.get('proxyMode','?')}")
        except Exception as e:
            print(f"  WAM parse error: {e}")
            print(f"  raw: {wam_line[0][:200]}")

    # ── Step 2: 检查wam_hub.py写入pool_apikey的机制 ──
    print("\n[2] wam_hub.py关键内容读取...")
    probe_py = r'''
import os, sys
from pathlib import Path

# Find wam_hub.py
possible = [
    r"E:\道\道生一\一生二\无感切号\scripts\wam_hub.py",
]
# Also search
for root, dirs, files in os.walk(r"E:\道"):
    for f in files:
        if f == "wam_hub.py":
            possible.append(os.path.join(root, f))
    break  # only top level first

found = None
for p in possible:
    if Path(p).exists():
        found = p
        break

if found:
    print(f"HUB_SCRIPT:{found}")
    content = Path(found).read_text(encoding="utf-8", errors="replace")
    print(f"HUB_SIZE:{len(content)}")
    # Print lines containing key patterns
    for i, line in enumerate(content.splitlines()):
        if any(kw in line for kw in ["pool_apikey", "_pool_apikey", "apikey.txt",
                                      "def ", "app.route", "@app", "port", "inject",
                                      "auth", "rotate", "switch", "active"]):
            print(f"LINE{i+1}:{line[:120]}")
else:
    print("HUB_SCRIPT:NOT_FOUND")
    # List 无感切号 directory
    base = r"E:\道\道生一\一生二\无感切号"
    if Path(base).exists():
        for p in Path(base).rglob("*"):
            if p.is_file():
                print(f"FILE:{p}")
    else:
        print(f"DIR_NOT_FOUND:{base}")
'''
    out2, _ = remote_py(probe_py, "_probe_hub", timeout=30)
    lines = [l for l in out2.splitlines() if l.strip()]
    for line in lines[:60]:
        print(f"    {line}")

    # ── Step 3: pool_apikey.txt 被WAM Hub更新了吗? ──
    print("\n[3] pool_apikey.txt当前内容...")
    pk_py = r'''
import os, json
from pathlib import Path
APPDATA = os.environ.get("APPDATA", "")
pk = Path(APPDATA) / "Windsurf" / "_pool_apikey.txt"
if pk.exists():
    k = pk.read_text(encoding="utf-8").strip()
    print(f"POOL_KEY:len={len(k)}:key={k[:50]}")
else:
    print("POOL_KEY:MISSING")

# Also check auth
import sqlite3
db = Path(APPDATA) / "Windsurf" / "User" / "globalStorage" / "state.vscdb"
if db.exists():
    try:
        c = sqlite3.connect(str(db), timeout=3)
        r = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        if r:
            import json as j
            a = j.loads(r[0])
            print(f"AUTH_EMAIL:{a.get('email','EMPTY')}")
            print(f"AUTH_KEYLEN:{len(a.get('apiKey',''))}")
            print(f"AUTH_KEY50:{a.get('apiKey','')[:50]}")
            # All keys
            print(f"AUTH_ALLKEYS:{list(a.keys())}")
        else:
            print("AUTH:NULL")
        c.close()
    except Exception as e:
        print(f"AUTH_ERR:{e}")
'''
    out3, _ = remote_py(pk_py, "_probe_pk", timeout=20)
    for line in out3.splitlines():
        if line.strip(): print(f"    {line}")

    # ── Step 4: 检查pool_apikey 和 WAM active key是否一致 ──
    print("\n[4] WAM Hub rotate (快速切换，更新pool_key)...")
    # Use short timeout to avoid hanging
    rotate_ps = r"""
try {
    $r = Invoke-WebRequest "http://127.0.0.1:9870/api/pool/rotate" -Method POST -Body "{}" -ContentType "application/json" -UseBasicParsing -TimeoutSec 8
    Write-Host "ROTATE:" + $r.Content
} catch {
    Write-Host "ROTATE:FAIL:$($_.Exception.Message)"
}
"""
    out4, _ = run_remote(rotate_ps, timeout=15)
    rotate_line = [l for l in out4.splitlines() if "ROTATE:" in l]
    if rotate_line:
        print(f"    {rotate_line[0][:200]}")

    # ── Step 5: pool_apikey.txt after rotate ──
    time.sleep(2)
    print("\n[5] rotate后检查pool_apikey.txt...")
    out5, _ = remote_py(pk_py, "_probe_pk2", timeout=20)
    for line in out5.splitlines():
        if "POOL_KEY:" in line or "AUTH_" in line:
            print(f"    {line}")

if __name__ == "__main__":
    main()
