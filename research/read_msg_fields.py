"""read_msg_fields.py — 找 cascade message 的 proto 字段定义"""
import re, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

FIELD_RE = re.compile(r'\{no:(\d+),name:"([^"]+)"(?:,kind:"([^"]*)")?')

# Find message class definitions for cascade request types
msg_types = [
    'StartCascadeRequest',
    'SendUserCascadeMessageRequest',
    'InitializeCascadePanelStateRequest',
    'UpdateWorkspaceTrustRequest',
    'StreamReactiveUpdatesRequest',
    'CascadeConfig',
    'CascadePlannerConfig',
    'Metadata',
]

for msg in msg_types:
    # Find all occurrences
    idx = 0
    found_fields = None
    while True:
        idx = content.find(msg, idx)
        if idx < 0:
            break
        # Look for field definitions in surrounding 3000 chars
        window = content[idx:idx+3000]
        fields = FIELD_RE.findall(window)
        if fields and any(int(f[0]) <= 10 for f in fields):
            found_fields = fields
            break
        idx += len(msg)
    
    if found_fields:
        print(f"=== {msg} ===")
        for no, name, kind in found_fields[:15]:
            print(f"  field {no:3s}: {name}  [{kind}]")
    else:
        # Try searching backwards from first occurrence
        idx = content.find(msg)
        if idx > 0:
            # Look backwards for field list
            back = content[max(0,idx-3000):idx+500]
            fields = FIELD_RE.findall(back)
            if fields:
                print(f"=== {msg} (backwards) ===")
                for no, name, kind in fields[-15:]:
                    print(f"  field {no:3s}: {name}  [{kind}]")
            else:
                print(f"{msg}: NOT FOUND in {content.count(msg)} occurrences")
    print()

# Targeted: find where field no:1 appears with "metadata" name
print("=== Fields named 'metadata' (field 1) ===")
for m in re.finditer(r'\{no:1,name:"metadata"', content):
    ctx = content[max(0,m.start()-200):m.start()+500]
    # Look for class/message name before this
    cls = re.search(r'class\s+(\w+)\s*extends', ctx)
    typname = re.search(r'typeName\s*[=:]\s*"([^"]+)"', ctx)
    print(f"  @ {m.start()}: cls={cls.group(1) if cls else '?'} type={typname.group(1) if typname else '?'}")
    fields = FIELD_RE.findall(ctx)
    for no, name, kind in fields[:10]:
        print(f"    field {no}: {name} [{kind}]")
    print()
