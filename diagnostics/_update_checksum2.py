#!/usr/bin/env python3
"""更新product.json checksum (无emoji输出)"""
import hashlib, base64, json
from pathlib import Path

wb = Path('D:/Windsurf/resources/app/out/vs/workbench/workbench.desktop.main.js')
prod = Path('D:/Windsurf/resources/app/product.json')

if not wb.exists() or not prod.exists():
    print('ERROR: files not found')
    exit(1)

digest = hashlib.sha256(wb.read_bytes()).digest()
new_cs = base64.b64encode(digest).decode().rstrip('=')

pj = json.loads(prod.read_text(encoding='utf-8'))
old_cs = pj.get('checksums', {}).get('vs/workbench/workbench.desktop.main.js', 'MISSING')
print('Old:', old_cs[:40])
print('New:', new_cs[:40])

if old_cs != new_cs:
    pj.setdefault('checksums', {})['vs/workbench/workbench.desktop.main.js'] = new_cs
    prod.write_text(json.dumps(pj, indent='\t', ensure_ascii=False), encoding='utf-8')
    print('D:/Windsurf product.json UPDATED')
else:
    print('D:/Windsurf product.json already matches')

# Also update ai local Windsurf
ai_wb = Path('C:/Users/ai/AppData/Local/Programs/Windsurf/resources/app/out/vs/workbench/workbench.desktop.main.js')
ai_prod = Path('C:/Users/ai/AppData/Local/Programs/Windsurf/resources/app/product.json')
if ai_wb.exists() and ai_prod.exists():
    ai_digest = hashlib.sha256(ai_wb.read_bytes()).digest()
    ai_cs = base64.b64encode(ai_digest).decode().rstrip('=')
    ai_pj = json.loads(ai_prod.read_text(encoding='utf-8'))
    ai_old = ai_pj.get('checksums', {}).get('vs/workbench/workbench.desktop.main.js', 'MISSING')
    if ai_old != ai_cs:
        ai_pj.setdefault('checksums', {})['vs/workbench/workbench.desktop.main.js'] = ai_cs
        ai_prod.write_text(json.dumps(ai_pj, indent='\t', ensure_ascii=False), encoding='utf-8')
        print('ai local product.json UPDATED')
    else:
        print('ai local product.json already matches')

print('DONE')
