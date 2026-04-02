import re

with open(r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

JA_POS = 18338140  # Where [ja,Aa]=useState([]) is
K5T_POS = 18357312

# Find Aa( calls between JA_POS and K5T_POS to see how ja gets populated
chunk = content[JA_POS : K5T_POS + 200]
print('=== Aa( calls (ja setter) ===')
for hit in re.finditer(r'\bAa\(', chunk):
    ctx = chunk[max(0, hit.start()-50) : hit.start()+300]
    print(f'  @{JA_POS+hit.start()}: {repr(ctx[:280])}')
    print()

# Also check: where does ja get set with actual model data?
# Look for Aa(... modelUid ... ) patterns
print('=== Aa with model data ===')
for hit in re.finditer(r'Aa\([^)]{0,200}modelUid', chunk):
    ctx = chunk[max(0,hit.start()-30): hit.start()+400]
    print(f'  @{JA_POS+hit.start()}: {repr(ctx[:350])}')

# Also - look for fetchModelConfigs/modelConfigs event
print()
print('=== Model config events near ja ===')
for pat in ['fetchModelConfigs', 'modelConfigs', 'setModels', r'Aa\(.*map\(']:
    for hit in re.finditer(pat, chunk):
        ctx = chunk[max(0,hit.start()-50):hit.start()+200]
        print(f'  [{pat}] @{JA_POS+hit.start()}: {repr(ctx[:200])}')
