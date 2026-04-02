#!/usr/bin/env python3
"""找 Config.IMPERSONATE_TIER 完整 key + 注入 TEAMS_TIER_PRO"""
import sys, io, re, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
txt = open(EXT, 'r', encoding='utf-8', errors='replace').read()

# 1. Find Config object with IMPERSONATE_TIER key
print('=== Config object definition ===')
for m in re.finditer(r'Config(?:uration)?\s*=\s*\{[^}]{0,3000}IMPERSONATE[^}]{0,2000}\}', txt):
    seg = m.group()
    print(seg[:3000])
    print('---')

# If not found, find IMPERSONATE_TIER as a string literal in config registration
print('\n=== IMPERSONATE_TIER config registration ===')
for m in re.finditer(r'.{0,300}IMPERSONATE_TIER["\']?\s*[:=]\s*["\'][^"\']+["\'].{0,200}', txt):
    print(m.group()[:500])
    print('---')

# Also search for how Config.XXX maps to setting keys
for m in re.finditer(r'IMPERSONATE_TIER[:\s]*["\']([^"\']+)["\']', txt):
    print(f'Config key string: {m.group(1)}')

# 2. Find the getConfig function
print('\n=== getConfig function ===')
for m in re.finditer(r'function getConfig\(.{0,500}', txt):
    print(m.group()[:500])
    print('---')
# Also try arrow function
for m in re.finditer(r'getConfig\s*=\s*(?:function|\(|A\s*=>).{0,500}', txt):
    print(m.group()[:500])
    print('---')

# 3. Find where settings are registered for IMPERSONATE_TIER
print('\n=== settings contribution for impersonate ===')
for m in re.finditer(r'.{0,100}impersonate.{0,400}', txt, re.I):
    ctx = m.group()
    if any(x in ctx for x in ['configuration', 'settings', 'contribute', 'register', 'schema']):
        print(ctx[:500])
        print('---')

# 4. Find actual settings JSON path
SETTINGS_PATHS = [
    r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\settings.json',
    r'C:\Users\Administrator\AppData\Roaming\Code\User\settings.json',
]
print('\n=== Current settings.json ===')
for path in SETTINGS_PATHS:
    if os.path.exists(path):
        print(f'Found: {path}')
        settings = json.load(open(path, encoding='utf-8'))
        # Show relevant settings
        for k, v in settings.items():
            if any(x in k.lower() for x in ['impersonate', 'tier', 'claude', 'opus', 'model', 'windsurf']):
                print(f'  {k}: {v}')
        print('(snippet done)')
        break

# 5. Find Config enum-like object
print('\n=== Config.IMPERSONATE_TIER = ? ===')
# Look for object patterns like {IMPERSONATE_TIER: "..."} or Config={..., IMPERSONATE_TIER: "..."}
for m in re.finditer(r'IMPERSONATE_TIER\s*[=:]\s*["\']([^"\']+)["\']', txt):
    print(f'  IMPERSONATE_TIER value: {repr(m.group(1))}')
