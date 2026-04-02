#!/usr/bin/env python3
"""DPAPI sessions injection - runs in user's interactive session"""
import sqlite3, json, os, sys, ctypes, ctypes.wintypes, base64, secrets, subprocess, time, shutil, uuid
from pathlib import Path
from datetime import datetime

LOG = Path("C:/ctemp/_dpapi_inject.log")

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"{ts} {msg}"
    LOG.write_text(LOG.read_text() + line + "\n" if LOG.exists() else line + "\n", encoding="utf-8")
    print(line)

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "cryptography", "-q"], check=True)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

def dpapi_decrypt(data):
    bi = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    bo = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(bi), None, None, None, None, 0x1, ctypes.byref(bo))
    if ok:
        raw = ctypes.string_at(bo.pbData, bo.cbData)
        ctypes.windll.kernel32.LocalFree(bo.pbData)
        return raw
    return None

def aes_gcm_encrypt(key, plaintext):
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return b"v10" + nonce + ct

def to_buf(data):
    return json.dumps({"type": "Buffer", "data": list(data)})

USER_BASE = Path(os.environ["APPDATA"]) / "Windsurf"
USER_LS   = USER_BASE / "Local State"
USER_DB   = USER_BASE / "User/globalStorage/state.vscdb"
LIVE_KEY_FILE = Path("C:/ctemp/_live_apikey.txt")
API_SERVER_URL = "https://server.self-serve.windsurf.com"

log("=== DPAPI Sessions Inject ===")
log(f"DB: {USER_DB}")
log(f"LS: {USER_LS}")

# Read live key
if not LIVE_KEY_FILE.exists():
    log("ERROR: No live key file at " + str(LIVE_KEY_FILE))
    sys.exit(1)
live_key = LIVE_KEY_FILE.read_text().strip()
log(f"Live key: {live_key[:40]}... ({len(live_key)} chars)")

# Get AES key via DPAPI
if not USER_LS.exists():
    log("ERROR: Local State not found")
    sys.exit(1)

ls = json.loads(USER_LS.read_text(encoding="utf-8", errors="replace"))
ek_b64 = ls.get("os_crypt", {}).get("encrypted_key", "")
if not ek_b64:
    log("ERROR: No encrypted_key in Local State")
    sys.exit(1)

ek = base64.b64decode(ek_b64)
if ek[:5] == b"DPAPI":
    ek = ek[5:]

aes_key = dpapi_decrypt(ek)
if not aes_key:
    log("ERROR: DPAPI CryptUnprotectData FAILED (not in interactive session?)")
    sys.exit(1)

log(f"AES key OK: {len(aes_key)} bytes, hex={aes_key.hex()[:16]}...")

# Build sessions
sessions = json.dumps([{
    "id": str(uuid.uuid4()),
    "accessToken": live_key,
    "account": {"label": "live_inject_dpapi", "id": "live_inject_dpapi"},
    "scopes": []
}])
log(f"Sessions: {sessions[:80]}...")

sess_enc = aes_gcm_encrypt(aes_key, sessions)
url_enc  = aes_gcm_encrypt(aes_key, API_SERVER_URL)

# Backup DB
try:
    bak = str(USER_DB) + f".bak_dpapi_{datetime.now().strftime('%H%M%S')}"
    shutil.copy2(str(USER_DB), bak)
    log(f"Backup: {bak}")
except Exception as e:
    log(f"Backup skip: {e}")

# Write to DB
conn = sqlite3.connect(str(USER_DB), timeout=15)
conn.execute("PRAGMA journal_mode=WAL")
sess_key = 'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.sessions"}'
url_key  = 'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.apiServerUrl"}'
conn.execute("INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)", (sess_key, to_buf(sess_enc)))
conn.execute("INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)", (url_key,  to_buf(url_enc)))
conn.commit()
conn.close()
log("Sessions and apiServerUrl injected!")

# Verify
conn2 = sqlite3.connect(str(USER_DB), timeout=5)
r = conn2.execute("SELECT length(value) FROM ItemTable WHERE key=?", (sess_key,)).fetchone()
log(f"Verify sessions size: {r[0] if r else 'MISSING'}")
conn2.close()

log("DPAPI_INJECT_COMPLETE")
