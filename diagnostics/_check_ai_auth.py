#!/usr/bin/env python3
"""Quick check of ai user's Windsurf auth state"""
import sqlite3, json, os

db = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')
conn = sqlite3.connect(db, timeout=5)

# 1. windsurfAuthStatus
row = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
if row:
    d = json.loads(row[0])
    ak = d.get('apiKey', '')
    print(f'apiKey: {ak[:30]}...')
    print(f'apiKey length: {len(ak)}')
    print(f'proto size: {len(d.get("userStatusProtoBinaryBase64", ""))}')
    print(f'command models: {len(d.get("allowedCommandModelConfigsProtoBinaryBase64", []))}')
    # Extract email from proto
    import base64, re
    pb = d.get('userStatusProtoBinaryBase64', '')
    if pb:
        raw = base64.b64decode(pb)
        emails = re.findall(rb'[\w.-]+@[\w.-]+\.\w+', raw[:500])
        print(f'proto email: {emails[0].decode() if emails else "NONE"}')
else:
    print('NO windsurfAuthStatus')

# 2. cachedPlanInfo
row2 = conn.execute("SELECT value FROM ItemTable WHERE key='windsurf.settings.cachedPlanInfo'").fetchone()
if row2:
    p = json.loads(row2[0])
    print(f'\nplan: {p.get("planName")} billing: {p.get("billingStrategy")}')
    qu = p.get('quotaUsage', {})
    print(f'daily: {qu.get("dailyRemainingPercent")}% weekly: {qu.get("weeklyRemainingPercent")}%')
else:
    print('\nNO cachedPlanInfo')

# 3. windsurfConfigurations
row3 = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfConfigurations'").fetchone()
print(f'\nwindsurfConfigurations: {"EXISTS" if row3 else "MISSING"} ({len(row3[0]) if row3 else 0} bytes)')

# 4. All windsurf keys
rows = conn.execute("SELECT key FROM ItemTable WHERE key LIKE '%windsurf%'").fetchall()
print(f'\nTotal windsurf keys: {len(rows)}')
for r in sorted(rows, key=lambda x: x[0])[:20]:
    print(f'  {r[0]}')

# 5. storage.json telemetry
print('\n--- storage.json ---')
sj_path = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\storage.json')
if os.path.exists(sj_path):
    sj = json.loads(open(sj_path, encoding='utf-8').read())
    for k in ['telemetry.machineId', 'telemetry.devDeviceId', 'telemetry.macMachineId', 
              'telemetry.sqmId', 'storage.serviceMachineId']:
        v = sj.get(k, 'NONE')
        print(f'  {k}: {v}')

# 6. Administrator's storage.json for comparison
print('\n--- Administrator storage.json ---')
admin_sj = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\storage.json'
if os.path.exists(admin_sj):
    asj = json.loads(open(admin_sj, encoding='utf-8').read())
    for k in ['telemetry.machineId', 'telemetry.devDeviceId', 'telemetry.macMachineId',
              'telemetry.sqmId', 'storage.serviceMachineId']:
        v = asj.get(k, 'NONE')
        print(f'  {k}: {v}')

# 7. Check Administrator's windsurfAuthStatus
print('\n--- Administrator state.vscdb ---')
admin_db = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
if os.path.exists(admin_db):
    aconn = sqlite3.connect(admin_db, timeout=5)
    arow = aconn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
    if arow:
        ad = json.loads(arow[0])
        aak = ad.get('apiKey', '')
        print(f'  apiKey: {aak[:30]}...' if aak else '  apiKey: EMPTY')
    else:
        print('  windsurfAuthStatus: MISSING')
    
    # Check all keys count
    all_keys = aconn.execute("SELECT COUNT(*) FROM ItemTable").fetchone()
    print(f'  Total keys in DB: {all_keys[0]}')
    
    # Check windsurf-specific
    ws_keys = aconn.execute("SELECT key FROM ItemTable WHERE key LIKE '%windsurf%' OR key LIKE '%cascade%'").fetchall()
    print(f'  Windsurf/Cascade keys: {len(ws_keys)}')
    for r in ws_keys[:15]:
        print(f'    {r[0]}')
    aconn.close()

# 8. Check Electron credential store
print('\n--- Credential Storage Analysis ---')
# Check for Cookies DB (Electron stores OAuth tokens here sometimes)
cookies_ai = os.path.expandvars(r'%APPDATA%\Windsurf\Cookies')
cookies_admin = r'C:\Users\Administrator\AppData\Roaming\Windsurf\Cookies'
print(f'  ai Cookies: {"EXISTS" if os.path.exists(cookies_ai) else "MISSING"}')
print(f'  Admin Cookies: {"EXISTS" if os.path.exists(cookies_admin) else "MISSING"}')

# Check Local State (contains encrypted_key for safeStorage)
ls_ai = os.path.expandvars(r'%APPDATA%\Windsurf\Local State')
ls_admin = r'C:\Users\Administrator\AppData\Roaming\Windsurf\Local State'
for label, path in [('ai', ls_ai), ('Admin', ls_admin)]:
    if os.path.exists(path):
        ls = json.loads(open(path, encoding='utf-8').read())
        os_crypt = ls.get('os_crypt', {})
        ek = os_crypt.get('encrypted_key', '')
        print(f'  {label} Local State: encrypted_key={ek[:40]}... ({len(ek)} chars)')
    else:
        print(f'  {label} Local State: MISSING')

conn.close()
