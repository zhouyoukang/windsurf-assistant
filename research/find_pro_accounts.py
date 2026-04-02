"""
Find Pro/Enterprise plan accounts that can use claude-opus-4-6
Check all account sources
"""
import json, io, sys, glob, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sources = [
    r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\windsurf-login-accounts.json',
    r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\windsurf-assistant-accounts.json',
    r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\zhouyoukang.windsurf-assistant\windsurf-assistant-accounts.json',
    r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\zhouyoukang.pool-admin\windsurf-assistant-accounts.json',
]

# Also check pool-admin extension
pool_admin_dir = r'C:\Users\Administrator\.windsurf\extensions\zhouyoukang.pool-admin-2.2.0'
if os.path.exists(pool_admin_dir):
    for f in glob.glob(os.path.join(pool_admin_dir, '**', '*.json'), recursive=True):
        if 'account' in f.lower() or 'pool' in f.lower():
            sources.append(f)

print("=== Searching all account sources for Pro/Enterprise accounts ===\n")

all_accounts = {}
for path in sources:
    if not os.path.exists(path):
        continue
    try:
        data = json.load(open(path, encoding='utf-8', errors='replace'))
        if isinstance(data, list):
            accounts = data
        elif isinstance(data, dict):
            accounts = list(data.values()) if all(isinstance(v, dict) for v in data.values()) else [data]
        else:
            continue
        
        print(f"[{os.path.basename(path)}] {len(accounts)} accounts")
        for a in accounts:
            if not isinstance(a, dict): continue
            email = a.get('email', '')
            usage = a.get('usage') or {}
            plan = usage.get('plan', a.get('plan', '?'))
            cr = a.get('credits', 0) or 0
            pw = bool(a.get('password'))
            lc = a.get('loginCount', 0)
            
            # Show plan info
            plan_str = str(plan).lower()
            is_special = any(x in plan_str for x in ['pro', 'enterprise', 'teams', 'paid', 'premium', 'devin'])
            
            if is_special or cr >= 50:
                marker = "*** PRO ***" if is_special else f"(cr={cr})"
                print(f"  {marker} {email} plan={plan} pw={pw} lc={lc}")
                if email not in all_accounts:
                    all_accounts[email] = a
        print()
    except Exception as e:
        print(f"  ERROR: {e}\n")

# Check pool-admin extension JS/config
print("=== Pool-Admin Extension ===")
if os.path.exists(pool_admin_dir):
    for fname in os.listdir(pool_admin_dir):
        fpath = os.path.join(pool_admin_dir, fname)
        print(f"  {fname} ({os.path.getsize(fpath)} bytes)")
    # Check globalStorage for pool-admin
    pa_storage = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\zhouyoukang.pool-admin'
    if os.path.exists(pa_storage):
        print(f"\nPool-admin storage files:")
        for f in os.listdir(pa_storage):
            fp = os.path.join(pa_storage, f)
            print(f"  {f} ({os.path.getsize(fp)} bytes)")
else:
    print("  Not found")

# Also check the relay server for any account hints
print("\n=== Relay info from authService.js ===")
print("Relay: https://aiotvr.xyz/wam")
print("This might proxy to Pro accounts server-side")

print(f"\nTotal unique special accounts found: {len(all_accounts)}")
