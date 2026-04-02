"""reverse_ext.py — 逆向 extension.js 找 RawGetChatMessage 真实调用路径"""
import re

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

print(f"extension.js size: {len(content)} bytes")
print()

# 1. Find RawGetChatMessage usage
print("=== 1. RawGetChatMessage calls ===")
for m in re.finditer(r'[Rr]aw[Gg]et[Cc]hat[Mm]essage', content):
    ctx = content[max(0,m.start()-150):m.start()+300]
    print(f"@{m.start()}: {repr(ctx[:400])}")
    print()

# 2. Find cascade session / cascadeSession handling
print("=== 2. cascadeSession / cascade_session ===")
for pat in [r'cascadeSession', r'cascade[_-]session', r'cascadeId', r'cascade_id']:
    hits = list(re.finditer(pat, content, re.I))
    if hits:
        print(f"[{pat}]: {len(hits)} hits")
        for h in hits[:3]:
            ctx = content[max(0,h.start()-80):h.start()+200]
            print(f"  @{h.start()}: {repr(ctx[:250])}")
        print()

# 3. Find HTTP headers set for cascade requests
print("=== 3. gRPC metadata headers ===")
for pat in [r'grpc-metadata', r'x-windsurf', r'cascade.*header', r'session.*token',
            r'installation.*id', r'client.*id.*cascade']:
    hits = list(re.finditer(pat, content, re.I))
    if hits:
        print(f"[{pat}]: {len(hits)} hits")
        for h in hits[:2]:
            ctx = content[max(0,h.start()-60):h.start()+200]
            print(f"  @{h.start()}: {repr(ctx[:220])}")
        print()

# 4. Find what token/key is used for cascade API calls
print("=== 4. Authentication in cascade ===")
for pat in [r'Authorization.*cascade|cascade.*Authorization',
            r'Bearer.*cascade|cascade.*Bearer',
            r'apiKey.*cascade|cascade.*apiKey',
            r'getMetadata\(\)', r'getCallCredentials',
            r'withMetadata', r'callMetadata']:
    hits = list(re.finditer(pat, content, re.I))
    if hits:
        print(f"[{pat}]: {len(hits)} hits")
        for h in hits[:2]:
            ctx = content[max(0,h.start()-80):h.start()+200]
            print(f"  @{h.start()}: {repr(ctx[:250])}")
        print()
