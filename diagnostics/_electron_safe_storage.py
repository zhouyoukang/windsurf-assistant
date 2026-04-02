#!/usr/bin/env python3
"""
Electron safeStorage — Chromium os_crypt逆向
=============================================
Windsurf (Electron/Chromium) secret storage 加密链:

  Local State → os_crypt.encrypted_key
    → Base64 decode → strip "DPAPI" 5-byte prefix → CryptUnprotectData → AES-256 key (32 bytes)

  state.vscdb secret:// values
    → {"type":"Buffer","data":[118,49,48,...]}
    → Strip v10 prefix (3 bytes)
    → First 12 bytes = GCM nonce
    → Remaining = AES-256-GCM ciphertext + 16-byte tag
    → Decrypt with AES key

Phase 1 (as ai):   Decrypt ai's AES key → decrypt sessions → save plaintext
Phase 2 (as Admin): Read Admin's AES key → encrypt sessions → inject to DB

Usage:
  python _electron_safe_storage.py decrypt    # as ai
  python _electron_safe_storage.py inject     # as Administrator  
  python _electron_safe_storage.py auto       # auto-detect
"""

import sqlite3, json, os, sys, ctypes, ctypes.wintypes, base64, shutil
from pathlib import Path
from datetime import datetime

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    print("需要安装 cryptography 库: pip install cryptography")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent
PLAINTEXT_FILE = SCRIPT_DIR / '_session_plaintext.json'

USERS = {
    'ai': {
        'local_state': Path(r'C:\Users\ai\AppData\Roaming\Windsurf\Local State'),
        'state_db': Path(r'C:\Users\ai\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'),
    },
    'Administrator': {
        'local_state': Path(r'C:\Users\Administrator\AppData\Roaming\Windsurf\Local State'),
        'state_db': Path(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'),
    },
}

SECRET_KEYS = [
    'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.sessions"}',
    'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.apiServerUrl"}',
]


# ============================================================
# DPAPI via ctypes (for decrypting os_crypt.encrypted_key)
# ============================================================
class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ('cbData', ctypes.wintypes.DWORD),
        ('pbData', ctypes.POINTER(ctypes.c_char)),
    ]

def dpapi_decrypt(encrypted_bytes):
    """CryptUnprotectData — decrypt DPAPI blob for current user"""
    blob_in = DATA_BLOB()
    blob_in.cbData = len(encrypted_bytes)
    buf = ctypes.create_string_buffer(encrypted_bytes)
    blob_in.pbData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    
    blob_out = DATA_BLOB()
    
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,           # description out
        None,           # entropy
        None,           # reserved
        None,           # prompt
        0x1,            # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(blob_out)
    )
    
    if ok:
        raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return raw
    else:
        err = ctypes.GetLastError()
        print(f"    DPAPI error: {err} (0x{err:08x})")
        return None

def dpapi_encrypt(plaintext_bytes):
    """CryptProtectData — encrypt with current user's DPAPI"""
    blob_in = DATA_BLOB()
    blob_in.cbData = len(plaintext_bytes)
    buf = ctypes.create_string_buffer(plaintext_bytes)
    blob_in.pbData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    
    blob_out = DATA_BLOB()
    
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        None, None, None, None,
        0x1,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(blob_out)
    )
    
    if ok:
        raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return raw
    return None


# ============================================================
# Chromium os_crypt: AES key extraction
# ============================================================
def get_aes_key(local_state_path):
    """Extract AES-256 key from Chromium's Local State file.
    
    Flow: Local State → os_crypt.encrypted_key → base64 decode → 
          strip 'DPAPI' prefix → CryptUnprotectData → 32-byte AES key
    """
    if not local_state_path.exists():
        print(f"    Local State not found: {local_state_path}")
        return None
    
    ls = json.loads(local_state_path.read_text(encoding='utf-8'))
    encrypted_key_b64 = ls.get('os_crypt', {}).get('encrypted_key', '')
    
    if not encrypted_key_b64:
        print(f"    No os_crypt.encrypted_key in Local State")
        return None
    
    print(f"    encrypted_key (base64): {encrypted_key_b64[:40]}... ({len(encrypted_key_b64)} chars)")
    
    # Base64 decode
    encrypted_key = base64.b64decode(encrypted_key_b64)
    print(f"    Decoded: {len(encrypted_key)} bytes, prefix: {encrypted_key[:5]}")
    
    # Strip "DPAPI" prefix (5 bytes)
    if encrypted_key[:5] != b'DPAPI':
        print(f"    ⚠️  Expected 'DPAPI' prefix, got: {encrypted_key[:5]}")
        # Try without stripping
        dpapi_blob = encrypted_key
    else:
        dpapi_blob = encrypted_key[5:]
    
    print(f"    DPAPI blob: {len(dpapi_blob)} bytes")
    
    # DPAPI decrypt
    aes_key = dpapi_decrypt(dpapi_blob)
    if aes_key:
        print(f"    ✅ AES key: {len(aes_key)} bytes ({aes_key.hex()[:32]}...)")
        return aes_key
    else:
        print(f"    ❌ DPAPI decrypt failed (wrong user?)")
        return None


# ============================================================
# Chromium os_crypt: AES-256-GCM encrypt/decrypt
# ============================================================
def decrypt_v10(v10_data, aes_key):
    """Decrypt Chromium v10 format: v10 + nonce(12) + ciphertext + tag(16)"""
    if v10_data[:3] != b'v10':
        return None, "Not v10 format"
    
    encrypted = v10_data[3:]  # strip v10 prefix
    
    if len(encrypted) < 12 + 16:  # nonce + minimum tag
        return None, f"Too short: {len(encrypted)} bytes"
    
    nonce = encrypted[:12]
    ciphertext = encrypted[12:]  # includes GCM tag at the end
    
    try:
        aesgcm = AESGCM(aes_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext, None
    except Exception as e:
        return None, f"AES-GCM decrypt error: {e}"


def encrypt_v10(plaintext, aes_key):
    """Encrypt to Chromium v10 format"""
    import secrets
    nonce = secrets.token_bytes(12)
    
    aesgcm = AESGCM(aes_key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    
    return b'v10' + nonce + ciphertext


# ============================================================
# Electron Buffer format
# ============================================================
def parse_electron_buffer(db_value):
    """{"type":"Buffer","data":[...]} → bytes"""
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
    """bytes → {"type":"Buffer","data":[...]}"""
    return json.dumps({"type": "Buffer", "data": list(raw_bytes)})


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
    print("=" * 60)
    print("  Phase 1: DECRYPT ai's secrets")
    print(f"  Running as: {os.environ.get('USERNAME')}")
    print("=" * 60)
    
    # Get ai's AES key
    print("\n  [AES Key Extraction]")
    aes_key = get_aes_key(USERS['ai']['local_state'])
    if not aes_key:
        print("  ❌ Cannot get ai's AES key")
        return False
    
    # Decrypt each secret
    results = {}
    ai_db = USERS['ai']['state_db']
    
    for key in SECRET_KEYS:
        short = key.split('"key":"')[1].rstrip('"}') if '"key":"' in key else key
        print(f"\n  [{short}]")
        
        raw_value = db_read(ai_db, key)
        if not raw_value:
            print(f"    NOT FOUND")
            continue
        
        # Parse Electron Buffer
        v10_data = parse_electron_buffer(raw_value)
        if not v10_data:
            print(f"    Failed to parse Buffer")
            continue
        
        print(f"    Buffer: {len(v10_data)} bytes, prefix: {v10_data[:3]}")
        
        # AES-GCM decrypt
        plaintext, error = decrypt_v10(v10_data, aes_key)
        if error:
            print(f"    ❌ {error}")
            continue
        
        try:
            text = plaintext.decode('utf-8')
            print(f"    ✅ Decrypted: {len(text)} chars")
            print(f"    Preview: {text[:200]}...")
            results[key] = text
            
            # Parse JSON
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    print(f"    Type: array with {len(parsed)} items")
                    for i, item in enumerate(parsed[:3]):
                        if isinstance(item, dict):
                            print(f"    [{i}] keys: {list(item.keys())}")
                            for k, v in item.items():
                                sv = str(v)
                                if len(sv) > 50:
                                    sv = sv[:50] + '...'
                                print(f"        {k}: {sv}")
                elif isinstance(parsed, dict):
                    print(f"    Type: object, keys: {list(parsed.keys())}")
                else:
                    print(f"    Type: {type(parsed).__name__}")
            except:
                pass
        except:
            print(f"    ✅ Decrypted: {len(plaintext)} bytes (binary)")
            results[key] = plaintext.hex()
    
    if results:
        PLAINTEXT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"\n  ✅ Saved {len(results)} decrypted secrets to: {PLAINTEXT_FILE}")
        print(f"\n  Next step: run in Administrator's Windsurf terminal:")
        print(f'    python "{Path(__file__).resolve()}" inject')
        return True
    else:
        print(f"\n  ❌ No secrets decrypted")
        return False


# ============================================================
# Phase 2: Inject (run as Administrator)
# ============================================================
def phase_inject():
    print("=" * 60)
    print("  Phase 2: INJECT into Administrator's secrets")
    print(f"  Running as: {os.environ.get('USERNAME')}")
    print("=" * 60)
    
    if not PLAINTEXT_FILE.exists():
        print(f"  ❌ No plaintext file. Run decrypt phase first.")
        return False
    
    results = json.loads(PLAINTEXT_FILE.read_text(encoding='utf-8'))
    
    # Get Administrator's AES key
    print("\n  [AES Key Extraction]")
    aes_key = get_aes_key(USERS['Administrator']['local_state'])
    if not aes_key:
        print("  ❌ Cannot get Administrator's AES key")
        print("  Make sure this script runs AS Administrator")
        return False
    
    # Backup
    admin_db = USERS['Administrator']['state_db']
    if admin_db.exists():
        backup = admin_db.parent / f'state.vscdb.bak_safe_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        shutil.copy2(str(admin_db), str(backup))
        print(f"  Backup: {backup.name}")
    
    # Encrypt and inject each secret
    injected = 0
    for key, plaintext in results.items():
        short = key.split('"key":"')[1].rstrip('"}') if '"key":"' in key else key
        print(f"\n  [{short}]")
        
        # Convert back to bytes
        if isinstance(plaintext, str):
            try:
                pt_bytes = bytes.fromhex(plaintext) if all(c in '0123456789abcdef' for c in plaintext) else plaintext.encode('utf-8')
            except:
                pt_bytes = plaintext.encode('utf-8')
        else:
            pt_bytes = plaintext
        
        # AES-GCM encrypt with Administrator's key
        v10_data = encrypt_v10(pt_bytes, aes_key)
        
        # Wrap in Electron Buffer format
        buffer_json = make_electron_buffer(v10_data)
        
        # Write to DB
        db_write(admin_db, key, buffer_json)
        print(f"    ✅ Injected ({len(buffer_json)} chars)")
        injected += 1
    
    if injected > 0:
        print(f"\n  ✅ Injected {injected} secrets")
        print(f"  ⚡ Restart Windsurf on Administrator to activate login!")
        return True
    return False


# ============================================================
# Auto mode
# ============================================================
def auto():
    user = os.environ.get('USERNAME', '').lower()
    print(f"  Auto mode — detected user: {user}")
    
    if user == 'ai':
        ok = phase_decrypt()
        if ok:
            print(f"\n  {'='*60}")
            print(f"  Phase 1 complete. Now run in Administrator's terminal:")
            print(f'  python "{Path(__file__).resolve()}" inject')
    elif user == 'administrator':
        phase_inject()
    else:
        print(f"  Unknown user. Use: decrypt / inject")


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'auto'
    {'decrypt': phase_decrypt, 'inject': phase_inject, 'auto': auto}.get(cmd, auto)()
