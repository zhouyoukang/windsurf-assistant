import re

with open(r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# K5t is at offset 18357312 — get 3000 chars before to find 'ja' definition
K5T_POS = 18357312
chunk = content[K5T_POS - 3000 : K5T_POS + 600]

# Find 'ja' assignments in that range
print('=== ja references near K5t ===')
for hit in re.finditer(r'\bja\b', chunk):
    ctx = chunk[max(0, hit.start()-30) : hit.start()+100]
    print(f'  offset {hit.start()}: {repr(ctx)}')

print()
# Also get full K5t function
k5t_hit = re.search(r'K5t=\(0,M\.useCallback\)', content)
if k5t_hit:
    full = content[k5t_hit.start() : k5t_hit.start() + 350]
    print('K5t full:')
    print(repr(full))

print()
# Find what XZ is
print('=== XZ near K5t ===')
for hit in re.finditer(r'\bXZ\b', chunk[-2000:]):
    ctx = chunk[-2000:][max(0,hit.start()-30):hit.start()+100]
    print(f'  {repr(ctx)}')
