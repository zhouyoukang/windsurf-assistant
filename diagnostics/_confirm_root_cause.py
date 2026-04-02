#!/usr/bin/env python3
"""确认根因: hot_patch V1 中的硬编码APPDATA路径"""
from pathlib import Path
import re, json

# 1. 检查D:/Windsurf extension.js中POOL_HOT_PATCH_V1的实际内容
print('=== D:/Windsurf extension.js POOL_HOT_PATCH_V1 内容 ===')
ext = Path('D:/Windsurf/resources/app/extensions/windsurf/dist/extension.js')
if ext.exists():
    data = ext.read_bytes()
    marker = b'POOL_HOT_PATCH_V1'
    if marker in data:
        idx = data.index(marker)
        # Look back 500 bytes to find the full patch
        start = max(0, idx - 600)
        snippet = data[start:idx+100].decode('utf-8', errors='replace')
        print(snippet)
        
        # Extract the _pf path specifically
        m = re.search(r'var _pf=([^;]+);', snippet)
        if m:
            pf_val = m.group(1).strip()
            print(f'\n  >> HARDCODED PATH: {pf_val}')
            if 'ai' in pf_val:
                print('  !! ROOT CAUSE CONFIRMED: Path hardcoded to ai user!')
                print('  !! Administrator Windsurf reads from ai\'s _pool_apikey.txt')
                print('  !! Switching Administrator\'s state.vscdb has NO EFFECT on gRPC requests')
            elif 'APPDATA' in pf_val:
                print('  OK: Path uses dynamic process.env.APPDATA')
            else:
                print(f'  Unknown path: {pf_val}')
    else:
        print('  POOL_HOT_PATCH_V1 marker NOT found in extension.js')
        print('  hot_patch may not be applied')

# 2. Cross-check: compare current pool_apikey.txt files
print('\n=== _pool_apikey.txt 比较 ===')
ai_pk = Path('C:/Users/ai/AppData/Roaming/Windsurf/_pool_apikey.txt')
adm_pk = Path('C:/Users/Administrator/AppData/Roaming/Windsurf/_pool_apikey.txt')
ai_key = ai_pk.read_text('utf-8').strip() if ai_pk.exists() else ''
adm_key = adm_pk.read_text('utf-8').strip() if adm_pk.exists() else ''
print(f'  ai   key: {ai_key[:50]}...')
print(f'  admin key: {adm_key[:50]}...')
print(f'  Same key: {ai_key == adm_key}')
if ai_key == adm_key:
    print('  !! Both users have SAME pool key - hot_patch gives same apiKey regardless of state.vscdb')

# 3. Check if Administrator's state.vscdb auth differs from pool_apikey
import sqlite3, json as _json
db = Path('C:/Users/Administrator/AppData/Roaming/Windsurf/User/globalStorage/state.vscdb')
if db.exists():
    c = sqlite3.connect(str(db), timeout=3)
    r = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
    if r:
        a = _json.loads(r[0])
        db_key = a.get('apiKey', '') if a else ''
        print(f'\n  Admin state.vscdb key: {db_key[:50]}...')
        print(f'  Admin pool_apikey.txt key: {adm_key[:50]}...')
        print(f'  Same as DB: {db_key == adm_key}')
        if db_key != adm_key and adm_key == ai_key:
            print('  !! CONFIRMED: Admin DB key differs from pool key (which=ai key)')
            print('  !! Hot_patch overrides Admin DB key with ai pool key for every gRPC call')
    c.close()

# 4. Check what the dynamic fix should look like
print('\n=== 修复方案预览 ===')
print('  问题: hot_patch V1 path hardcoded to ai user APPDATA')
print('  修复: 改为 process.env.APPDATA (动态路径)')
print('  修复后: 每个用户读各自的 _pool_apikey.txt')
print('  额外: 清空/禁用 Administrator 的 _pool_apikey.txt (让其fallback到state.vscdb)')
print('  OR:  各用户_pool_apikey.txt独立由各自WAM管理')
