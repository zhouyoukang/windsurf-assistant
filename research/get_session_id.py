"""get_session_id.py — 找 session_id + 解码 allowedCommandModelConfigs + 找 WAM 可用账号"""
import sqlite3, json, base64, re

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'

con = sqlite3.connect(DB)
cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable")
rows = dict(cur.fetchall())
con.close()

# 1. Session ID
print("=== Session/Installation IDs ===")
for key in rows:
    if any(x in key.lower() for x in ['sessionid', 'session_id', 'installationid', 'installation_id', 'devicefingerprint', 'device_fingerprint']):
        print(f"  {key}: {rows[key][:200]}")

# 2. Decode windsurfAuthStatus
print("\n=== windsurfAuthStatus decoded ===")
auth_status_raw = rows.get('windsurfAuthStatus', '{}')
auth_status = json.loads(auth_status_raw)
print(f"  apiKey: {auth_status.get('apiKey','')[:80]}...")
print(f"  planName: (from cachedPlanInfo)")

# 3. Decode allowedCommandModelConfigs
print("\n=== Allowed Models (decoded) ===")
for i, b64 in enumerate(auth_status.get('allowedCommandModelConfigsProtoBinaryBase64', [])):
    try:
        data = base64.b64decode(b64)
        # Parse simple proto: field 1 (string) = model label
        def decode_field(data, pos):
            if pos >= len(data): return None, pos
            tag = data[pos]; pos += 1
            field_num = tag >> 3; wire_type = tag & 7
            if wire_type == 2:  # length-delimited
                length = data[pos]; pos += 1
                value = data[pos:pos+length]; pos += length
                return (field_num, value), pos
            elif wire_type == 0:  # varint
                v = 0; shift = 0
                while True:
                    b = data[pos]; pos += 1
                    v |= (b & 0x7f) << shift
                    if not (b & 0x80): break
                    shift += 7
                return (field_num, v), pos
            return None, pos + 1
        
        pos = 0; fields = []
        while pos < len(data):
            result, pos = decode_field(data, pos)
            if result: fields.append(result)
        
        label = next((v.decode('utf-8', errors='ignore') for fn, v in fields if fn == 1 and isinstance(v, bytes)), '?')
        print(f"  Model[{i}]: {label} | raw fields: {[(fn, v if isinstance(v, int) else v.hex() if isinstance(v, bytes) else v) for fn, v in fields[:5]]}")
    except Exception as e:
        print(f"  Model[{i}]: decode error: {e}")

# 4. Find WAM pool accounts with api keys
print("\n=== WAM Pool Accounts (windsurf_auth-*) ===")
wam_accounts = {}
for key in rows:
    if key.startswith('windsurf_auth-') and not key.endswith('-usages'):
        try:
            data = json.loads(rows[key])
            if 'apiKey' in data or 'token' in data or 'api_key' in data:
                wam_accounts[key] = data
                name = key.replace('windsurf_auth-', '')
                ak = data.get('apiKey', data.get('token', data.get('api_key', 'N/A')))
                plan = data.get('planName', data.get('plan', 'unknown'))
                print(f"  {name}: apiKey={ak[:50]}..., plan={plan}")
        except: pass

# 5. Find codeium.installationId
print("\n=== Codeium installationId ===")
for key in rows:
    if 'installationId' in key or 'installation_id' in key or 'installationid' in key.lower():
        print(f"  {key}: {rows[key][:200]}")

# 6. Try to find session_id in extension's own storage
print("\n=== WindsurfExtensionMetadata sessionId ===")
for key in rows:
    if 'METADATA_INSTALLATION_ID' in key or key == 'codeium.installationId':
        print(f"  {key}: {rows[key][:200]}")

# Print all relevant windsurf keys
print("\n=== All windsurf. prefixed keys ===")
for key in rows:
    if key.startswith('windsurf.') and 'auth' not in key.lower():
        v = rows[key][:100]
        print(f"  {key}: {v}")
