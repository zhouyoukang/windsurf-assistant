import json, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
accounts = json.load(open(
    r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\windsurf-assistant-accounts.json',
    encoding='utf-8', errors='replace'))
print(f'Total accounts: {len(accounts)}')
for i, a in enumerate(accounts):
    cr = a.get('credits', 0) or 0
    pw = 'Y' if a.get('password') else 'N'
    usage = a.get('usage') or {}
    wk = usage.get('weekly') or {}
    rem = wk.get('remaining', '?')
    plan = usage.get('plan', '?')
    lc = a.get('loginCount', 0)
    print(f'[{i:3d}] {a.get("email","?")[:38]:38s} cr={cr:3d} plan={plan:8s} pw={pw} lc={lc:3d} wkrem={rem}')
