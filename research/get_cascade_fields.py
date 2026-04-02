import re, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

FIELD_RE = re.compile(r'\{no:(\d+),name:"([^"]+)"(?:,kind:"([^"]*)")?')
TYPE_RE  = re.compile(r'type\s*[=:]\s*"(exa\.[^"]+)"')

targets = [
    'SendUserCascadeMessageRequest',
    'StartCascadeRequest',
    'InitializeCascadePanelStateRequest',
    'UpdateWorkspaceTrustRequest',
    'StreamReactiveUpdatesRequest',
    'CascadePlannerConfig',
    'CascadeConfig',
    'CortexTrajectoryItem',
]
for msg in targets:
    idx = content.find(f'type="exa.language_server_pb.{msg}"')
    if idx < 0:
        idx = content.find(f'typeName:"exa.language_server_pb.{msg}"')
    if idx < 0:
        # try just the class name
        idx = content.find(f'"{msg}"')
    if idx < 0:
        print(f"{msg}: NOT FOUND"); continue
    win = content[max(0,idx-100):idx+2000]
    fields = FIELD_RE.findall(win)
    types  = TYPE_RE.findall(win)
    print(f"=== {msg} @{idx} ===")
    for no, name, kind in fields[:20]:
        print(f"  {no}: {name}  [{kind}]")
    if not fields:
        # dump raw for manual inspection
        print(f"  raw: {content[idx:idx+400]}")
    print()
