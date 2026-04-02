"""Find high-credit accounts and their credentials"""
import json, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

for fp in [
    r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\windsurf-assistant-accounts.json',
    r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\windsurf-login-accounts.json',
]:
    try:
        data = json.load(open(fp, encoding='utf-8', errors='replace'))
        accounts = data if isinstance(data, list) else [data]
        high_credit = [a for a in accounts if (a.get('credits', 0) or 0) >= 10]
        if high_credit:
            print(f"=== {fp.split(chr(92))[-1]} — HIGH CREDIT ACCOUNTS ===")
            for a in high_credit:
                print(json.dumps(a, ensure_ascii=False, indent=2)[:500])
                print()
    except Exception as e:
        print(f"{fp}: {e}")
