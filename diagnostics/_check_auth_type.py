#!/usr/bin/env python3
import sqlite3, json, os, base64, struct

STATE_DB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')
conn = sqlite3.connect('file:' + STATE_DB + '?mode=ro', uri=True)
auth_raw = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()[0]
auth = json.loads(auth_raw)
conn.close()

field = auth.get('allowedCommandModelConfigsProtoBinaryBase64')
print(f'Type: {type(field).__name__}')
print(f'IsArray: {isinstance(field, list)}')

if isinstance(field, list):
    print(f'Length: {len(field)}')
    for i, item in enumerate(field[:3]):
        print(f'  [{i}] type={type(item).__name__} len={len(item)}: {str(item)[:80]}')
elif isinstance(field, str):
    print(f'String len: {len(field)}')
    print(f'First 80 chars: {field[:80]}')
elif field is None:
    print('Field is None')

# Also check what the workbench.js THIS.C function does when given an array vs string
# Search for this.C definition in workbench.js context
WB = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
with open(WB, 'r', encoding='utf-8', errors='replace') as f:
    wb = f.read()

# Find method C in the auth/updateWindsurfAuthStatus class
# Look around LOC2 for the C method definition
import re
# Find the class containing updateWindsurfAuthStatus
idx = wb.find('updateWindsurfAuthStatus')
if idx > 0:
    # Look back 5000 chars for method C definition
    chunk = wb[max(0, idx-6000):idx+100]
    # Find 'C(' method definitions  
    c_methods = re.findall(r'\bC\(([^)]{0,60})\)\{([^}]{0,300})\}', chunk)
    print(f'\nC() method candidates near updateWindsurfAuthStatus:')
    for args, body in c_methods[-10:]:
        if any(x in body for x in ['proto', 'binary', 'parse', 'base64', 'decode', 'model', 'config', 'from', 'map']):
            print(f'\n  C({args}):')
            print(f'  {body[:200]}')

# Also search for the specific pattern this.C = function or C(D) in auth class
# Find 2000 chars before updateWindsurfAuthStatus
chunk2 = wb[max(0, idx-2000):idx+50]
print(f'\nContext around updateWindsurfAuthStatus (-2000):')
# Find any C= or C: patterns
for m in re.finditer(r'\bC[=:]\s*(?:function|\()', chunk2):
    print(f'  @{m.start()}: {chunk2[m.start():m.start()+150]}')
