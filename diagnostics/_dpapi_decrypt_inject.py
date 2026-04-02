#!/usr/bin/env python3
"""
DPAPI Decrypt & Inject — 彻底解决Windsurf跨用户登录
====================================================
Electron safeStorage format: {"type":"Buffer","data":[118,49,48,...]}
  - 118,49,48 = "v10" prefix (Electron encryption version)
  - Remaining bytes = DPAPI CryptProtectData output

Phase 1 (run as ai):     Decrypt ai's sessions → get plaintext
Phase 2 (run as Admin):  Encrypt plaintext → inject into Admin's DB

Usage:
  python _dpapi_decrypt_inject.py decrypt    # Phase 1: run as ai
  python _dpapi_decrypt_inject.py inject     # Phase 2: run as Administrator
"""

import sqlite3, json, os, sys, ctypes, ctypes.wintypes, time, shutil
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
PLAINTEXT_FILE = SCRIPT_DIR / '_session_plaintext.json'

AI_DB = Path(r'C:\Users\ai\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb')
ADMIN_DB = Path(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb')

SECRET_KEYS = [
    'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.sessions"}',
    'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.apiServerUrl"}',
]


# ============================================================
# DPAPI via ctypes
# ============================================================
class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ('cbData', ctypes.wintypes.DWORD),
        ('pbData', ctypes.POINTER(ctypes.c_char)),
    ]

def dpapi_decrypt(encrypted_bytes):
    blob_in = DATA_BLOB(len(encrypted_bytes),
                        ctypes.cast(ctypes.create_string_buffer(encrypted_bytes),
                                    ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return raw
    return None

def dpapi_encrypt(plaintext_bytes):
    blob_in = DATA_BLOB(len(plaintext_bytes),
                        ctypes.cast(ctypes.create_string_buffer(plaintext_bytes),
                                    ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return raw
    return None


# ============================================================
# Electron safeStorage Buffer format
# ============================================================
def parse_electron_buffer(db_value):
    """Parse {"type":"Buffer","data":[118,49,48,...]} → raw bytes"""
    if not db_value:
        return None
    try:
        obj = json.loads(db_value)
        if obj.get('type') == 'Buffer' and 'data' in obj:
            return bytes(obj['data'])
    except:
        pass
    return None

def make_electron_buffer(raw_bytes):
    """raw bytes → {"type":"Buffer","data":[118,49,48,...]}"""
    return json.dumps({"type": "Buffer", "data": list(raw_bytes)})

def decrypt_electron_secret(db_value):
    """Decrypt Electron safeStorage value from state.vscdb"""
    raw = parse_electron_buffer(db_value)
    if not raw:
        return None, "Failed to parse Buffer"
    
    # Check v10 prefix
    if raw[:3] != b'v10':
        return None, f"Unknown prefix: {raw[:3]}"
    
    # DPAPI decrypt (skip v10 prefix)
    encrypted = raw[3:]
    plaintext = dpapi_decrypt(encrypted)
    if plaintext:
        try:
            return plaintext.decode('utf-8'), None
        except:
            return plaintext, None
    return None, "DPAPI decrypt failed (wrong user?)"

def encrypt_electron_secret(plaintext):
    """Encrypt plaintext → Electron safeStorage Buffer format for state.vscdb"""
    if isinstance(plaintext, str):
        plaintext = plaintext.encode('utf-8')
    
    encrypted = dpapi_encrypt(plaintext)
    if not encrypted:
        return None
    
    # Prepend v10 prefix
    full = b'v10' + encrypted
    return make_electron_buffer(full)


# ============================================================
# DB helpers
# ============================================================
def db_read(db_path, key):
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path), timeout=10)
    row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
    conn.close()
    return row[0] if row else None

def db_write(db_path, key, value):
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (key, value))
    conn.commit()
    conn.close()


# ============================================================
# Phase 1: Decrypt (run as ai)
# ============================================================
def phase_decrypt():
    """Decrypt ai user's safeStorage secrets and save plaintext"""
    print("=" * 60)
    print("  Phase 1: DECRYPT (running as ai)")
    print("=" * 60)
    
    user = os.environ.get('USERNAME', '?')
    if user.lower() != 'ai':
        print(f"  ⚠️  Current user is '{user}', expected 'ai'")
        print(f"  DPAPI can only decrypt current user's data")
    
    results = {}
    
    for key in SECRET_KEYS:
        short_key = key.split('"key":"')[1].rstrip('"}') if '"key":"' in key else key
        print(f"\n  [{short_key}]")
        
        raw_value = db_read(AI_DB, key)
        if not raw_value:
            print(f"    NOT FOUND in DB")
            continue
        
        plaintext, error = decrypt_electron_secret(raw_value)
        if error:
            print(f"    Error: {error}")
            continue
        
        if isinstance(plaintext, bytes):
            print(f"    Decrypted: {len(plaintext)} bytes (binary)")
            results[key] = {'type': 'hex', 'value': plaintext.hex()}
        else:
            print(f"    Decrypted: {len(plaintext)} chars")
            print(f"    Content: {plaintext[:200]}...")
            results[key] = {'type': 'text', 'value': plaintext}
            
            # Parse if JSON
            try:
                parsed = json.loads(plaintext)
                print(f"    JSON structure: {list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__}")
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict):
                            print(f"      Entry keys: {list(item.keys())}")
                            # Show key fields but redact sensitive values
                            for k, v in item.items():
                                if k in ('apiKey', 'token', 'refreshToken', 'accessToken'):
                                    print(f"        {k}: {str(v)[:20]}... ({len(str(v))} chars)")
                                else:
                                    print(f"        {k}: {str(v)[:80]}")
            except:
                pass
    
    if results:
        PLAINTEXT_FILE.write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(f"\n  ✅ Saved plaintext to: {PLAINTEXT_FILE}")
        print(f"  Next: Run 'python {Path(__file__).name} inject' AS Administrator")
    else:
        print(f"\n  ❌ No secrets decrypted")
    
    return bool(results)


# ============================================================
# Phase 2: Inject (run as Administrator)
# ============================================================
def phase_inject():
    """Encrypt plaintext with Administrator's DPAPI and inject into state.vscdb"""
    print("=" * 60)
    print("  Phase 2: INJECT (running as Administrator)")
    print("=" * 60)
    
    user = os.environ.get('USERNAME', '?')
    print(f"  Current user: {user}")
    
    if not PLAINTEXT_FILE.exists():
        print(f"  ❌ Plaintext file not found: {PLAINTEXT_FILE}")
        print(f"  Run 'python {Path(__file__).name} decrypt' as ai user first")
        return False
    
    results = json.loads(PLAINTEXT_FILE.read_text(encoding='utf-8'))
    
    # Backup
    if ADMIN_DB.exists():
        backup = ADMIN_DB.parent / f'state.vscdb.bak_dpapi_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        shutil.copy2(str(ADMIN_DB), str(backup))
        print(f"  Backup: {backup.name}")
    
    injected = 0
    for key, data in results.items():
        short_key = key.split('"key":"')[1].rstrip('"}') if '"key":"' in key else key
        print(f"\n  [{short_key}]")
        
        if data['type'] == 'text':
            plaintext = data['value']
        elif data['type'] == 'hex':
            plaintext = bytes.fromhex(data['value'])
        else:
            print(f"    Unknown type: {data['type']}")
            continue
        
        # Encrypt with current user's DPAPI
        encrypted_buffer = encrypt_electron_secret(plaintext)
        if not encrypted_buffer:
            print(f"    ❌ DPAPI encrypt failed")
            continue
        
        # Write to Administrator's state.vscdb
        db_write(ADMIN_DB, key, encrypted_buffer)
        print(f"    ✅ Injected ({len(encrypted_buffer)} chars)")
        injected += 1
    
    if injected > 0:
        print(f"\n  ✅ Injected {injected} secrets into Administrator's state.vscdb")
        print(f"  Next: Restart Windsurf on Administrator → should be logged in!")
    else:
        print(f"\n  ❌ No secrets injected")
    
    return injected > 0


# ============================================================
# Auto mode: detect user and do the right thing
# ============================================================
def auto():
    """Automatically detect phase based on current user"""
    user = os.environ.get('USERNAME', '?').lower()
    
    if user == 'ai':
        # Phase 1: Decrypt
        ok = phase_decrypt()
        if ok:
            # Also try to inject directly if we have write access to Admin DB
            print(f"\n  Attempting direct cross-user injection...")
            # We can write to Admin's state.vscdb (file system access)
            # But DPAPI encrypt will use AI's key, not Admin's
            # This WON'T work for DPAPI — need to run as Admin
            print(f"  ℹ️  Direct injection not possible (DPAPI is per-user)")
            print(f"  ⚡ Please run the following in Administrator's Windsurf terminal:")
            print(f"")
            print(f'    python "{Path(__file__).resolve()}" inject')
            print(f"")
    elif user == 'administrator':
        # Phase 2: Inject
        phase_inject()
    else:
        print(f"  Unknown user: {user}")
        print(f"  Run 'decrypt' as ai, then 'inject' as Administrator")


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'auto'
    
    if cmd == 'decrypt':
        phase_decrypt()
    elif cmd == 'inject':
        phase_inject()
    elif cmd == 'auto':
        auto()
    else:
        print(f"Usage: python {Path(__file__).name} [decrypt|inject|auto]")
