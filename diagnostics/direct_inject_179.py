"""
直注入脚本: 从141云池读取auth_blob -> 直写179 state.vscdb
无需DPAPI, 无需Firebase, 绕过provideAuthTokenToAuthProvider
"""
import sqlite3, json, sys, subprocess, os, time

POOL_DB = r'e:\道\道生一\一生二\Windsurf无限额度\030-云端号池_CloudPool\cloud_pool.db'
STATE_DB_REMOTE = r'C:/Users/zhouyoukang/AppData/Roaming/Windsurf/User/globalStorage/state.vscdb'
PS_HOST = '192.168.31.179'
PS_USER = 'zhouyoukang'
PS_PASS = 'wsy057066wsy'

def get_best_account():
    c = sqlite3.connect(POOL_DB)
    c.row_factory = sqlite3.Row
    row = c.execute("""
        SELECT email, auth_blob_enc, api_key_enc, api_key_preview, password_enc
        FROM accounts
        WHERE status='available'
          AND auth_blob_enc!='' AND auth_blob_enc IS NOT NULL
          AND daily_pct > 30
        ORDER BY (daily_pct + weekly_pct) DESC LIMIT 1
    """).fetchone()
    if not row:
        print("ERROR: no available accounts with auth_blob")
        c.close()
        return None, None
    email = row['email']
    blob = json.loads(row['auth_blob_enc'])
    # Mark as allocated
    c.execute("UPDATE accounts SET status='allocated', allocated_to='179', allocated_at=? WHERE email=?",
              (time.strftime('%Y-%m-%d %H:%M:%S'), email))
    c.commit()
    c.close()
    print("Got account: %s (apiKey: %s...)" % (email, row['api_key_preview'][:25] if row['api_key_preview'] else '?'))
    return email, blob

def build_inject_script(blob):
    status_val = blob.get('windsurfAuthStatus', '')
    config_val = blob.get('windsurfConfigurations', '')
    # Escape for PowerShell heredoc
    status_json = json.dumps(status_val).replace("'", "''")
    config_json = json.dumps(config_val).replace("'", "''")
    py_code = r"""
import sqlite3, json, sys
db = r'""" + STATE_DB_REMOTE + r"""'
c = sqlite3.connect(db, timeout=10)
status_val = """ + repr(status_val) + r"""
config_val = """ + repr(config_val) + r"""
# Write windsurfAuthStatus
c.execute("INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)", ('windsurfAuthStatus', status_val))
# Write windsurfConfigurations if present
if config_val:
    c.execute("INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)", ('windsurfConfigurations', config_val))
# Clear cached plan info to force re-read
c.execute("DELETE FROM ItemTable WHERE key='cachedPlanInfo'")
c.commit()
c.close()
# Verify
c2 = sqlite3.connect(db, timeout=5)
r = c2.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
if r:
    d = json.loads(r[0])
    print("INJECTED: apiKey=" + d.get('apiKey','?')[:30])
else:
    print("ERROR: injection failed")
c2.close()
"""
    return py_code

def run_remote_python(py_code):
    # Write py script to temp
    tmp_py = r'C:\Temp\_direct_inject_exec.py'
    with open(tmp_py, 'w', encoding='utf-8') as f:
        f.write(py_code)
    
    ps_cmd = r"""
$sp = New-Object System.Security.SecureString
'""" + PS_PASS + r"""'.ToCharArray() | ForEach-Object { $sp.AppendChar($_) }
$cr = New-Object System.Management.Automation.PSCredential('""" + PS_USER + r"""', $sp)
$localPy = Get-Content 'C:\Temp\_direct_inject_exec.py' -Raw
Invoke-Command -ComputerName """ + PS_HOST + r""" -Credential $cr -ArgumentList $localPy -ScriptBlock {
    param($code)
    [System.IO.File]::WriteAllText('C:\Temp\_inject_exec.py', $code, [System.Text.Encoding]::UTF8)
    python 'C:\Temp\_inject_exec.py' 2>&1
}
"""
    result = subprocess.run(['powershell', '-NonInteractive', '-Command', ps_cmd],
                            capture_output=True, text=True, timeout=60)
    print("STDOUT:", result.stdout.strip())
    if result.stderr.strip():
        print("STDERR:", result.stderr.strip()[:300])
    return result.returncode == 0

def main():
    print("=== Direct Auth Blob Injection: 141->179 ===")
    email, blob = get_best_account()
    if not blob:
        sys.exit(1)
    
    print("Building injection script...")
    py_code = build_inject_script(blob)
    
    print("Injecting into 179 state.vscdb...")
    ok = run_remote_python(py_code)
    
    if ok:
        print("SUCCESS: auth_blob injected directly into 179 state.vscdb")
        print("Account %s is now active. Windsurf will pick up new apiKey on next request." % email)
    else:
        print("FAILED: injection returned non-zero exit code")

if __name__ == '__main__':
    main()
