#!/usr/bin/env python3
"""
从本机提取有效Windsurf auth，跨机注入179
道法自然：本机正在工作 → 提取 → 注入179 → 重启
"""
import sqlite3, json, os, sys, base64, subprocess, time, shutil, tempfile
from pathlib import Path

TARGET_IP   = '192.168.31.179'
TARGET_USER = 'zhouyoukang'
TARGET_PASS = 'wsy057066wsy'

def log(tag, msg):
    c = {'OK':'\033[92m','ERR':'\033[91m','WARN':'\033[93m','INFO':'\033[96m'}.get(tag,'')
    print(f'  [{tag}] {c}{msg}\033[0m')

# ── Step 1: 提取本机auth ──
def extract_local_auth():
    log('INFO', '提取本机 windsurfAuthStatus...')
    local_db = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')
    conn = sqlite3.connect(local_db, timeout=5)
    
    auth_blob = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
    conf_blob = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfConfigurations'").fetchone()
    conn.close()
    
    if not auth_blob:
        log('ERR', '本机无windsurfAuthStatus!')
        return None, None
    
    auth_str = auth_blob[0]
    conf_str = conf_blob[0] if conf_blob else ''
    
    auth_obj = json.loads(auth_str)
    api_key = auth_obj.get('apiKey', '')
    email_label = 'local_inject'
    
    log('OK', f'本机apiKey: {api_key[:50]}...')
    log('INFO', f'本机model_configs_len: {len(str(auth_obj.get("allowedCommandModelConfigsProtoBinaryBase64","")))}')
    log('INFO', f'本机windsurfConfigurations: {len(conf_str)} chars')
    
    return auth_str, conf_str, api_key, email_label

# ── Step 2: 生成在179上运行的注入脚本 ──
def gen_inject_script(auth_str, conf_str, api_key, email_label):
    log('INFO', '生成179注入脚本...')
    
    # Encode blobs as JSON strings to safely embed in script
    auth_json = json.dumps(auth_str)
    conf_json = json.dumps(conf_str)
    api_key_json = json.dumps(api_key)
    email_label_json = json.dumps(email_label)
    api_server_url = "https://server.self-serve.windsurf.com"
    
    script = f'''#!/usr/bin/env python3
"""注入脚本 - 在179上执行"""
import sqlite3, json, os, sys, ctypes, ctypes.wintypes, base64, secrets, subprocess, time, shutil
from pathlib import Path
from datetime import datetime
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "cryptography", "-q"], check=True)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TARGET_USER = "zhouyoukang"
USER_BASE = Path(f"C:/Users/{{TARGET_USER}}/AppData/Roaming/Windsurf")
USER_LS   = USER_BASE / "Local State"
USER_DB   = USER_BASE / "User/globalStorage/state.vscdb"

NEW_AUTH_STATUS   = {auth_json}
NEW_CONFIGURATIONS = {conf_json}
NEW_API_KEY       = {api_key_json}
EMAIL_LABEL       = {email_label_json}
API_SERVER_URL    = "{api_server_url}"

class DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', ctypes.wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

def dpapi_decrypt(data: bytes):
    bi = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    bo = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(bi), None, None, None, None, 0x1, ctypes.byref(bo))
    if ok:
        raw = ctypes.string_at(bo.pbData, bo.cbData)
        ctypes.windll.kernel32.LocalFree(bo.pbData)
        return raw
    return None

def aes_gcm_encrypt(key: bytes, plaintext: str) -> bytes:
    nonce = secrets.token_bytes(12)
    ct_tag = AESGCM(key).encrypt(nonce, plaintext.encode('utf-8'), None)
    return b'v10' + nonce + ct_tag

def to_electron_buffer(data: bytes) -> str:
    return json.dumps({{"type": "Buffer", "data": list(data)}})

def get_aes_key():
    if not USER_LS.exists():
        print("ERR: Local State not found")
        return None
    ls = json.loads(USER_LS.read_text(encoding='utf-8', errors='replace'))
    ek_b64 = ls.get('os_crypt', {{}}).get('encrypted_key', '')
    if not ek_b64:
        print("ERR: No encrypted_key")
        return None
    ek = base64.b64decode(ek_b64)
    if ek[:5] == b'DPAPI':
        ek = ek[5:]
    aes_key = dpapi_decrypt(ek)
    if aes_key:
        print(f"AES_KEY_OK: {{len(aes_key)}} bytes")
    else:
        print("ERR: DPAPI decrypt failed")
    return aes_key

# Kill Windsurf
print("Killing Windsurf...")
subprocess.run(['taskkill', '/F', '/IM', 'Windsurf.exe'], capture_output=True)
time.sleep(2)

# Backup
if USER_DB.exists():
    try:
        bak = USER_DB.parent / f"state.vscdb.bak_{{datetime.now().strftime('%Y%m%d_%H%M%S')}}"
        shutil.copy2(str(USER_DB), str(bak))
        print(f"BACKUP: {{bak.name}}")
    except Exception as e:
        print(f"BACKUP_SKIP: {{e}}")

# Get AES key
aes_key = get_aes_key()

# Build injection dict
kv = {{}}

# A. windsurfAuthStatus
kv['windsurfAuthStatus'] = NEW_AUTH_STATUS
print(f"AUTH_STATUS: {{len(NEW_AUTH_STATUS)}} chars")

# B. windsurfConfigurations
if NEW_CONFIGURATIONS:
    kv['windsurfConfigurations'] = NEW_CONFIGURATIONS
    print(f"CONFIGURATIONS: {{len(NEW_CONFIGURATIONS)}} chars")

# C. safeStorage sessions
if aes_key:
    import uuid
    session_id = str(uuid.uuid4())
    sessions_plaintext = json.dumps([{{
        "id": session_id,
        "accessToken": NEW_API_KEY,
        "account": {{"label": EMAIL_LABEL, "id": EMAIL_LABEL}},
        "scopes": []
    }}])
    sess_v10 = aes_gcm_encrypt(aes_key, sessions_plaintext)
    sess_buf = to_electron_buffer(sess_v10)
    kv['secret://{{"extensionId":"codeium.windsurf","key":"windsurf_auth.sessions"}}'] = sess_buf
    print(f"SESSIONS: encrypted {{len(sess_buf)}} chars")
    
    url_v10 = aes_gcm_encrypt(aes_key, API_SERVER_URL)
    url_buf = to_electron_buffer(url_v10)
    kv['secret://{{"extensionId":"codeium.windsurf","key":"windsurf_auth.apiServerUrl"}}'] = url_buf
    print("API_SERVER_URL: encrypted")
else:
    print("WARN: No AES key, skipping safeStorage injection")

# Write to DB
conn = sqlite3.connect(str(USER_DB), timeout=15)
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA busy_timeout=10000')
n = 0
for k, v in kv.items():
    conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (k, v))
    n += 1
conn.commit()
conn.close()
print(f"DB_WRITE: {{n}} keys written")

# Verify
conn2 = sqlite3.connect(str(USER_DB), timeout=5)
row = conn2.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
if row:
    a = json.loads(row[0])
    ak = a.get('apiKey','')
    print(f"VERIFY_OK: apikey_len={{len(ak)}} preview={{ak[:40]}}")
conn2.close()

# Restart Windsurf
ws_exe = r"D:\\Windsurf\\Windsurf.exe"
if not Path(ws_exe).exists():
    ws_exe = r"C:\\Users\\zhouyoukang\\AppData\\Local\\Programs\\Windsurf\\Windsurf.exe"
if Path(ws_exe).exists():
    subprocess.Popen([ws_exe])
    print(f"RESTART: {{ws_exe}}")
else:
    print("WARN: Windsurf.exe not found at known paths")

print("INJECT_COMPLETE")
'''
    return script

# ── Step 3: Copy and run on 179 ──
def copy_and_run_on_179(script_content):
    log('INFO', '复制脚本到179...')
    
    # Write locally
    tmp = Path(tempfile.gettempdir()) / '_cross_inject_ws.py'
    tmp.write_text(script_content, encoding='utf-8')
    log('OK', f'本地脚本: {tmp} ({tmp.stat().st_size} bytes)')
    
    # Copy via WinRM PSSession
    ps_copy = [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -ErrorAction SilentlyContinue
$sess = New-PSSession -ComputerName {TARGET_IP} -Credential $cr -ErrorAction Stop
if (-not (Invoke-Command -Session $sess -ScriptBlock {{ Test-Path "C:\\ctemp" }})) {{
    Invoke-Command -Session $sess -ScriptBlock {{ New-Item -ItemType Directory "C:\\ctemp" -Force | Out-Null }}
}}
Copy-Item -Path "{tmp}" -Destination "C:\\ctemp\\_cross_inject_ws.py" -ToSession $sess -Force
Remove-PSSession $sess
Write-Host "COPY_OK"
'''
    ]
    r = subprocess.run(ps_copy, capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace')
    out = r.stdout.strip()
    err = r.stderr.strip()
    log('INFO', f'Copy结果: {out} | err: {err[:100] if err else "none"}')
    
    if 'COPY_OK' not in out:
        log('ERR', f'Copy-Item失败，尝试base64分块写入...')
        return False
    
    log('OK', 'Copy-Item成功')
    return True

def run_inject_on_179():
    log('INFO', '在179执行注入脚本...')
    ps_run = [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -ErrorAction SilentlyContinue
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock {{
    python C:\\ctemp\\_cross_inject_ws.py 2>&1
}} -ErrorAction Stop
'''
    ]
    r = subprocess.run(ps_run, capture_output=True, text=True, timeout=90, encoding='utf-8', errors='replace')
    out = r.stdout.strip()
    err = r.stderr.strip()
    return out, err

def main():
    print('\n' + '='*60)
    print('  跨机Windsurf注入 — 本机→179')
    print('='*60)
    
    result = extract_local_auth()
    if result[0] is None:
        sys.exit(1)
    auth_str, conf_str, api_key, email_label = result
    
    script = gen_inject_script(auth_str, conf_str, api_key, email_label)
    log('OK', f'注入脚本生成: {len(script)} chars')
    
    if not copy_and_run_on_179(script):
        log('ERR', '脚本复制失败')
        sys.exit(1)
    
    out, err = run_inject_on_179()
    print('\n--- 179执行输出 ---')
    print(out)
    if err:
        print('STDERR:', err[:300])
    
    if 'INJECT_COMPLETE' in out:
        log('OK', '注入成功！Windsurf已重启')
    else:
        log('ERR', '注入可能失败，检查输出')
    
    print('='*60)

if __name__ == '__main__':
    main()
