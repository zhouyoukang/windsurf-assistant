"""find_cascade_protos.py — 找 TextOrScopeItem + CascadeConfig + StreamReactiveUpdates + service name"""
import re

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# 1. Find the service typeName for SendUserCascadeMessage
print("=== Service containing SendUserCascadeMessage ===")
m = re.search(r'sendUserCascadeMessage.*?MethodKind', content)
if m:
    # Search backwards for typeName
    search_start = max(0, m.start()-3000)
    tn = re.search(r'typeName="([^"]+)"', content[search_start:m.start()])
    if tn:
        print(f"Service typeName: {tn.group(1)}")
    # Get all methods
    block = content[search_start:m.start()+2000]
    methods = re.findall(r'(\w+):\{name:"([^"]+)"', block)
    print("Methods:")
    for k, n in methods[-20:]:
        print(f"  {k} -> {n}")
print()

# 2. Find TextOrScopeItem proto definition
print("=== TextOrScopeItem proto fields ===")
m2 = re.search(r'typeName="exa\.codeium_common_pb\.TextOrScopeItem"', content)
if m2:
    ctx = content[m2.start():m2.start()+1000]
    fields_m = re.search(r'newFieldList\(\(\)=>\[(.*?)\]\)', ctx, re.DOTALL)
    if fields_m:
        print(f"Fields: {fields_m.group(1)[:800]}")
    else:
        print(f"Context: {repr(ctx[:500])}")
else:
    # Search by class name
    for m3 in re.finditer(r'TextOrScopeItem', content):
        ctx = content[max(0,m3.start()-10):m3.start()+300]
        if 'fields' in ctx or 'newFieldList' in ctx:
            print(f"@{m3.start()}: {repr(ctx[:300])}")
            break
print()

# 3. Find CascadeConfig proto fields
print("=== CascadeConfig proto fields ===")
m4 = re.search(r'typeName="exa\.language_server_pb\.CascadeConfig"', content)
if m4:
    ctx = content[m4.start():m4.start()+800]
    fields_m = re.search(r'newFieldList\(\(\)=>\[(.*?)\]\)', ctx, re.DOTALL)
    if fields_m:
        print(f"Fields: {fields_m.group(1)[:600]}")
else:
    # Search by regex
    for m5 in re.finditer(r'CascadeConfig', content):
        ctx = content[max(0,m5.start()-10):m5.start()+400]
        if 'newFieldList' in ctx:
            print(f"@{m5.start()}: {repr(ctx[:400])}")
            break
print()

# 4. Find StreamReactiveUpdatesRequest
print("=== StreamReactiveUpdatesRequest proto fields ===")
m6 = re.search(r'typeName="exa\..*?StreamReactiveUpdatesRequest"', content)
if m6:
    ctx = content[m6.start():m6.start()+600]
    fields_m = re.search(r'newFieldList\(\(\)=>\[(.*?)\]\)', ctx, re.DOTALL)
    if fields_m:
        print(f"Fields: {fields_m.group(1)[:400]}")
    else:
        print(repr(ctx[:400]))
else:
    for m7 in re.finditer(r'StreamReactiveUpdatesRequest', content):
        ctx = content[max(0,m7.start()-10):m7.start()+400]
        if 'newFieldList' in ctx or 'fields' in ctx:
            print(f"@{m7.start()}: {repr(ctx[:350])}")
            break
print()

# 5. Find SendUserCascadeMessageRequest FULL definition
print("=== SendUserCascadeMessageRequest full fields ===")
m8 = re.search(r'typeName="exa\.language_server_pb\.SendUserCascadeMessageRequest"', content)
if m8:
    ctx = content[m8.start():m8.start()+800]
    fields_m = re.search(r'newFieldList\(\(\)=>\[(.*?)\]\)', ctx, re.DOTALL)
    if fields_m:
        print(f"Fields: {fields_m.group(1)[:700]}")
print()

# 6. Find StartCascadeRequest fields
print("=== StartCascadeRequest fields ===")
m9 = re.search(r'typeName="exa\.language_server_pb\.StartCascadeRequest"', content)
if m9:
    ctx = content[m9.start():m9.start()+600]
    fields_m = re.search(r'newFieldList\(\(\)=>\[(.*?)\]\)', ctx, re.DOTALL)
    if fields_m:
        print(f"Fields: {fields_m.group(1)[:500]}")
print()

# 7. Find cascadeConfig in extension usage
print("=== cascadeConfig usage in extension ===")
for m10 in re.finditer(r'cascadeConfig.*?requestedModelUid|requestedModelUid.*?cascadeConfig', content, re.DOTALL):
    ctx = content[max(0,m10.start()-50):m10.start()+400]
    if len(ctx) < 500:
        print(f"@{m10.start()}: {repr(ctx[:400])}")
        print()
        break
