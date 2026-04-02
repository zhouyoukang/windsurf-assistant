#!/usr/bin/env python3
"""修复3: 清空Administrator的_pool_apikey.txt，让hot_patch fallback到state.vscdb真实auth"""
import json, sqlite3
from pathlib import Path

# Clear Administrator's _pool_apikey.txt
adm_pk = Path('C:/Users/Administrator/AppData/Roaming/Windsurf/_pool_apikey.txt')
adm_pk.write_text('', encoding='utf-8')
print(f'Cleared: {adm_pk}')

# Verify Administrator state.vscdb has valid auth
db = Path('C:/Users/Administrator/AppData/Roaming/Windsurf/User/globalStorage/state.vscdb')
if db.exists():
    c = sqlite3.connect(str(db), timeout=3)
    r = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
    if r:
        a = json.loads(r[0]) if r[0] else None
        k = a.get('apiKey', '') if a else ''
        print(f'Admin state.vscdb key valid: {len(k) > 20} ({k[:30]}...)')
    else:
        print('Admin state.vscdb: NO AUTH ROW - need to inject')
    c.close()

print()
print('After fix:')
print('  1. Administrator hot_patch reads empty _pool_apikey.txt')
print('  2. Falls back to this.apiKey (state.vscdb auth)')
print('  3. VSIX switches state.vscdb -> hot_patch uses new key on next gRPC call')
print('  4. hot_guardian no longer overwrites Administrator pool key')
