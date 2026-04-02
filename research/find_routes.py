"""find_routes.py — 从 extension.js 找 setupRoutes 注册的所有路由"""
import re

EXT_JS = r"D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"

with open(EXT_JS, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# 1. 找 setupRoutes 函数
idx = content.find('setupRoutes')
print(f"setupRoutes @{idx}:")
ctx = content[idx:idx+3000]
print(ctx[:2000])
print()

# 2. 找所有 create.*Service.*router patterns (Connect-RPC service creation)
print("--- Connect-RPC service registrations ---")
for pat in [r'create\w*Service\w*', r'createRoute\w*', r'addRoute\w*']:
    hits = re.findall(pat, content)
    if hits:
        print(f"  {pat}: {list(set(hits))[:5]}")

# 3. 找所有 typeName 在 router/service 注册附近
print("\n--- typeNames ---")
type_names = re.findall(r'typeName:\s*["\']([^"\']+)["\']', content)
for t in sorted(set(type_names)):
    print(f"  {t}")

# 4. 找 GetChatMessage 的 proto field definitions
print("\n--- GetChatMessageRequest fields ---")
idx2 = content.find('GetChatMessageRequest')
if idx2 >= 0:
    region = content[idx2:idx2+2000]
    fields = re.findall(r'\{no:(\d+),name:"([^"]+)",kind:"([^"]+)"[^}]*\}', region)
    for no, name, kind in fields[:20]:
        print(f"  field {no}: {name} ({kind})")
