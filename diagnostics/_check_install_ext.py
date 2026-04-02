#!/usr/bin/env python3
"""检查D:/Windsurf内置extension.js的hot-load补丁状态，以及各用户的VSIX安装状态"""
import os, json, subprocess
from pathlib import Path

# 1. Check D:/Windsurf built-in windsurf extension
print('=== D:/Windsurf 内置windsurf extension ===')
ext_candidates = [
    Path('D:/Windsurf/resources/app/extensions/windsurf/dist/extension.js'),
    Path('D:/Windsurf/resources/app/extensions/codeium/dist/extension.js'),
]
for ext in ext_candidates:
    if ext.exists():
        data = ext.read_bytes()
        size = len(data)
        print(f'  {ext.name} ({size:,}b):')
        checks = [
            ('POOL_HOT_PATCH', b'POOL_HOT_PATCH'),
            ('wam-hot load', b'.wam-hot'),
            ('wam_hot', b'wam_hot'),
            ('.wam_switching', b'.wam_switching'),
            ('9870', b'9870'),
            ('9876', b'9876'),
        ]
        for name, marker in checks:
            print(f'    {name}: {"YES" if marker in data else "NO"}')
        # Print last few lines to understand what was appended
        try:
            text = data.decode('utf-8', errors='replace')
            lines = text.split('\n')
            if len(lines) > 5:
                print(f'  Last 3 lines:')
                for l in lines[-4:]:
                    if l.strip():
                        print(f'    {l.strip()[:120]}')
        except:
            pass

# 2. Check installed VSIX extensions per user
print('\n=== VSIX扩展安装状态 ===')
for user in ['ai', 'Administrator']:
    ext_dir = Path(f'C:/Users/{user}/.vscode/extensions')
    ws_ext_dir = Path(f'C:/Users/{user}/AppData/Roaming/Windsurf/User')
    # Also check Windsurf extensions
    ws_ext2 = Path(f'C:/Users/{user}/.windsurf/extensions')
    
    print(f'  --- {user} ---')
    for d in [ext_dir, ws_ext_dir, ws_ext2]:
        if d.exists():
            items = [x.name for x in d.iterdir() if 'windsurf' in x.name.lower() or 'wam' in x.name.lower()]
            if items:
                print(f'    {d}: {items[:5]}')
    
    # Check Windsurf extensions specifically
    ws_ext3 = Path(f'C:/Users/{user}/AppData/Local/Programs/Windsurf/resources/app/extensions')
    if ws_ext3.exists():
        items = list(ws_ext3.iterdir())
        print(f'    WS extensions dir: {[x.name for x in items[:10]]}')

# 3. Check if the hot-dir extension.js is newer than the installed one
print('\n=== 时间戳对比 ===')
for user in ['ai', 'Administrator']:
    hot_ext = Path(f'C:/Users/{user}/.wam-hot/extension.js')
    if hot_ext.exists():
        import time
        mtime = hot_ext.stat().st_mtime
        age_hours = (time.time() - mtime) / 3600
        print(f'  {user}/.wam-hot/extension.js: modified {age_hours:.1f}h ago')

# 4. Check patch_info.json in Administrator's hot-dir
patch_info = Path('C:/Users/Administrator/.wam-hot/patch_info.json')
if patch_info.exists():
    try:
        print(f'\n=== Administrator patch_info.json ===')
        pj = json.loads(patch_info.read_text('utf-8'))
        print(json.dumps(pj, indent=2)[:500])
    except Exception as e:
        print(f'  parse err: {e}')

# 5. Check what ports are in use
print('\n=== 端口占用 ===')
r = subprocess.run(
    ['powershell', '-NoProfile', '-Command',
     'netstat -ano | Select-String "9870|9876|9875|19443|19877" | Select-Object -First 20'],
    capture_output=True, text=True, timeout=10, encoding='utf-8', errors='replace'
)
print(r.stdout.strip() or 'none matching')
