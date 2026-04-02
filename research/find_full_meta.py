"""find_full_meta.py — 找完整 Metadata + ChatIntent + ChatMessageSource + 构建正确 proto"""
import re

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# 1. Find the Metadata newFieldList that contains BOTH extension_version AND url
print("=== Full Metadata definition (has extension_version AND url) ===")
# Find the block that has auth_source (field 15)
m = re.search(r'auth_source', content)
if m:
    # Walk backwards to find the start of the newFieldList
    start = content.rfind('newFieldList', 0, m.start())
    end_m = re.search(r'\]\)', content[start:])
    if end_m:
        block = content[start: start + end_m.end()]
        print(f"Full block: {block[:2000]}")
    print()
    
    # Also show a broader context
    ctx = content[max(0,m.start()-800):m.start()+500]
    print(f"Context around auth_source: {repr(ctx[:1200])}")

print()

# 2. Find ChatIntent fields
print("=== ChatIntent proto definition ===")
# Look for user_input field in intent context
for m2 in re.finditer(r'typeName="exa\.chat_pb\.(ChatIntent|Intent|UserChatContent)"', content):
    ctx = content[m2.start():m2.start()+600]
    print(f"@{m2.start()}: {repr(ctx[:500])}")
    print()

# Also try a direct approach - find fields near ChatIntent
for m3 in re.finditer(r'ChatIntent[^=]*=.*?Message', content):
    ctx = content[max(0,m3.start()-20):m3.start()+600]
    if 'fields' in ctx or 'newFieldList' in ctx:
        print(f"@{m3.start()}: {repr(ctx[:500])}")
        print()
        break

print()

# 3. Find ChatMessageSource enum with USER value
print("=== ChatMessageSource USER enum value ===")
# Search in the compiled enum object
for m4 in re.finditer(r'ChatMessageSource\b', content):
    ctx = content[max(0,m4.start()-10):m4.start()+400]
    if 'USER' in ctx or 'HUMAN' in ctx or '[1]' in ctx:
        print(f"@{m4.start()}: {repr(ctx[:380])}")
        print()
        break
        
# Also find the numeric enum values
for m5 in re.finditer(r'A\[A\.CHAT_MESSAGE_SOURCE_USER\s*=\s*(\d+)\]', content):
    print(f"CHAT_MESSAGE_SOURCE_USER = {m5.group(1)}")

# 4. Find ChatMessageSource enum definition
print("=== ChatMessageSource enum ===")
m6 = re.search(r'CHAT_MESSAGE_SOURCE.*?UNSPECIFIED.*?USER|CHAT_MESSAGE_SOURCE_USER', content)
if m6:
    ctx = content[max(0,m6.start()-50):m6.start()+300]
    print(f"@{m6.start()}: {repr(ctx[:300])}")

# 5. Look for ideName / ide_name in the language_server_pb Metadata
print()
print("=== ide_name/ideName in Metadata ===")
for m7 in re.finditer(r'ide_name|ideName', content):
    ctx = content[max(0,m7.start()-100):m7.start()+200]
    if 'no:' in ctx or 'field' in ctx.lower() or 'metadata' in ctx.lower():
        print(f"@{m7.start()}: {repr(ctx[:260])}")
        print()

# 6. Find getMetadata function
print("=== getMetadata function ===")
for m8 in re.finditer(r'getMetadata\(\)', content):
    ctx = content[max(0,m8.start()-20):m8.start()+400]
    if 'return' in ctx or 'new' in ctx:
        print(f"@{m8.start()}: {repr(ctx[:380])}")
        print()
        break
