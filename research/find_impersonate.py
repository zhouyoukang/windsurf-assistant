#!/usr/bin/env python3
"""找 IMPERSONATE_TIER config 的 key + 有效值"""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
txt = open(EXT, 'r', encoding='utf-8', errors='replace').read()

# 1. Find Config.IMPERSONATE_TIER definition
print('=== Config.IMPERSONATE_TIER definition ===')
for m in re.finditer(r'.{0,200}IMPERSONATE_TIER.{0,400}', txt):
    ctx = m.group()
    print(ctx[:600])
    print('---')

# 2. Find getConfig usage pattern  
print('\n=== getConfig(Config.IMPERSONATE_TIER) ===')
for m in re.finditer(r'getConfig\(.*?IMPERSONATE.*?\)', txt):
    ctx_start = max(0, m.start()-200)
    ctx = txt[ctx_start:m.end()+300]
    print(ctx[:600])
    print('---')

# 3. Find Config enum/object
print('\n=== Config enum/object keys ===')
for m in re.finditer(r'Config[=\s]*\{[^}]{0,2000}IMPERSONATE[^}]{0,1000}\}', txt):
    print(m.group()[:2000])
    print('---')

# 4. Find tier enum values
print('\n=== Tier/Plan enum values ===')
for m in re.finditer(r'.{0,100}(PlanTier|TeamTier|TIER_ENTERPRISE|TIER_PRO|TIER_TEAM|impersonateTier).{0,400}', txt):
    ctx = m.group()
    if any(x in ctx for x in ['pro', 'Pro', 'PRO', 'enterprise', 'Enterprise', 'team', 'Team']):
        print(ctx[:500])
        print('---')

# 5. Find where impersonateTier is validated server-side hint
print('\n=== impersonateTier usage in cascade/stream ===')
for m in re.finditer(r'.{0,100}impersonateTier.{0,500}', txt):
    ctx = m.group()
    if any(x in ctx for x in ['plan', 'tier', 'model', 'cascade', 'allowed', 'pro']):
        print(ctx[:600])
        print('---')

# 6. Find Windsurf config key for IMPERSONATE_TIER
print('\n=== windsurf config keys containing impersonate ===')
for m in re.finditer(r'["\']windsurf[^"\']*impersonate[^"\']*["\']', txt, re.I):
    print(m.group()[:200])
    print('---')
for m in re.finditer(r'["\']impersonate[^"\']*["\']', txt, re.I):
    ctx = m.group()
    print(ctx[:200])
    print('---')
