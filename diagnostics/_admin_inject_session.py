#!/usr/bin/env python3
"""Auto-generated: Run this IN Administrator's terminal to inject safeStorage"""
import sqlite3, json, os, sys, ctypes, ctypes.wintypes, base64, secrets, shutil
from pathlib import Path
from datetime import datetime

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    print("Installing cryptography..."); import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "cryptography"], check=True)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ADMIN_LS = Path(r'C:\Users\Administrator\AppData\Roaming\Windsurf\Local State')
ADMIN_DB = Path(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb')

PLAINTEXTS = json.loads('{"secret://{\\"extensionId\\":\\"codeium.windsurf\\",\\"key\\":\\"windsurf_auth.sessions\\"}": "[{\\"id\\":\\"21765441-1ff8-4e3c-a1ae-4a8b14f01a47\\",\\"accessToken\\":\\"sk-ws-01-ZjtRvwZuPanGJdfQm40IrdA9IIouTc4oXe1dNHw2xK8sVZbAspyBmDMtZ38GQXcjiEH3s-l3-b-FGwDrzsEqf0eJ7Ane8Q\\",\\"account\\":{\\"label\\":\\"Miller Harper\\",\\"id\\":\\"Miller Harper\\"},\\"scopes\\":[]}]", "secret://{\\"extensionId\\":\\"codeium.windsurf\\",\\"key\\":\\"windsurf_auth.apiServerUrl\\"}": "https://server.self-serve.windsurf.com"}')

class DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', ctypes.wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

def dpapi_decrypt(data):
    bi = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    bo = DATA_BLOB()
    if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(bi), None, None, None, None, 1, ctypes.byref(bo)):
        r = ctypes.string_at(bo.pbData, bo.cbData); ctypes.windll.kernel32.LocalFree(bo.pbData); return r
    return None

ls = json.loads(ADMIN_LS.read_text(encoding='utf-8'))
ek = base64.b64decode(ls['os_crypt']['encrypted_key'])
if ek[:5] == b'DPAPI': ek = ek[5:]
aes_key = dpapi_decrypt(ek)
if not aes_key:
    print("DPAPI failed — are you running as Administrator?"); sys.exit(1)
print(f"AES key: {aes_key.hex()[:16]}...")

backup = ADMIN_DB.parent / f'state.vscdb.bak_safe_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
shutil.copy2(str(ADMIN_DB), str(backup))

for key, pt in PLAINTEXTS.items():
    short = key.split('"key":"')[1].rstrip('"}') if '"key":"' in key else key
    nonce = secrets.token_bytes(12)
    ct = AESGCM(aes_key).encrypt(nonce, pt.encode('utf-8'), None)
    v10 = b'v10' + nonce + ct
    buf = json.dumps({"type": "Buffer", "data": list(v10)})
    conn = sqlite3.connect(str(ADMIN_DB), timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (key, buf))
    conn.commit(); conn.close()
    print(f"Injected: {short} ({len(buf)} chars)")

# Sync apiKey in windsurfAuthStatus
sessions = json.loads(PLAINTEXTS.get('secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.sessions"}', '[]'))
if isinstance(sessions, list) and sessions:
    ak = sessions[0].get('accessToken', '')
    if ak:
        conn = sqlite3.connect(str(ADMIN_DB), timeout=10)
        row = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        if row:
            try:
                auth = json.loads(row[0])
                if auth and isinstance(auth, dict):
                    auth['apiKey'] = ak
                    conn.execute('PRAGMA journal_mode=WAL')
                    conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)",
                                ('windsurfAuthStatus', json.dumps(auth)))
                    conn.commit()
                    print(f"windsurfAuthStatus.apiKey synced")
            except: pass
        conn.close()

print("\nDone! Restart Windsurf on Administrator.")
