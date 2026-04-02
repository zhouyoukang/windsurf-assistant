#!/usr/bin/env python3
"""直接修改 windsurfAuthStatus.allowedCommandModelConfigsProtoBinaryBase64 注入 claude-opus-4-6"""
import sqlite3, json, os, shutil
from datetime import datetime

STATE_DB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')
OPUS_B64 = 'Cg9DbGF1ZGUgT3B1cyA0LjayAQ9jbGF1ZGUtb3B1cy00LTYdAADAQCAAaASQAcCaDKABAMABAw=='

# Backup
bak = STATE_DB + f'.bak_authstatus_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
shutil.copy2(STATE_DB, bak)
print(f'Backup: {bak}')

conn = sqlite3.connect(STATE_DB)
cur = conn.cursor()

# Read current windsurfAuthStatus
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
auth = json.loads(cur.fetchone()[0])

field = auth.get('allowedCommandModelConfigsProtoBinaryBase64', [])
print(f'Current type: {type(field).__name__}, len: {len(field) if isinstance(field, list) else "N/A"}')

if isinstance(field, list):
    if OPUS_B64 not in field:
        field.append(OPUS_B64)
        auth['allowedCommandModelConfigsProtoBinaryBase64'] = field
        new_val = json.dumps(auth, ensure_ascii=False, separators=(',', ':'))
        cur.execute("UPDATE ItemTable SET value=? WHERE key='windsurfAuthStatus'", (new_val,))
        conn.commit()
        print(f'Injected! New len: {len(field)}')
        # Verify
        cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
        verify = json.loads(cur.fetchone()[0])
        arr = verify.get('allowedCommandModelConfigsProtoBinaryBase64', [])
        print(f'Verify: len={len(arr)}, opus46_present={OPUS_B64 in arr}')
    else:
        print('OPUS_B64 already present in windsurfAuthStatus')
else:
    print(f'Field is not list: {type(field)} — trying string wrap')
    new_list = [field, OPUS_B64] if field else [OPUS_B64]
    auth['allowedCommandModelConfigsProtoBinaryBase64'] = new_list
    cur.execute("UPDATE ItemTable SET value=? WHERE key='windsurfAuthStatus'",
                (json.dumps(auth, ensure_ascii=False, separators=(',', ':')),))
    conn.commit()
    print(f'Injected as list, len={len(new_list)}')

conn.close()
print('Done.')
