"""find_cascade_service.py — 找 StartCascade 所在的 service + 所有 cascade 方法"""
import re

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# 1. Find the service block containing startCascade
print("=== Service block containing startCascade ===")
m = re.search(r'startCascade.*?MethodKind', content)
if m:
    service_start = max(0, m.start()-5000)
    block = content[service_start:m.start()+500]
    methods = re.findall(r'(\w+):\{name:"(\w+)"', block)
    print("All methods in this service block:")
    for key, name in methods:
        print(f"  {key} -> {name}")
    
    # Find the typeName
    tn = re.search(r'typeName="([^"]+)"', content[service_start:m.start()+200])
    if tn:
        print(f"\nService typeName: {tn.group(1)}")
else:
    print("startCascade not found as method definition")

print()

# 2. Find all MethodKind definitions (all methods across all services)
print("=== ALL service method definitions ===")
for m2 in re.finditer(r'(\w+):\{name:"([^"]+)",I:(\w+),O:(\w+),kind:(\w+)\.MethodKind\.(\w+)\}', content):
    method_key = m2.group(1)
    method_name = m2.group(2)
    kind = m2.group(6)
    if any(x in method_name.lower() for x in ['cascade', 'chat', 'message', 'send', 'stream', 'start']):
        ctx = content[max(0,m2.start()-100):m2.start()+50]
        service_m = re.search(r'typeName="([^"]+)"', content[max(0,m2.start()-3000):m2.start()])
        service = service_m.group(1) if service_m else '?'
        print(f"  [{service}] {method_key} -> {method_name} ({kind})")

print()

# 3. Find sendUserCascadeMessage specifically
print("=== sendUserCascadeMessage location ===")
for m3 in re.finditer(r'sendUserCascadeMessage|SendUserCascadeMessage', content):
    ctx = content[max(0,m3.start()-100):m3.start()+300]
    print(f"@{m3.start()}: {repr(ctx[:350])}")
    print()

# 4. Find StreamCascadeReactiveUpdates
print("=== StreamCascadeReactiveUpdates ===")
for m4 in re.finditer(r'[Ss]tream[Cc]ascade[Rr]eactive', content):
    ctx = content[max(0,m4.start()-100):m4.start()+300]
    print(f"@{m4.start()}: {repr(ctx[:350])}")
    print()
