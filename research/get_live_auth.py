"""get_live_auth.py — 从 Windsurf 数据库提取 user_jwt + session_id + 完整认证信息"""
import sqlite3, json, os, re, glob

# Known DB paths
DB_PATHS = [
    r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb',
    r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\workspaceStorage',
]

def query_db(path):
    """Query all key-value pairs from state.vscdb"""
    try:
        con = sqlite3.connect(path)
        cur = con.cursor()
        cur.execute("SELECT key, value FROM ItemTable")
        rows = cur.fetchall()
        con.close()
        return rows
    except Exception as e:
        return []

# 1. Check main state.vscdb
print("=== Windsurf state.vscdb ===")
rows = query_db(DB_PATHS[0])
keys_of_interest = [
    'jwt', 'token', 'apiKey', 'api_key', 'session', 'auth',
    'codeium', 'windsurf', 'userId', 'user_id', 'user_jwt',
    'installationId', 'sessionId', 'deviceFingerprint'
]
for key, value in rows:
    for k in keys_of_interest:
        if k.lower() in key.lower():
            v_str = str(value)[:200]
            print(f"  {key}: {v_str}")
            break

print()

# 2. Look for JWT tokens in the state
print("=== JWT tokens in state ===")
for key, value in rows:
    v_str = str(value)
    # JWT pattern: three base64 segments separated by dots
    jwtm = re.findall(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', v_str)
    if jwtm:
        print(f"  {key}: JWT found: {jwtm[0][:100]}...")
        print()

# 3. Look in codeium.windsurf specific keys
print("=== codeium.windsurf keys ===")
for key, value in rows:
    if 'windsurf' in key.lower() or 'codeium' in key.lower():
        try:
            parsed = json.loads(value)
            print(f"  {key}: {json.dumps(parsed)[:300]}")
        except:
            print(f"  {key}: {str(value)[:200]}")
        print()

# 4. Find the live LS port from process
print("=== Live LS port from process ===")
import subprocess
try:
    result = subprocess.run(
        ['powershell', '-Command',
         'Get-Process -Name windsurf* | Where-Object {$_.CommandLine -match "port"} | Select-Object -First 5 -ExpandProperty CommandLine'],
        capture_output=True, text=True, timeout=10
    )
    print(result.stdout[:500])
except: pass

# 5. Read environment variables for session tokens
print("=== Environment variables (WINDSURF/CODEIUM) ===")
for k, v in os.environ.items():
    if any(x in k.upper() for x in ['WINDSURF', 'CODEIUM', 'JWT', 'TOKEN', 'SESSION', 'API_KEY']):
        print(f"  {k}={v[:100]}")

# 6. Look for session files
print()
print("=== Session files ===")
session_paths = [
    r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage',
    r'C:\Users\Administrator\AppData\Roaming\Windsurf',
]
for sp in session_paths:
    if os.path.exists(sp):
        for fn in os.listdir(sp):
            fp = os.path.join(sp, fn)
            if os.path.isfile(fp) and any(x in fn.lower() for x in ['auth', 'token', 'session', 'jwt', 'cred']):
                print(f"  {fp}: size={os.path.getsize(fp)}")
                try:
                    with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                        print(f"  Content: {f.read(300)}")
                except: pass
