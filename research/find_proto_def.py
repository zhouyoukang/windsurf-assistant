"""find_proto_def.py — 找 RawGetChatMessageRequest 完整 proto 字段定义"""
import re

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# 1. Find RawGetChatMessageRequest proto definition
print("=== RawGetChatMessageRequest proto fields ===")
m = re.search(r'RawGetChatMessageRequest["\'].*?fields\s*=.*?newFieldList\(', content, re.DOTALL)
if not m:
    # Try alternate pattern
    m = re.search(r'typeName.*RawGetChatMessageRequest.*?fields', content, re.DOTALL)
if m:
    ctx = content[m.start():m.start()+2000]
    print(repr(ctx[:1500]))
else:
    print("Not found via typeName, searching for class...")
    for hit in re.finditer(r'RawGetChatMessageRequest', content):
        ctx = content[max(0,hit.start()-30):hit.start()+600]
        if 'fields' in ctx or 'newFieldList' in ctx:
            print(f"@{hit.start()}: {repr(ctx[:500])}")
            print()
            break

print()

# 2. Find fields definition near RawGetChatMessageRequest
print("=== Find newFieldList for RawGetChatMessage ===")
# Look at all RawGetChatMessageRequest class definitions
for m2 in re.finditer(r'class \w+ extends \w+\.\w+\{[^{]*typeName="exa\.chat_pb\.RawGetChatMessageRequest"', content, re.DOTALL):
    ctx = content[m2.start():m2.start()+2000]
    # find fields section
    fields_m = re.search(r'fields=.*?newFieldList\(\(\)=>\[(.*?)\]\)', ctx, re.DOTALL)
    if fields_m:
        print("Fields:")
        print(fields_m.group(1)[:1000])
    else:
        print(f"Context: {repr(ctx[:500])}")

# 3. Search specifically for cascade_id field occurrence near chat_pb
print()
print("=== cascade_id fields in chat_pb context ===")
for m3 in re.finditer(r'cascade_id', content):
    ctx = content[max(0,m3.start()-200):m3.start()+200]
    if 'chat' in ctx.lower() or 'GetChat' in ctx or 'raw' in ctx.lower():
        print(f"@{m3.start()}: {repr(ctx)}")
        print()

# 4. Find the actual cascade_id field number in RawGetChatMessageRequest
print("=== Direct field scan for no:7, cascade_id ===")
for m4 in re.finditer(r'no:\s*7,\s*name:\s*"cascade_id"', content):
    ctx = content[max(0,m4.start()-500):m4.start()+200]
    print(f"@{m4.start()}: {repr(ctx[-400:])}")
    print()

# 5. Find how the extension actually creates RawGetChatMessageRequest
print("=== Extension creates RawGetChatMessageRequest ===")
for m5 in re.finditer(r'new.*?RawGetChatMessageRequest|RawGetChatMessageRequest\s*\(', content):
    ctx = content[max(0,m5.start()-100):m5.start()+500]
    print(f"@{m5.start()}: {repr(ctx[:500])}")
    print()
    if len(list(re.finditer(r'new.*?RawGetChatMessageRequest|RawGetChatMessageRequest\s*\(', content))) > 3:
        break
