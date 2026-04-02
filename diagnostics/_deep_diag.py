#!/usr/bin/env python3
"""深度诊断：端口/进程/bridge/根因"""
import os, json, subprocess, sqlite3, time, socket
from pathlib import Path

# 1. 测试9870端口的实际HTTP响应
print('=== Port 9870 HTTP测试 ===')
import urllib.request, urllib.error
for path in ['/health', '/api/health', '/api/status', '/', '/api/pool/status']:
    try:
        r = urllib.request.urlopen(f'http://127.0.0.1:9870{path}', timeout=3)
        print(f'  {path}: {r.getcode()} -> {r.read()[:150]}')
    except urllib.error.HTTPError as e:
        print(f'  {path}: HTTP {e.code}')
    except Exception as e:
        print(f'  {path}: {type(e).__name__}: {str(e)[:60]}')

# 2. 哪个进程是34076 (9870的监听者)
print('\n=== PID 34076 进程详情 ===')
r = subprocess.run(
    ['powershell', '-NoProfile', '-Command',
     'Get-Process -Id 34076 -EA SilentlyContinue | Select-Object Id,Name,Path | Format-List'],
    capture_output=True, text=True, timeout=10, encoding='utf-8', errors='replace'
)
print(r.stdout.strip() or 'process not found')

# 3. 所有Python/Node进程的命令行
print('\n=== Python/Node进程命令行 ===')
r = subprocess.run(
    ['powershell', '-NoProfile', '-Command',
     'Get-CimInstance Win32_Process | Where-Object {$_.Name -match "python|node"} | Select-Object ProcessId,Name,CommandLine | Format-List'],
    capture_output=True, text=True, timeout=15, encoding='utf-8', errors='replace'
)
print(r.stdout.strip() or 'none')

# 4. cross_user_bridge是否在运行 + 最新日志
print('\n=== cross_user_bridge 状态 ===')
bridge_log = Path(r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\_cross_user_bridge.log')
if bridge_log.exists():
    # Read last 20 lines (can't read .log files due to .codeiumignore, read directly)
    try:
        with open(str(bridge_log), 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        print(f'  Total lines: {len(lines)}')
        print('  Last 15 lines:')
        for l in lines[-15:]:
            print(f'    {l.rstrip()}')
    except Exception as e:
        print(f'  read err: {e}')
else:
    print('  log not found')

# 5. 检查计划任务
print('\n=== WAM计划任务 ===')
r = subprocess.run(
    ['schtasks', '/Query', '/FO', 'LIST', '/V'],
    capture_output=True, text=True, timeout=15, encoding='gbk', errors='replace'
)
output = r.stdout
# Filter relevant tasks
lines = output.split('\n')
in_relevant = False
for line in lines:
    if any(k in line for k in ['Windsurf', 'WAM', 'wuwei', 'Guardian', 'Bridge', 'wam']):
        in_relevant = True
    if in_relevant:
        print(f'  {line.rstrip()}')
        if line.strip() == '':
            in_relevant = False

# 6. 检查D:/Windsurf extension.js的POOL_HOT_PATCH内容
print('\n=== D:/Windsurf extension.js POOL_HOT_PATCH内容 ===')
ext_path = Path('D:/Windsurf/resources/app/extensions/windsurf/dist/extension.js')
if ext_path.exists():
    data = ext_path.read_bytes()
    marker = b'POOL_HOT_PATCH'
    if marker in data:
        idx = data.index(marker)
        # Show 500 bytes around the marker
        start = max(0, idx - 100)
        end = min(len(data), idx + 400)
        context = data[start:end].decode('utf-8', errors='replace')
        print(f'  Context around POOL_HOT_PATCH:')
        for l in context.split('\n')[:20]:
            print(f'    {l[:120]}')

# 7. 检查Administrator的Windsurf是否有独立的globalStorage
print('\n=== Administrator globalStorage检查 ===')
admin_gs = Path('C:/Users/Administrator/AppData/Roaming/Windsurf/User/globalStorage')
if admin_gs.exists():
    items = list(admin_gs.iterdir())
    print(f'  Files: {[x.name for x in items]}')
    # Check windsurf-assistant extension storage
    asst_dir = admin_gs / 'zhouyoukang.windsurf-assistant'
    if asst_dir.exists():
        print(f'  windsurf-assistant files: {[x.name for x in asst_dir.iterdir()]}')
        # Check accounts.json freshness
        acc_file = asst_dir / 'windsurf-login-accounts.json'
        if acc_file.exists():
            mtime = acc_file.stat().st_mtime
            age_min = (time.time() - mtime) / 60
            data = json.loads(acc_file.read_text('utf-8'))
            print(f'  extension accounts.json: {len(data)} accounts, modified {age_min:.1f}m ago')

# 8. 检查ai用户的windsurf-assistant extension storage  
print('\n=== ai globalStorage检查 ===')
ai_gs = Path('C:/Users/ai/AppData/Roaming/Windsurf/User/globalStorage')
if ai_gs.exists():
    asst_dir = ai_gs / 'zhouyoukang.windsurf-assistant'
    if asst_dir.exists():
        acc_file = asst_dir / 'windsurf-login-accounts.json'
        if acc_file.exists():
            mtime = acc_file.stat().st_mtime
            age_min = (time.time() - mtime) / 60
            data = json.loads(acc_file.read_text('utf-8'))
            print(f'  ai extension accounts.json: {len(data)} accounts, modified {age_min:.1f}m ago')

print('\n=== Done ===')
