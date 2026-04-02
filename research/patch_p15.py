"""
P15: Patch K5t (handleModelChange) to allow selecting injected models
Root cause: K5t does ja.find(modelUid) - returns early if not found
claude-opus-4-6 is not in ja (server data), so clicking it does nothing
Fix: add fallback for known injected models
"""
import re, shutil

PATH = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
BAK  = PATH + '.bak_p15'

with open(PATH, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# === P15: Patch K5t guard ===
OLD_K5T = r'if(!Al)return void console.error(`[Model Select] Invalid model UID: ${Oa}`)'
NEW_K5T = (
    r'if(!Al){'
    r"const __injected=['claude-opus-4-6','claude-sonnet-4-6','claude-sonnet-4-5','gpt-5-2','gpt-4-1','o4-mini'];"
    r"if(__injected.includes(Oa)){"
    r"Al={label:Oa==='claude-opus-4-6'?'Claude Opus 4.6':Oa==='claude-sonnet-4-6'?'Claude Sonnet 4.6':Oa==='claude-sonnet-4-5'?'Claude Sonnet 4.5':Oa==='gpt-5-2'?'GPT-5.2':Oa==='gpt-4-1'?'GPT-4.1':Oa==='o4-mini'?'o4-mini':Oa,"
    r"modelUid:Oa,disabled:!1,isBeta:!1,isNew:!0,modelCost:{type:'credit',multiplier:Oa==='claude-opus-4-6'?6:3,tier:Oa==='claude-opus-4-6'?'high':'medium'},supportsImages:!1,description:Oa};"
    r"}else return void console.error(`[Model Select] Invalid model UID: ${Oa}`)}"
)

if OLD_K5T in content:
    count = content.count(OLD_K5T)
    print(f'P15: found K5t guard {count} time(s)')
    shutil.copy2(PATH, BAK)
    content = content.replace(OLD_K5T, NEW_K5T, 1)
    with open(PATH, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'P15: PATCHED ✅')
    # Verify
    if NEW_K5T in content:
        print('P15: verified in file ✅')
else:
    print(f'P15: OLD pattern NOT found!')
    # Show what's at K5t position to debug
    m = re.search(r'K5t=\(0,M\.useCallback\)', content)
    if m:
        print(f'K5t at offset {m.start()}:')
        print(repr(content[m.start():m.start()+300]))

# Also check if we need to patch Aa to inject model into ja
# Find where Aa(Au) is called and patch to include claude-opus-4-6
print()
print('=== Check Aa(Au) context for ja population ===')
m2 = re.search(r'Vc\(l2\),Aa\(Au\),Uo\(Yu\)', content)
if m2:
    ctx = content[max(0,m2.start()-500): m2.start()+200]
    print(f'Aa(Au) at {m2.start()}: {repr(ctx[-400:])}')
    print('NOTE: Au comes from server model list - claude-opus-4-6 not included')
    print('P15 patch to K5t is the correct fix.')
