"""
Extract cascade proto field numbers from extension.js
Strategy: search for all {no:N,name:"fieldname"} blocks, group by proximity,
then identify cascade message blocks by their field names.
"""
import re, io, sys, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Find ALL field definition blocks: {no:N,name:"xxx",kind:"yyy",...}
FIELD_RE = re.compile(r'\{no:(\d+),name:"([^"]+)",kind:"([^"]+)"[^}]*\}')

# Collect all fields with their positions
all_fields = []
for m in FIELD_RE.finditer(content):
    all_fields.append({
        'pos': m.start(),
        'no': int(m.group(1)),
        'name': m.group(2),
        'kind': m.group(3),
        'raw': m.group(0)
    })

print(f"Total field definitions found: {len(all_fields)}")

# Group fields into messages: fields within 2000 chars of each other
messages = []
current_group = []
for i, f in enumerate(all_fields):
    if not current_group:
        current_group = [f]
    elif f['pos'] - current_group[-1]['pos'] < 2000:
        current_group.append(f)
    else:
        messages.append(current_group)
        current_group = [f]
if current_group:
    messages.append(current_group)

print(f"Message groups: {len(messages)}\n")

# Find cascade-related messages by field names
cascade_keywords = {'cascade_id', 'cascade_config', 'workspace_trusted', 'source',
                    'protocol_version', 'requested_model_uid', 'planner_type_config',
                    'cortex_trajectory', 'cascade', 'items', 'text_or_scope'}

interesting = []
for group in messages:
    names = {f['name'] for f in group}
    if names & cascade_keywords or any('cascade' in n.lower() for n in names):
        interesting.append(group)

print(f"Cascade-related message groups: {len(interesting)}\n")

for group in interesting:
    names = [f['name'] for f in group]
    print(f"--- Group @ pos {group[0]['pos']} ({len(group)} fields) ---")
    # Find typeName nearby
    pos = group[0]['pos']
    ctx = content[max(0,pos-300):pos+300]
    tn_match = re.search(r'typeName:"([^"]+)"', ctx)
    if tn_match:
        print(f"  typeName: {tn_match.group(1)}")
    for f in group:
        print(f"  field {f['no']:3d}: {f['name']}  [{f['kind']}]")
    print()

# Also specifically search for key field names with context
print("\n=== Key field searches ===")
for field_name in ['workspace_trusted', 'source', 'cascade_id', 'protocol_version',
                   'requested_model_uid', 'workspace_uri']:
    idx = content.find(f'"name":"{field_name}"')
    if idx < 0:
        idx = content.find(f'name:"{field_name}"')
    if idx >= 0:
        ctx = content[max(0,idx-200):idx+400]
        tn = re.search(r'typeName:"([^"]+)"', ctx)
        fields = FIELD_RE.findall(ctx)
        print(f"\n'{field_name}' @ {idx}:")
        if tn: print(f"  type: {tn.group(1)}")
        for no, name, kind in fields[:10]:
            marker = ' <<<<' if name == field_name else ''
            print(f"  field {no}: {name} [{kind}]{marker}")
    else:
        print(f"'{field_name}': NOT FOUND")
