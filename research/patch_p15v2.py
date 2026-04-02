"""P15v2: fix const-reassignment bug. Use || fallback in const Al declaration."""
import re, shutil

PATH = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'

with open(PATH, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Correct fallback string (no f-string nesting issues)
FALLBACK = (
    "(['claude-opus-4-6','claude-sonnet-4-6','claude-sonnet-4-5','gpt-5-2','gpt-4-1','o4-mini'].includes(Oa)"
    "?{label:Oa==='claude-opus-4-6'?'Claude Opus 4.6':Oa==='claude-sonnet-4-6'?'Claude Sonnet 4.6'"
    ":Oa==='claude-sonnet-4-5'?'Claude Sonnet 4.5':Oa==='gpt-5-2'?'GPT-5.2'"
    ":Oa==='gpt-4-1'?'GPT-4.1':'o4-mini',"
    "modelUid:Oa,disabled:!1,isBeta:!1,isNew:!0,"
    "modelCost:{type:'credit',multiplier:Oa==='claude-opus-4-6'?6:3,"
    "tier:Oa==='claude-opus-4-6'?'high':'medium'},supportsImages:!1}"
    ":null)"
)

ORIG_ERR  = "if(!Al)return void console.error(`[Model Select] Invalid model UID: ${Oa}`)"
FIXED_NEW = "if(!Al)return void console.error(`[Model Select] Invalid model UID: ${Oa}`)"  # keep same after Al fix

# Find K5t in current state (handles both original and broken-P15 versions)
k5t_m = re.search(r'K5t=\(0,M\.useCallback\)', content)
if not k5t_m:
    print("ERROR: K5t not found"); exit(1)

k5t_chunk = content[k5t_m.start(): k5t_m.start()+600]
print("Current K5t:")
print(repr(k5t_chunk[:400]))
print()

# Strategy: find & replace the const Al line
# Original:  const Al=ja.find(F0=>F0.modelUid===Oa);if(!Al)return void console.error(...)
# Broken P15: const Al=ja.find(F0=>F0.modelUid===Oa);if(!Al){const __injected=[...];if(...){Al={...}}...}
# Target:    const Al=ja.find(F0=>F0.modelUid===Oa)||FALLBACK;if(!Al)return void console.error(...)

OLD_ORIG = "const Al=ja.find(F0=>F0.modelUid===Oa);if(!Al)return void console.error(`[Model Select] Invalid model UID: ${Oa}`);const t0={...Al,smartFriendModelUid:vo};XZ(t0)"
NEW_CORRECT = ("const Al=ja.find(F0=>F0.modelUid===Oa)||" + FALLBACK +
               ";if(!Al)return void console.error(`[Model Select] Invalid model UID: ${Oa}`);"
               "const t0={...Al,smartFriendModelUid:vo};XZ(t0)")

if OLD_ORIG in content:
    shutil.copy2(PATH, PATH + '.bak_p15v2')
    content = content.replace(OLD_ORIG, NEW_CORRECT, 1)
    with open(PATH, 'w', encoding='utf-8') as f:
        f.write(content)
    print("P15v2 applied to ORIGINAL K5t ✅")
else:
    # Try broken P15 - find and replace entire K5t body
    # Broken P15: const Al=ja.find(...);if(!Al){const __injected=[...];...}const t0=...;XZ(t0)
    OLD_BROKEN_PAT = r"const Al=ja\.find\(F0=>F0\.modelUid===Oa\);if\(!Al\)\{const __injected=\[.{10,300}?\}\}const t0=\{\.\.\.Al,smartFriendModelUid:vo\};XZ\(t0\)"
    m2 = re.search(OLD_BROKEN_PAT, content, re.DOTALL)
    if m2:
        shutil.copy2(PATH, PATH + '.bak_p15v2')
        content = content[:m2.start()] + NEW_CORRECT + content[m2.end():]
        with open(PATH, 'w', encoding='utf-8') as f:
            f.write(content)
        print("P15v2 applied replacing broken P15 ✅")
    else:
        print("ERROR: pattern not found - showing K5t context:")
        print(repr(k5t_chunk[:500]))

# Verify
with open(PATH, 'r', encoding='utf-8', errors='ignore') as f:
    v = f.read()
if FALLBACK[:50] in v:
    print("VERIFIED: || fallback present in file ✅")
    k5t_v = re.search(r'K5t=\(0,M\.useCallback\)', v)
    if k5t_v:
        print("K5t final:")
        print(repr(v[k5t_v.start():k5t_v.start()+300]))
else:
    print("WARNING: fallback not found in file")
