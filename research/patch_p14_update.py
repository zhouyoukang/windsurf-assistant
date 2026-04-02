"""patch_p14_update.py — 更新已存在的 P14 注入，加入 claude-sonnet-4-6"""
import re, shutil

WB = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
with open(WB, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Find the current P14 block (has __mc4 signature)
m = re.search(r'zo=\(0,M\.useMemo\)\(\(\)=>\{const __mc4=Ie\.map\(lpe\);', content)
if not m:
    print("P14 block not found")
    exit(1)

# Find the end of the block: },[Ie])
end_m = re.search(r',\[Ie\]\)', content[m.start():])
if not end_m:
    print("P14 block end not found")
    exit(1)

old_block = content[m.start(): m.start() + end_m.end()]
print(f"Current P14 ({len(old_block)} chars):")
print(repr(old_block[:300]))
print("...")
print()

# Build new P14 block
NEW_BLOCK = (
    'zo=(0,M.useMemo)(()=>{'
    'const __mc4=Ie.map(lpe);'
    "const __injectModels=["
    "{label:'Claude Sonnet 4.6',modelUid:'claude-sonnet-4-6',"
    "displayOption:'standard-picker',disabled:!1,isBeta:!1,isNew:!0,"
    "isRecommended:!0,isCapacityLimited:!1,"
    "modelCost:{type:'credit',multiplier:3,tier:'medium'},"
    "description:'Claude Sonnet 4.6'},"
    "{label:'Claude Opus 4.6',modelUid:'claude-opus-4-6',"
    "displayOption:'standard-picker',disabled:!1,isBeta:!1,isNew:!0,"
    "isRecommended:!1,isCapacityLimited:!1,"
    "modelCost:{type:'credit',multiplier:6,tier:'high'},"
    "description:'Claude Opus 4.6 \u2014 injected'}"
    "];"
    "__injectModels.forEach(function(__im){"
    "if(!__mc4.some(function(__m4){return __m4.modelUid===__im.modelUid;}))"
    "__mc4.push(__im);"
    "});"
    "return __mc4;},[Ie])"
)

print(f"New P14 ({len(NEW_BLOCK)} chars):")
print(repr(NEW_BLOCK[:300]))
print()

shutil.copy2(WB, WB + '.bak_p14update')
content = content[:m.start()] + NEW_BLOCK + content[m.start() + len(old_block):]
with open(WB, 'w', encoding='utf-8') as f:
    f.write(content)
print("P14 updated ✅")

# Verify
with open(WB, 'r', encoding='utf-8', errors='ignore') as f:
    v = f.read()
if 'claude-sonnet-4-6' in v:
    print("✅ claude-sonnet-4-6 confirmed in workbench.js")
if 'claude-opus-4-6' in v:
    print("✅ claude-opus-4-6 confirmed in workbench.js")
