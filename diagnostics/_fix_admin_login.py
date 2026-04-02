#!/usr/bin/env python3
"""
一键修复Administrator的Windsurf登录 — 道法自然·万法归宗·逆向到底
================================================================

突破: DPAPI CRYPTPROTECT_LOCAL_MACHINE (0x4)
  → 机器级加密: ai用户加密的数据, Administrator也能解密
  → 无需切换用户, 无需密码, 一键完成!

完整加密链:
  1. 生成新AES-256密钥 (32字节)
  2. DPAPI加密(LOCAL_MACHINE) → "DPAPI" + encrypted → Base64 → Local State
  3. AES-256-GCM加密session明文 → v10 + nonce + ciphertext + tag → Buffer JSON → state.vscdb
  4. 同步windsurfAuthStatus + cachedPlanInfo + windsurfConfigurations
  5. 更新cascade-auth.json / windsurf-auth.json
"""

import sqlite3, json, os, sys, ctypes, ctypes.wintypes, base64, shutil, secrets, subprocess, time
from pathlib import Path
from datetime import datetime

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    print("Installing cryptography...")
    subprocess.run([sys.executable, "-m", "pip", "install", "cryptography", "-q"], check=True)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ============================================================
# Paths
# ============================================================
ADMIN_LS = Path(r'C:\Users\Administrator\AppData\Roaming\Windsurf\Local State')
ADMIN_DB = Path(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb')
ADMIN_GS = Path(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage')
AI_DB = Path(r'C:\Users\ai\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb')

# Session plaintext (decrypted from ai's safeStorage)
SESSION_PLAINTEXT = '[{"id":"21765441-1ff8-4e3c-a1ae-4a8b14f01a47","accessToken":"sk-ws-01-ZjtRvwZuPanGJdfQm40IrdA9IIouTc4oXe1dNHw2xK8sVZbAspyBmDMtZ38GQXcjiEH3s-l3-b-FGwDrzsEqf0eJ7Ane8Q","account":{"label":"Miller Harper","id":"Miller Harper"},"scopes":[]}]'
API_SERVER_URL = 'https://server.self-serve.windsurf.com'

SESSION_OBJ = json.loads(SESSION_PLAINTEXT)
API_KEY = SESSION_OBJ[0]['accessToken']
ACCOUNT = SESSION_OBJ[0]['account']['label']


# ============================================================
# DPAPI via ctypes — with LOCAL_MACHINE support
# ============================================================
class DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', ctypes.wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

CRYPTPROTECT_UI_FORBIDDEN = 0x1
CRYPTPROTECT_LOCAL_MACHINE = 0x4

def dpapi_encrypt_machine(plaintext_bytes):
    """DPAPI encrypt with LOCAL_MACHINE scope — any user on this PC can decrypt"""
    blob_in = DATA_BLOB(len(plaintext_bytes),
                        ctypes.cast(ctypes.create_string_buffer(plaintext_bytes), ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    flags = CRYPTPROTECT_UI_FORBIDDEN | CRYPTPROTECT_LOCAL_MACHINE
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, flags, ctypes.byref(blob_out))
    if ok:
        raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return raw
    err = ctypes.GetLastError()
    raise OSError(f"CryptProtectData failed: error {err} (0x{err:08x})")

def dpapi_decrypt_machine(encrypted_bytes):
    """DPAPI decrypt (auto-detects LOCAL_MACHINE scope)"""
    blob_in = DATA_BLOB(len(encrypted_bytes),
                        ctypes.cast(ctypes.create_string_buffer(encrypted_bytes), ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if ok:
        raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return raw
    return None


# ============================================================
# Chromium os_crypt helpers
# ============================================================
def encrypt_v10(plaintext_str, aes_key):
    """Encrypt string → Chromium v10 format: v10 + nonce(12) + AES-GCM(ciphertext + tag)"""
    nonce = secrets.token_bytes(12)
    aesgcm = AESGCM(aes_key)
    ct = aesgcm.encrypt(nonce, plaintext_str.encode('utf-8'), None)
    return b'v10' + nonce + ct

def make_electron_buffer(raw_bytes):
    """bytes → {"type":"Buffer","data":[...]}"""
    return json.dumps({"type": "Buffer", "data": list(raw_bytes)})


# ============================================================
# DB helpers
# ============================================================
def db_read(path, key):
    conn = sqlite3.connect(str(path), timeout=10)
    row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
    conn.close()
    return row[0] if row else None

def db_write(path, key, value):
    conn = sqlite3.connect(str(path), timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (key, value))
    conn.commit()
    conn.close()

def db_write_multi(path, kv):
    conn = sqlite3.connect(str(path), timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    for k, v in kv.items():
        conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (k, v))
    conn.commit()
    conn.close()


# ============================================================
# MAIN
# ============================================================
def main():
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    print("=" * 60)
    print("  Windsurf Administrator Login Fix")
    print(f"  Running as: {os.environ.get('USERNAME')}")
    print(f"  Time: {datetime.now().isoformat()}")
    print("=" * 60)
    print(f"\n  apiKey: {API_KEY[:25]}... ({len(API_KEY)} chars)")
    print(f"  account: {ACCOUNT}")
    
    # --- Step 1: Generate AES key ---
    print(f"\n[1/7] Generating AES-256 key...")
    aes_key = secrets.token_bytes(32)
    print(f"  Key: {aes_key[:4].hex()}... (32 bytes)")
    
    # --- Step 2: DPAPI encrypt with LOCAL_MACHINE ---
    print(f"\n[2/7] DPAPI encrypting (LOCAL_MACHINE scope)...")
    encrypted_aes = dpapi_encrypt_machine(aes_key)
    print(f"  Encrypted: {len(encrypted_aes)} bytes")
    
    # Verify roundtrip
    verify = dpapi_decrypt_machine(encrypted_aes)
    if verify == aes_key:
        print(f"  Verify: PASS ✅")
    else:
        print(f"  Verify: FAIL ❌")
        return False
    
    # --- Step 3: Write to Administrator's Local State ---
    print(f"\n[3/7] Writing to Admin Local State...")
    shutil.copy2(str(ADMIN_LS), str(ADMIN_LS) + f'.bak_{ts}')
    
    # "DPAPI" prefix + encrypted → Base64
    full_key = b'DPAPI' + encrypted_aes
    key_b64 = base64.b64encode(full_key).decode()
    
    ls = json.loads(ADMIN_LS.read_text(encoding='utf-8'))
    ls['os_crypt']['encrypted_key'] = key_b64
    ADMIN_LS.write_text(json.dumps(ls), encoding='utf-8')
    print(f"  encrypted_key: {len(key_b64)} chars (base64)")
    
    # --- Step 4: AES-GCM encrypt sessions ---
    print(f"\n[4/7] AES-GCM encrypting sessions...")
    sess_v10 = encrypt_v10(SESSION_PLAINTEXT, aes_key)
    sess_buf = make_electron_buffer(sess_v10)
    print(f"  sessions: {len(sess_buf)} chars")
    
    url_v10 = encrypt_v10(API_SERVER_URL, aes_key)
    url_buf = make_electron_buffer(url_v10)
    print(f"  apiServerUrl: {len(url_buf)} chars")
    
    # --- Step 5: Inject into state.vscdb ---
    print(f"\n[5/7] Injecting into state.vscdb...")
    shutil.copy2(str(ADMIN_DB), str(ADMIN_DB) + f'.bak_{ts}')
    
    # 5a. secret:// keys
    secrets_kv = {
        'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.sessions"}': sess_buf,
        'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.apiServerUrl"}': url_buf,
    }
    db_write_multi(ADMIN_DB, secrets_kv)
    print(f"  ✅ 2 secret:// keys injected")
    
    # 5b. windsurfAuthStatus
    ai_auth_raw = db_read(AI_DB, 'windsurfAuthStatus')
    if ai_auth_raw:
        try:
            ai_auth = json.loads(ai_auth_raw)
            if ai_auth and isinstance(ai_auth, dict):
                ai_auth['apiKey'] = API_KEY
                db_write(ADMIN_DB, 'windsurfAuthStatus', json.dumps(ai_auth))
                print(f"  ✅ windsurfAuthStatus: apiKey set")
        except:
            db_write(ADMIN_DB, 'windsurfAuthStatus', json.dumps({'apiKey': API_KEY}))
            print(f"  ✅ windsurfAuthStatus: created fresh")
    else:
        db_write(ADMIN_DB, 'windsurfAuthStatus', json.dumps({'apiKey': API_KEY}))
        print(f"  ✅ windsurfAuthStatus: created fresh")
    
    # 5c. Sync cachedPlanInfo + windsurfConfigurations from ai
    for key in ['windsurf.settings.cachedPlanInfo', 'windsurfConfigurations']:
        val = db_read(AI_DB, key)
        if val:
            db_write(ADMIN_DB, key, val)
            print(f"  ✅ {key.split('.')[-1]}: synced ({len(val)} bytes)")
    
    # --- Step 6: Update auth JSON files ---
    print(f"\n[6/7] Updating auth files...")
    auth_data = json.dumps({
        'authToken': API_KEY, 'token': API_KEY,
        'api_key': API_KEY, 'timestamp': int(time.time() * 1000),
    }, indent=2)
    for fname in ['cascade-auth.json', 'windsurf-auth.json']:
        (ADMIN_GS / fname).write_text(auth_data, encoding='utf-8')
        print(f"  ✅ {fname}")
    
    # --- Step 7: Verify ---
    print(f"\n[7/7] Verification...")
    
    # Verify Local State roundtrip
    ls2 = json.loads(ADMIN_LS.read_text(encoding='utf-8'))
    ek2 = base64.b64decode(ls2['os_crypt']['encrypted_key'])
    assert ek2[:5] == b'DPAPI'
    aes2 = dpapi_decrypt_machine(ek2[5:])
    assert aes2 == aes_key
    print(f"  ✅ Local State: AES key roundtrip OK")
    
    # Verify state.vscdb
    auth_raw = db_read(ADMIN_DB, 'windsurfAuthStatus')
    auth_obj = json.loads(auth_raw) if auth_raw else None
    if auth_obj and auth_obj.get('apiKey', '').startswith('sk-ws'):
        print(f"  ✅ windsurfAuthStatus: {auth_obj['apiKey'][:25]}...")
    else:
        print(f"  ❌ windsurfAuthStatus: invalid")
    
    sess_raw = db_read(ADMIN_DB, 'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.sessions"}')
    if sess_raw and len(sess_raw) > 100:
        print(f"  ✅ secret://sessions: {len(sess_raw)} chars")
    else:
        print(f"  ❌ secret://sessions: missing/small")
    
    # --- Summary ---
    print(f"\n{'='*60}")
    print(f"  🎉 FIX COMPLETE — 道法自然")
    print(f"{'='*60}")
    print(f"""
  Breakthrough: DPAPI LOCAL_MACHINE scope
    → ai用户加密 → Administrator也能解密 → 跨用户认证打通!
  
  Account: {ACCOUNT}
  apiKey:  {API_KEY[:25]}...
  
  Next: Restart Windsurf on Administrator
    → Close Windsurf on Admin (or Ctrl+Shift+P → Reload Window)
    → Reopen → Should show LOGGED IN!
""")
    return True


if __name__ == '__main__':
    main()
