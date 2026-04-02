#!/usr/bin/env python3
"""修复 CSS checksum 被错误覆盖的问题"""
import os, json

PRODUCT_JSON = r'D:\Windsurf\resources\app\product.json'
prod_dir = os.path.dirname(PRODUCT_JSON)

baks = sorted([f for f in os.listdir(prod_dir) if 'bak_ac' in f])
print('Backups found:', baks)

if not baks:
    print('No backup found!')
    exit(1)

bak_path = os.path.join(prod_dir, baks[0])
with open(bak_path, 'r', encoding='utf-8') as f:
    orig = json.load(f)

with open(PRODUCT_JSON, 'r', encoding='utf-8') as f:
    prod = json.load(f)

orig_checksums = orig.get('checksums', {})
curr_checksums = prod.get('checksums', {})

print('\nCurrent checksums:')
for k, v in curr_checksums.items():
    if 'workbench.desktop.main' in k:
        print(f'  {k}: {v[:30]}...')

print('\nOriginal checksums:')
for k, v in orig_checksums.items():
    if 'workbench.desktop.main' in k:
        print(f'  {k}: {v[:30]}...')

# Restore CSS checksum from backup, keep JS checksum (updated)
restored = 0
for k in list(curr_checksums.keys()):
    if 'workbench.desktop.main.css' in k:
        orig_val = orig_checksums.get(k, '')
        if orig_val and curr_checksums[k] != orig_val:
            print(f'\nRestoring CSS: {k}')
            print(f'  Wrong: {curr_checksums[k][:30]}')
            print(f'  Fixed: {orig_val[:30]}')
            prod['checksums'][k] = orig_val
            restored += 1

if restored:
    with open(PRODUCT_JSON, 'w', encoding='utf-8') as f:
        json.dump(prod, f, indent=2, ensure_ascii=False)
    print(f'\n✅ Restored {restored} CSS checksum(s)')
else:
    print('\nNo CSS checksums needed restoring')

print('\nFinal checksums:')
for k, v in prod.get('checksums', {}).items():
    if 'workbench.desktop.main' in k:
        print(f'  {k}: {v[:30]}...')
