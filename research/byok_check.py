#!/usr/bin/env python3
"""
byok_check.py — 检查 Windsurf BYOK 配置 + 账号池状态
1. 扫描 state.vscdb 中的 byok/anthropic 相关 key
2. 列出 WAM token cache 中所有账号的 key
3. 测试哪个 key 能通 cascade (SendUserCascadeMessage 不 RemoteDisconnect)
"""
import sys, io, json, os, time, sqlite3, struct, requests, subprocess, re, ctypes
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
VAULT = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\claude_key.vault'
WAM_CACHE_GLOB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage'

# ═══ 1. state.vscdb 扫描 ═══
print('=== state.vscdb 扫描 ===')
con = sqlite3.connect(DB)
rows = con.execute("SELECT key, value FROM ItemTable").fetchall()
con.close()

for k, v in rows:
    kl = k.lower()
    if any(x in kl for x in ['byok', 'anthropic', 'apikey', 'token', 'auth', 'claude']):
        try:
            parsed = json.loads(v) if v else {}
            if isinstance(parsed, dict):
                # Extract keys
                api_key = parsed.get('apiKey') or parsed.get('api_key') or parsed.get('anthropicApiKey')
                if api_key:
                    print(f'  [{k}] apiKey: {api_key[:30]}...')
                else:
                    # Show all string values
                    for pk, pv in list(parsed.items())[:5]:
                        if isinstance(pv, str) and 10 < len(pv) < 100:
                            print(f'  [{k}] {pk}: {pv[:40]}...')
            elif isinstance(parsed, str) and 10 < len(parsed) < 200:
                print(f'  [{k}]: {parsed[:60]}...')
        except:
            if v and 10 < len(v) < 200:
                print(f'  [{k}]: {v[:60]}...')

# Check BYOK config
print('\n=== BYOK / Model config ===')
for k, v in rows:
    if any(x in k.lower() for x in ['model', 'byok', 'provider']):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, dict) and any(x in str(parsed) for x in ['anthropic', 'BYOK', 'byok', 'claude-3', 'claude-4']):
                print(f'  [{k[:50]}]: {str(parsed)[:200]}')
        except: pass

# ═══ 2. WAM token cache ═══
print('\n=== WAM Token Cache ===')
for root, dirs, files in os.walk(WAM_CACHE_GLOB):
    for fname in files:
        if 'token' in fname.lower() or 'cache' in fname.lower() or 'wam' in fname.lower():
            path = os.path.join(root, fname)
            try:
                data = json.load(open(path, encoding='utf-8'))
                if isinstance(data, dict) and len(data) > 0:
                    print(f'\n  File: {path}')
                    count = 0
                    for email, v in data.items():
                        if isinstance(v, dict):
                            k = v.get('apiKey', '')
                            ts = v.get('timestamp', 0)
                            age_h = (time.time() - ts) / 3600 if ts else 0
                            if k:
                                print(f'    {email[:35]}: {k[:22]}... ({age_h:.0f}h ago)')
                                count += 1
                                if count >= 10: 
                                    print(f'    ... and {len(data)-count} more')
                                    break
            except: pass

# ═══ 3. Account Pool ═══
print('\n=== Account Pool ===')
for pool_dir in [
    r'e:\道\道生一\一生二\Windsurf无限额度\_archive',
    r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine',
]:
    for fname in ['_account_pool.json', 'account_pool.json', 'accounts.json']:
        path = os.path.join(pool_dir, fname)
        if os.path.exists(path):
            data = json.load(open(path, encoding='utf-8'))
            accs = data.get('accounts', data if isinstance(data, list) else [])
            from collections import Counter
            plans = Counter(a.get('plan', '?') for a in accs if isinstance(a, dict))
            print(f'  {path}: {len(accs)} accounts, plans={dict(plans)}')
            for a in accs[:5]:
                if isinstance(a, dict):
                    e = a.get('email','?')[:35]
                    k = (a.get('apiKey') or a.get('api_key','?'))[:22]
                    plan = a.get('plan','?')
                    ts = a.get('ts', a.get('timestamp', 0))
                    age_h = (time.time() - ts) / 3600 if ts else 0
                    print(f'    {e}: plan={plan} key={k}... ({age_h:.0f}h ago)')

# ═══ 4. Vault status ═══
print('\n=== Vault ===')
if os.path.exists(VAULT):
    v = json.load(open(VAULT))
    age_h = (time.time() - v.get('ts', 0)) / 3600
    print(f'  key: {v.get("key","")[:30]}... age={age_h:.1f}h')
    print(f'  expired: {age_h > 24}')
else:
    print('  vault file not found')
