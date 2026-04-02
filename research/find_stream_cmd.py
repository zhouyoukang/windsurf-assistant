"""find_stream_cmd.py — 找 StreamReactiveUpdatesRequest.command 值 + 流正确打开方式"""
import re
EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT,'r',encoding='utf-8',errors='ignore') as f: content=f.read()

# 1. StreamReactiveUpdatesRequest full definition
print("=== StreamReactiveUpdatesRequest fields ===")
for m in re.finditer(r'StreamReactiveUpdatesRequest"', content):
    ctx = content[m.start():m.start()+400]
    if 'newFieldList' in ctx:
        fl = re.search(r'newFieldList\(\(\)=>\[(.*?)\]\)', ctx, re.DOTALL)
        if fl: print(f"@{m.start()}: {fl.group(1)[:300]}")
        break
print()

# 2. How extension opens streamCascadeReactiveUpdates
print("=== Extension calls streamCascadeReactiveUpdates ===")
for m2 in re.finditer(r'streamCascadeReactiveUpdates\(', content):
    ctx = content[max(0,m2.start()-100):m2.start()+500]
    print(f"@{m2.start()}: {repr(ctx[:500])}")
    print()

# 3. streamCascadePanelReactiveUpdates usage
print("=== streamCascadePanelReactiveUpdates usage ===")
for m3 in re.finditer(r'streamCascadePanelReactiveUpdates\(', content):
    ctx = content[max(0,m3.start()-50):m3.start()+300]
    print(f"@{m3.start()}: {repr(ctx[:300])}")
    print()
    break

# 4. Find StreamReactiveUpdatesRequest construction
print("=== new.*StreamReactiveUpdatesRequest ===")
for m4 in re.finditer(r'new \w+\.StreamReactiveUpdatesRequest\(', content):
    ctx = content[max(0,m4.start()-50):m4.start()+400]
    print(f"@{m4.start()}: {repr(ctx[:380])}")
    print()
