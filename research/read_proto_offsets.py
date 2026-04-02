"""read_proto_offsets.py — 直接读 extension.js 已知偏移处的 proto 定义"""
import re, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT, 'rb') as f:
    raw = f.read()
content = raw.decode('utf-8', errors='replace')

# 已知关键字偏移（从上次搜索结果）
offsets = {
    'StartCascade':               2096505,
    'SendUserCascadeMessage':     2097087,
    'InitializeCascadePanelState':2099788,
    'UpdateWorkspaceTrust':       2100129,
    'StreamCascadeReactiveUpdates':2100775,
    'CascadeConfig':              1087343,
}

# 在每个偏移附近找 {no:N,name:"xxx"} 和 typeName:"xxx" 模式
FIELD_RE  = re.compile(r'\{no:(\d+),name:"([^"]+)"(?:,kind:"([^"]*)")?')
TNAME_RE  = re.compile(r'typeName:"([^"]+)"')
MSG_RE    = re.compile(r'messageName:"([^"]+)"')

for label, off in offsets.items():
    # 扫 offset 前 200 字节到 offset 后 4000 字节
    window = content[max(0, off-200): off+4000]
    fields = FIELD_RE.findall(window)
    typenames = TNAME_RE.findall(window)
    msgnames  = MSG_RE.findall(window)
    print(f"=== {label} (offset {off}) ===")
    print(f"  typeNames: {typenames[:5]}")
    print(f"  msgNames:  {msgnames[:5]}")
    for no, name, kind in fields[:20]:
        print(f"  field {no:3s}: {name}  [{kind}]")
    # Also dump raw 500 chars around offset for manual inspection
    raw_ctx = content[off:off+500].replace('\n',' ')
    print(f"  raw: {raw_ctx[:300]}")
    print()

# 额外：找所有 cascade 相关 typeName
print("=== All cascade typeNames ===")
for m in re.finditer(r'typeName:"([^"]*[Cc]ascade[^"]*)"', content):
    print(f"  {m.group(1)} @ {m.start()}")
