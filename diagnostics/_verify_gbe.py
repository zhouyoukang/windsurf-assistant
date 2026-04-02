#!/usr/bin/env python3
"""验证GBe v4.0补丁的实际signature"""
from pathlib import Path
wb = Path('D:/Windsurf/resources/app/out/vs/workbench/workbench.desktop.main.js')
data = wb.read_bytes()
checks = [
    ('GBe errorCodePrefix silent (real sig)', b'_rl?"":Z?.errorCode?'),
    ('GBe userErrorMessage silent', b'_rl?"":Z?.userErrorMessage'),
    ('GBe errorParts void0 (real sig)', b'errorParts:_rl?void 0:Z?.structuredErrorParts'),
    ('GBe __wamRateLimit signal', b'globalThis.__wamRateLimit'),
    ('GBe isBenign:_rl||B', b'isBenign:_rl||B'),
    ('opus-4-6 inject P12', b'__o46=Object.assign('),
    ('opus-4-6 inject P13', b'__o46b=Object.assign('),
]
all_pass = True
for name, marker in checks:
    found = marker in data
    status = 'PASS' if found else 'FAIL'
    if not found:
        all_pass = False
    print(f'  {status}  {name}')
print()
if all_pass:
    print('All GBe patches verified OK')
else:
    print('Some patches missing')
