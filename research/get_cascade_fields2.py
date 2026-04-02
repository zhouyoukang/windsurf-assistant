"""Find cascade request message field numbers from extension.js"""
import re, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

FIELD_RE = re.compile(r'\{no:(\d+),name:"([^"]+)",kind:"([^"]+)"[^}]*\}')

def find_msg_with_fields(required_fields, window=3000):
    """Find message blocks containing all required field names"""
    # Find positions of the first required field
    first = required_fields[0]
    results = []
    for m in re.finditer(f'name:"{first}"', content):
        pos = m.start()
        ctx = content[max(0, pos-500): pos+window]
        fields = FIELD_RE.findall(ctx)
        found_names = {f[1] for f in fields}
        if all(req in found_names for req in required_fields):
            results.append((pos, fields))
    return results

# Find StartCascadeRequest: metadata + source
print("=== StartCascadeRequest (metadata + source) ===")
for pos, fields in find_msg_with_fields(['metadata', 'source'])[:3]:
    print(f"  @ {pos}")
    for no, name, kind in fields[:15]:
        print(f"    field {no}: {name} [{kind}]")
    print()

# Find SendUserCascadeMessageRequest: metadata + cascade_id + items
print("=== SendUserCascadeMessageRequest (metadata + cascade_id + items) ===")
for pos, fields in find_msg_with_fields(['metadata', 'cascade_id', 'items'])[:3]:
    print(f"  @ {pos}")
    for no, name, kind in fields[:15]:
        print(f"    field {no}: {name} [{kind}]")
    print()

# Find SendUserCascadeMessageRequest: metadata + cascade_id + cascade_config
print("=== SendUserCascadeMessageRequest (metadata + cascade_id + cascade_config) ===")
for pos, fields in find_msg_with_fields(['metadata', 'cascade_id', 'cascade_config'])[:3]:
    print(f"  @ {pos}")
    for no, name, kind in fields[:15]:
        print(f"    field {no}: {name} [{kind}]")
    print()

# Find CascadeConfig / CascadePlannerConfig
print("=== CascadeConfig (planner_config field) ===")
for m in re.finditer(r'name:"planner_config"', content):
    pos = m.start()
    ctx = content[max(0,pos-200):pos+1000]
    fields = FIELD_RE.findall(ctx)
    if fields:
        print(f"  @ {pos}")
        for no, name, kind in fields[:10]:
            print(f"    field {no}: {name} [{kind}]")
        print()

# Find CascadePlannerConfig (requested_model_uid field)
print("=== CascadePlannerConfig (requested_model_uid) ===")
for m in re.finditer(r'name:"requested_model_uid"', content):
    pos = m.start()
    ctx = content[max(0,pos-300):pos+1000]
    fields = FIELD_RE.findall(ctx)
    if fields:
        print(f"  @ {pos}")
        for no, name, kind in fields[:15]:
            print(f"    field {no}: {name} [{kind}]")
        print()

# Find text item (items in SendUserCascadeMessage contain text)
print("=== TextItem / text field in items ===")
for m in re.finditer(r'\{no:(\d+),name:"text",kind:"scalar"', content):
    pos = m.start()
    ctx = content[max(0,pos-100):pos+300]
    fields = FIELD_RE.findall(ctx)
    # Only show short, isolated text fields (likely TextItem)
    if len(fields) <= 5:
        print(f"  @ {pos}: fields={[(f[0],f[1]) for f in fields]}")
