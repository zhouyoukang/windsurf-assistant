#!/usr/bin/env python3
"""本机全账号Windsurf诊断"""
import os, sqlite3, json, subprocess
from pathlib import Path

users = ['ai', 'Administrator']
ws_d = Path('D:/Windsurf/Windsurf.exe')
print(f'WS D-drive shared: {ws_d.exists()}')
if ws_d.exists():
    wb_d = Path('D:/Windsurf/resources/app/out/vs/workbench/workbench.desktop.main.js')
    print(f'WB D-drive: {wb_d.exists()} sz={wb_d.stat().st_size if wb_d.exists() else 0}')

for u in users:
    print(f'\n--- {u} ---')
    db   = Path(f'C:/Users/{u}/AppData/Roaming/Windsurf/User/globalStorage/state.vscdb')
    hot  = Path(f'C:/Users/{u}/.wam-hot')
    acc  = Path(f'C:/Users/{u}/AppData/Roaming/Windsurf/User/globalStorage/windsurf-login-accounts.json')
    ws1  = Path(f'C:/Users/{u}/AppData/Local/Programs/Windsurf/Windsurf.exe')
    print(f'  state.vscdb:   {db.exists()}')
    print(f'  .wam-hot:      {hot.exists()}')
    if hot.exists():
        files = list(hot.iterdir())
        print(f'  .wam-hot files: {[f.name for f in files]}')
    print(f'  accounts.json: {acc.exists()}')
    if acc.exists():
        try:
            arr = json.loads(acc.read_text('utf-8'))
            print(f'  accounts count: {len(arr)}')
        except Exception as e:
            print(f'  accounts err: {e}')
    print(f'  WS local:      {ws1.exists()}')
    if db.exists():
        try:
            c = sqlite3.connect(str(db), timeout=3)
            r = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
            if r:
                a = json.loads(r[0]) if r[0] else None
                if a and isinstance(a, dict):
                    k = a.get('apiKey','')
                    print(f'  auth email:    {a.get("email","?")}')
                    print(f'  auth apiKey:   {k[:50]}... len={len(k)}')
                    print(f'  auth valid:    {len(k) > 20}')
                else:
                    print(f'  auth:          NULL/empty')
            else:
                print(f'  auth:          NO ROW')
            # Check pool apikey file
            pool_key = Path(f'C:/Users/{u}/AppData/Roaming/Windsurf/_pool_apikey.txt')
            if pool_key.exists():
                pk = pool_key.read_text('utf-8').strip()
                print(f'  _pool_apikey:  {pk[:40]}...')
            # Check for WAM version in hot dir
            ext_js = hot / 'extension.js' if hot.exists() else None
            if ext_js and ext_js.exists():
                data = ext_js.read_bytes()
                ver_marker = b'WAM_VERSION'
                if ver_marker in data:
                    idx = data.index(ver_marker)
                    print(f'  extension.js:  exists, has WAM_VERSION marker')
                else:
                    print(f'  extension.js:  exists, no version marker')
            c.close()
        except Exception as e:
            print(f'  db_err: {e}')

# Check workbench patches for shared D: install
print('\n--- Workbench patches (D:/Windsurf) ---')
wb = Path('D:/Windsurf/resources/app/out/vs/workbench/workbench.desktop.main.js')
if wb.exists():
    data = wb.read_bytes()
    patches = {
        '__wamRateLimit': b'__wamRateLimit',
        'errorCodePrefix=""': b'errorCodePrefix=""',
        'maxGenerationTokens=9999': b'maxGenerationTokens=9999',
        'errorParts:[]': b'errorParts:[]',
        'hasCapacity bypass': b'if(!1&&!',
    }
    for name, marker in patches.items():
        print(f'  {name}: {"YES" if marker in data else "NO"}')

# WAM hub
print('\n--- WAM Hub ---')
try:
    import urllib.request
    r = urllib.request.urlopen('http://127.0.0.1:9870/health', timeout=3)
    d = json.loads(r.read())
    print(f'  Hub: version={d.get("version","?")} accounts={d.get("accounts",0)} active={d.get("activeIndex",-1)}')
except Exception as e:
    print(f'  Hub: offline ({e})')

# Running processes
print('\n--- Running Windsurf processes ---')
try:
    r = subprocess.run(['powershell','-NoProfile','-Command',
        '(Get-Process Windsurf -EA SilentlyContinue) | Select-Object Id,UserName,SessionId | Format-Table'],
        capture_output=True, text=True, timeout=10, encoding='utf-8', errors='replace')
    print(r.stdout.strip() or 'none')
except Exception as e:
    print(f'  err: {e}')

print('\n=== Done ===')
