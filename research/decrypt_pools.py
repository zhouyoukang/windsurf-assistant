"""
decrypt_pools.py
Decrypt ~/.pool-admin/pools.enc to get cloud pool URL and credentials
Mirrors lanGuard.js getMachineIdentity() + poolManager.js _decrypt()
"""
import hashlib, hmac as hmac_mod, json, os, io, sys, subprocess, struct, requests, re, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.backends import default_backend

POOLS_ENC  = os.path.expanduser(r'~\.pool-admin\pools.enc')
VAULT      = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\claude_key.vault'
REGISTER_URL = 'https://register.windsurf.com/exa.seat_management_pb.SeatManagementService/RegisterUser'

# ── Get real CPU model ─────────────────────────────────────────────────────
def get_cpu_model():
    try:
        r = subprocess.run(['wmic','cpu','get','Name','/value'],
                           capture_output=True,text=True,timeout=5)
        for line in r.stdout.strip().splitlines():
            if '=' in line:
                return line.split('=',1)[1].strip()
    except: pass
    return ''

# ── getMachineIdentity (mirrors lanGuard.js) ─────────────────────────────
def get_machine_identity():
    import platform
    hostname = platform.node()
    username = os.environ.get('USERNAME', 'Administrator')
    cpu      = get_cpu_model()
    plat     = 'win32'
    arch     = 'x64'
    data     = f'{hostname}|{username}|{cpu}|{plat}|{arch}'
    print(f"machineId input: {data}")
    return hashlib.sha256(data.encode()).hexdigest()

# ── getMachineSecret (mirrors lanGuard.js) ─────────────────────────────────
def get_machine_secret(mid):
    raw = hashlib.sha256(f'dao-pool-admin-{mid}'.encode()).hexdigest()
    return raw[:32]  # first 32 chars (32 bytes of hex string)

# ── Decrypt AES-256-CBC (mirrors poolManager.js _decrypt) ─────────────────
def decrypt_enc(text, machine_secret):
    """text = ivHex:encHex, key = scrypt(machine_secret, 'pool-salt', 32)"""
    parts = text.split(':')
    if len(parts) < 2: return None
    iv_hex = parts[0]
    enc_hex = ':'.join(parts[1:])
    try:
        iv  = bytes.fromhex(iv_hex)
        enc = bytes.fromhex(enc_hex)
        # key = scryptSync(getMachineSecret(), 'pool-salt', 32)
        kdf = Scrypt(salt=b'pool-salt', length=32, n=16384, r=8, p=1,
                     backend=default_backend())
        key = kdf.derive(machine_secret.encode())
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        dec = cipher.decryptor()
        padded = dec.update(enc) + dec.finalize()
        # Remove PKCS7 padding
        pad_len = padded[-1]
        return padded[:-pad_len].decode('utf-8')
    except Exception as e:
        print(f"  decrypt error: {e}")
        return None

# ── Proto helpers ─────────────────────────────────────────────────────────
def encode_proto_string(value):
    b = value.encode('utf-8'); tag = 0x0a
    L = len(b); lb = []
    while L > 127: lb.append((L & 0x7f) | 0x80); L >>= 7
    lb.append(L)
    return bytes([tag] + lb) + b

def parse_proto_string(buf):
    if not buf or len(buf) < 3 or buf[0] != 0x0a: return None
    pos = 1; L = 0; shift = 0
    while pos < len(buf):
        b = buf[pos]; pos += 1; L |= (b & 0x7f) << shift
        if not (b & 0x80): break
        shift += 7
    return buf[pos:pos+L].decode('utf-8', errors='replace') if pos+L <= len(buf) else None

# ── Main ──────────────────────────────────────────────────────────────────
print("=== Decrypting pools.enc ===")
print(f"Path: {POOLS_ENC}")
print(f"Exists: {os.path.exists(POOLS_ENC)}")
print()

mid = get_machine_identity()
print(f"machineId: {mid[:20]}...")
msec = get_machine_secret(mid)
print(f"machineSecret: {msec[:16]}...")
print()

if os.path.exists(POOLS_ENC):
    enc_text = open(POOLS_ENC, 'r', encoding='utf-8').read().strip()
    print(f"Encrypted text (first 80): {enc_text[:80]}...")
    result = decrypt_enc(enc_text, msec)
    if result:
        print(f"\nDecrypted pools.enc:")
        try:
            data = json.loads(result)
            print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
            
            # Extract pool URLs
            pools = data.get('pools', {})
            print(f"\n=== {len(pools)} cloud pools found ===")
            for pool_id, pool in pools.items():
                print(f"  Pool: {pool.get('name','?')}")
                print(f"  URL:  {pool.get('url','?')}")
                print(f"  adminKeyHalf: {pool.get('adminKeyHalf','')[:20]}...")
                print()
        except Exception as e:
            print(f"JSON parse error: {e}")
            print(f"Raw: {result[:500]}")
    else:
        print("Decryption FAILED — trying with scrypt params n=32768...")
        # Try alternative scrypt params
        try:
            iv = bytes.fromhex(enc_text.split(':')[0])
            enc = bytes.fromhex(':'.join(enc_text.split(':')[1:]))
            kdf2 = Scrypt(salt=b'pool-salt', length=32, n=32768, r=8, p=1, backend=default_backend())
            key2 = kdf2.derive(msec.encode())
            cipher2 = Cipher(algorithms.AES(key2), modes.CBC(iv), backend=default_backend())
            dec2 = cipher2.decryptor()
            padded2 = dec2.update(enc) + dec2.finalize()
            pad_len2 = padded2[-1]
            result2 = padded2[:-pad_len2].decode('utf-8')
            print(f"n=32768 result: {result2[:200]}")
        except Exception as e:
            print(f"n=32768 also failed: {e}")
else:
    print("pools.enc NOT FOUND - checking other locations...")
    # Check alternate locations
    for loc in [
        os.path.expanduser(r'~\.pool-admin'),
        r'C:\Users\Administrator\.pool-admin',
        r'C:\ProgramData\.pool-admin',
    ]:
        if os.path.exists(loc):
            print(f"Found dir: {loc}")
            for f in os.listdir(loc):
                print(f"  {f}: {os.path.getsize(os.path.join(loc,f))} bytes")

# Also try the hub's status endpoint without any auth
print("\n=== Port 9870 endpoints (no auth) ===")
for path_try in ['/api/v1/pool-accounts', '/api/v1/status', '/api/v1/ping',
                 '/api/v1/accounts', '/status', '/ping', '/health']:
    try:
        r = requests.get(f'http://127.0.0.1:9870{path_try}', timeout=4)
        if r.status_code != 404:
            print(f"  {path_try} → {r.status_code}: {r.text[:200]}")
    except: pass
