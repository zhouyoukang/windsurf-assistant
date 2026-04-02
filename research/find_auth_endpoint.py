import re, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

AUTH_JS = r'C:\Users\Administrator\.windsurf\extensions\zhouyoukang.windsurf-assistant-3.19.0\src\authService.js'
with open(AUTH_JS, 'r', encoding='utf-8', errors='replace') as f:
    txt = f.read()

print("=== URLs ===")
seen = set()
for u in re.findall(r'https?://[^\s\"\'\`\)]{5,120}', txt):
    if u not in seen:
        seen.add(u)
        print(u)

print()
print("=== fetch/post calls ===")
for m in re.finditer(r'(?:fetch|\.post)\s*\([^;]{10,300}', txt, re.I):
    print(m.group()[:300])
    print()

print()
print("=== API key patterns ===")
for kw in ['apiKey', 'api_key', 'getKey', 'exchangeToken', 'signInWithCustomToken', 'createApiKey']:
    idx = txt.find(kw)
    if idx >= 0:
        print(f"== {kw} @ {idx} ==")
        print(txt[max(0,idx-100):idx+300])
        print()
