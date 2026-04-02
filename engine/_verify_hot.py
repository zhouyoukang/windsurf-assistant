#!/usr/bin/env python3
"""Verify hot-patch system state — key file, patch, engine, proxy."""
import os, sys, json, time
import urllib.request
import urllib.error
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
EXT_JS = Path(r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js')
APPDATA = Path(os.environ.get('APPDATA', ''))
KEY_FILE = APPDATA / 'Windsurf' / '_pool_apikey.txt'
PATCH_MARKER = '/* POOL_HOT_PATCH_V1 */'

print('=' * 65)
print('  HOT-PATCH SYSTEM VERIFICATION')
print('=' * 65)

# 1. Extension.js patch status
src = EXT_JS.read_text(encoding='utf-8', errors='replace') if EXT_JS.exists() else ''
patched = PATCH_MARKER in src
original_present = 'apiKey:this.apiKey,sessionId:this.sessionId,requestId:BigInt' in src
print(f'\n[1] extension.js patch:')
print(f'    patched = {patched}')
print(f'    original_target_present = {original_present}')
print(f'    file size = {EXT_JS.stat().st_size:,} bytes' if EXT_JS.exists() else '    FILE NOT FOUND')

# 2. Key file
time.sleep(1)  # wait for key_writer
print(f'\n[2] Pool key file: {KEY_FILE}')
if KEY_FILE.exists():
    key = KEY_FILE.read_text(encoding='utf-8', errors='replace').strip()
    valid = len(key) > 20 and key.startswith('sk-ws')
    print(f'    exists = True')
    print(f'    preview = {key[:30]}...')
    print(f'    length = {len(key)} chars')
    print(f'    valid = {valid}')
else:
    print(f'    exists = False')

# 3. Pool engine API (try multiple ports)
print(f'\n[3] Pool engine API:')
engine_port = None
for port in range(19877, 19883):
    try:
        r = urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=2)
        d = json.loads(r.read())
        print(f'    ✅ Running on :{port}  v{d.get("version","?")}')
        engine_port = port
        # Get full status
        r2 = urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status', timeout=2)
        s = json.loads(r2.read())
        p = s['pool']
        print(f'    pool: {p["total"]} accts, {p["available"]} avail, {p["has_api_key"]} keys')
        print(f'    capacity: D{p["total_daily"]}% W{p["total_weekly"]}%')
        a = s.get('active', {})
        if a:
            print(f'    active: #{a["index"]} {a["email"][:30]} D{a["daily"]}% W{a["weekly"]}%')
        break
    except Exception:
        continue
else:
    print(f'    ❌ Not responding on :19877-:19882')

# 4. Proxy API
print(f'\n[4] Pool proxy:')
for port in range(19876, 19880):
    try:
        r = urllib.request.urlopen(f'http://127.0.0.1:{port}/pool/health', timeout=2)
        d = json.loads(r.read())
        print(f'    ✅ Running on :{port}  proxy={d.get("proxy","?")}')
        break
    except Exception:
        continue
else:
    print(f'    ⚠️  Not running (optional for hot-patch approach)')

# 5. apiServerUrl in state.vscdb
print(f'\n[5] apiServerUrl state:')
try:
    import sqlite3
    STATE_DB = APPDATA / 'Windsurf' / 'User' / 'globalStorage' / 'state.vscdb'
    conn = sqlite3.connect(f'file:{STATE_DB}?mode=ro', uri=True)
    secret_key = 'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.apiServerUrl"}'
    backup_key = secret_key + '__proxy_backup'
    row = conn.execute("SELECT length(value) FROM ItemTable WHERE key=?", (secret_key,)).fetchone()
    brow = conn.execute("SELECT length(value) FROM ItemTable WHERE key=?", (backup_key,)).fetchone()
    conn.close()
    print(f'    current secret: {row[0] if row else "not found"} bytes')
    print(f'    proxy backup: {"exists" if brow else "not found"} ({brow[0] if brow else 0}B)')
except Exception as e:
    print(f'    Error reading state.vscdb: {e}')

# 6. Hot-patch flow test
print(f'\n[6] Hot-patch flow simulation:')
if KEY_FILE.exists() and patched:
    key = KEY_FILE.read_text(encoding='utf-8', errors='replace').strip()
    if key.startswith('sk-ws') and len(key) > 20:
        print(f'    ✅ FLOW READY: extension reads {key[:25]}... on next gRPC call')
    else:
        print(f'    ❌ Key file invalid')
elif not patched:
    print(f'    ⚠️  Patch not applied yet — run: python hot_patch.py apply')
    print(f'    Then restart Windsurf ONCE to activate')
elif not KEY_FILE.exists():
    print(f'    ❌ Key file missing — run: python pool_engine.py serve')

# 7. Summary
print(f'\n{"=" * 65}')
ready = patched and KEY_FILE.exists()
if ready:
    key_valid = KEY_FILE.read_text(encoding='utf-8', errors='replace').strip().startswith('sk-ws')
    if key_valid:
        print(f'  🟢 PATCH READY — restart Windsurf once, then PERMANENTLY HOT')
    else:
        print(f'  🟡 PATCH APPLIED but key file empty — run pool_engine.py serve')
elif not patched:
    print(f'  🟡 APPLY PATCH: python hot_patch.py apply → restart Windsurf → done forever')
else:
    print(f'  🔴 NOT READY — check errors above')
print(f'{"=" * 65}')
