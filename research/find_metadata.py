"""find_metadata.py — 找 MetadataProvider.getMetadata 完整实现 + ChatMessage intent/request 字段"""
import re

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# 1. Find MetadataProvider.getMetadata implementation
print("=== MetadataProvider.getMetadata ===")
for m in re.finditer(r'getMetadata\s*\(\s*\)\s*\{', content):
    ctx = content[m.start():m.start()+600]
    print(f"@{m.start()}: {repr(ctx[:500])}")
    print()

# 2. Find Metadata proto fields
print("=== Metadata proto fields (language_server_pb.Metadata) ===")
for m2 in re.finditer(r'typeName="exa\.language_server_pb\.Metadata"', content):
    ctx = content[m2.start():m2.start()+1500]
    fields = re.search(r'newFieldList\(\(\)=>\[(.*?)\]\)', ctx, re.DOTALL)
    if fields:
        print(f"Metadata fields: {fields.group(1)[:1000]}")
    print()

# 3. Find ChatMessage.intent / request sub-message fields
print("=== ChatMessage.intent / request fields ===")
for pat in ['typeName="exa.chat_pb.ChatIntent"', 'typeName="exa.chat_pb.ChatRequest"',
            'typeName="exa.chat_pb.UserChatMessage"']:
    m3 = re.search(pat, content)
    if m3:
        ctx = content[m3.start():m3.start()+600]
        print(f"[{pat}]: {repr(ctx[:500])}")
        print()

# 4. Find what ChatMessageSource enum values are
print("=== ChatMessageSource enum ===")
for m4 in re.finditer(r'ChatMessageSource', content):
    ctx = content[max(0,m4.start()-30):m4.start()+200]
    if 'USER' in ctx or 'UNSPECIFIED' in ctx or '=' in ctx:
        print(f"@{m4.start()}: {repr(ctx[:200])}")
        break

# 5. The crucial part: find exactly what the extension sends for a user message
print("=== Extension user message construction ===")
for pat in [r'source.*ChatMessageSource\.USER', r'ChatMessageSource\.USER',
            r'intent.*userInput\|userInput.*intent',
            r'new.*ChatMessage\(', r'ChatMessage\(\{']:
    hits = list(re.finditer(pat, content, re.I))
    if hits:
        print(f"[{pat}]: {len(hits)} hits")
        for h in hits[:2]:
            ctx = content[max(0,h.start()-100):h.start()+400]
            print(f"  @{h.start()}: {repr(ctx[:400])}")
        print()

# 6. Find actual rawGetChatMessage call
print("=== rawGetChatMessage actual usage ===")
for m5 in re.finditer(r'\.rawGetChatMessage\(', content):
    ctx = content[max(0,m5.start()-400):m5.start()+600]
    print(f"@{m5.start()}: {repr(ctx[:800])}")
    print()
