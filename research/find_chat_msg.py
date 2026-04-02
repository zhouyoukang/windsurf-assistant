"""find_chat_msg.py — 找 ChatMessage proto 字段 + extension 实际发送逻辑"""
import re

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# 1. Find ChatMessage proto definition (field 2's type F in RawGetChatMessageRequest)
print("=== ChatMessage proto fields ===")
for m in re.finditer(r'typeName="exa\.chat_pb\.ChatMessage"', content):
    ctx = content[m.start():m.start()+800]
    print(f"@{m.start()}: {repr(ctx[:700])}")
    print()

# 2. Find where rawGetChatMessage is actually CALLED in the extension
print("=== Extension rawGetChatMessage call site ===")
for m in re.finditer(r'rawGetChatMessage\s*\(', content):
    ctx = content[max(0,m.start()-300):m.start()+600]
    print(f"@{m.start()}: {repr(ctx[:800])}")
    print()

# 3. Find the cascade session message type
print("=== Cascade message type with cascade_id ===")
m = re.search(r'no:7,name:"cascade_id"', content)
if m:
    # Get the class definition
    ctx_start = content.rfind('class ', 0, m.start())
    ctx = content[ctx_start: m.start()+300]
    print(f"class context: {repr(ctx[-400:])}")
    # Also get the typeName
    tn = re.search(r'typeName="([^"]+)"', content[m.start()-600:m.start()+100])
    if tn:
        print(f"typeName: {tn.group(1)}")
    print()

# 4. Find Metadata proto fields (what's in the metadata?)
print("=== Metadata proto fields ===")
for m2 in re.finditer(r'typeName="exa\.language_server_pb\.Metadata"', content):
    ctx = content[m2.start():m2.start()+1000]
    fields = re.search(r'newFieldList\(\(\)=>\[(.*?)\]\)', ctx, re.DOTALL)
    if fields:
        print(f"@{m2.start()}: fields = {fields.group(1)[:800]}")
    print()

# 5. Find sendMessage / sendCascadeMessage actual usage
print("=== sendCascadeMessage / send to cascade ===")
for m3 in re.finditer(r'sendUserCascadeMessage|sendMessage.*cascade|cascade.*sendMessage', content, re.I):
    ctx = content[max(0,m3.start()-100):m3.start()+400]
    print(f"@{m3.start()}: {repr(ctx[:400])}")
    print()
    if sum(1 for _ in re.finditer(r'sendUserCascadeMessage|sendMessage.*cascade', content, re.I)) > 5:
        break

# 6. Find what model enum values exist (Model enum)
print("=== Model enum values ===")
for m4 in re.finditer(r'"CLAUDE_OPUS|claude.opus|OPUS', content):
    ctx = content[max(0,m4.start()-50):m4.start()+100]
    print(f"  @{m4.start()}: {repr(ctx)}")
