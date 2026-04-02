#!/usr/bin/env python3
"""
_deploy_179_v322.py — 推送WAM v3.22.0全量模块到179机
道法自然·推进到底·解决到底
"""
import subprocess, base64, json, os, sys, time
from pathlib import Path

TARGET_IP   = '192.168.31.179'
TARGET_USER = 'zhouyoukang'
TARGET_PASS = 'wsy057066wsy'
HOT_REMOTE  = r'C:\Users\zhouyoukang\.wam-hot'

SRC_DIR = Path(r'e:\道\道生一\一生二\无感切号\src')
ACCOUNTS_SRC = Path(r'C:\Users\ai\AppData\Roaming\Windsurf\User\globalStorage\windsurf-login-accounts.json')

FILES = [
    'extension.js',
    'accountManager.js',
    'authService.js',
    'cloudPool.js',
    'fingerprintManager.js',
    'webviewProvider.js',
]

def log(tag, msg):
    colors = {'OK': '\033[92m', 'ERR': '\033[91m', 'WARN': '\033[93m', 'INFO': '\033[96m'}
    c = colors.get(tag, '')
    print(f'  [{tag}] {c}{msg}\033[0m')

def winrm_exec(script_b64, timeout=60):
    """Execute a base64-encoded Python script on 179 via WinRM."""
    ps_cmd = f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -ErrorAction SilentlyContinue
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock {{
    $b64 = "{script_b64}"
    $bytes = [Convert]::FromBase64String($b64)
    $tmp = "C:\\ctemp\\_wam_deploy_tmp.py"
    if (-not (Test-Path "C:\\ctemp")) {{ New-Item -ItemType Directory "C:\\ctemp" -Force | Out-Null }}
    [IO.File]::WriteAllBytes($tmp, $bytes)
    python $tmp 2>&1
}} 2>&1
'''
    r = subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps_cmd],
        capture_output=True, text=True, timeout=timeout,
        encoding='utf-8', errors='replace'
    )
    return (r.stdout + r.stderr).strip()

def push_file(remote_name, local_path):
    """Push a single file to 179 hot-dir via base64 chunks."""
    data = local_path.read_bytes()
    b64_full = base64.b64encode(data).decode('ascii')
    sz = len(data)

    # Write file script via Python on 179
    py_script = f'''
import base64, os
from pathlib import Path
hot = Path(r"{HOT_REMOTE}")
hot.mkdir(parents=True, exist_ok=True)
b64 = "{b64_full}"
data = base64.b64decode(b64)
(hot / "{remote_name}").write_bytes(data)
print("WRITE_OK:" + "{remote_name}" + ":" + str(len(data)))
'''
    script_b64 = base64.b64encode(py_script.encode('utf-8')).decode('ascii')
    out = winrm_exec(script_b64, timeout=90)
    if f'WRITE_OK:{remote_name}' in out:
        log('OK', f'{remote_name} ({sz}B) → 179 hot-dir')
        return True
    else:
        log('ERR', f'{remote_name} failed: {out[:300]}')
        return False

def push_accounts():
    """Push accounts JSON to 179."""
    if not ACCOUNTS_SRC.exists():
        log('WARN', f'accounts source not found: {ACCOUNTS_SRC}')
        return False

    data = ACCOUNTS_SRC.read_bytes()
    b64_full = base64.b64encode(data).decode('ascii')
    remote_accounts = r'C:\Users\zhouyoukang\AppData\Roaming\Windsurf\User\globalStorage\windsurf-login-accounts.json'
    remote_ext_accounts = r'C:\Users\zhouyoukang\AppData\Roaming\Windsurf\User\globalStorage\zhouyoukang.windsurf-assistant\windsurf-login-accounts.json'

    py_script = f'''
import base64, json
from pathlib import Path
data = base64.b64decode("{b64_full}")
# Try to parse to verify
try:
    arr = json.loads(data.decode("utf-8-sig"))
    cnt = len(arr)
except:
    cnt = -1
# Write to main location
p1 = Path(r"{remote_accounts}")
p1.parent.mkdir(parents=True, exist_ok=True)
p1.write_bytes(data)
# Write to extension location
p2 = Path(r"{remote_ext_accounts}")
p2.parent.mkdir(parents=True, exist_ok=True)
p2.write_bytes(data)
print("ACCOUNTS_OK:count=" + str(cnt))
'''
    script_b64 = base64.b64encode(py_script.encode('utf-8')).decode('ascii')
    out = winrm_exec(script_b64, timeout=60)
    if 'ACCOUNTS_OK' in out:
        log('OK', f'accounts synced: {out.strip()}')
        return True
    else:
        log('ERR', f'accounts push failed: {out[:300]}')
        return False

def send_reload():
    """Write .reload signal to 179 hot-dir."""
    ts = str(int(time.time() * 1000))
    py_script = f'''
from pathlib import Path
import time
p = Path(r"{HOT_REMOTE}") / ".reload"
p.write_text("{ts}", encoding="utf-8")
print("RELOAD_OK:" + "{ts}")
'''
    script_b64 = base64.b64encode(py_script.encode('utf-8')).decode('ascii')
    out = winrm_exec(script_b64, timeout=20)
    if 'RELOAD_OK' in out:
        log('OK', '.reload signal written')
        return True
    else:
        log('ERR', f'.reload failed: {out[:200]}')
        return False

def verify_hub():
    """Check WAM hub version on 179."""
    py_script = '''
import urllib.request, json
try:
    r = urllib.request.urlopen("http://127.0.0.1:9870/health", timeout=5)
    d = json.loads(r.read())
    print("HUB_OK:version=" + d.get("version","?") + " accounts=" + str(d.get("accounts",0)) + " active=" + str(d.get("activeIndex",-1)))
except Exception as e:
    print("HUB_ERR:" + str(e)[:100])
'''
    script_b64 = base64.b64encode(py_script.encode('utf-8')).decode('ascii')
    out = winrm_exec(script_b64, timeout=20)
    return out.strip()

def test_rotate():
    """Call /api/pool/rotate on 179 hub to test switching."""
    py_script = '''
import urllib.request, json
try:
    req = urllib.request.Request(
        "http://127.0.0.1:9870/api/pool/rotate",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    r = urllib.request.urlopen(req, timeout=30)
    d = json.loads(r.read())
    print("ROTATE_OK:" + json.dumps(d)[:200])
except Exception as e:
    print("ROTATE_ERR:" + str(e)[:200])
'''
    script_b64 = base64.b64encode(py_script.encode('utf-8')).decode('ascii')
    out = winrm_exec(script_b64, timeout=45)
    return out.strip()

def verify_auth():
    """Check 179 state.vscdb current auth."""
    py_script = '''
import sqlite3, json
db = r"C:\\Users\\zhouyoukang\\AppData\\Roaming\\Windsurf\\User\\globalStorage\\state.vscdb"
try:
    c = sqlite3.connect(db, timeout=3)
    r = c.execute("SELECT value FROM ItemTable WHERE key=?", ("windsurfAuthStatus",)).fetchone()
    if r:
        a = json.loads(r[0])
        print("AUTH:" + a.get("email","?") + "|" + a.get("apiKey","?")[:40])
    else:
        print("AUTH:NULL")
    c.close()
except Exception as e:
    print("AUTH_ERR:" + str(e)[:100])
'''
    script_b64 = base64.b64encode(py_script.encode('utf-8')).decode('ascii')
    out = winrm_exec(script_b64, timeout=20)
    return out.strip()

def main():
    print('\n' + '='*65)
    print('  WAM v3.22.0 → 179机 zhouyoukang 全量部署')
    print('  道法自然·推进到底·解决到底')
    print('='*65)

    # Phase 1: Push hot-dir modules
    print('\n[Phase 1] 推送热目录模块...')
    ok = 0
    for name in FILES:
        src = SRC_DIR / name
        if not src.exists():
            log('WARN', f'{name} not found at {src}')
            continue
        if push_file(name, src):
            ok += 1
    log('INFO', f'模块推送: {ok}/{len(FILES)} 成功')

    # Phase 2: Push accounts
    print('\n[Phase 2] 同步账号池...')
    push_accounts()

    # Phase 3: .reload signal
    print('\n[Phase 3] 触发热重载...')
    send_reload()

    # Phase 4: Wait for hot reload
    print('\n[Phase 4] 等待热重载(5s)...')
    time.sleep(5)

    # Phase 5: Verify hub
    print('\n[Phase 5] 验证hub版本...')
    hub_out = verify_hub()
    print(f'  Hub: {hub_out}')

    # Phase 6: Test rotate
    print('\n[Phase 6] 切号测试...')
    auth_before = verify_auth()
    print(f'  切前auth: {auth_before}')

    rotate_out = test_rotate()
    print(f'  Rotate结果: {rotate_out}')

    time.sleep(3)
    auth_after = verify_auth()
    print(f'  切后auth: {auth_after}')

    if auth_before != auth_after:
        log('OK', f'切号成功! apiKey已变化')
    elif 'ROTATE_OK' in rotate_out:
        log('OK', 'Hub接受rotate请求 (apiKey可能在Windsurf内存中已更新)')
    else:
        log('WARN', '切号可能未完成，检查上方输出')

    print('\n' + '='*65)
    print('  部署完成')
    print('='*65)

if __name__ == '__main__':
    main()
