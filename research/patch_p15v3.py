"""P15v3: direct exact-string replacement of broken K5t"""
import re, shutil

PATH = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'

with open(PATH, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Find K5t and extract the EXACT current text to replace
m = re.search(r'K5t=\(0,M\.useCallback\)', content)
if not m:
    print("K5t not found"); exit(1)

# Get the full function (from K5t= to the closing ,[ja,XZ]))
# The function ends with },[ja,XZ]) or },[ja,XZ])
end_pat = re.search(r',\[ja,XZ\]\)', content[m.start():])
if not end_pat:
    print("End pattern not found"); exit(1)

full_k5t = content[m.start(): m.start() + end_pat.end()]
print(f"Found K5t ({len(full_k5t)} chars):")
print(repr(full_k5t[:200]))
print("...")
print(repr(full_k5t[-100:]))
print()

# Build the correct replacement
FALLBACK = (
    "(['claude-opus-4-6','claude-sonnet-4-6','claude-sonnet-4-5',"
    "'gpt-5-2','gpt-4-1','o4-mini'].includes(Oa)"
    "?{label:Oa==='claude-opus-4-6'?'Claude Opus 4.6'"
    ":Oa==='claude-sonnet-4-6'?'Claude Sonnet 4.6'"
    ":Oa==='claude-sonnet-4-5'?'Claude Sonnet 4.5'"
    ":Oa==='gpt-5-2'?'GPT-5.2':Oa==='gpt-4-1'?'GPT-4.1':'o4-mini',"
    "modelUid:Oa,disabled:!1,isBeta:!1,isNew:!0,"
    "modelCost:{type:'credit',"
    "multiplier:Oa==='claude-opus-4-6'?6:3,"
    "tier:Oa==='claude-opus-4-6'?'high':'medium'},"
    "supportsImages:!1}:null)"
)

NEW_K5T = (
    "K5t=(0,M.useCallback)((Oa,vo)=>{"
    "const Al=ja.find(F0=>F0.modelUid===Oa)||" + FALLBACK + ";"
    "if(!Al)return void console.error(`[Model Select] Invalid model UID: ${Oa}`);"
    "const t0={...Al,smartFriendModelUid:vo};XZ(t0)"
    "},[ja,XZ])"
)

shutil.copy2(PATH, PATH + '.bak_p15v3')
content = content[:m.start()] + NEW_K5T + content[m.start() + len(full_k5t):]
with open(PATH, 'w', encoding='utf-8') as f:
    f.write(content)
print("P15v3 written ✅")

# Verify
with open(PATH, 'r', encoding='utf-8', errors='ignore') as f:
    v = f.read()
m2 = re.search(r'K5t=\(0,M\.useCallback\)', v)
if m2:
    print("K5t after patch:")
    print(repr(v[m2.start():m2.start()+300]))
    if "||" in v[m2.start():m2.start()+300]:
        print("✅ || fallback confirmed")
    else:
        print("❌ || fallback NOT found")
