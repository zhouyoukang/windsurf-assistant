#!/usr/bin/env python3
"""
解密本机safeStorage sessions，获取真正运行中的API key
然后用该key注入179
"""
import sqlite3, json, os, sys, ctypes, ctypes.wintypes, base64, subprocess, time
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "cryptography", "-q"], check=True)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', ctypes.wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

def dpapi_decrypt(data: bytes):
    bi = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    bo = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(bi), None, None, None, None, 0x1, ctypes.byref(bo))
    if ok:
        raw = ctypes.string_at(bo.pbData, bo.cbData)
        ctypes.windll.kernel32.LocalFree(bo.pbData)
        return raw
    return None

def aes_gcm_decrypt(key: bytes, data: bytes) -> str | None:
    """Decrypt Electron safeStorage v10 format"""
    if data[:3] == b'v10':
        data = data[3:]
    nonce = data[:12]
    ciphertext = data[12:]
    try:
        plain = AESGCM(key).decrypt(nonce, ciphertext, None)
        return plain.decode('utf-8')
    except Exception as e:
        print(f"  AES decrypt error: {e}")
        return None

def get_local_aes_key():
    local_state = os.path.expandvars(r'%APPDATA%\Windsurf\Local State')
    print(f"Local State: {local_state}")
    if not os.path.exists(local_state):
        print("ERROR: Local State not found")
        return None
    ls = json.loads(open(local_state, encoding='utf-8', errors='replace').read())
    ek_b64 = ls.get('os_crypt', {}).get('encrypted_key', '')
    if not ek_b64:
        print("ERROR: No encrypted_key")
        return None
    ek = base64.b64decode(ek_b64)
    if ek[:5] == b'DPAPI':
        ek = ek[5:]
    aes_key = dpapi_decrypt(ek)
    if aes_key:
        print(f"AES key OK: {len(aes_key)} bytes, hex={aes_key.hex()[:20]}...")
    else:
        print("ERROR: DPAPI decrypt failed")
    return aes_key

def decrypt_sessions(aes_key: bytes) -> list | None:
    local_db = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')
    conn = sqlite3.connect(local_db, timeout=5)
    sess_key = 'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.sessions"}'
    rows = conn.execute('SELECT key, value FROM ItemTable WHERE key LIKE ?', ('%windsurf_auth.sessions%',)).fetchall()
    conn.close()
    
    if not rows:
        print("No sessions key in DB")
        return None
    
    raw_val = rows[0][1]
    print(f"Sessions raw value type: {type(raw_val)}, len: {len(str(raw_val))}")
    
    # Parse as Electron Buffer JSON
    try:
        buf = json.loads(raw_val)
        if isinstance(buf, dict) and buf.get('type') == 'Buffer':
            data = bytes(buf['data'])
            print(f"Buffer data: {len(data)} bytes, starts with: {data[:3]}")
            plain = aes_gcm_decrypt(aes_key, data)
            if plain:
                print(f"Decrypted sessions: {plain[:200]}")
                sessions = json.loads(plain)
                return sessions
    except Exception as e:
        print(f"Buffer parse error: {e}")
    
    return None

def main():
    print("="*60)
    print("本机safeStorage解密 → 获取真实运行API key")
    print("="*60)
    
    # Get AES key
    aes_key = get_local_aes_key()
    if not aes_key:
        sys.exit(1)
    
    # Decrypt sessions
    sessions = decrypt_sessions(aes_key)
    if not sessions:
        print("ERROR: Cannot decrypt sessions")
        # Try alternative - read windsurfAuthStatus directly
        local_db = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')
        conn = sqlite3.connect(local_db)
        row = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        if row:
            d = json.loads(row[0])
            ak = d.get('apiKey', '')
            print(f"Fallback: windsurfAuthStatus.apiKey = {ak[:80]}...")
        conn.close()
        return
    
    print(f"\nDecrypted {len(sessions)} session(s):")
    for i, sess in enumerate(sessions):
        at = sess.get('accessToken', '')
        acc = sess.get('account', {})
        print(f"  [{i}] account={acc} accessToken={at[:60]}... (len={len(at)})")
    
    # Best session
    best = max(sessions, key=lambda s: len(s.get('accessToken', '')))
    real_api_key = best.get('accessToken', '')
    print(f"\nReal working API key: {real_api_key[:60]}... (len={len(real_api_key)})")
    
    # Save for use
    out = Path(__file__).parent / '_live_apikey.txt'
    out.write_text(real_api_key, encoding='utf-8')
    print(f"Saved to: {out}")
    
    return real_api_key

if __name__ == '__main__':
    key = main()
    if key:
        print(f"\n✓ API key extracted: {key[:40]}...")
        print("Next: inject this key into 179")
