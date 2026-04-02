"""deep_grep.py — 精准提取关键代码"""
import re, subprocess

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

print(f"File: {len(content)} bytes\n")

def show(label, pattern, ctx_before=200, ctx_after=400, max_hits=3, flags=0):
    hits = list(re.finditer(pattern, content, flags))
    print(f"=== {label} ({len(hits)} hits) ===")
    for h in hits[:max_hits]:
        ctx = content[max(0,h.start()-ctx_before):h.start()+ctx_after]
        print(f"@{h.start()}: {repr(ctx)}")
        print()

# 1. Metadata class definition
show("Metadata class", r'class \w+ extends \w+\.Message\{[^}]*ideName', ctx_before=0, ctx_after=600)

# 2. MetadataProvider class  
show("MetadataProvider getInstance", r'getInstance\(\)[^}]{0,30}this\._metadata|_metadata.*=.*new.*Metadata', ctx_before=50, ctx_after=400)

# 3. rawGetChatMessage service call
show("rawGetChatMessage in service", r'rawGetChatMessage:\{name', ctx_before=100, ctx_after=200)

# 4. How extension sends messages to RawGetChatMessage
show("Ask/chat mode usage", r'rawGetChatMessage\|rawGetChatMessage\.call\|client\.rawGet', ctx_before=200, ctx_after=500)

# 5. ideName / extensionVersion in Metadata construction
show("ideName field", r'ideName.*Windsurf|Windsurf.*ideName|ideName.*=.*["\']', ctx_before=50, ctx_after=300)

# 6. getApiKey usage
show("getApiKey", r'getApiKey\(\)|apiKey.*=.*get[Aa]pi', ctx_before=50, ctx_after=200, max_hits=5)

# 7. cascade session error - what triggers it on the server
show("cascade session error text", r'Cascade session|cascade.*session.*error', ctx_before=50, ctx_after=200, flags=re.I)

# 8. The LS client interface - what methods it has
show("client.startCascade", r'client\.startCascade', ctx_before=100, ctx_after=400)

# 9. RawGetChatMessageRequest actual construction site
show("RawGetChatMessageRequest construction", r'new \w+\.RawGetChatMessageRequest|RawGetChatMessageRequest\(\{', ctx_before=100, ctx_after=500, max_hits=5)

# 10. What sends a message in chat mode (not cascade)
show("sendChatMessage / getChatMessage usage", r'\.getChatMessage\(|\.rawGetChatMessage\(', ctx_before=300, ctx_after=600, max_hits=3)
