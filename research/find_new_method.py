import re

EXT_JS = r"D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
with open(EXT_JS, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Search for cascade/chat related method names
print("=== Chat/Cascade methods near 'chat' ===")
for m in re.finditer(r'["\']([A-Z][a-zA-Z]*(?:Chat|Message|Cascade|Convers)[a-zA-Z]*)["\']', content):
    val = m.group(1)
    if len(val) > 5:
        ctx = content[max(0, m.start()-50):m.start()+80]
        print(f"  {val}: {ctx[:100]}")

print("\n=== Service method definitions ===")
# Find all method definitions in service objects
for m in re.finditer(r'method\s*:\s*["\']([A-Z][a-zA-Z]+)["\']', content):
    print(f"  {m.group(1)}")

print("\n=== All string literals with 'Chat' or 'Stream' ===")
hits = list(set(re.findall(r'["\']([A-Za-z]*(?:Chat|Stream|Message|Convers)[A-Za-z]+)["\']', content)))
hits.sort()
for h in hits[:30]:
    print(f"  {h}")

print("\n=== Methods on LanguageServerService ===")
idx = content.find('LanguageServerService')
while idx >= 0 and idx < len(content) - 200:
    region = content[idx:idx+300]
    if 'method' in region.lower() or 'Chat' in region or 'Stream' in region:
        print(f"  @{idx}: {region[:200]}")
    idx = content.find('LanguageServerService', idx + 1)
    if idx > 15_000_000: break
