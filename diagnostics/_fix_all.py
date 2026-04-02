#!/usr/bin/env python3
"""一键修复：完整性校验 + state.vscdb注入 + port 1590 测试"""
import os, json, hashlib, base64, sqlite3, struct, re, urllib.request, urllib.error

# ══════════════════════════════════════════════════════════
# PART 1: 修复 product.json 完整性校验
# ══════════════════════════════════════════════════════════
print("="*65)
print("PART 1: 修复 product.json 完整性校验")
print("="*65)

PRODUCT_JSON = r'D:\Windsurf\resources\app\product.json'
WB_JS = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'

with open(PRODUCT_JSON, 'r', encoding='utf-8') as f:
    product = json.load(f)

old_hash = product.get('checksums', {}).get('vs/workbench/workbench.desktop.main.js', 'NOT FOUND')
print(f"Old hash: {old_hash}")

# Compute new hash of patched workbench.js
wb_bytes = open(WB_JS, 'rb').read()
sha256_raw = hashlib.sha256(wb_bytes).digest()
# VSCode uses base64url without padding (url-safe base64)
new_hash_b64 = base64.b64encode(sha256_raw).decode('ascii').rstrip('=')
new_hash_b64url = base64.urlsafe_b64encode(sha256_raw).decode('ascii').rstrip('=')
print(f"New hash (b64):    {new_hash_b64}")
print(f"New hash (b64url): {new_hash_b64url}")

# Determine which format by comparing old hash decoding
try:
    old_decoded = base64.b64decode(old_hash + '==')
    print(f"Old hash decoded length: {len(old_decoded)} bytes (SHA256=32)")
    if len(old_decoded) == 32:
        # Standard base64 SHA256
        new_hash = new_hash_b64
    else:
        new_hash = new_hash_b64url
except Exception as e:
    print(f"Base64 decode error: {e}")
    new_hash = new_hash_b64

print(f"Using new hash: {new_hash}")

# Backup product.json
import shutil
bak = PRODUCT_JSON + '.bak_integrity'
if not os.path.exists(bak):
    shutil.copy2(PRODUCT_JSON, bak)
    print(f"Backup: {bak}")

# Update product.json
product['checksums']['vs/workbench/workbench.desktop.main.js'] = new_hash
with open(PRODUCT_JSON, 'w', encoding='utf-8') as f:
    json.dump(product, f, ensure_ascii=False, separators=(',', ':'))
print(f"✅ product.json updated!")

# Verify
with open(PRODUCT_JSON, 'r', encoding='utf-8') as f:
    verify = json.load(f)
print(f"Verify: {verify['checksums']['vs/workbench/workbench.desktop.main.js']}")

# ══════════════════════════════════════════════════════════
# PART 2: 重新注入 state.vscdb
# ══════════════════════════════════════════════════════════
print("\n" + "="*65)
print("PART 2: 重新注入 state.vscdb (claude-opus-4-6)")
print("="*65)

# Import and run the injection
import sys
sys.path.insert(0, r'v:\道\道生一\一生二\Windsurf无限额度\040-诊断工具_Diagnostics')
try:
    import subprocess
    result = subprocess.run(
        ['python', r'v:\道\道生一\一生二\Windsurf无限额度\040-诊断工具_Diagnostics\_inject_opus46.py', '--db'],
        capture_output=True, text=True, timeout=60, encoding='utf-8', errors='replace'
    )
    print(result.stdout[-2000:] if result.stdout else 'No output')
    if result.returncode != 0:
        print(f"STDERR: {result.stderr[-500:]}")
except Exception as e:
    print(f"Error: {e}")

# ══════════════════════════════════════════════════════════
# PART 3: Port 1590 gRPC 测试 (CheckChatCapacity)
# ══════════════════════════════════════════════════════════
print("\n" + "="*65)
print("PART 3: Port 1590 CheckChatCapacity 测试")
print("="*65)

STATE_DB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')
CSRF = '9d439854-47f4-4dcd-ba4c-92229f43777f'

def ev(v):
    r=[]
    while True:
        b=v&0x7F; v>>=7
        r.append(b|0x80 if v else b); 
        if not v: break
    return bytes(r)
def ef_str(fn, s): d=s.encode(); return ev((fn<<3)|2)+ev(len(d))+d
def ef_bytes(fn, b): return ev((fn<<3)|2)+ev(len(b))+b
def grpc_frame(pb): return b'\x00'+struct.pack('>I',len(pb))+pb

conn = sqlite3.connect('file:' + STATE_DB + '?mode=ro', uri=True)
api_key = json.loads(conn.execute(
    "SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'"
).fetchone()[0]).get('apiKey', '')
conn.close()

meta = ef_bytes(1, ef_str(1, api_key))

SERVICE = 'exa.language_server_pb.LanguageServerService'
PATH = f'/{SERVICE}/CheckChatCapacity'

def test_port(port, model_uid, ct, with_frame=False, with_csrf=True):
    req_pb = meta + ef_str(3, model_uid)
    body = grpc_frame(req_pb) if with_frame else req_pb
    url = f'http://127.0.0.1:{port}{PATH}'
    h = {'Content-Type': ct, 'Accept': ct}
    if with_csrf:
        h['x-codeium-csrf-token'] = CSRF
    req = urllib.request.Request(url, data=body, headers=h, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read(1000)
            return resp.status, raw[:200].decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read(200).decode('utf-8', errors='replace')
    except Exception as ex:
        return -1, str(ex)

# Try different content-types and formats on port 1590
models = ['claude-opus-4-6', 'claude-opus-4-5']
configs = [
    ('application/grpc-web+proto', True, False),
    ('application/grpc-web+proto', True, True),
    ('application/grpc-web', True, False),
    ('application/grpc+proto', False, False),
    ('application/proto', False, False),
    ('application/connect+json', False, False),
]

print(f"API Key: {api_key[:20]}...")
for model in models[:1]:  # Test target model first
    print(f"\nModel: {model}")
    for ct, with_frame, with_csrf in configs:
        status, body = test_port(1590, model, ct, with_frame, with_csrf)
        marker = '✅' if status == 200 else ('⚠️' if status in (400, 401, 403) else '❌')
        print(f"  {marker} [{ct[:35]}|frame={with_frame}|csrf={with_csrf}]: HTTP {status} -> {body[:80]}")
        if status == 200:
            print(f"     FULL RESPONSE: {body[:300]}")
            break

# Also test port 1588 with CSRF
print("\n" + "="*65)
print("PART 4: Port 1588 ExtensionServer 测试")
print("="*65)

paths_1588 = [
    ('/exa.extension_server_pb.ExtensionServerService/CheckHasCursorRules', b'', 'application/connect+proto'),
    ('/', b'', 'text/html'),
]
for path, body, ct in paths_1588:
    url = f'http://127.0.0.1:1588{path}'
    h = {'x-codeium-csrf-token': CSRF, 'Content-Type': ct}
    req = urllib.request.Request(url, data=body, headers=h, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            print(f"  POST {path}: HTTP {resp.status} -> {resp.read(200).decode(errors='replace')[:100]}")
    except urllib.error.HTTPError as e:
        print(f"  POST {path}: HTTP {e.code} -> {e.read(100).decode(errors='replace')[:80]}")
    except Exception as ex:
        print(f"  POST {path}: {ex}")

print("\n=== DONE ===")
print("\n⚡ 请在 Windsurf 中执行: Ctrl+Shift+P → Reload Window")
print("   重载后 Claude Opus 4.6 应出现在模型选择器中")
