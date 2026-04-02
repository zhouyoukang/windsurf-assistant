#!/usr/bin/env python3
"""检查各用户hot-dir extension.js的关键特性"""
from pathlib import Path

for user in ['ai', 'Administrator']:
    hot = Path(f'C:/Users/{user}/.wam-hot')
    ext = hot / 'extension.js'
    if not ext.exists():
        print(f'--- {user}: extension.js MISSING ---')
        continue
    data = ext.read_bytes()
    size = len(data)
    print(f'--- {user} extension.js ({size:,} bytes) ---')
    checks = [
        ('wam_switching lock', b'.wam_switching'),
        ('Hub port 9870', b'9870'),
        ('Hub port 9876', b'9876'),
        ('injectAuth', b'injectAuth'),
        ('_injectCachedSession', b'_injectCachedSession'),
        ('POOL_HOT_PATCH', b'POOL_HOT_PATCH'),
        ('multiUserDB', b'multiUserDB'),
        ('SESSION_POOL', b'SESSION_POOL'),
        ('transparentProxy', b'transparentProxy'),
        ('9443', b'9443'),
        ('_wam_switching', b'_wam_switching'),
        ('v3.22', b'v3.22'),
        ('v3.2', b'v3.2'),
        ('WAM v', b'WAM v'),
    ]
    for name, marker in checks:
        found = marker in data
        print(f'  {name}: {"YES" if found else "NO"}')
    # Find version string
    for vmarker in [b'"version":"', b"'version':'", b'version:"', b'"WAM_VERSION"', b'WAM_VERSION=']:
        if vmarker in data:
            idx = data.index(vmarker)
            print(f'  Version context: {data[idx:idx+60]}')
            break

# Check D: workbench patches
print('\n--- D:/Windsurf workbench.js patches ---')
wb = Path('D:/Windsurf/resources/app/out/vs/workbench/workbench.desktop.main.js')
if wb.exists():
    data = wb.read_bytes()
    patches = {
        '__wamRateLimit': b'__wamRateLimit',
        'errorCodePrefix=""': b'errorCodePrefix=""',
        'maxGenerationTokens=9999': b'maxGenerationTokens=9999',
        'errorParts:[]': b'errorParts:[]',
        'hasCapacity bypass': b'if(!1&&!',
        'autoContinue ENABLED': b'autoContinueOnMaxGeneratorInvocations.ENABLED',
        'autoRunAllowed=!0': b'autoRunAllowed=!0',
    }
    for name, marker in patches.items():
        print(f'  {name}: {"YES" if marker in data else "NO"}')

# Check D: product.json checksum
print('\n--- product.json checksum ---')
import hashlib, base64, json
prod = Path('D:/Windsurf/resources/app/product.json')
if prod.exists() and wb.exists():
    pj = json.loads(prod.read_text(encoding='utf-8'))
    stored = pj.get('checksums', {}).get('vs/workbench/workbench.desktop.main.js', 'MISSING')
    digest = hashlib.sha256(wb.read_bytes()).digest()
    computed = base64.b64encode(digest).decode().rstrip('=')
    print(f'  stored:   {stored[:40]}')
    print(f'  computed: {computed[:40]}')
    print(f'  match: {stored == computed}')

# Check scheduled tasks
print('\n--- Checking WAM-related processes ---')
import subprocess
r = subprocess.run(
    ['powershell', '-NoProfile', '-Command',
     'Get-Process python,node -EA SilentlyContinue | Select-Object Id,ProcessName,CommandLine | Format-Table'],
    capture_output=True, text=True, timeout=10, encoding='utf-8', errors='replace'
)
print(r.stdout.strip() or 'none')
