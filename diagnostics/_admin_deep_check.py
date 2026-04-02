#!/usr/bin/env python3
"""Deep check of Administrator's state.vscdb - what's actually in windsurfAuthStatus"""
import sqlite3, json, os

admin_db = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
conn = sqlite3.connect(admin_db, timeout=5)

# 1. Raw value of windsurfAuthStatus
print("=== windsurfAuthStatus RAW ===")
row = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
if row:
    raw = row[0]
    print(f"  Type: {type(raw).__name__}")
    print(f"  Length: {len(str(raw))}")
    print(f"  First 200 chars: {str(raw)[:200]}")
    
    # Try JSON parse
    try:
        d = json.loads(raw)
        if d is None:
            print("  JSON parsed to: None (null)")
        elif isinstance(d, dict):
            print(f"  JSON keys: {list(d.keys())}")
            print(f"  apiKey: {d.get('apiKey', 'MISSING')[:40]}")
        else:
            print(f"  JSON type: {type(d).__name__}")
    except Exception as e:
        print(f"  JSON parse error: {e}")
else:
    print("  KEY NOT FOUND")

# 2. Check windsurfConfigurations
print("\n=== windsurfConfigurations ===")
row2 = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfConfigurations'").fetchone()
if row2:
    print(f"  Type: {type(row2[0]).__name__}, Length: {len(str(row2[0]))}")
else:
    print("  MISSING")

# 3. Check cachedPlanInfo
print("\n=== cachedPlanInfo ===")
row3 = conn.execute("SELECT value FROM ItemTable WHERE key='windsurf.settings.cachedPlanInfo'").fetchone()
if row3:
    print(f"  Value: {str(row3[0])[:300]}")
else:
    print("  MISSING")

# 4. Check secret keys (Electron safeStorage)
print("\n=== Secret/Auth keys ===")
secrets = conn.execute(
    "SELECT key, length(value) FROM ItemTable WHERE key LIKE '%secret%' OR key LIKE '%auth%session%' OR key LIKE '%token%'"
).fetchall()
for k, vlen in secrets:
    print(f"  {k}: {vlen} bytes")

# 5. Check ALL keys in Administrator's DB
print("\n=== ALL keys in Administrator state.vscdb ===")
all_rows = conn.execute("SELECT key, length(value) FROM ItemTable ORDER BY key").fetchall()
print(f"  Total: {len(all_rows)} keys")
for k, vlen in all_rows:
    print(f"  [{vlen:>8}] {k}")

# 6. Check cascade-auth.json content
print("\n=== cascade-auth.json ===")
ca_path = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\cascade-auth.json'
if os.path.exists(ca_path):
    ca = json.loads(open(ca_path, encoding='utf-8').read())
    print(f"  Keys: {list(ca.keys())}")
    for k, v in ca.items():
        print(f"  {k}: {str(v)[:80]}")
else:
    print("  NOT FOUND")

# 7. Check wam-window-state.json
print("\n=== wam-window-state.json ===")
wam_path = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\wam-window-state.json'
if os.path.exists(wam_path):
    print(f"  {open(wam_path, encoding='utf-8').read()[:500]}")

# 8. Check Local State encrypted_key
print("\n=== Local State (DPAPI/safeStorage) ===")
for label, path in [
    ('ai', os.path.expandvars(r'%APPDATA%\Windsurf\Local State')),
    ('Admin', r'C:\Users\Administrator\AppData\Roaming\Windsurf\Local State')
]:
    if os.path.exists(path):
        ls = json.loads(open(path, encoding='utf-8').read())
        ek = ls.get('os_crypt', {}).get('encrypted_key', '')
        print(f"  {label}: encrypted_key present={bool(ek)}, len={len(ek)}")
        # Also check profile info
        pi = ls.get('profile', {})
        print(f"  {label}: profile={pi}")
    else:
        print(f"  {label}: MISSING")

conn.close()
