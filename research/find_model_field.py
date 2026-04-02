"""find_model_field.py — 找 CascadeConfig 完整字段 + PlanModel/RequestedModel 字段位置"""
import re

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# 1. Find full CascadeConfig newFieldList (no truncation)
print("=== CascadeConfig FULL field list ===")
m = re.search(r'typeName="exa\.cortex_pb\.CascadeConfig"', content)
if m:
    # Find the newFieldList start
    fl_start = content.find('newFieldList', m.start())
    # Find the closing ]
    depth = 0; pos = fl_start; start_bracket = None
    while pos < len(content):
        if content[pos] == '[':
            if start_bracket is None: start_bracket = pos
            depth += 1
        elif content[pos] == ']':
            depth -= 1
            if depth == 0:
                print(content[start_bracket:pos+1][:3000])
                break
        pos += 1
print()

# 2. Find requested_model_uid in CascadeConfig context (at offset ~8960079)
print("=== requested_model_uid field search (full context) ===")
m2 = re.search(r'typeName="exa\.cortex_pb\.CascadeConfig"', content)
if m2:
    # Get 5000 chars of CascadeConfig definition
    block = content[m2.start():m2.start()+5000]
    # Find all field definitions in this block
    fields = re.findall(r'\{no:(\d+),name:"([^"]+)"', block)
    print("All fields:")
    for no, name in sorted(fields, key=lambda x: int(x[0])):
        print(f"  no:{no} = {name}")
print()

# 3. Find plannerConfig's type and its requestedModelUid
print("=== CortexPlannerConfig fields (planner_config type) ===")
# From CascadeConfig: planner_config type is 'pt'
# Find pt's typeName - look for what 'pt' resolves to near CascadeConfig
m3 = re.search(r'typeName="exa\.cortex_pb\.CascadeConfig"', content)
if m3:
    before = content[max(0,m3.start()-2000):m3.start()]
    # Find class definitions (pt = ...)
    class_defs = re.findall(r'class (\w+) extends \w+\.Message\{', before[-1000:])
    print(f"Classes defined before CascadeConfig: {class_defs[-5:]}")
    
# Find CortexPlannerConfig or PlannerConfig
for name in ['CortexPlannerConfig', 'CascadePlannerConfig', 'PlannerConfig']:
    m4 = re.search(f'typeName="exa\\.cortex_pb\\.{name}"', content)
    if m4:
        block4 = content[m4.start():m4.start()+2000]
        fields4 = re.findall(r'\{no:(\d+),name:"([^"]+)"', block4)
        print(f"\n{name} fields:")
        for no, name_f in sorted(fields4, key=lambda x: int(x[0]))[:20]:
            print(f"  no:{no} = {name_f}")
        break

# 4. Try all proto types containing 'requested_model_uid'
print()
print("=== All messages with requested_model_uid ===")
for m5 in re.finditer(r'name:"requested_model_uid"', content):
    # Find nearby typeName
    back = content[max(0,m5.start()-2000):m5.start()]
    tn = re.findall(r'typeName="([^"]+)"', back)
    if tn:
        print(f"  @{m5.start()}: typeName={tn[-1]}")
        # Also show surrounding fields
        ctx = content[max(0,m5.start()-200):m5.start()+200]
        fields_nearby = re.findall(r'\{no:(\d+),name:"([^"]+)"', ctx)
        for no, fn in fields_nearby:
            print(f"    no:{no} = {fn}")
    print()
