"""find_ls_methods.py — 找 LanguageServerService 完整方法列表 + cascade send 方法"""
import re

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# 1. Find LanguageServerService method list
print("=== LanguageServerService methods ===")
m = re.search(r'LanguageServerService.*?methods\s*=\s*\{(.*?)\}', content, re.DOTALL)
if not m:
    # Try finding via typeName
    m = re.search(r'typeName="exa\.language_server_pb\.LanguageServerService".*?(\{[^}]{200,})', content, re.DOTALL)
if m:
    print(m.group(0)[:3000])
else:
    # Find all method names: {name:"MethodName", I:..., O:..., kind:MethodKind}
    for hit in re.finditer(r'\{name:"(\w+)",I:\w+,O:\w+,kind:\w+\.MethodKind\.\w+\}', content):
        ctx = content[max(0,hit.start()-100):hit.start()+200]
        print(f"  {hit.group(1)}: {repr(ctx[:200])}")

print()

# 2. Find cascade-specific methods
print("=== Cascade-related methods ===")
for pat in ['[Ss]endUserCascade', '[Ss]endCascade', '[Ss]treamCascade', 
            '[Cc]ascade.*[Mm]essage', '[Mm]essage.*[Cc]ascade',
            'GetCascade', 'UpdateCascade', 'AddCascade']:
    for m2 in re.finditer(pat, content):
        ctx = content[max(0,m2.start()-50):m2.start()+200]
        if 'name:' in ctx or 'method' in ctx.lower() or 'Service' in ctx:
            print(f"  [{pat}] @{m2.start()}: {repr(ctx[:200])}")
            break

print()

# 3. Find all method names with "Cascade" in them in the service definition
print("=== All method defs with 'Cascade' ===")
for m3 in re.finditer(r'name:"(\w*[Cc]ascade\w*)"', content):
    ctx = content[max(0,m3.start()-30):m3.start()+150]
    if 'I:' in ctx or 'kind:' in ctx:
        print(f"  @{m3.start()}: {repr(ctx[:150])}")

print()

# 4. Find the RawGetChatMessage service definition context
print("=== Service block containing RawGetChatMessage ===")
m4 = re.search(r'rawGetChatMessage.*?MethodKind', content)
if m4:
    # Find the start of this service object
    start = content.rfind('{', 0, m4.start())
    # Find the outer service object (go back to find the service definition)
    service_start = max(0, m4.start()-5000)
    service_block = content[service_start:m4.start()+500]
    # Extract all method names
    methods = re.findall(r'(\w+):\{name:"(\w+)"', service_block)
    print("Methods found in block:")
    for key, name in methods:
        print(f"  {key} -> {name}")
