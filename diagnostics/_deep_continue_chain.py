#!/usr/bin/env python3
"""深度分析 sendCascadeInput 完整调用链 + 用户设置存储位置"""
import re, os, json

WB  = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'

wb  = open(WB,  'r', encoding='utf-8', errors='replace').read()
ext = open(EXT, 'r', encoding='utf-8', errors='replace').read()

# 1. $mhb callers
print("=== $mhb callers ===")
for m in re.finditer(r'\$mhb\(', wb):
    i = m.start()
    print(f'@{i}: {repr(wb[max(0,i-150):i+250][:350])}')
    print()

# 2. new $4C( - the UserSettings constructor for cascade
print("=== new $4C( ===")
for m in re.finditer(r'new \$4C\(', wb):
    i = m.start()
    print(f'@{i}: {repr(wb[max(0,i-100):i+300][:350])}')
    print()

# 3. Find where sendMessage("Continue") goes - the cascade continue request
print("=== sendCascadeInput in ext ===")
for m in re.finditer(r'sendCascadeInput|SendCascadeInput', ext):
    i = m.start()
    print(f'@{i}: {repr(ext[max(0,i-80):i+250][:300])}')
    print()
    if m.start() > 100000:
        break

# 4. Where user settings are SAVED (persisted)
print("=== userSettings persist ===")
for pat in ['saveUserSettings', 'persistUserSettings', 'storeUserSettings',
            'localStorag', 'indexedDB', 'electron-store', 'userData']:
    idx = wb.find(pat)
    if idx >= 0:
        print(f'WB {pat!r} @{idx}: {repr(wb[max(0,idx-50):idx+200][:220])}')
        print()

for pat in ['saveUserSettings', 'persistUserSettings', 'writeUserSettings',
            'localStorag', 'userData', 'WINDSURF_USER_SETTINGS']:
    idx = ext.find(pat)
    if idx >= 0:
        print(f'EXT {pat!r} @{idx}: {repr(ext[max(0,idx-50):idx+200][:220])}')
        print()

# 5. Find the NON-turbo normalization function (should exist near $mhb)
print("=== Non-turbo settings normalization ===")
# Look for functions near $mhb that also use $4C
idx_mhb = wb.find('function $mhb(')
if idx_mhb < 0:
    idx_mhb = wb.find('$mhb=')
print(f'$mhb at: {idx_mhb}')
# Look for other functions using new $4C in the same area
for m in re.finditer(r'new \$4C\(', wb):
    i = m.start()
    ctx = wb[max(0,i-200):i+100]
    if 'function' in ctx or '=>' in ctx:
        print(f'new $4C @{i}: {repr(ctx[:250])}')
        print()

# 6. Find where autoContinueOnMaxGeneratorInvocations is READ in extension.js  
print("=== autoContinue READ in ext ===")
for m in re.finditer(r'autoContinueOnMaxGeneratorInvocations', ext):
    i = m.start()
    print(f'EXT @{i}: {repr(ext[max(0,i-100):i+250][:300])}')
    print()
