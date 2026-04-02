import json, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

for fp in [
    r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\windsurf-assistant-accounts.json',
    r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\windsurf-login-accounts.json',
]:
    try:
        data = json.load(open(fp))
        print(f"=== {fp.split(chr(92))[-1]} ({len(data)} accounts) ===")
        for acc in (data if isinstance(data, list) else [data]):
            ak = acc.get('apiKey', acc.get('api_key', acc.get('authToken', 'NONE')))
            print(f"  email={acc.get('email','?')} credits={acc.get('credits','?')} "
                  f"loginCount={acc.get('loginCount','?')} apiKey={str(ak)[:35]}")
    except Exception as e:
        print(f"{fp}: {e}")
