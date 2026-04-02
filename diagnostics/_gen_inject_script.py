#!/usr/bin/env python3
"""
生成注入脚本并通过WinRM复制到179执行
道法自然·无为而治
"""
import json, subprocess, sys, tempfile, os
from pathlib import Path

TARGET_IP   = '192.168.31.179'
TARGET_USER = 'zhouyoukang'
TARGET_PASS = 'wsy057066wsy'

SCRIPT_DIR = Path(__file__).parent
ENGINE_DIR = SCRIPT_DIR.parent / '010-道引擎_DaoEngine'
SNAP_FILE  = ENGINE_DIR / '_wam_snapshots.json'
SKIP_EMAILS = {'ehhs619938345@yahoo.com', 'fpzgcmcdaqbq152@yahoo.com'}

def log(tag, msg):
    colors = {'OK':'\033[92m','ERR':'\033[91m','WARN':'\033[93m','INFO':'\033[96m'}
    c = colors.get(tag, '')
    print(f'  [{tag}] {c}{msg}\033[0m')

def pick_best_account():
    data = json.loads(SNAP_FILE.read_text('utf-8'))
    snapshots = data.get('snapshots', {})
    candidates = []
    for email, snap in snapshots.items():
        if email in SKIP_EMAILS:
            continue
        blobs = snap.get('blobs', {})
        auth_blob = blobs.get('windsurfAuthStatus', '')
        if not auth_blob:
            continue
        try:
            auth_obj = json.loads(auth_blob)
            ak = auth_obj.get('apiKey', '')
            em = auth_obj.get('email', '')
            if len(ak) > 20 and em:
                candidates.append({
                    'email': email,
                    'apiKey': ak,
                    'authBlob': auth_blob,
                    'confBlob': blobs.get('windsurfConfigurations', ''),
                    'harvestedAt': snap.get('harvested_at', ''),
                })
        except:
            pass
    candidates.sort(key=lambda x: x['harvestedAt'], reverse=True)
    return candidates[0] if candidates else None

def write_inject_script(account):
    """生成注入脚本，存到本地临时文件"""
    auth_blob = account['authBlob']
    conf_blob = account['confBlob']
    
    # Use json.dumps to safely encode the blob strings
    auth_json = json.dumps(auth_blob)
    conf_json = json.dumps(conf_blob)
    
    script = f"""import sqlite3, json, sys
DB = r'C:\\\\Users\\\\zhouyoukang\\\\AppData\\\\Roaming\\\\Windsurf\\\\User\\\\globalStorage\\\\state.vscdb'
AUTH_BLOB = {auth_json}
CONF_BLOB = {conf_json}
try:
    c = sqlite3.connect(DB, timeout=10)
    c.execute("UPDATE ItemTable SET value=? WHERE key='windsurfAuthStatus'", (AUTH_BLOB,))
    changed = c.execute("SELECT changes()").fetchone()[0]
    if changed == 0:
        c.execute("INSERT INTO ItemTable(key,value) VALUES('windsurfAuthStatus',?)", (AUTH_BLOB,))
    if CONF_BLOB:
        c.execute("UPDATE ItemTable SET value=? WHERE key='windsurfConfigurations'", (CONF_BLOB,))
        ch2 = c.execute("SELECT changes()").fetchone()[0]
        if ch2 == 0:
            c.execute("INSERT INTO ItemTable(key,value) VALUES('windsurfConfigurations',?)", (CONF_BLOB,))
    c.commit()
    c.close()
    c2 = sqlite3.connect(DB, timeout=5)
    row = c2.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
    a = json.loads(row[0])
    print('INJECT_OK email=' + str(a.get('email','')) + ' apikey_len=' + str(len(a.get('apiKey',''))))
    c2.close()
except Exception as e:
    print('INJECT_ERR ' + str(e))
"""
    tmp = Path(tempfile.gettempdir()) / '_inject_ws_179.py'
    tmp.write_text(script, encoding='utf-8')
    return tmp

def run_winrm(ps_block, timeout=30):
    """通过PowerShell WinRM执行命令"""
    full = [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -ErrorAction SilentlyContinue
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ErrorAction Stop -ScriptBlock {{
{ps_block}
}} 2>&1
'''
    ]
    r = subprocess.run(full, capture_output=True, text=True, timeout=timeout,
                       encoding='utf-8', errors='replace')
    out = r.stdout.strip()
    if r.stderr.strip():
        out += '\nSTDERR:' + r.stderr.strip()
    return out, r.returncode

def copy_file_to_179(local_path: Path, remote_path: str):
    """通过PowerShell Copy-Item + WinRM Session复制文件到179"""
    full = [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -ErrorAction SilentlyContinue
$sess = New-PSSession -ComputerName {TARGET_IP} -Credential $cr -ErrorAction Stop
Copy-Item -Path "{local_path}" -Destination "{remote_path}" -ToSession $sess -Force
Remove-PSSession $sess
Write-Host "COPY_OK"
'''
    ]
    r = subprocess.run(full, capture_output=True, text=True, timeout=30,
                       encoding='utf-8', errors='replace')
    out = r.stdout.strip()
    err = r.stderr.strip()
    return out, r.returncode, err

def main():
    print('\n' + '='*60)
    print('  179 Windsurf注入修复 — 道法自然')
    print('='*60)
    
    # Step 1: Pick best account
    log('INFO', '从WAM快照选最优账号...')
    account = pick_best_account()
    if not account:
        log('ERR', '无可用账号！')
        sys.exit(1)
    log('OK', f"选中: {account['email']}")
    log('INFO', f"收割时间: {account['harvestedAt']}")
    log('INFO', f"ApiKey: {account['apiKey'][:50]}...")
    
    # Step 2: Write inject script locally
    log('INFO', '生成注入脚本...')
    tmp_script = write_inject_script(account)
    log('OK', f'脚本写入: {tmp_script} ({tmp_script.stat().st_size} bytes)')
    
    # Step 3: Kill Windsurf on 179 (unlock DB)
    log('INFO', '关闭179 Windsurf进程(释放DB锁)...')
    out, rc = run_winrm('Stop-Process -Name Windsurf -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 1; Write-Host "KILLED"')
    log('INFO', f'Kill结果: {out.strip()}')
    
    # Step 4: Copy inject script to 179
    log('INFO', '复制注入脚本到179...')
    out, rc, err = copy_file_to_179(tmp_script, r'C:\ctemp\_inject_ws.py')
    if 'COPY_OK' not in out:
        log('WARN', f'Copy-Item返回: {out} | err: {err[:100]}')
        # Fallback: mkdir + write via WinRM
        log('INFO', '尝试通过WinRM直接写文件...')
        content = tmp_script.read_text('utf-8')
        import base64
        b64 = base64.b64encode(content.encode('utf-8')).decode('ascii')
        # Split b64 into chunks to avoid arg length limit
        chunk_size = 4000
        chunks = [b64[i:i+chunk_size] for i in range(0, len(b64), chunk_size)]
        ps_write = f'''
if (-not (Test-Path 'C:\\ctemp')) {{ New-Item -ItemType Directory 'C:\\ctemp' -Force | Out-Null }}
$chunks = @({','.join([f'"{c}"' for c in chunks])})
$b64 = $chunks -join ""
$bytes = [System.Convert]::FromBase64String($b64)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
[System.IO.File]::WriteAllText('C:\\ctemp\\_inject_ws.py', $text, [System.Text.Encoding]::UTF8)
Write-Host "WRITE_OK:$((Get-Item 'C:\\ctemp\\_inject_ws.py').Length)bytes"
'''
        out2, rc2 = run_winrm(ps_write, timeout=30)
        log('INFO', f'Write结果: {out2.strip()}')
    else:
        log('OK', 'Copy-Item成功')
    
    # Step 5: Execute inject script on 179
    log('INFO', '在179执行注入...')
    out, rc = run_winrm('python C:\\ctemp\\_inject_ws.py 2>&1', timeout=30)
    log('INFO', f'注入输出: {out.strip()}')
    if 'INJECT_OK' in out:
        log('OK', '注入成功！')
    else:
        log('ERR', f'注入失败: {out}')
        sys.exit(1)
    
    # Step 6: Restart Windsurf
    log('INFO', '重启179 Windsurf...')
    ws_path = r'D:\Windsurf\Windsurf.exe'
    out, rc = run_winrm(f'Start-Process "{ws_path}" -WindowStyle Normal; Write-Host "STARTED"', timeout=15)
    log('INFO', f'启动结果: {out.strip()}')
    
    # Step 7: Verify
    import time
    log('INFO', '等待3秒后验证...')
    time.sleep(3)
    verify_script = Path(tempfile.gettempdir()) / '_verify_ws_179.py'
    verify_script.write_text(f'''import sqlite3, json
db = r'C:\\Users\\zhouyoukang\\AppData\\Roaming\\Windsurf\\User\\globalStorage\\state.vscdb'
c = sqlite3.connect(db)
r = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
a = json.loads(r[0])
print('VERIFY email='+a.get('email','')+' len='+str(len(a.get('apiKey',''))))
c.close()
''', encoding='utf-8')
    out, rc, err = copy_file_to_179(verify_script, r'C:\ctemp\_verify_ws.py')
    if 'COPY_OK' not in out:
        log('WARN', f'Copy-Item返回: {out} | err: {err[:100]}')
    else:
        log('OK', 'Copy-Item成功')
    out, rc = run_winrm('python C:\\ctemp\\_verify_ws.py 2>&1', timeout=15)
    log('INFO', f'验证: {out.strip()}')
    
    print('\n' + '='*60)
    print('  修复完成！Windsurf已重启，请在179上测试。')
    print('='*60)

if __name__ == '__main__':
    main()
