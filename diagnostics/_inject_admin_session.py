#!/usr/bin/env python3
"""
直接注入Administrator的safeStorage — 尝试从ai用户解密Admin的AES key
如果DPAPI失败(per-user)，则生成可在Admin终端运行的命令
"""

import sqlite3, json, os, sys, ctypes, ctypes.wintypes, base64, shutil, secrets
from pathlib import Path
from datetime import datetime

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    print("pip install cryptography")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent
PLAINTEXT_FILE = SCRIPT_DIR / '_session_plaintext.json'

ADMIN_LOCAL_STATE = Path(r'C:\Users\Administrator\AppData\Roaming\Windsurf\Local State')
ADMIN_DB = Path(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb')


class DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', ctypes.wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

def dpapi_decrypt(data, flags=0x1):
    blob_in = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, flags, ctypes.byref(blob_out)):
        raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return raw
    return None

def dpapi_encrypt(data, flags=0x1):
    blob_in = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if ctypes.windll.crypt32.CryptProtectData(ctypes.byref(blob_in), None, None, None, None, flags, ctypes.byref(blob_out)):
        raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return raw
    return None


def get_admin_aes_key():
    """Try to decrypt Administrator's AES key from ai user context"""
    ls = json.loads(ADMIN_LOCAL_STATE.read_text(encoding='utf-8'))
    ek_b64 = ls.get('os_crypt', {}).get('encrypted_key', '')
    ek = base64.b64decode(ek_b64)
    
    if ek[:5] == b'DPAPI':
        ek = ek[5:]
    
    # Try 1: Standard DPAPI (user-scope)
    key = dpapi_decrypt(ek, 0x1)
    if key:
        print(f"  ✅ Admin AES key decrypted (user-scope DPAPI)")
        return key
    
    # Try 2: Machine-scope DPAPI  
    key = dpapi_decrypt(ek, 0x5)  # CRYPTPROTECT_UI_FORBIDDEN | CRYPTPROTECT_LOCAL_MACHINE
    if key:
        print(f"  ✅ Admin AES key decrypted (machine-scope DPAPI)")
        return key
    
    # Try 3: No flags
    key = dpapi_decrypt(ek, 0x0)
    if key:
        print(f"  ✅ Admin AES key decrypted (no flags)")
        return key
    
    print(f"  ❌ Cannot decrypt Admin's AES key from ai context")
    return None


def encrypt_v10(plaintext_bytes, aes_key):
    nonce = secrets.token_bytes(12)
    aesgcm = AESGCM(aes_key)
    ct = aesgcm.encrypt(nonce, plaintext_bytes, None)
    return b'v10' + nonce + ct

def make_buffer(raw):
    return json.dumps({"type": "Buffer", "data": list(raw)})

def db_write(db_path, key, value):
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (key, value))
    conn.commit()
    conn.close()


def main():
    print("=" * 60)
    print("  Administrator Session Injection")
    print(f"  Running as: {os.environ.get('USERNAME')}")
    print("=" * 60)
    
    # Load plaintext
    if not PLAINTEXT_FILE.exists():
        print(f"  ❌ No plaintext file: {PLAINTEXT_FILE}")
        return
    
    plaintexts = json.loads(PLAINTEXT_FILE.read_text(encoding='utf-8'))
    print(f"  Loaded {len(plaintexts)} secrets")
    
    # Try to get Admin's AES key
    print(f"\n  [Admin AES Key]")
    aes_key = get_admin_aes_key()
    
    if not aes_key:
        # Can't decrypt from ai — generate a script for Admin to run
        print(f"\n  ⚡ Generating Admin-side injection script...")
        generate_admin_script(plaintexts)
        return
    
    # Direct injection
    print(f"\n  [Direct Injection]")
    backup = ADMIN_DB.parent / f'state.vscdb.bak_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    shutil.copy2(str(ADMIN_DB), str(backup))
    
    for key, plaintext in plaintexts.items():
        short = key.split('"key":"')[1].rstrip('"}') if '"key":"' in key else key
        pt_bytes = plaintext.encode('utf-8')
        v10 = encrypt_v10(pt_bytes, aes_key)
        buf = make_buffer(v10)
        db_write(ADMIN_DB, key, buf)
        print(f"  ✅ {short}: injected ({len(buf)} chars)")
    
    # Also ensure windsurfAuthStatus is valid
    sessions_key = 'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.sessions"}'
    if sessions_key in plaintexts:
        try:
            sessions = json.loads(plaintexts[sessions_key])
            if isinstance(sessions, list) and sessions:
                access_token = sessions[0].get('accessToken', '')
                account = sessions[0].get('account', {})
                
                # Read current windsurfAuthStatus to update apiKey
                conn = sqlite3.connect(str(ADMIN_DB), timeout=10)
                row = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
                if row:
                    try:
                        auth = json.loads(row[0])
                        if auth and isinstance(auth, dict):
                            auth['apiKey'] = access_token
                            conn.execute('PRAGMA journal_mode=WAL')
                            conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)",
                                        ('windsurfAuthStatus', json.dumps(auth)))
                            conn.commit()
                            print(f"  ✅ windsurfAuthStatus.apiKey synced")
                    except:
                        pass
                conn.close()
        except:
            pass
    
    print(f"\n  🎉 Injection complete!")
    print(f"  Restart Windsurf on Administrator → should show logged in")


def generate_admin_script(plaintexts):
    """Generate a self-contained Python script that Administrator can run"""
    # Serialize plaintexts as embedded data
    pt_json = json.dumps(plaintexts, ensure_ascii=False)
    
    script = f'''#!/usr/bin/env python3
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

ADMIN_LS = Path(r'C:\\Users\\Administrator\\AppData\\Roaming\\Windsurf\\Local State')
ADMIN_DB = Path(r'C:\\Users\\Administrator\\AppData\\Roaming\\Windsurf\\User\\globalStorage\\state.vscdb')

PLAINTEXTS = json.loads({repr(pt_json)})

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
print(f"AES key: {{aes_key.hex()[:16]}}...")

backup = ADMIN_DB.parent / f'state.vscdb.bak_safe_{{datetime.now().strftime("%Y%m%d_%H%M%S")}}'
shutil.copy2(str(ADMIN_DB), str(backup))

for key, pt in PLAINTEXTS.items():
    short = key.split('"key":"')[1].rstrip('"}}') if '"key":"' in key else key
    nonce = secrets.token_bytes(12)
    ct = AESGCM(aes_key).encrypt(nonce, pt.encode('utf-8'), None)
    v10 = b'v10' + nonce + ct
    buf = json.dumps({{"type": "Buffer", "data": list(v10)}})
    conn = sqlite3.connect(str(ADMIN_DB), timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (key, buf))
    conn.commit(); conn.close()
    print(f"Injected: {{short}} ({{len(buf)}} chars)")

# Sync apiKey in windsurfAuthStatus
sessions = json.loads(PLAINTEXTS.get('secret://{{"extensionId":"codeium.windsurf","key":"windsurf_auth.sessions"}}', '[]'))
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

print("\\nDone! Restart Windsurf on Administrator.")
'''
    
    out = SCRIPT_DIR / '_admin_inject_session.py'
    out.write_text(script, encoding='utf-8')
    print(f"  ✅ Script saved to: {out}")
    print(f"\n  ⚡ Run in Administrator's Windsurf terminal:")
    print(f'    python "{out}"')


if __name__ == '__main__':
    main()
