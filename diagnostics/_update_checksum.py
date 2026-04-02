#!/usr/bin/env python3
"""更新product.json中workbench.js的checksum，与已打补丁的版本匹配"""
import hashlib, base64, json
from pathlib import Path

wb = Path('D:/Windsurf/resources/app/out/vs/workbench/workbench.desktop.main.js')
prod = Path('D:/Windsurf/resources/app/product.json')

if not wb.exists() or not prod.exists():
    print('ERROR: workbench.js or product.json not found')
    exit(1)

# Compute new checksum
digest = hashlib.sha256(wb.read_bytes()).digest()
new_checksum = base64.b64encode(digest).decode().rstrip('=')

# Read and update product.json
pj = json.loads(prod.read_text(encoding='utf-8'))
old_checksum = pj.get('checksums', {}).get('vs/workbench/workbench.desktop.main.js', 'MISSING')
print(f'Old: {old_checksum[:40]}...')
print(f'New: {new_checksum[:40]}...')

pj.setdefault('checksums', {})['vs/workbench/workbench.desktop.main.js'] = new_checksum
prod.write_text(json.dumps(pj, indent='\t', ensure_ascii=False), encoding='utf-8')
print('product.json updated ✅')

# Also check and update ai local Windsurf if different
ai_wb = Path('C:/Users/ai/AppData/Local/Programs/Windsurf/resources/app/out/vs/workbench/workbench.desktop.main.js')
ai_prod = Path('C:/Users/ai/AppData/Local/Programs/Windsurf/resources/app/product.json')
if ai_wb.exists() and ai_prod.exists():
    ai_digest = hashlib.sha256(ai_wb.read_bytes()).digest()
    ai_checksum = base64.b64encode(ai_digest).decode().rstrip('=')
    ai_pj = json.loads(ai_prod.read_text(encoding='utf-8'))
    ai_old = ai_pj.get('checksums', {}).get('vs/workbench/workbench.desktop.main.js', 'MISSING')
    if ai_old != ai_checksum:
        ai_pj.setdefault('checksums', {})['vs/workbench/workbench.desktop.main.js'] = ai_checksum
        ai_prod.write_text(json.dumps(ai_pj, indent='\t', ensure_ascii=False), encoding='utf-8')
        print(f'ai local product.json updated ✅')
    else:
        print(f'ai local product.json already matches ✅')
