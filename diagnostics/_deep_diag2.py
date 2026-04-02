#!/usr/bin/env python3
"""深度诊断 v2: 端口/进程/bridge状态"""
import os, json, subprocess, time
from pathlib import Path
import urllib.request, urllib.error

# 1. 测试端口
print('=== HTTP端口扫描 ===')
ports = [9870, 9876, 9875, 19443, 19877, 19876, 19875, 3000, 8080]
for p in ports:
    try:
        r = urllib.request.urlopen(f'http://127.0.0.1:{p}/', timeout=2)
        print(f'  :{p} OK {r.getcode()}')
    except urllib.error.HTTPError as e:
        print(f'  :{p} HTTP {e.code}')
    except Exception as e:
        print(f'  :{p} {type(e).__name__[:20]}')

# 2. cross_user_bridge日志
print('\n=== cross_user_bridge最新日志 ===')
bridge_log = Path(r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\_cross_user_bridge.log')
try:
    with open(str(bridge_log), 'rb') as f:
        # Read last 4KB
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 4000))
        raw = f.read()
    text = raw.decode('utf-8', errors='replace')
    lines = text.split('\n')
    for l in lines[-20:]:
        print(f'  {l.rstrip()}')
except Exception as e:
    print(f'  err: {e}')

# 3. WAM snapshots count
print('\n=== Snapshot池 ===')
snap_file = Path(r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\_wam_snapshots.json')
try:
    data = json.loads(snap_file.read_text('utf-8'))
    snaps = data.get('snapshots', {})
    print(f'  Total snapshots: {len(snaps)}')
    emails = list(snaps.keys())[:5]
    print(f'  Sample emails: {emails}')
except Exception as e:
    print(f'  err: {e}')

# 4. Python/Node进程 (encoded properly)
print('\n=== 进程命令行 ===')
try:
    r = subprocess.run(
        ['wmic', 'process', 'where', 'name="python.exe" or name="pythonw.exe" or name="node.exe"',
         'get', 'ProcessId,Name,CommandLine'],
        capture_output=True, timeout=15, encoding='utf-8', errors='replace'
    )
    lines = r.stdout.strip().split('\n')
    for l in lines[:30]:
        l = l.strip()
        if l and l != 'CommandLine  Name  ProcessId':
            print(f'  {l[:150]}')
except Exception as e:
    print(f'  err: {e}')

# 5. Check cross_user_bridge scheduled task
print('\n=== 计划任务 ===')
try:
    r = subprocess.run(
        ['schtasks', '/Query', '/TN', 'WindsurfCrossUserBridge', '/FO', 'LIST'],
        capture_output=True, timeout=10, encoding='utf-8', errors='replace'
    )
    print(r.stdout.strip() or r.stderr.strip() or 'not found')
except Exception as e:
    print(f'  schtasks err: {e}')

try:
    r = subprocess.run(
        ['schtasks', '/Query', '/TN', 'WindsurfWuWeiGuard', '/FO', 'LIST'],
        capture_output=True, timeout=10, encoding='utf-8', errors='replace'
    )
    print(r.stdout.strip() or r.stderr.strip() or 'not found')
except Exception as e:
    print(f'  schtasks err: {e}')

# 6. Pool engine log
print('\n=== pool_engine最新日志 ===')
pool_log = Path(r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\_pool_engine.stdout.log')
try:
    with open(str(pool_log), 'rb') as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 3000))
        raw = f.read()
    text = raw.decode('utf-8', errors='replace')
    lines = text.split('\n')
    for l in lines[-15:]:
        print(f'  {l.rstrip()}')
except Exception as e:
    print(f'  err: {e}')

# 7. Check Administrator's active_account marker and snapshots
print('\n=== Administrator WAM状态 ===')
active_marker = Path(r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\_active_account.txt')
if active_marker.exists():
    print(f'  Active account: {active_marker.read_text("utf-8").strip()}')

# Check Administrator state.vscdb auth
db = Path('C:/Users/Administrator/AppData/Roaming/Windsurf/User/globalStorage/state.vscdb')
if db.exists():
    import sqlite3
    try:
        c = sqlite3.connect(str(db), timeout=3)
        r = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        if r:
            a = json.loads(r[0])
            k = a.get('apiKey', '') if a else ''
            print(f'  Admin auth: email={a.get("email","?") if a else "?"} key_len={len(k)}')
            # Check if key matches ai's key
            ai_db = Path('C:/Users/ai/AppData/Roaming/Windsurf/User/globalStorage/state.vscdb')
            if ai_db.exists():
                c2 = sqlite3.connect(str(ai_db), timeout=3)
                r2 = c2.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
                if r2:
                    a2 = json.loads(r2[0])
                    k2 = a2.get('apiKey', '') if a2 else ''
                    print(f'  ai auth:    email={a2.get("email","?") if a2 else "?"} key_len={len(k2)}')
                    print(f'  Same apiKey: {k == k2}')
                    if k == k2:
                        print('  !! WARNING: Both users have SAME apiKey - cross_user_bridge overwriting?')
                c2.close()
        c.close()
    except Exception as e:
        print(f'  db err: {e}')

print('\n=== Done ===')
