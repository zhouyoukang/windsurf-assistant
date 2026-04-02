import re
with open(r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Find K5t definition (handleModelChange)
for hit in re.finditer(r'\bK5t\b', content):
    ctx = content[hit.start():hit.start()+500]
    if '=' in ctx[:5] or 'function' in ctx[:20]:
        print(f'K5t def @{hit.start()}: {repr(ctx[:400])}')
        print()

# Also find where model change is guarded by isPaying/hasPaidFeatures/tier
print('=== isPaying guard in model change ===')
for pat in [r'hasPaidFeatures.*modelUid|modelUid.*hasPaidFeatures',
            r'isPaying.*setActive|setActive.*isPaying',
            r'openUrl.*model|model.*openUrl.*pricing']:
    for hit in re.finditer(pat, content):
        ctx = content[max(0,hit.start()-100):hit.start()+300]
        print(f'[{pat}]@{hit.start()}: {repr(ctx[:350])}')
        print()

# Find what happens when setActiveModel is called - is there a plan check?
print('=== setActiveModel / activeModelId checks ===')
for hit in re.finditer(r'setActiveModel\b', content):
    ctx = content[hit.start():hit.start()+300]
    if 'isPaying' in ctx or 'hasPaid' in ctx or 'plan' in ctx.lower()[:100]:
        print(f'@{hit.start()}: {repr(ctx[:250])}')
        print()
