#!/usr/bin/env python3
"""找到 UserSettings 加载/存储的完整链路"""
import re, os

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
ext = open(EXT, 'r', encoding='utf-8', errors='replace').read()

# 1. Full context of writeUserSettings
print("=== writeUserSettings full context ===")
idx = ext.find('writeUserSettingsToLanguageServer')
print(repr(ext[max(0,idx-600):idx+600]))
print()

# 2. Find the class that has writeUserSettings - look at the class definition
print("=== Settings class definition ===")
# search backward from writeUserSettings for the class start
chunk = ext[max(0,idx-5000):idx]
class_starts = [(m.start()+max(0,idx-5000), m.group()) for m in re.finditer(
    r'class \w+ extends \w+|class \w+\s*\{', chunk)]
if class_starts:
    last = class_starts[-1]
    print(f'Last class before writeUserSettings @{last[0]}: {last[1][:100]}')
    # Get class content
    class_start = last[0]
    print(repr(ext[class_start:class_start+2000]))
print()

# 3. Find UserSettings load from language server
print("=== getUserSettings / loadSettings from LS ===")
for pat in ['getUserSettings', 'getSettings', 'onUserSettingsChanged',
            'userSettingsChanged', 'initializeSettings', 'loadSettings',
            'setUserSettings']:
    for m in re.finditer(pat, ext):
        i = m.start()
        c = ext[max(0,i-80):i+250]
        print(f'EXT {pat!r} @{i}: {repr(c[:300])}')
        print()
        break  # only first occurrence per pattern

# 4. Find sA enum (AutoContinueOnMaxGeneratorInvocations alias in ext)
print("=== sA enum in ext ===")
for m in re.finditer(r'var sA;|sA\[sA\.', ext):
    i = m.start()
    print(f'@{i}: {repr(ext[i:i+200])}')
    break

# 5. Find the language server port / connection
print()
print("=== LanguageServerClient.getInstance ===")
for m in re.finditer(r'LanguageServerClient.getInstance', ext):
    i = m.start()
    print(f'@{i}: {repr(ext[max(0,i-50):i+300][:300])}')
    print()
    if m.start() > 2000000:
        break

# 6. Find Windsurf user data/storage directory
print("=== Windsurf storage paths ===")
for pat in ['globalStorage', 'userDataPath', 'WINDSURF_DATA', 'codeium.windsurf',
            'language_server', 'languageServer']:
    idx2 = ext.find(pat)
    if idx2 >= 0:
        print(f'EXT {pat!r} @{idx2}: {repr(ext[max(0,idx2-30):idx2+150][:150])}')
