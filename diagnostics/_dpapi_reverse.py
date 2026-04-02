#!/usr/bin/env python3
"""
DPAPI Reverse — 逆向Windsurf safeStorage认证链
================================================
Windsurf的登录状态由 secret://windsurf_auth.sessions 控制
该值使用Electron safeStorage (Windows DPAPI) 加密
本脚本: 读取ai用户的加密数据 → 解密 → 分析格式
"""

import sqlite3, json, os, sys, ctypes, ctypes.wintypes
from pathlib import Path

# DPAPI via ctypes
class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ('cbData', ctypes.wintypes.DWORD),
        ('pbData', ctypes.POINTER(ctypes.c_char)),
    ]

def dpapi_decrypt(encrypted_bytes):
    """Decrypt DPAPI-encrypted data (works for current Windows user only)"""
    blob_in = DATA_BLOB()
    blob_in.cbData = len(encrypted_bytes)
    blob_in.pbData = ctypes.cast(ctypes.create_string_buffer(encrypted_bytes), ctypes.POINTER(ctypes.c_char))
    
    blob_out = DATA_BLOB()
    
    result = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,  # description
        None,  # entropy
        None,  # reserved
        None,  # prompt
        0,     # flags
        ctypes.byref(blob_out)
    )
    
    if result:
        raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return raw
    else:
        error = ctypes.GetLastError()
        return None

def dpapi_encrypt(plaintext_bytes):
    """Encrypt data with DPAPI (for current Windows user)"""
    blob_in = DATA_BLOB()
    blob_in.cbData = len(plaintext_bytes)
    blob_in.pbData = ctypes.cast(ctypes.create_string_buffer(plaintext_bytes), ctypes.POINTER(ctypes.c_char))
    
    blob_out = DATA_BLOB()
    
    result = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        None,  # description
        None,  # entropy
        None,  # reserved
        None,  # prompt
        0,     # flags (no UI)
        ctypes.byref(blob_out)
    )
    
    if result:
        raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return raw
    else:
        return None


# ============================================================
# Read secret:// keys from state.vscdb
# ============================================================
def read_all_secrets(db_path):
    """Read all secret:// entries from state.vscdb"""
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'secret://%'").fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


def analyze_secret_value(key, raw_value):
    """Analyze the raw secret value format"""
    print(f"\n  Key: {key}")
    
    if raw_value is None:
        print(f"    Value: NULL")
        return None
    
    # Check type
    if isinstance(raw_value, bytes):
        print(f"    Type: bytes, Length: {len(raw_value)}")
        raw_bytes = raw_value
    elif isinstance(raw_value, str):
        print(f"    Type: str, Length: {len(raw_value)}")
        # In VS Code, secrets might be stored as latin-1 encoded binary strings
        raw_bytes = raw_value.encode('latin-1')
    else:
        print(f"    Type: {type(raw_value).__name__}")
        return None
    
    # Show first bytes (hex)
    hex_preview = raw_bytes[:32].hex()
    print(f"    Hex (first 32): {hex_preview}")
    
    # Check if it starts with DPAPI magic
    if raw_bytes[:4] == b'\x01\x00\x00\x00':
        print(f"    Format: DPAPI blob (starts with 01 00 00 00)")
        
        # Try to decrypt
        decrypted = dpapi_decrypt(raw_bytes)
        if decrypted:
            print(f"    Decrypted length: {len(decrypted)}")
            try:
                text = decrypted.decode('utf-8')
                print(f"    Decrypted (UTF-8): {text[:500]}")
                return text
            except:
                print(f"    Decrypted (hex): {decrypted[:100].hex()}")
                return decrypted
        else:
            print(f"    DPAPI decrypt FAILED (expected - wrong user)")
    else:
        # Maybe plaintext or base64
        print(f"    Format: NOT DPAPI blob")
        try:
            text = raw_bytes.decode('utf-8')
            print(f"    As text: {text[:300]}")
            return text
        except:
            print(f"    Not decodable as UTF-8")
    
    return None


# ============================================================
# Main
# ============================================================
if __name__ == '__main__':
    print("=" * 60)
    print("  DPAPI Reverse — Windsurf safeStorage Analysis")
    print("=" * 60)
    
    current_user = os.environ.get('USERNAME', '?')
    print(f"  Running as: {current_user}")
    
    # 1. Read current user (ai) secrets
    ai_db = Path(os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb'))
    print(f"\n{'='*60}")
    print(f"  AI User Secrets ({ai_db})")
    print(f"{'='*60}")
    
    ai_secrets = read_all_secrets(ai_db)
    ai_decrypted = {}
    for key, value in ai_secrets.items():
        result = analyze_secret_value(key, value)
        if result:
            ai_decrypted[key] = result
    
    # 2. Read Administrator secrets
    admin_db = Path(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb')
    print(f"\n{'='*60}")
    print(f"  Administrator Secrets ({admin_db})")
    print(f"{'='*60}")
    
    admin_secrets = read_all_secrets(admin_db)
    for key, value in admin_secrets.items():
        analyze_secret_value(key, value)
    
    # 3. Analysis
    print(f"\n{'='*60}")
    print(f"  ANALYSIS")
    print(f"{'='*60}")
    
    if ai_decrypted:
        sessions_key = 'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.sessions"}'
        api_key = 'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.apiServerUrl"}'
        
        if sessions_key in ai_decrypted:
            session_data = ai_decrypted[sessions_key]
            print(f"\n  AI Session Data (decrypted):")
            print(f"    {str(session_data)[:500]}")
            
            # Parse if JSON
            try:
                if isinstance(session_data, str):
                    parsed = json.loads(session_data)
                    print(f"\n  Parsed session JSON:")
                    print(json.dumps(parsed, indent=4, default=str)[:2000])
            except:
                pass
        
        if api_key in ai_decrypted:
            print(f"\n  AI API Server URL (decrypted): {ai_decrypted[api_key]}")
    
    # 4. Save decrypted data for injection script
    if ai_decrypted:
        out = Path(__file__).parent / '_dpapi_decrypted.json'
        safe_data = {}
        for k, v in ai_decrypted.items():
            if isinstance(v, bytes):
                safe_data[k] = v.hex()
            else:
                safe_data[k] = v
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(safe_data, f, indent=2, ensure_ascii=False)
        print(f"\n  Saved decrypted data to: {out}")
