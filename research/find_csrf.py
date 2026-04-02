"""find_csrf.py — 找 LSP CSRF token"""
import re, os, json, sqlite3, glob

EXT_JS  = r"D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
DB_PATH = r"C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb"
DB_DIR  = r"C:\WINDOWS\system32\config\systemprofile\.codeium\windsurf\database"

def search_ext_js():
    print("[ext.js] 搜索 CSRF token 相关代码...")
    with open(EXT_JS, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()

    # 找 csrf 相关
    for kw in ['csrf', 'CSRF', 'x-csrf', 'initial_metadata', 'stdin_initial', 'csrfToken']:
        for m in re.finditer(re.escape(kw), content, re.IGNORECASE):
            ctx = content[max(0, m.start()-100):m.start()+200]
            print(f"  [{kw}] @{m.start()}: {repr(ctx)}")
            print()

def search_vscdb():
    print("[vscdb] 搜索 CSRF token...")
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("SELECT key, length(value) FROM ItemTable")
    rows = cur.fetchall()
    for k, l in rows:
        if any(x in k.lower() for x in ['csrf', 'token', 'lsp', 'language', 'server_port']):
            cur.execute("SELECT value FROM ItemTable WHERE key=?", (k,))
            val = cur.fetchone()[0]
            print(f"  key={k} len={l}: {str(val)[:200]}")
    conn.close()

def search_db_dir():
    print(f"\n[db_dir] 搜索 {DB_DIR}...")
    if not os.path.exists(DB_DIR):
        print("  目录不存在")
        return
    for root, dirs, files in os.walk(DB_DIR):
        for fn in files:
            fp = os.path.join(root, fn)
            size = os.path.getsize(fp)
            rel = fp.replace(DB_DIR, '')
            print(f"  {rel} ({size}B)")
            if size < 5000 and fn.endswith(('.json','.txt','.db','')):
                try:
                    txt = open(fp, 'rb').read(500)
                    if b'csrf' in txt.lower() or b'token' in txt.lower():
                        print(f"    → contains token: {txt[:200]}")
                except: pass

def search_codeium_dir():
    base = r"C:\WINDOWS\system32\config\systemprofile\.codeium\windsurf"
    print(f"\n[codeium_dir] 搜索 {base}...")
    if not os.path.exists(base):
        print("  不存在")
        return
    for root, dirs, files in os.walk(base):
        depth = root.replace(base,'').count(os.sep)
        if depth > 3: continue
        for fn in files[:5]:
            fp = os.path.join(root, fn)
            size = os.path.getsize(fp)
            print(f"  {fp.replace(base,'')} ({size}B)")

def find_token_in_named_pipe():
    """检查 named pipe 是否可读"""
    import subprocess
    print("\n[pipe] 检查 named pipe...")
    pipe_path = r'\\.\pipe\server_1c5411630a30f596'
    try:
        # 尝试列出所有 pipes
        r = subprocess.run(['pipelist'], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if 'server' in line.lower() or 'windsurf' in line.lower() or 'codeium' in line.lower():
                    print(f"  pipe: {line}")
    except:
        pass
    # 列出通过 PowerShell 的 pipes
    try:
        r2 = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             '[System.IO.Directory]::GetFiles(\'\\\\\\\\.\\\pipe\') | Where-Object { $_ -match \'server|codeium|windsurf\' }'],
            capture_output=True, text=True, timeout=5
        )
        if r2.stdout:
            print(f"  PowerShell pipes:\n{r2.stdout[:500]}")
    except Exception as e:
        print(f"  pipe list error: {e}")

if __name__ == '__main__':
    search_ext_js()
    print()
    search_vscdb()
    search_db_dir()
    search_codeium_dir()
    find_token_in_named_pipe()
