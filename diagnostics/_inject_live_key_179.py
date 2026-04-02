#!/usr/bin/env python3
"""
用本机真实运行API key注入179
真实key来自safeStorage解密，而非DB缓存
"""
import sqlite3, json, os, sys, base64, subprocess, time, tempfile
from pathlib import Path

TARGET_IP   = '192.168.31.179'
TARGET_USER = 'zhouyoukang'
TARGET_PASS = 'wsy057066wsy'
SCRIPT_DIR  = Path(__file__).parent

def log(tag, msg):
    c = {'OK':'\033[92m','ERR':'\033[91m','WARN':'\033[93m','INFO':'\033[96m'}.get(tag,'')
    print(f'  [{tag}] {c}{msg}\033[0m')

def get_live_key():
    """从本机safeStorage获取真实运行中的API key"""
    live_file = SCRIPT_DIR / '_live_apikey.txt'
    if live_file.exists():
        k = live_file.read_text().strip()
        if len(k) > 20:
            log('OK', f'Live key: {k[:50]}...')
            return k
    log('ERR', 'No live key found, run _decrypt_local_session.py first')
    return None

def get_local_auth_blob_with_new_key(new_key: str):
    """读取本机windsurfAuthStatus，替换为真实key"""
    local_db = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')
    conn = sqlite3.connect(local_db, timeout=5)
    row = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
    conf_row = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfConfigurations'").fetchone()
    conn.close()
    
    if row:
        auth_obj = json.loads(row[0])
        auth_obj['apiKey'] = new_key  # Replace with live key
        auth_str = json.dumps(auth_obj)
        log('OK', f'Auth blob updated: apiKey={new_key[:40]}..., model_configs_len={len(str(auth_obj.get("allowedCommandModelConfigsProtoBinaryBase64","")))}')
    else:
        # Minimal auth blob
        auth_str = json.dumps({"apiKey": new_key, "allowedCommandModelConfigsProtoBinaryBase64": "", "userStatusProtoBinaryBase64": ""})
        log('WARN', 'No local auth blob, using minimal')
    
    conf_str = conf_row[0] if conf_row else ''
    return auth_str, conf_str

def gen_inject_script(live_key: str, auth_str: str, conf_str: str):
    """生成在179上运行的注入脚本"""
    auth_json = json.dumps(auth_str)
    conf_json = json.dumps(conf_str)
    live_key_json = json.dumps(live_key)
    
    script = f'''#!/usr/bin/env python3
import sqlite3, json, os, sys, ctypes, ctypes.wintypes, base64, secrets, subprocess, time, shutil
from pathlib import Path
from datetime import datetime
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "cryptography", "-q"], check=True)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

USER_BASE = Path("C:/Users/zhouyoukang/AppData/Roaming/Windsurf")
USER_LS   = USER_BASE / "Local State"
USER_DB   = USER_BASE / "User/globalStorage/state.vscdb"
LIVE_KEY  = {live_key_json}
AUTH_STATUS = {auth_json}
CONFIGURATIONS = {conf_json}
API_SERVER_URL = "https://server.self-serve.windsurf.com"

class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

def dpapi_decrypt(data):
    bi = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    bo = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(bi), None, None, None, None, 0x1, ctypes.byref(bo))
    if ok:
        raw = ctypes.string_at(bo.pbData, bo.cbData); ctypes.windll.kernel32.LocalFree(bo.pbData); return raw
    return None

def aes_gcm_encrypt(key, plaintext):
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return b"v10" + nonce + ct

def to_buf(data):
    return json.dumps({{"type":"Buffer","data":list(data)}})

# Kill Windsurf
print("Killing Windsurf...")
subprocess.run(["taskkill", "/F", "/IM", "Windsurf.exe"], capture_output=True)
time.sleep(2)

# Backup
if USER_DB.exists():
    try:
        bak = USER_DB.parent / f"state.vscdb.bak_livekey_{{datetime.now().strftime('%Y%m%d_%H%M%S')}}"
        shutil.copy2(str(USER_DB), str(bak)); print(f"BACKUP: {{bak.name}}")
    except Exception as e: print(f"BACKUP_SKIP: {{e}}")

# Get AES key
aes_key = None
if USER_LS.exists():
    ls = json.loads(USER_LS.read_text(encoding="utf-8", errors="replace"))
    ek_b64 = ls.get("os_crypt", {{}}).get("encrypted_key", "")
    if ek_b64:
        ek = base64.b64decode(ek_b64)
        if ek[:5] == b"DPAPI": ek = ek[5:]
        aes_key = dpapi_decrypt(ek)
        print(f"AES_KEY: {{len(aes_key) if aes_key else 0}} bytes")

# Build kv
kv = {{}}
kv["windsurfAuthStatus"] = AUTH_STATUS
print(f"AUTH_STATUS: {{len(AUTH_STATUS)}} chars, key={{LIVE_KEY[:40]}}...")

if CONFIGURATIONS:
    kv["windsurfConfigurations"] = CONFIGURATIONS
    print(f"CONFIGURATIONS: {{len(CONFIGURATIONS)}} chars")

if aes_key:
    import uuid
    sess = json.dumps([{{"id":str(uuid.uuid4()),"accessToken":LIVE_KEY,"account":{{"label":"live_inject","id":"live_inject"}},"scopes":[]}}])
    kv['secret://{{"extensionId":"codeium.windsurf","key":"windsurf_auth.sessions"}}'] = to_buf(aes_gcm_encrypt(aes_key, sess))
    kv['secret://{{"extensionId":"codeium.windsurf","key":"windsurf_auth.apiServerUrl"}}'] = to_buf(aes_gcm_encrypt(aes_key, API_SERVER_URL))
    print(f"SESSIONS: encrypted with live key")

# Write DB
conn = sqlite3.connect(str(USER_DB), timeout=15)
conn.execute("PRAGMA journal_mode=WAL"); conn.execute("PRAGMA busy_timeout=10000")
for k, v in kv.items():
    conn.execute("INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)", (k, v))
conn.commit(); conn.close()
print(f"DB_WRITE: {{len(kv)}} keys")

# Verify
conn2 = sqlite3.connect(str(USER_DB), timeout=5)
r = conn2.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
if r:
    a = json.loads(r[0]); ak = a.get("apiKey","")
    print(f"VERIFY_OK: key={{ak[:50]}} len={{len(ak)}}")
conn2.close()

# Restart via Shell.Application (works in user session)
try:
    import win32com.client
    shell = win32com.client.Dispatch("Shell.Application")
    shell.Open(r"D:\\Windsurf\\Windsurf.exe")
    print("RESTART_SHELL: OK")
except:
    ws_exe = r"D:\\Windsurf\\Windsurf.exe"
    subprocess.Popen([ws_exe], creationflags=0x00000008)
    print("RESTART_POPEN: OK")

print("INJECT_COMPLETE")
'''
    return script

def copy_and_run_on_179(script: str):
    tmp = Path(tempfile.gettempdir()) / '_live_inject_ws.py'
    tmp.write_text(script, encoding='utf-8')
    log('INFO', f'Script: {tmp} ({tmp.stat().st_size} bytes)')
    
    # Copy via PSSession
    ps_copy = [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -EA SilentlyContinue
$sess = New-PSSession -ComputerName {TARGET_IP} -Credential $cr -EA Stop
Invoke-Command -Session $sess -ScriptBlock {{ if (-not (Test-Path "C:\\ctemp")) {{ New-Item -IT Directory "C:\\ctemp" -Force | Out-Null }} }}
Copy-Item -Path "{tmp}" -Destination "C:\\ctemp\\_live_inject_ws.py" -ToSession $sess -Force
Remove-PSSession $sess
Write-Host "COPY_OK"
'''
    ]
    r = subprocess.run(ps_copy, capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace')
    if 'COPY_OK' not in r.stdout:
        log('ERR', f'Copy failed: {r.stdout.strip()} {r.stderr.strip()[:100]}')
        return False
    log('OK', 'Copied to 179')
    
    # Run on 179
    ps_run = [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -EA SilentlyContinue
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock {{
    python C:\\ctemp\\_live_inject_ws.py 2>&1
}} -EA Stop
'''
    ]
    r2 = subprocess.run(ps_run, capture_output=True, text=True, timeout=90, encoding='utf-8', errors='replace')
    print('\n--- 179执行输出 ---')
    print(r2.stdout.strip())
    if r2.stderr.strip():
        print('STDERR:', r2.stderr.strip()[:300])
    return 'INJECT_COMPLETE' in r2.stdout

def restart_windsurf_179():
    """通过Shell.Application在交互会话启动Windsurf"""
    log('INFO', '通过Shell.Application启动Windsurf...')
    ps = [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock {{
    $shell = New-Object -ComObject Shell.Application
    $shell.Open("D:\\Windsurf\\Windsurf.exe")
    Start-Sleep -Seconds 6
    $c = (Get-Process -Name Windsurf -EA SilentlyContinue).Count
    Write-Host "WS_PROCS:$c"
}} -EA Stop
'''
    ]
    r = subprocess.run(ps, capture_output=True, text=True, timeout=20, encoding='utf-8', errors='replace')
    print(r.stdout.strip())

def main():
    print('\n' + '='*60)
    print('  真实Live Key注入179 — 道法自然')
    print('='*60)
    
    live_key = get_live_key()
    if not live_key:
        sys.exit(1)
    
    auth_str, conf_str = get_local_auth_blob_with_new_key(live_key)
    script = gen_inject_script(live_key, auth_str, conf_str)
    log('OK', f'脚本生成: {len(script)} chars')
    
    ok = copy_and_run_on_179(script)
    
    if ok:
        log('OK', '注入成功！')
        time.sleep(2)
        restart_windsurf_179()
    else:
        log('ERR', '注入失败，检查输出')
        sys.exit(1)
    
    # Wait and check logs
    log('INFO', '等待10秒检查日志...')
    time.sleep(10)
    
    ps_check = [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock {{
    $c = (Get-Process -Name Windsurf -EA SilentlyContinue).Count
    Write-Host "WS_PROCS:$c"
    $logPath = "C:\\Users\\zhouyoukang\\AppData\\Roaming\\Windsurf\\logs"
    $f = Get-ChildItem $logPath -Recurse -Filter "renderer.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($f) {{
        Write-Host "LOG:$($f.LastWriteTime)"
        $lines = Get-Content $f.FullName -Tail 30 -EA SilentlyContinue
        $errs = $lines | Where-Object {{ $_ -match "api.key|unauthenticated|permission|denied|error" }}
        if ($errs) {{ Write-Host "[ERRORS]"; $errs | Select-Object -Last 3 }}
        else {{ Write-Host "[NO_API_ERRORS] - Windsurf looks OK!" }}
    }}
}} -EA Stop
'''
    ]
    r = subprocess.run(ps_check, capture_output=True, text=True, timeout=20, encoding='utf-8', errors='replace')
    print('\n--- 验证结果 ---')
    print(r.stdout.strip())
    
    print('='*60)

if __name__ == '__main__':
    main()
