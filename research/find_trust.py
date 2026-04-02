"""find_trust.py — 找 UpdateWorkspaceTrust proto + AddTrackedWorkspace"""
import re
EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT,'r',encoding='utf-8',errors='ignore') as f: content = f.read()

for name in ['UpdateWorkspaceTrust','AddTrackedWorkspace','WorkspaceTrust','InitializeCascadePanelState']:
    m = re.search(f'typeName="exa\\.language_server_pb\\.{name}Request"', content)
    if m:
        ctx = content[m.start():m.start()+600]
        fl = re.search(r'newFieldList\(\(\)=>\[(.*?)\]\)', ctx, re.DOTALL)
        print(f"=== {name}Request ===")
        if fl: print(f"Fields: {fl.group(1)[:400]}")
        else: print(repr(ctx[:300]))
        print()
