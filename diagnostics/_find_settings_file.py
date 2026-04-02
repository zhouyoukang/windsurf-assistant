#!/usr/bin/env python3
"""找到 resolveUnspecifiedSettings + SettingsWatcher 文件路径"""
import re

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
ext = open(EXT, 'r', encoding='utf-8', errors='replace').read()

# 1. resolveUnspecifiedSettings
print("=== resolveUnspecifiedSettings ===")
idx = ext.find('resolveUnspecifiedSettings')
print(f'First occurrence @{idx}')
print(repr(ext[max(0,idx-50):idx+800]))
print()

# Find ALL occurrences
for m in re.finditer('resolveUnspecifiedSettings', ext):
    i = m.start()
    print(f'@{i}: {repr(ext[max(0,i-30):i+200][:200])}')

print()

# 2. SettingsWatcher
print("=== SettingsWatcher ===")
idx2 = ext.find('class SettingsWatcher')
if idx2 < 0:
    idx2 = ext.find('SettingsWatcher')
print(f'@{idx2}: {repr(ext[max(0,idx2-30):idx2+600])}')
print()

# 3. readSettingsFile path
print("=== readSettingsFile / settings file path ===")
for pat in ['readSettingsFile', 'settingsFile', 'settings.bin', 'user_settings',
            'userSettings.bin', '.proto', 'settings_file']:
    idx3 = ext.find(pat)
    if idx3 >= 0:
        print(f'{pat!r} @{idx3}: {repr(ext[max(0,idx3-100):idx3+300][:350])}')
        print()

# 4. Language server data directory
print("=== Language server data dir ===")
for pat in ['.codeium', 'language_server_v', 'manager_pb', 'settings_path',
            'userDataPath', r'\.codeium', 'codeium/']:
    idx4 = ext.find(pat)
    if idx4 >= 0:
        print(f'{pat!r} @{idx4}: {repr(ext[max(0,idx4-80):idx4+200][:250])}')
        print()
