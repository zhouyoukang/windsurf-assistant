#!/usr/bin/env python3
"""找 Opus/Claude 模型的 tier 限制检查点 + impersonateTier 用法"""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

WB  = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'

for fpath, label in [(WB, 'workbench'), (EXT, 'extension')]:
    txt = open(fpath, 'r', encoding='utf-8', errors='replace').read()
    print(f'\n{"="*60}')
    print(f'FILE: {label}')
    print('='*60)

    # 1. impersonateTier usage
    print('\n--- impersonateTier ---')
    for m in re.finditer(r'.{0,200}impersonateTier.{0,300}', txt):
        ctx = m.group()
        if any(x in ctx for x in ['claude', 'opus', 'model', 'tier', 'plan', 'allowed', 'pro']):
            print(ctx[:500])
            print('---')

    # 2. model upgrade/plan check
    print('\n--- upgrade / plan required for model ---')
    for m in re.finditer(r'.{0,150}(requiresUpgrade|needsUpgrade|upgradePlan|planRequired|modelLocked|lockedModel|tierRequired|requiresTier).{0,300}', txt):
        print(m.group()[:500])
        print('---')

    # 3. Claude/Opus model access check
    print('\n--- Claude access check ---')
    for m in re.finditer(r'.{0,100}(CLAUDE|[Cc]laude|[Oo]pus).{0,200}(tier|plan|pro|allowed|access|require|upgrade).{0,100}', txt):
        ctx = m.group()
        print(ctx[:400])
        print('---')

    # 4. model filter based on plan
    print('\n--- model filter/allowed by plan ---')
    for m in re.finditer(r'.{0,100}(allowedModels|modelAllowed|filteredModels|availableModels).{0,400}', txt):
        ctx = m.group()
        if any(x in ctx for x in ['tier', 'plan', 'pro', 'trial', 'filter']):
            print(ctx[:400])
            print('---')

    # 5. free tier model list
    print('\n--- free/trial model list ---')
    for m in re.finditer(r'.{0,100}(free|trial|TRIAL|FREE|TIER_0|TIER_FREE).{0,300}(model|MODEL|uid).{0,100}', txt):
        ctx = m.group()
        print(ctx[:400])
        print('---')
