#!/usr/bin/env python3
"""深度逆向 Continue 机制 — 找到根本触发点"""
import re, json

WB  = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'

print("=" * 70)
print("DEEP REVERSE: Continue 机制完整分析")
print("=" * 70)

wb = open(WB, 'r', encoding='utf-8', errors='replace').read()
ext = open(EXT, 'r', encoding='utf-8', errors='replace').read()

def ctx(s, idx, before=200, after=400):
    return s[max(0,idx-before):idx+after].replace('\n',' ')

results = {}

# ── 1. rYt 组件完整定义 (auto-continue UI组件) ──────────────────
print("\n[1] rYt 组件 (handleContinue auto-trigger):")
idx = wb.find('rYt=({handleContinue:Z')
if idx >= 0:
    # 找到完整函数体
    depth = 0
    start = idx
    end = idx
    for i, c in enumerate(wb[idx:idx+3000]):
        if c == '{': depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                end = idx + i + 1
                break
    snippet = wb[start:min(end, start+1500)]
    print(snippet)
    results['rYt_offset'] = idx
    results['rYt_snippet'] = snippet[:800]
else:
    print("  NOT FOUND")

# ── 2. Auto-continue 设置存储 key ────────────────────────────────
print("\n[2] Auto-continue 设置存储 key:")
for pat in ['autoContinue', 'auto_continue', 'AutoContinue', 'autoAccept',
            'auto-continue', 'autocontinue', 'shouldAutoContinue',
            'isAutoContinue', 'enableAutoContinue']:
    for source, name in [(wb, 'WB'), (ext, 'EXT')]:
        idx = source.find(pat)
        if idx >= 0:
            c = ctx(source, idx, 150, 250)
            print(f'  [{name}] "{pat}" @{idx}: {c[:300]}')
            results[f'setting_{pat}'] = {'source': name, 'offset': idx, 'ctx': c[:300]}

# ── 3. output limit / stream truncated 触发点 ────────────────────
print("\n[3] 输出限制触发信号:")
for pat in ['outputTokenLimit', 'output_token_limit', 'maxOutputTokens',
            'streamComplete', 'streamDone', 'generationComplete',
            'GENERATION_COMPLETE', 'STREAM_DONE', 'needsContinuation',
            'continuationNeeded', 'requiresContinuation',
            'REQUIRES_CONTINUATION', 'isContinuation', 'continueChat',
            'continueGeneration', 'CONTINUE_GENERATION',
            'outputLimitReached', 'hitOutputLimit', 'tokenLimitReached']:
    for source, name in [(wb, 'WB'), (ext, 'EXT')]:
        idx = source.find(pat)
        if idx >= 0:
            c = ctx(source, idx, 100, 300)
            print(f'  [{name}] "{pat}" @{idx}: {c[:300]}')
            results[f'limit_{pat}'] = {'source': name, 'offset': idx}

# ── 4. handleContinue 函数实现 (被调用时做什么) ────────────────────
print("\n[4] handleContinue 实现 (调用链):")
# 找所有 handleContinue 赋值/调用
for m in re.finditer(r'handleContinue[=:\s]', wb):
    i = m.start()
    c = ctx(wb, i, 50, 250)
    print(f'  @{i}: {c[:280]}')

# ── 5. 查找 Continue 按钮渲染条件 ────────────────────────────────
print("\n[5] Continue 按钮渲染条件:")
# 找 children:"Continue" 或 text:"Continue"
for m in re.finditer(r'children\s*:\s*["\']Continue["\']', wb):
    i = m.start()
    c = ctx(wb, i, 300, 200)
    print(f'  @{i}: {c[:450]}')
    print()

# ── 6. 查找 "On"/"Off" auto-continue 开关状态 ────────────────────
print("\n[6] Auto-continue 开关 (On/Off):")
# 找 auto-continue 相关的 On/Off 渲染
for m in re.finditer(r'Auto-continued|autoContinued|auto_continued', wb, re.IGNORECASE):
    i = m.start()
    c = ctx(wb, i, 200, 400)
    print(f'  @{i}: {c[:500]}')
    print()

# ── 7. extension.js: sendCascadeInput / continue 触发 ─────────────
print("\n[7] Extension.js sendCascadeInput / continuation:")
for pat in ['sendCascadeInput', 'CascadeInput', 'continueGeneration',
            'continuation', 'streamTruncated', 'outputLimit']:
    idx = ext.find(pat)
    if idx >= 0:
        c = ctx(ext, idx, 100, 300)
        print(f'  EXT "{pat}" @{idx}: {c[:350]}')
        print()

# ── 8. 查找 setTimeout+handleContinue 的所有调用点 ───────────────
print("\n[8] 所有 setTimeout + Continue 自动触发点:")
for m in re.finditer(r'setTimeout\([^,]{0,50}[Cc]ontinue[^,]{0,50},\s*\d+\)', wb):
    i = m.start()
    c = ctx(wb, i, 80, 200)
    print(f'  @{i}: {c[:250]}')

# ── 9. 查找 useAutoContinue / useContinue hook ────────────────────
print("\n[9] useContinue / useAutoContinue hooks:")
for pat in ['useAutoContinue', 'useContinue', 'useContinuation', 'useHandleContinue']:
    for m in re.finditer(pat, wb):
        i = m.start()
        c = ctx(wb, i, 50, 300)
        print(f'  "{pat}" @{i}: {c[:300]}')
        print()

# ── 10. gRPC/HTTP continue 请求 ────────────────────────────────────
print("\n[10] gRPC Continue 请求:")
for pat in ['ContinueCascade', 'continueCascade', 'ContinueChat', 'continueChat',
            'Continue\b', r'\"continue\"', "\"Continue\"",
            'isContinuation:true', 'is_continuation']:
    for source, name in [(wb, 'WB'), (ext, 'EXT')]:
        for m in re.finditer(re.escape(pat), source):
            i = m.start()
            c = ctx(source, i, 80, 250)
            print(f'  [{name}] "{pat}" @{i}: {c[:280]}')

# ─── 保存结果 ────────────────────────────────────────────────────
OUT = r'e:\道\道生一\一生二\Windsurf无限额度\040-诊断工具_Diagnostics\_continue_reverse.json'
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"\n=== 分析结果保存到: {OUT} ===")
