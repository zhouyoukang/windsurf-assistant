"""find_cascade_config.py — 找 CascadeConfig.requestedModelUid 字段号 + service URL"""
import re

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# 1. Find requestedModelUid in CascadeConfig
print("=== CascadeConfig full fields ===")
m = re.search(r'cortex_pb\.CascadeConfig.*?newFieldList\(\(\)=>\[(.*?)\]\)', content, re.DOTALL)
if not m:
    m = re.search(r'typeName="exa\.cortex_pb\.CascadeConfig"', content)
if m:
    ctx = content[m.start():m.start()+2000]
    fl = re.search(r'newFieldList\(\(\)=>\[(.*?)\]\)', ctx, re.DOTALL)
    if fl:
        print(f"Fields: {fl.group(1)[:1500]}")
    else:
        print(repr(ctx[:1000]))

# Direct search for requestedModelUid
print("\n=== requestedModelUid field number ===")
for m2 in re.finditer(r'requested_model_uid|requestedModelUid', content):
    ctx = content[max(0,m2.start()-100):m2.start()+200]
    if 'no:' in ctx or 'kind' in ctx:
        print(f"@{m2.start()}: {repr(ctx[:250])}")
        print()

# 2. Find the service typeName containing sendUserCascadeMessage
print("=== Service typeName at offset ~2097058 ===")
target = content.find('sendUserCascadeMessage:{name:"SendUserCascadeMessage"')
if target > 0:
    # Search backwards for typeName
    search_block = content[max(0,target-5000):target]
    tn_matches = list(re.finditer(r'typeName="([^"]+)"', search_block))
    if tn_matches:
        print(f"Last typeName before sendUserCascadeMessage: {tn_matches[-1].group(1)}")
    
    # Also find all methods in this service
    methods = re.findall(r'(\w+):\{name:"([^"]+)",I:\w+', search_block[-3000:])
    print("Methods in this service:")
    for k, n in methods:
        print(f"  {k} -> {n}")

print()

# 3. Find StreamCascadeReactiveUpdates service typeName
print("=== StreamCascadeReactiveUpdates service ===")
target2 = content.find('streamCascadeReactiveUpdates:{name:"StreamCascadeReactiveUpdates"')
if target2 > 0:
    search_block2 = content[max(0,target2-3000):target2]
    tn2 = list(re.finditer(r'typeName="([^"]+)"', search_block2))
    if tn2:
        print(f"Service typeName: {tn2[-1].group(1)}")
    methods2 = re.findall(r'(\w+):\{name:"([^"]+)",I:\w+', search_block2[-2000:])
    print("Methods:")
    for k, n in methods2[-10:]:
        print(f"  {k} -> {n}")
    # Also look ahead
    ahead = content[target2:target2+500]
    methods3 = re.findall(r'(\w+):\{name:"([^"]+)",I:\w+', ahead)
    for k, n in methods3[:10]:
        print(f"  {k} -> {n}")

print()

# 4. Find StartCascadeRequest fields
print("=== StartCascadeRequest fields ===")
for m3 in re.finditer(r'StartCascadeRequest', content):
    ctx = content[max(0,m3.start()-10):m3.start()+400]
    if 'newFieldList' in ctx or 'fields' in ctx:
        print(f"@{m3.start()}: {repr(ctx[:380])}")
        break

# 5. CascadeConfig requestedModelUid - search broader
print()
print("=== CascadeConfig with requestedModelUid ===")
m4 = re.search(r'requestedModelUid', content)
while m4:
    ctx = content[max(0,m4.start()-80):m4.start()+200]
    if 'no:' in ctx:
        print(f"@{m4.start()}: {repr(ctx[:240])}")
        print()
    next_start = m4.end()
    m4 = re.search(r'requestedModelUid', content[next_start:])
    if m4:
        m4 = type('', (), {'start': lambda s=next_start+m4.start(): s, 'end': lambda s=next_start+m4.end(): s, 'group': m4.group})()
    # Safety: check all occurrences differently
    break

# Find all requestedModelUid occurrences
for m5 in re.finditer(r'requested_model_uid', content):
    ctx = content[max(0,m5.start()-80):m5.start()+200]
    print(f"@{m5.start()}: {repr(ctx[:230])}")
    print()
