#!/usr/bin/env python3
"""
179笔记本 Windsurf账号远程注入 — 道法自然·从根本解决
=====================================================
功能:
  1. 读取Local State AES密钥(DPAPI解密 — 当前用户)
  2. 用新账号重新加密sessions → safeStorage注入
  3. 注入windsurfAuthStatus (plain JSON)
  4. 注入windsurfConfigurations (plain JSON)
  5. Kill Windsurf → Restart

用法:
  python _inject_179.py           # 使用内嵌的新账号数据
  python _inject_179.py --check   # 仅检查当前状态

道法自然: 不用签入流程, 直接注入auth blob, 3秒搞定。
"""

import sqlite3, json, os, sys, ctypes, ctypes.wintypes, base64, shutil, secrets, subprocess, time
from pathlib import Path
from datetime import datetime

# ── 安装依赖 ──
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    print("[*] Installing cryptography...")
    subprocess.run([sys.executable, "-m", "pip", "install", "cryptography", "-q"], check=True)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# =============================================
# 配置 — 新账号数据 (从_wam_snapshots.json提取)
# =============================================
TARGET_USER = os.environ.get("TARGET_WS_USER", os.environ.get("USERNAME", "zhouyoukang"))
USER_BASE   = Path(f"C:/Users/{TARGET_USER}/AppData/Roaming/Windsurf")
USER_LS     = USER_BASE / "Local State"
USER_DB     = USER_BASE / "User/globalStorage/state.vscdb"

# 新账号: 从141机器的_wam_snapshots.json提取的新鲜账号
# 注入时间: __INJECT_TIME__
NEW_EMAIL   = "__NEW_EMAIL__"
NEW_API_KEY = "__NEW_API_KEY__"
NEW_AUTH_STATUS      = '__NEW_AUTH_STATUS__'
NEW_CONFIGURATIONS   = '__NEW_CONFIGURATIONS__'
API_SERVER_URL = "https://server.self-serve.windsurf.com"

# =============================================
# DPAPI via ctypes
# =============================================
class DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', ctypes.wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

CRYPTPROTECT_UI_FORBIDDEN = 0x1

def dpapi_decrypt(data: bytes) -> bytes | None:
    bi = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    bo = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(bi), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(bo))
    if ok:
        raw = ctypes.string_at(bo.pbData, bo.cbData)
        ctypes.windll.kernel32.LocalFree(bo.pbData)
        return raw
    return None

def aes_gcm_encrypt(key: bytes, plaintext: str) -> bytes:
    nonce = secrets.token_bytes(12)
    ct_tag = AESGCM(key).encrypt(nonce, plaintext.encode('utf-8'), None)
    # Format: "v10" + nonce(12) + ciphertext + tag(16)
    return b'v10' + nonce + ct_tag

def to_electron_buffer(data: bytes) -> str:
    return json.dumps({"type": "Buffer", "data": list(data)})

# =============================================
# DB helpers
# =============================================
def db_read(db_path: Path, key: str):
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
    conn.close()
    return row[0] if row else None

def db_write_multi(db_path: Path, kv: dict):
    conn = sqlite3.connect(str(db_path), timeout=15)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=10000')
    n = 0
    for k, v in kv.items():
        conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (k, v))
        n += 1
    conn.commit()
    conn.close()
    return n

# =============================================
# Step 0: 检查当前状态
# =============================================
def check_state():
    print(f"\n  [Check] User: {TARGET_USER}")
    print(f"  [Check] DB: {USER_DB}")
    print(f"  [Check] DB exists: {USER_DB.exists()} ({USER_DB.stat().st_size//1024}KB)" if USER_DB.exists() else f"  [Check] DB: NOT FOUND")
    print(f"  [Check] Local State: {USER_LS.exists()}")

    if not USER_DB.exists():
        print("  [ERROR] state.vscdb not found!")
        return False

    # 读取当前auth状态
    raw = db_read(USER_DB, 'windsurfAuthStatus')
    if raw:
        try:
            auth = json.loads(raw)
            ak = auth.get('apiKey', '')
            print(f"  [Auth] Current apiKey: {ak[:30]}...")
        except:
            print(f"  [Auth] Raw (non-JSON): {raw[:60]}")
    else:
        print("  [Auth] windsurfAuthStatus: NULL")

    # 检查sessions
    sessions_key = 'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.sessions"}'
    raw_sess = db_read(USER_DB, sessions_key)
    print(f"  [SafeStorage] sessions: {'EXISTS' if raw_sess else 'NULL'} ({len(raw_sess) if raw_sess else 0} chars)")

    # Windsurf进程状态
    ws = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Windsurf.exe', '/FO', 'CSV', '/NH'],
                        capture_output=True, text=True, encoding='utf-8', errors='replace')
    ws_running = 'Windsurf.exe' in ws.stdout
    print(f"  [Windsurf] Running: {ws_running}")

    return True

# =============================================
# Step 1: 提取AES密钥 (DPAPI解密)
# =============================================
def get_aes_key() -> bytes | None:
    if not USER_LS.exists():
        print(f"  [ERROR] Local State not found: {USER_LS}")
        return None
    try:
        ls = json.loads(USER_LS.read_text(encoding='utf-8', errors='replace'))
        ek_b64 = ls.get('os_crypt', {}).get('encrypted_key', '')
        if not ek_b64:
            print("  [ERROR] No encrypted_key in Local State")
            return None
        ek = base64.b64decode(ek_b64)
        if ek[:5] == b'DPAPI':
            ek = ek[5:]
        aes_key = dpapi_decrypt(ek)
        if aes_key:
            print(f"  [AES] Key extracted: {aes_key.hex()[:16]}... ({len(aes_key)} bytes)")
            return aes_key
        else:
            print("  [ERROR] DPAPI decrypt failed — running as wrong user?")
            return None
    except Exception as e:
        print(f"  [ERROR] AES key extraction failed: {e}")
        return None

# =============================================
# Step 2: 注入新账号
# =============================================
def inject(dry_run=False):
    print(f"\n{'='*60}")
    print(f"  注入新账号: {NEW_EMAIL}")
    print(f"  注入时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # 备份 (磁盘满时跳过)
    if USER_DB.exists():
        try:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            bak = USER_DB.parent / f"state.vscdb.bak_inject179_{ts}"
            shutil.copy2(str(USER_DB), str(bak))
            print(f"  [Backup] {bak.name}")
        except OSError as e:
            print(f"  [Backup] SKIPPED ({e})")

    # 提取AES密钥
    print("\n  [Step 1] 提取DPAPI/AES密钥...")
    aes_key = get_aes_key()

    # 构建sessions plaintext
    session_id = str(__import__('uuid').uuid4())
    sessions_plaintext = json.dumps([{
        "id": session_id,
        "accessToken": NEW_API_KEY,
        "account": {"label": NEW_EMAIL.split('@')[0], "id": NEW_EMAIL.split('@')[0]},
        "scopes": []
    }])

    # 构建注入数据
    kv = {}

    # A. windsurfAuthStatus (plain JSON — 最重要)
    kv['windsurfAuthStatus'] = NEW_AUTH_STATUS
    print(f"  [Auth] windsurfAuthStatus: {len(NEW_AUTH_STATUS)} chars")

    # B. windsurfConfigurations (plain JSON)
    if NEW_CONFIGURATIONS and NEW_CONFIGURATIONS != "null":
        kv['windsurfConfigurations'] = NEW_CONFIGURATIONS
        print(f"  [Conf] windsurfConfigurations: {len(NEW_CONFIGURATIONS)} chars")

    # C. safeStorage sessions (DPAPI加密 — 确保重启后不回退)
    if aes_key:
        print("\n  [Step 2] 加密sessions → safeStorage...")
        sess_v10 = aes_gcm_encrypt(aes_key, sessions_plaintext)
        sess_buf = to_electron_buffer(sess_v10)
        kv['secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.sessions"}'] = sess_buf
        print(f"  [Sessions] Encrypted: {len(sess_buf)} chars")

        # D. apiServerUrl
        url_v10 = aes_gcm_encrypt(aes_key, API_SERVER_URL)
        url_buf = to_electron_buffer(url_v10)
        kv['secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.apiServerUrl"}'] = url_buf
        print(f"  [ApiUrl] Encrypted: {len(url_buf)} chars")
    else:
        print("  [WARN] Skipping safeStorage update (no AES key) — only windsurfAuthStatus injected")
        print("  [WARN] After Windsurf RESTART, old account may return. Use Reload Window instead.")

    if dry_run:
        print("\n  [DryRun] 不实际写入 — 以上是将写入的数据")
        return True

    # 写入state.vscdb
    print("\n  [Step 3] 写入state.vscdb...")
    n = db_write_multi(USER_DB, kv)
    print(f"  [DB] Written: {n} keys")

    return n > 0

# =============================================
# Step 3: Kill + Restart Windsurf
# =============================================
def restart_windsurf():
    print("\n  [Step 4] Kill + Restart Windsurf...")

    # Kill
    kill_res = subprocess.run(
        ['taskkill', '/F', '/IM', 'Windsurf.exe', '/T'],
        capture_output=True, text=True, encoding='utf-8', errors='replace'
    )
    print(f"  [Kill] {kill_res.stdout.strip()[:80] or kill_res.stderr.strip()[:80]}")
    time.sleep(3)

    # 找Windsurf.exe路径
    candidates = [
        Path('D:/Windsurf/Windsurf.exe'),  # 179笔记本实际路径
        Path(os.environ.get('LOCALAPPDATA', 'C:/Users/zhouyoukang/AppData/Local')) / 'Programs' / 'Windsurf' / 'Windsurf.exe',
        Path('C:/Users/zhouyoukang/AppData/Local/Programs/Windsurf/Windsurf.exe'),
        Path('C:/Program Files/Windsurf/Windsurf.exe'),
    ]

    ws_exe = next((p for p in candidates if p.exists()), None)
    if not ws_exe:
        print("  [WARN] Windsurf.exe not found in known paths. Please start Windsurf manually.")
        print("         Or run: Start-Process 'Windsurf.exe'")
        return False

    print(f"  [Start] {ws_exe}")
    subprocess.Popen([str(ws_exe)], creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    print(f"  [Start] Windsurf launched!")
    return True

# =============================================
# Main
# =============================================
if __name__ == '__main__':
    args = sys.argv[1:]

    print("\n" + "="*60)
    print("  179笔记本 Windsurf账号注入器")
    print(f"  Target: {TARGET_USER} @ {os.environ.get('COMPUTERNAME','?')}")
    print("="*60)

    if '--check' in args:
        check_state()
        sys.exit(0)

    # 检查当前状态
    check_state()

    # 验证数据完整性 (check without using placeholder string to avoid self-replacement)
    if not (NEW_API_KEY and NEW_API_KEY.startswith('sk-')):
        print("\n[ERROR] 脚本中的账号数据未填充。请先运行 _gen_inject_179.py 生成注入脚本。")
        sys.exit(1)

    # 执行注入
    dry_run = '--dry' in args
    ok = inject(dry_run=dry_run)

    if ok and not dry_run:
        print("\n  [SUCCESS] 注入完成!")
        # 重启
        if '--no-restart' not in args:
            restart_windsurf()
        else:
            print("  [INFO] 跳过重启。请手动关闭并重启Windsurf。")
    elif not ok:
        print("\n  [FAILED] 注入失败!")
        sys.exit(1)

    print("\n" + "="*60)
    print(f"  账号切换: {NEW_EMAIL}")
    print(f"  Windsurf将使用新账号 → 额度续期")
    print("="*60)
