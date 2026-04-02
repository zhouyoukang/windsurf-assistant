import re, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

FIELD_RE = re.compile(r'\{no:(\d+),name:"([^"]+)"(?:,kind:"([^"]*)")?')

# Find all typeName entries with "ascade" in them
print("=== All cascade typeName entries ===")
for m in re.finditer(r'typeName:"([^"]*[Cc]ascade[^"]*)"', content):
    idx = m.start()
    win = content[max(0,idx-50):idx+2000]
    fields = FIELD_RE.findall(win)
    print(f"\nType: {m.group(1)} @{idx}")
    for no, name, kind in fields[:20]:
        print(f"  field {no}: {name}  [{kind}]")
    if not fields:
        print(f"  [no fields found nearby]")
        print(f"  context: {content[idx:idx+300]}")
