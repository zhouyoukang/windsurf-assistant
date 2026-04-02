#!/usr/bin/env python3
"""
交互式DPAPI注入 — 通过Shell.Application在179用户桌面会话执行DPAPI
道法自然：WinRM无DPAPI权限 → Shell.Application获取桌面上下文
"""
import json, os, sys, subprocess, time, tempfile, base64
from pathlib import Path

TARGET_IP   = '192.168.31.179'
TARGET_USER = 'zhouyoukang'
TARGET_PASS = 'wsy057066wsy'
SCRIPT_DIR  = Path(__file__).parent

def log(tag, msg):
    c = {'OK':'\033[92m','ERR':'\033[91m','WARN':'\033[93m','INFO':'\033[96m'}.get(tag,'')
    print(f'  [{tag}] {c}{msg}\033[0m')

def get_live_key():
    live_file = SCRIPT_DIR / '_live_apikey.txt'
    if live_file.exists():
        k = live_file.read_text().strip()
        if len(k) > 20:
            return k
    return None

def run_winrm_ps(ps_block, timeout=30):
    full = [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -EA SilentlyContinue
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock {{
{ps_block}
}} -EA Stop
'''
    ]
    r = subprocess.run(full, capture_output=True, text=True, timeout=timeout,
                       encoding='utf-8', errors='replace')
    return r.stdout.strip(), r.returncode

def copy_file_to_179(local_path: Path, remote_path: str):
    full = [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -EA SilentlyContinue
$sess = New-PSSession -ComputerName {TARGET_IP} -Credential $cr -EA Stop
if (-not (Invoke-Command -Session $sess -ScriptBlock {{ Test-Path "C:\\ctemp" }})) {{
    Invoke-Command -Session $sess -ScriptBlock {{ New-Item -IT Directory "C:\\ctemp" -Force | Out-Null }}
}}
Copy-Item -Path "{local_path}" -Destination "{remote_path}" -ToSession $sess -Force
Remove-PSSession $sess
Write-Host "COPY_OK"
'''
    ]
    r = subprocess.run(full, capture_output=True, text=True, timeout=30,
                       encoding='utf-8', errors='replace')
    return 'COPY_OK' in r.stdout, r.stderr.strip()[:100]

def main():
    print('\n' + '='*60)
    print('  交互式DPAPI注入 — Shell.Application + 用户会话')
    print('='*60)
    
    live_key = get_live_key()
    if not live_key:
        log('ERR', '未找到live key，先运行 _decrypt_local_session.py')
        sys.exit(1)
    log('OK', f'Live key: {live_key[:50]}...')
    
    # Step 1: 写sessions数据到179临时文件
    sessions_data = json.dumps([{
        "id": "a1b2c3d4-live-inject-2026",
        "accessToken": live_key,
        "account": {"label": "live_inject", "id": "live_inject"},
        "scopes": []
    }])
    log('INFO', f'Sessions plaintext: {sessions_data[:80]}...')
    
    # Write to local temp then copy
    tmp_sess = Path(tempfile.gettempdir()) / '_live_sessions.json'
    tmp_sess.write_text(sessions_data, encoding='utf-8')
    ok, err = copy_file_to_179(tmp_sess, r'C:\ctemp\_live_sessions.json')
    if not ok:
        log('ERR', f'Copy sessions.json failed: {err}')
        sys.exit(1)
    log('OK', 'Sessions data copied to 179')
    
    # Step 2: 生成在交互会话中运行的PowerShell脚本
    # This script runs in the user's interactive desktop session (via Shell.Application)
    ps1_content = r'''
$ErrorActionPreference = "Stop"
$DB = "C:\Users\zhouyoukang\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb"
$LS = "C:\Users\zhouyoukang\AppData\Roaming\Windsurf\Local State"
$SESSIONS_FILE = "C:\ctemp\_live_sessions.json"
$LOG = "C:\ctemp\_dpapi_inject.log"

function Log($msg) { 
    $ts = (Get-Date -Format "HH:mm:ss")
    "$ts $msg" | Add-Content $LOG
    Write-Host $msg
}

Log "=== DPAPI Interactive Inject ==="
Log "DB: $DB"
Log "LS: $LS"

try {
    # Step 1: Read sessions plaintext
    $sessPlain = Get-Content $SESSIONS_FILE -Raw -Encoding UTF8
    Log "Sessions plaintext: $($sessPlain.Length) chars"
    
    # Step 2: Get AES key from Local State via DPAPI
    $lsJson = Get-Content $LS -Raw -Encoding UTF8 | ConvertFrom-Json
    $ekB64 = $lsJson.os_crypt.encrypted_key
    $ekBytes = [Convert]::FromBase64String($ekB64)
    # Strip DPAPI prefix (5 bytes: "DPAPI")
    $ekBytes = $ekBytes[5..($ekBytes.Length-1)]
    
    # DPAPI decrypt
    Add-Type -AssemblyName System.Security
    $ekSecure = [System.Security.Cryptography.ProtectedData]::Unprotect(
        $ekBytes, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser
    )
    Log "AES key: $($ekSecure.Length) bytes"
    
    # Step 3: AES-GCM encrypt sessions
    # Install cryptography if needed, then use Python for AES-GCM
    $pyScript = @"
import sys, json, base64, secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

aes_key_hex = sys.argv[1]
plaintext = open(r'C:\ctemp\_live_sessions.json', encoding='utf-8').read()
api_server = 'https://server.self-serve.windsurf.com'

key = bytes.fromhex(aes_key_hex)
def encrypt(key, plain):
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, plain.encode('utf-8'), None)
    raw = b'v10' + nonce + ct
    return json.dumps({'type':'Buffer','data':list(raw)})

sess_enc = encrypt(key, plaintext)
url_enc = encrypt(key, api_server)

# Write results
import sqlite3
db = r'C:\Users\zhouyoukang\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
conn = sqlite3.connect(db, timeout=15)
conn.execute('PRAGMA journal_mode=WAL')

sess_key = 'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.sessions"}'
url_key = 'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.apiServerUrl"}'
conn.execute('INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)', (sess_key, sess_enc))
conn.execute('INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)', (url_key, url_enc))
conn.commit()
conn.close()
print('SESSIONS_INJECTED OK')
"@
    
    $aesHex = [BitConverter]::ToString($ekSecure).Replace('-','').ToLower()
    Log "AES hex: $($aesHex.Substring(0,16))..."
    
    $pyTmp = "C:\ctemp\_aes_inject.py"
    $pyScript | Out-File $pyTmp -Encoding UTF8
    
    $result = python $pyTmp $aesHex 2>&1
    Log "Python result: $result"
    
    if ($result -match "SESSIONS_INJECTED") {
        Log "SUCCESS: Sessions encrypted and injected"
    } else {
        Log "ERROR: Sessions injection failed: $result"
    }
    
} catch {
    Log "EXCEPTION: $_"
}

Log "Done."
'''
    
    tmp_ps1 = Path(tempfile.gettempdir()) / '_dpapi_inject_interactive.ps1'
    tmp_ps1.write_text(ps1_content, encoding='utf-8')
    
    # Step 3: Copy PS1 to 179
    ok2, err2 = copy_file_to_179(tmp_ps1, r'C:\ctemp\_dpapi_inject_interactive.ps1')
    if not ok2:
        log('ERR', f'Copy PS1 failed: {err2}')
        sys.exit(1)
    log('OK', 'PS1 script copied to 179')
    
    # Step 4: Kill Windsurf first (release DB lock)
    log('INFO', 'Kill Windsurf on 179...')
    out, rc = run_winrm_ps('Stop-Process -Name Windsurf -Force -EA SilentlyContinue; Write-Host "KILLED"')
    log('INFO', f'Kill: {out.strip()}')
    time.sleep(2)
    
    # Step 5: Run PS1 via Shell.Application (interactive session = DPAPI works!)
    log('INFO', 'Shell.Application で PS1 を実行 (interactive DPAPI)...')
    ps_shell = r'''
$shell = New-Object -ComObject Shell.Application
$shell.ShellExecute("powershell.exe", "-NoProfile -ExecutionPolicy Bypass -File C:\ctemp\_dpapi_inject_interactive.ps1", "", "open", 1)
Write-Host "SHELL_EXEC: sent"
'''
    out2, rc2 = run_winrm_ps(ps_shell, timeout=10)
    log('INFO', f'Shell exec: {out2.strip()}')
    
    # Wait for PS1 to complete
    log('INFO', '等待15秒让交互式脚本完成...')
    time.sleep(15)
    
    # Step 6: Check the log file
    log('INFO', '读取注入日志...')
    out3, rc3 = run_winrm_ps(r'Get-Content "C:\ctemp\_dpapi_inject.log" -EA SilentlyContinue')
    log('INFO', f'注入日志:\n{out3}')
    
    # Step 7: Verify sessions in DB
    log('INFO', '验证sessions...')
    verify_ps = r'''
python -c "
import sqlite3
db = r'C:\Users\zhouyoukang\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
c = sqlite3.connect(db)
rows = c.execute('SELECT key, length(value) FROM ItemTable WHERE key LIKE ?', ('%windsurf_auth%',)).fetchall()
for r in rows: print(r[0][:60] + ' => ' + str(r[1]))
c.close()
" 2>&1'''
    out4, rc4 = run_winrm_ps(verify_ps)
    log('INFO', f'DB状态:\n{out4}')
    
    # Step 8: Start Windsurf
    log('INFO', '启动Windsurf...')
    ps_start = r'''
$shell = New-Object -ComObject Shell.Application
$shell.Open("D:\Windsurf\Windsurf.exe")
Start-Sleep -Seconds 6
$c = (Get-Process -Name Windsurf -EA SilentlyContinue).Count
Write-Host "WS_PROCS:$c"
'''
    out5, rc5 = run_winrm_ps(ps_start, timeout=15)
    log('INFO', f'启动结果: {out5.strip()}')
    
    # Step 9: Check logs after 12 seconds
    log('INFO', '等待12秒检查日志...')
    time.sleep(12)
    
    check_ps = r'''
$logPath = "C:\Users\zhouyoukang\AppData\Roaming\Windsurf\logs"
$f = Get-ChildItem $logPath -Recurse -Filter "renderer.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($f) {
    Write-Host "LOG:$($f.Name) $($f.LastWriteTime)"
    $lines = Get-Content $f.FullName -Tail 30 -EA SilentlyContinue
    $errs = $lines | Where-Object { $_ -match "unauthenticated|primary.api|API key not found" }
    if ($errs) { 
        Write-Host "[STILL_FAILING]"
        $errs | Select-Object -Last 3
    } else { 
        Write-Host "[NO_AUTH_ERRORS] Windsurf auth looks OK!"
        $lines | Select-Object -Last 5
    }
}
$c = (Get-Process -Name Windsurf -EA SilentlyContinue).Count
Write-Host "WS_PROCS:$c"
'''
    out6, rc6 = run_winrm_ps(check_ps, timeout=20)
    print('\n--- 最终验证 ---')
    print(out6)
    
    print('='*60)

if __name__ == '__main__':
    main()
