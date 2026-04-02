import re

with open(r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

K5T_POS = 18357312
chunk = content[K5T_POS - 5000 : K5T_POS + 200]

# Find 'ja' assignments/definitions
print('=== ja definitions in 5000 chars before K5t ===')
for hit in re.finditer(r'\bja\s*=', chunk):
    ctx = chunk[max(0, hit.start()-20) : hit.start()+200]
    print(f'  @{hit.start()}: {repr(ctx[:200])}')

print()
# Also look for const/let/var ja
for hit in re.finditer(r'(?:const|let|var)\s+ja\b', chunk):
    ctx = chunk[max(0, hit.start()-10) : hit.start()+200]
    print(f'  decl @{hit.start()}: {repr(ctx[:200])}')

print()
# Find the P14 zo patch context and nearby ja
p14_hit = re.search(r'__mc4=Ie\.map\(lpe\)', content)
if p14_hit:
    print(f'P14 patch at: {p14_hit.start()}')
    # Get context around P14 - find ja near it
    p14_ctx = content[p14_hit.start()-3000: p14_hit.start()+500]
    for hit2 in re.finditer(r'\bja\s*=', p14_ctx):
        ctx = p14_ctx[max(0, hit2.start()-20): hit2.start()+150]
        print(f'  ja near P14 @{hit2.start()}: {repr(ctx)}')
    # Look for what 'ja' might be - search for comma-ja or destructuring
    for hit2 in re.finditer(r',ja[,=\)]', p14_ctx):
        ctx = p14_ctx[max(0, hit2.start()-30): hit2.start()+150]
        print(f'  ,ja @{hit2.start()}: {repr(ctx)}')

print()
# Most importantly: check if ja = Ie.map(lpe) somewhere else or ja = zo
p14_chunk = content[K5T_POS-5000: K5T_POS]
# Find all variable assignments that contain lpe or visibleModelConfigs
for pat in [r'=\s*Ie\.map\(lpe\)', r'visibleModelConfigs', r'lpe\)', r'\bzo\b']:
    for hit3 in re.finditer(pat, p14_chunk):
        ctx = p14_chunk[max(0,hit3.start()-30):hit3.start()+150]
        print(f'[{pat}] @{hit3.start()}: {repr(ctx)}')
