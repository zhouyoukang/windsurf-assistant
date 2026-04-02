#!/usr/bin/env python3
"""读取179 wam_hub.py源码中pool_apikey/inject/active相关逻辑"""
import subprocess, base64
from pathlib import Path
import tempfile

TARGET_IP   = "192.168.31.179"
TARGET_USER = "zhouyoukang"
TARGET_PASS = "wsy057066wsy"

def run_remote_ps1(content, timeout=60):
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

def remote_py(py_code, label="_p", timeout=60):
    b64 = base64.b64encode(py_code.encode("utf-8")).decode("ascii")
    chunks = [b64[i:i+8000] for i in range(0, len(b64), 8000)]
    init_ps = f'[System.IO.File]::WriteAllText("C:\\\\ctemp\\\\{label}_b64.txt","", [System.Text.Encoding]::ASCII)'
    run_remote(init_ps, timeout=8)
    for chunk in chunks:
        run_remote(f'[System.IO.File]::AppendAllText("C:\\\\ctemp\\\\{label}_b64.txt","{chunk}",[System.Text.Encoding]::ASCII)', timeout=8)
    exec_ps = f"""
$b64=[System.IO.File]::ReadAllText("C:\\\\ctemp\\\\{label}_b64.txt").Trim()
$bytes=[System.Convert]::FromBase64String($b64)
$text=[System.Text.Encoding]::UTF8.GetString($bytes)
[System.IO.File]::WriteAllText("C:\\\\ctemp\\\\{label}.py",$text,[System.Text.Encoding]::UTF8)
$env:PYTHONIOENCODING="utf-8"
python "C:\\\\ctemp\\\\{label}.py" 2>&1 | ForEach-Object {{ Write-Host $_ }}
"""
    return run_remote(exec_ps, timeout=timeout)

def main():
    print("=" * 60)
    print("  wam_hub.py源码深度分析")
    print("=" * 60)

    read_hub_py = r'''
from pathlib import Path
import re

hub_path = Path(r"E:\道\道生一\一生二\无感切号\scripts\wam_hub.py")
if not hub_path.exists():
    print("NOT_FOUND")
    exit()

src = hub_path.read_text(encoding="utf-8", errors="replace")
lines = src.splitlines()

print(f"=== FILE SIZE: {len(src)} bytes, {len(lines)} lines ===")

# Find sections related to pool_apikey writing
print("\n=== pool_apikey 相关 ===")
for i, line in enumerate(lines):
    if "_pool_apikey" in line.lower() or "pool_apikey" in line.lower() or "apikey.txt" in line.lower():
        ctx = lines[max(0,i-1):i+3]
        for j, l in enumerate(ctx):
            print(f"L{i-1+j}: {l}")
        print("---")

print("\n=== /api/pool/active 处理器 ===")
in_active = False
for i, line in enumerate(lines):
    if "/api/pool/active" in line or "pool/active" in line:
        # Print context
        for j in range(max(0,i-2), min(len(lines), i+20)):
            print(f"L{j}: {lines[j]}")
        print("---")

print("\n=== inject/write到state.vscdb ===")
for i, line in enumerate(lines):
    if "state.vscdb" in line or "windsurfAuthStatus" in line or "inject" in line.lower():
        for j in range(max(0,i-1), min(len(lines), i+5)):
            print(f"L{j}: {lines[j]}")
        print("---")

print("\n=== rotate 函数 ===")
in_rotate = False
rotate_start = -1
for i, line in enumerate(lines):
    if "def " in line and "rotate" in line.lower():
        rotate_start = i
        print(f"=== ROTATE FUNC at L{i} ===")
        for j in range(i, min(len(lines), i+40)):
            print(f"L{j}: {lines[j]}")
            if j > i and "def " in lines[j]:
                break
        print("---")

print("\n=== active 账号key如何传递到Windsurf ===")
for i, line in enumerate(lines):
    if "pool_key" in line or "apiKey" in line and "write" in lines[max(0,i-3):i+3].__str__():
        for j in range(max(0,i-2), min(len(lines), i+5)):
            print(f"L{j}: {lines[j]}")
        print("---")

print("DONE")
'''
    out, _ = remote_py(read_hub_py, "_rdhub", timeout=30)
    for line in out.splitlines():
        if line.strip():
            print(line)

    # Also check /api/pool/active via HTTP
    print("\n=== /api/pool/active HTTP ===")
    active_ps = r"""
try {
    $r = Invoke-WebRequest "http://127.0.0.1:9870/api/pool/active" -UseBasicParsing -TimeoutSec 5
    Write-Host "ACTIVE:" + $r.Content.Substring(0, [Math]::Min(500, $r.Content.Length))
} catch {
    Write-Host "ACTIVE:FAIL"
}
"""
    out2, _ = run_remote(active_ps, timeout=12)
    for line in out2.splitlines():
        if "ACTIVE:" in line:
            print(f"  {line[:300]}")

if __name__ == "__main__":
    main()
