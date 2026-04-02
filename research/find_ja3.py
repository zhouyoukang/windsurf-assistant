import re

with open(r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

K5T_POS = 18357312

# K5t is at 18357312. Look for ja= in a wider range (20000 chars before)
chunk = content[K5T_POS - 20000 : K5T_POS + 200]

print('=== ja assignments in 20000 chars before K5t ===')
hits = []
for hit in re.finditer(r'\bja\b\s*[=,\)]', chunk):
    ctx = chunk[max(0, hit.start()-50) : hit.start()+150]
    # Skip noise - only show actual assignments and destructurings
    if any(x in ctx for x in ['ja=', 'ja,', ',ja=', 'const ja', 'let ja']):
        hits.append((hit.start(), ctx))

for pos, ctx in hits[-20:]:  # last 20 (closest to K5t)
    print(f'  @{K5T_POS - 20000 + pos}: {repr(ctx)}')

# Also: look at the component function that K5t is inside
# K5t is used in useCallback with [ja, XZ] dependency
# Let's find the enclosing function
print()
print('=== Component boundary search: find useMemo/useState before K5t ===')
# Look at 1000 chars before K5t
ctx1000 = content[K5T_POS - 1000 : K5T_POS]
print(repr(ctx1000[-500:]))

# Look for what XZ is
print()
print('=== XZ definition ===')
chunk2 = content[K5T_POS - 15000 : K5T_POS]
for hit in re.finditer(r'\bXZ\s*=', chunk2):
    ctx = chunk2[max(0, hit.start()-20) : hit.start()+200]
    print(f'  @{hit.start()}: {repr(ctx)}')
