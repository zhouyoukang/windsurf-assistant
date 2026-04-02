"""find_proto_fields.py — 从 extension.js 提取完整 proto 字段定义"""
import re
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

EXT_JS = r"D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
with open(EXT_JS, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

print(f"File size: {len(content)//1024}KB\n")

# Find field blocks: [{no:N,name:"fieldname",...},...]
# Look for cascade-related message field lists
targets = [
    'SendUserCascadeMessage',
    'StartCascade',
    'InitializeCascadePanelState',
    'UpdateWorkspaceTrust',
    'StreamCascadeReactiveUpdates',
    'CascadeConfig',
    'PlannerConfig',
]

for target in targets:
    idx = content.find(f'"{target}"')
    if idx < 0:
        idx = content.find(target)
    if idx < 0:
        print(f"{target}: NOT FOUND"); continue
    # scan forward for field list pattern [{no:
    block = content[idx:idx+3000]
    fields = re.findall(r'\{no:(\d+),name:"([^"]+)"', block)
    if fields:
        print(f"{target}:")
        for no, name in fields[:15]:
            print(f"  field {no}: {name}")
    else:
        # Try typeName context
        tn = re.search(r'typeName:"([^"]+)"', block)
        print(f"{target}: found at {idx}, typeName={tn.group(1) if tn else 'N/A'}")
    print()

def extract_fields_near(keyword, context=4000):
    idx = content.find(keyword)
    if idx < 0:
        return f"[{keyword} NOT FOUND]"
    region = content[idx:idx+context]
    # Extract field definitions: {no:N,name:"xxx",kind:"yyy",...}
    fields = re.findall(r'\{no:(\d+),name:"([^"]+)",kind:"([^"]+)"[^}]*\}', region)
    return fields

print("=== GetChatMessageRequest fields ===")
for f in extract_fields_near('GetChatMessageRequest'):
    print(f"  field {f[0]}: {f[1]} ({f[2]})")

print("\n=== ChatMessage fields ===")
for f in extract_fields_near('"ChatMessage"'):
    print(f"  field {f[0]}: {f[1]} ({f[2]})")

print("\n=== ChatMessagePrompt fields ===")
for f in extract_fields_near('ChatMessagePrompt'):
    print(f"  field {f[0]}: {f[1]} ({f[2]})")

# Also look for the full service definition
print("\n=== LanguageServerService methods ===")
idx = content.find('LanguageServerService')
while idx >= 0 and idx < len(content) - 1:
    ctx = content[idx:idx+200]
    if 'methods' in ctx or 'GetChatMessage' in ctx or 'typeName' in ctx:
        # Find the service descriptor block
        print(f"  @{idx}: {ctx[:150]}")
    idx = content.find('LanguageServerService', idx+1)
    if idx > 10_000_000: break  # safety

print("\n=== Full GetChatMessage definition (first 3000 chars) ===")
idx = content.find('GetChatMessageRequest')
if idx >= 0:
    print(content[idx:idx+3000])
