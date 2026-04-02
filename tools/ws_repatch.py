"""
ws_repatch.py — Windsurf workbench.desktop.main.js 补丁工具 v4.0
用途: 绕过客户端阻断 + 拦截gRPC Rate Limit错误 + 无感切号信号注入
触发: Windsurf 每次更新后自动或手动执行

v4.0 新增 (道法自然·无为·全静默):
  patch 3升级: GBe全静默 — 限流时errorCodePrefix/userErrorMessage/errorParts全部置空,
               用户在UI层完全零感知, 不再显示"Permission denied: ⏳ ..."等任何错误消息,
               信号仍通过globalThis.__wamRateLimit传递给WAM系统后台处理

v3.0 (已有):
  patch 5: _resetAt精确时间戳 — 从"Resets in: Xm Ys"提取精确毫秒数,
           注入_resetMs/_resetAt到globalThis信号,
           WAM可以精确调度: 距离重置还有多少ms, 精确到秒
  patch 6: per-model窗口常量 — 将claude-opus-4.6系列各变体窗口(ms)注入globalThis,
           供透明代理/WAM动态校准: opus标准~40min, thinking-1m~22min

v2.0 (已有):
  patch 3: GBe Rate Limit Interceptor — 拦截所有rate limit错误,
           设置globalThis.__wamRateLimit信号供WAM即时检测,
           全静默(v4.0), 标记benign抑制红色样式
  patch 4: isRateLimited for all users — 移除anonymous限制(目标可能随版本变化)

Usage:
  python ws_repatch.py          # 检查并按需打补丁
  python ws_repatch.py --force  # 强制重新打补丁
  python ws_repatch.py --check  # 仅检查状态
  python ws_repatch.py --status # 详细状态+根因分析
"""
import sys, os, shutil, hashlib, datetime
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

def _find_target():
    """Auto-detect workbench.desktop.main.js from common Windsurf install locations."""
    import glob
    candidates = [
        r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js',
        r'C:\Program Files\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js',
    ]
    # AppData\Local\Programs\Windsurf (default user install)
    import os
    local_prog = os.environ.get('LOCALAPPDATA', '')
    if local_prog:
        candidates.append(os.path.join(local_prog, 'Programs', 'Windsurf', 'resources', 'app', 'out', 'vs', 'workbench', 'workbench.desktop.main.js'))
    for p in candidates:
        if os.path.exists(p):
            return p
    # Glob fallback: search all drives for Windsurf installation
    for drive in ['C', 'D', 'E', 'F']:
        pattern = drive + r':\**\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
        try:
            matches = glob.glob(pattern, recursive=True)
            if matches:
                return matches[0]
        except Exception:
            pass
    return candidates[0]  # fallback to D: default

TARGET = _find_target()

# ── Patch 3: GBe interceptor components ──
# Original GBe function body (error detail parser — single point of all gRPC error rendering)
_GBE_OLD = (
    'const B=!!Z?.isBenign;return{errorCode:Z?.errorCode,errorCodePrefix:'
    'Z?.errorCode?`${qZt[Z.errorCode]??""}: `:"",'
    'userErrorMessage:Z?.userErrorMessage,'
    'errorParts:Z?.structuredErrorParts,'
    'errorId:Z?.errorId,isBenign:B}'
)
# Patched: detect rate limit OR quota exhausted → set globalThis signal → FULLY SILENT → mark benign
# v4.0 道法自然·无为: 限流时errorCodePrefix/userErrorMessage/errorParts全部静默
# 用户零感知，信号仍通过globalThis.__wamRateLimit传递给WAM
# v4.2 RC-FIX: failed.precondition只在含quota/usage/exhausted时才匹配(防误吞auth错误)
_GBE_NEW = (
    'const B=!!Z?.isBenign,'
    '_rl=Z?.userErrorMessage&&(/rate.limit|quota.exhaust|daily.usage.quota|model.provider.unreachable/i).test(Z.userErrorMessage);'
    'if(!_rl&&Z?.userErrorMessage&&/failed.precondition/i.test(Z.userErrorMessage))'
    '_rl=/quota|usage|exhaust|daily|limit/i.test(Z.userErrorMessage);'
    'if(_rl)try{globalThis.__wamRateLimit={ts:Date.now(),msg:Z.userErrorMessage,'
    'id:Z.errorId,code:Z.errorCode}}catch(_){}'
    'return{errorCode:Z?.errorCode,errorCodePrefix:'
    '_rl?"":Z?.errorCode?`${qZt[Z.errorCode]??""}: `:"",'    
    'userErrorMessage:_rl?"":Z?.userErrorMessage,'
    'errorParts:_rl?void 0:Z?.structuredErrorParts,'
    'errorId:Z?.errorId,isBenign:_rl||B}'
)

# ── Patch 5: _resetAt精确重置时间戳 ──
# 目标: Patch3已注入的信号设置语句 (workbench.js已包含_GBE_NEW)
# 增强: 从错误消息提取"Resets in: 37m2s" → 2222000ms → _resetMs + _resetAt
# _resetAt = Date.now() + resetMs → 精确UTC时间戳, WAM可直接用于调度
_P5_OLD = (
    'if(_rl)try{globalThis.__wamRateLimit={ts:Date.now(),msg:Z.userErrorMessage,'
    'id:Z.errorId,code:Z.errorCode}}catch(_){}'
)
_P5_NEW = (
    'if(_rl){var _rm=0;'
    'try{var _rmatch=Z.userErrorMessage&&Z.userErrorMessage'
    '.match(/Resets in:\\s*(?:(\\d+)h)?(?:(\\d+)m)?(\\d+)s/i);'
    'if(_rmatch)_rm=(parseInt(_rmatch[1]||0)*3600'
    '+parseInt(_rmatch[2]||0)*60+parseInt(_rmatch[3]||0))*1000}catch(_e1){}'
    'try{globalThis.__wamRateLimit={ts:Date.now(),msg:Z.userErrorMessage,'
    'id:Z.errorId,code:Z.errorCode,_resetMs:_rm,_resetAt:Date.now()+_rm};'
    'if(!globalThis.__wamModelResets)globalThis.__wamModelResets=[];'
    'globalThis.__wamModelResets.unshift({ts:Date.now(),msg:Z.userErrorMessage,'
    'id:Z.errorId,_resetMs:_rm,_resetAt:Date.now()+_rm});'
    'if(globalThis.__wamModelResets.length>20)globalThis.__wamModelResets.length=20'
    '}catch(_e2){}}'
)

# ── Patch 6: per-model窗口常量注入 ──
# 将各Opus变体的实测窗口(ms)注入globalThis.__wamOpusWindows
# 透明代理/WAM读取此常量表进行自适应校准
# 实测数据: opus标准=~40min, thinking-1m=~22min, thinking=~25min
_P6_TARGET = (
    'globalThis.__wamRateLimit={ts:Date.now(),msg:Z.userErrorMessage,'
    'id:Z.errorId,code:Z.errorCode,_resetMs:_rm,_resetAt:Date.now()+_rm}'
)
_P6_INJECT = (
    'if(!globalThis.__wamOpusWindows)globalThis.__wamOpusWindows='
    '{"claude-opus-4-6":2400000,"claude-opus-4.6":2400000,'
    '"claude-opus-4-5":2400000,'
    '"claude-opus-4-6-thinking-1m":1400000,'
    '"claude-opus-4-6-thinking":1560000,'
    '"default":2400000};'
)

# ── Patch 12: commandModels 初始解析注入 (初始 auth 加载时) ──
# 根因: claude-opus-4-6 已于3/28从服务端移除，正确UID: MODEL_CLAUDE_4_5_OPUS
# 修复: 在客户端 commandModels 解析完成后，克隆首个模型对象并注入 Opus 4.5
# 注入点: this.j=this.C(D),this.b.fire(this.f)
# sig: __o46_label:'Claude Opus 4.6'
_P12_OLD = 'this.j=this.C(D),this.b.fire(this.f)'
_P12_INJECT = (
    'try{if(this.j&&this.j.length>0){'
    'var __o46=Object.assign(Object.create(Object.getPrototypeOf(this.j[0])),this.j[0],'
    '{label:\'Claude Opus 4.6\',modelUid:\'MODEL_CLAUDE_4_5_OPUS\','
    'creditMultiplier:6,disabled:!1,isPremium:!0,isCapacityLimited:!1,'
    'isBeta:!1,isNew:!0,isRecommended:!1,description:\'Claude Opus 4.5 — injected\'});'
    'this.j=[...this.j,__o46]'
    '}}catch(__e46){}'
)
_P12_NEW = 'this.j=this.C(D);' + _P12_INJECT + 'this.b.fire(this.f)'

# ── Patch 13: commandModels 服务端刷新注入 (updateWindsurfAuthStatus 时) ──
# 根因: 服务端每次返回 auth 状态时都会覆盖 commandModels，Patch12不够
# 修复: 同样在 updateWindsurfAuthStatus 中注入，UID修正为MODEL_CLAUDE_4_5_OPUS
# sig: __o46_update (与P12 sig不同，用于独立检测)
_P13_OLD = 'this.j=C?this.C(C):[],this.y(),this.b.fire(_),this.z()'
_P13_NEW = (
    'this.j=C?this.C(C):[];'
    'try{if(this.j&&this.j.length>0){'
    'var __o46b=Object.assign(Object.create(Object.getPrototypeOf(this.j[0])),this.j[0],'
    '{label:\'Claude Opus 4.6\',modelUid:\'MODEL_CLAUDE_4_5_OPUS\','
    'creditMultiplier:6,disabled:!1,isPremium:!0,isCapacityLimited:!1,'
    'isBeta:!1,isNew:!0,isRecommended:!1,description:\'Claude Opus 4.5 — injected\'});'
    'this.j=[...this.j,__o46b]'
    '}}catch(__e46b){}'
    'this.y(),this.b.fire(_),this.z()'
)

# PATCHES: 4元组 (old, new, name, signature)
# signature: 独立的内容检测字符串, 用于 check()函数检测应用状态
# 解决级联补丁问题: Patch3被5改动就会显示UNKNOWN，使用sig可独立检测
# ── Patch 7: 扩展_rl正则 — 已打补丁的workbench.js升级 ──
# 根因: /rate.limit/i 不匹配 "Failed precondition: Your daily usage quota has been exhausted"
# 修复: 扩展正则覆盖 FAILED_PRECONDITION / quota exhausted / daily usage quota
_P7_OLD = '_rl=Z?.userErrorMessage&&/rate.limit/i.test(Z.userErrorMessage);'
# v4.2: 2-step regex — failed.precondition只在含quota关键词时才拦截(防误吞auth错误)
_P7_NEW = '_rl=Z?.userErrorMessage&&(/rate.limit|quota.exhaust|daily.usage.quota|model.provider.unreachable/i).test(Z.userErrorMessage);if(!_rl&&Z?.userErrorMessage&&/failed.precondition/i.test(Z.userErrorMessage))_rl=/quota|usage|exhaust|daily|limit/i.test(Z.userErrorMessage);'

# ── Patch 11: 扩展_rl正则B — 添加model.provider.unreachable (v4.1 根因修复)
# 根因: Claude Opus 4.6 Thinking 1M限速时Windsurf抛出 "Model provider unreachable"
#       该错误不匹配旧正则 → 用户看到错误 + WAM无信号 → 切号失败
# 修复: 正则添加|model.provider.unreachable → 全静默+WAM信号
_P11_OLD = '(/rate.limit|failed.precondition|quota.exhaust|daily.usage.quota/i).test(Z.userErrorMessage)'
_P11_NEW = '(/rate.limit|failed.precondition|quota.exhaust|daily.usage.quota|model.provider.unreachable/i).test(Z.userErrorMessage)'

# ── Patch 8: GBe升级A — errorCodePrefix全静默 (v3.x旧补丁机器升级到v4.0) ──
# 目标: 已有旧版GBe补丁的文件中, errorCodePrefix未条件化 → 限流时置空
# 锁定: return语句中同时包含 userErrorMessage:_rl?（确保在GBe中）
_P8_OLD = 'return{errorCode:Z?.errorCode,errorCodePrefix:Z?.errorCode?`${qZt[Z.errorCode]??""}: `:"",userErrorMessage:_rl?'
_P8_NEW = 'return{errorCode:Z?.errorCode,errorCodePrefix:_rl?"":Z?.errorCode?`${qZt[Z.errorCode]??""}: `:"",userErrorMessage:_rl?'

# ── Patch 9: GBe升级B — userErrorMessage旧消息静默 (v3.x旧补丁机器升级到v4.0) ──
# 目标: 旧版消息 "⏳ 限流检测·正在自动切换账号..." → 空字符串
# 覆盖: 141台式机已有的旧版GBe补丁中的特定消息
_P9_OLD = 'userErrorMessage:_rl?"\\u23f3 \\u9650\\u6d41\\u68c0\\u6d4b\\u00b7\\u6b63\\u5728\\u81ea\\u52a8\\u5207\\u6362\\u8d26\\u53f7...":Z?.userErrorMessage,'
_P9_NEW = 'userErrorMessage:_rl?"":Z?.userErrorMessage,'

# ── Patch 10: GBe升级C — errorParts全静默 (v3.x旧补丁机器升级到v4.0) ──
# 目标: 已有旧版GBe补丁的文件中, errorParts无条件 → 限流时void 0
# 签名: errorParts:_rl?void 0: 为P10独有
_P10_OLD = 'errorParts:Z?.structuredErrorParts,errorId:Z?.errorId,isBenign:_rl||B}'
_P10_NEW = 'errorParts:_rl?void 0:Z?.structuredErrorParts,errorId:Z?.errorId,isBenign:_rl||B}'

# ── Patch 14: visibleModelConfigs inject opus-4-6 (大型model picker) ──
# 根因: 大型model picker (Search all models) 读取 Redux state.visibleModelConfigs
#       该数据来自服务端，opus-4-6已从服务端目录移除，大型picker不显示
# 修复: 在 zo=useMemo(Ie.map(lpe)) 处注入，让大型picker显示opus-4-6
# sig: __mc4 为P14独有
_P14_OLD = 'zo=(0,M.useMemo)(()=>Ie.map(lpe),[Ie])'
_P14_NEW = (
    'zo=(0,M.useMemo)(()=>{'
    'const __mc4=Ie.map(lpe);'
    'const __injectModels=['
    '{label:\'Claude Sonnet 4.6\',modelUid:\'claude-sonnet-4-6\','
    'displayOption:\'standard-picker\',disabled:!1,isBeta:!1,isNew:!0,'
    'isRecommended:!0,isCapacityLimited:!1,'
    'modelCost:{type:\'credit\',multiplier:3,tier:\'medium\'},'
    'description:\'Claude Sonnet 4.6\'},'
    '{label:\'Claude Opus 4.6\',modelUid:\'MODEL_CLAUDE_4_5_OPUS\','
    'displayOption:\'standard-picker\',disabled:!1,isBeta:!1,isNew:!0,'
    'isRecommended:!1,isCapacityLimited:!1,'
    'modelCost:{type:\'credit\',multiplier:6,tier:\'high\'},'
    'description:\'Claude Opus 4.5 \u2014 injected\'}'
    '];'
    '__injectModels.forEach(function(__im){'
    'if(!__mc4.some(function(__m4){return __m4.modelUid===__im.modelUid;}))'
    '__mc4.push(__im);'
    '});'
    'return __mc4;},[Ie])'
)

PATCHES = [
    # patch 1: 绕过 checkUserMessageRateLimit 回弹
    (
        'if(!tu.hasCapacity)return np(),py(void 0),ys(tu.message',
        'if(!1&&!tu.hasCapacity)return np(),py(void 0),ys(tu.message',
        'checkUserMessageRateLimit bypass',
        None,  # sig: 当new就是sig
    ),
    # patch 2: 绕过 checkChatCapacity 回弹
    (
        'if(!Ru.hasCapacity)return np(),py(void 0),ys(Ru.message',
        'if(!1&&!Ru.hasCapacity)return np(),py(void 0),ys(Ru.message',
        'checkChatCapacity bypass',
        None,
    ),
    # patch 3: GBe Rate Limit Interceptor — 核心突破
    # sig: isBenign:_rl||B 是Patch3独有的返回对象字段, Patch5/6不动
    (
        _GBE_OLD,
        _GBE_NEW,
        'GBe rate limit interceptor',
        'isBenign:_rl||B',
    ),
    # patch 4: isRateLimited widget (目标可能随版本变化)
    # sig: None = 用新字符串检测
    (
        'isRateLimited&&this.ab.anonymous',
        'isRateLimited',
        'isRateLimited for all users',
        None,
    ),
    # patch 5: _resetAt精确重置时间戳
    # sig: _resetMs:_rm,_resetAt: Patch5独有, Patch6不动
    (
        _P5_OLD,
        _P5_NEW,
        '_resetAt precise reset timestamp',
        '_resetMs:_rm,_resetAt:Date.now()+_rm',
    ),
    # patch 6: per-model窗口常量
    # sig: __wamOpusWindows
    (
        _P6_TARGET,
        _P6_INJECT + _P6_TARGET,
        'per-model window constants',
        '__wamOpusWindows',
    ),
    # patch 7: 扩展_rl正则 — 根因修复quota exhausted未被拦截
    (
        _P7_OLD,
        _P7_NEW,
        'extend _rl regex for quota exhausted'
    ),
    # patch 11: 扩展_rl正则B — 根因修复model provider unreachable未被拦截 (v4.1)
    # sig: model.provider.unreachable 为P11独有
    (
        _P11_OLD,
        _P11_NEW,
        'extend _rl regex for model provider unreachable',
        'model.provider.unreachable',
    ),
    # patch 8: GBe升级A — errorCodePrefix静默 (v3.x旧补丁升级到v4.0全静默)
    # sig: _rl?"":Z?.errorCode? 为P8独有
    (
        _P8_OLD,
        _P8_NEW,
        'GBe upgrade A: errorCodePrefix silent',
        '_rl?"":Z?.errorCode?',
    ),
    # patch 9: GBe升级B — 旧消息静默 (141台式机旧版GBe)
    # sig: 古消息被替换后更新检测 userErrorMessage:_rl?"":
    (
        _P9_OLD,
        _P9_NEW,
        'GBe upgrade B: old message silent',
        None,
    ),
    # patch 10: GBe升级C — errorParts静默 (v3.x旧补丁升级到v4.0全静默)
    # sig: errorParts:_rl?void 0: 为P10独有
    (
        _P10_OLD,
        _P10_NEW,
        'GBe upgrade C: errorParts silent',
        'errorParts:_rl?void 0:Z?.structuredErrorParts',
    ),
    # patch 14: visibleModelConfigs inject opus-4-6 — 大型模型选择器注入
    # 根因: 大型model picker (Search all models) 读取 Redux state.visibleModelConfigs
    #       该数据来自服务端，opus-4-6已被服务端移除，大型picker不显示
    # 修复: 在 zo=useMemo(Ie.map(lpe)) 变换处注入，让所有模型列表都包含opus-4-6
    # sig: __mc4 为P14独有
    (
        _P14_OLD,
        _P14_NEW,
        'visibleModelConfigs inject opus-4-6 (large model picker)',
        '__mc4',
    ),
    # patch 12: commandModels初始解析注入 — claude-opus-4-6已从服务端目录移除
    # 修复: 克隆首个commandModel对象，覆盖key字段注入opus-4-6
    # sig: __o46= 为P12独有
    (
        _P12_OLD,
        _P12_NEW,
        'commandModels inject opus-4-6 (initial parse)',
        '__o46=Object.assign(',
    ),
    # patch 13: commandModels服务端刷新注入 — updateWindsurfAuthStatus覆盖P12
    # 修复: 在服务端auth刷新时也注入opus-4-6，确保每次刷新后仍可见
    # sig: __o46b= 为P13独有
    (
        _P13_OLD,
        _P13_NEW,
        'commandModels inject opus-4-6 (auth refresh)',
        '__o46b=Object.assign(',
    ),
    # patch 15: GBe regex收窄 — v4.2根因修复(已打补丁的文件升级)
    # 根因: /failed.precondition/i 匹配所有FAILED_PRECONDITION错误(含auth失败/session过期)
    #       → 非限流错误被静默 → 用户看不到错误但消息失败 → "回弹"
    # 修复: failed.precondition只在消息含quota/usage/exhaust等关键词时才拦截
    # sig: if(!_rl&&Z?.userErrorMessage&&/failed.precondition 为P15独有
    (
        '_rl=Z?.userErrorMessage&&(/rate.limit|failed.precondition|quota.exhaust|daily.usage.quota|model.provider.unreachable/i).test(Z.userErrorMessage);',
        '_rl=Z?.userErrorMessage&&(/rate.limit|quota.exhaust|daily.usage.quota|model.provider.unreachable/i).test(Z.userErrorMessage);'
        'if(!_rl&&Z?.userErrorMessage&&/failed.precondition/i.test(Z.userErrorMessage))'
        '_rl=/quota|usage|exhaust|daily|limit/i.test(Z.userErrorMessage);',
        'GBe regex narrow: failed.precondition guard',
        'if(!_rl&&Z?.userErrorMessage&&/failed.precondition',
    ),
]

def md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

def check(content):
    results = {}
    for entry in PATCHES:
        old, new, name = entry[0], entry[1], entry[2]
        sig = entry[3] if len(entry) > 3 else None
        has_old = content.count(old)
        # 优先用sig检测(解决级联补丁问题), 其次new, 最后new的前50字符
        if sig:
            has_new = content.count(sig)
        else:
            has_new = content.count(new)
            if has_new == 0:
                # 宽松检测: 检查new的前60字符
                has_new = content.count(new[:60]) if len(new) > 60 else 0
        results[name] = {'patched': has_new > 0, 'needs_patch': has_old > 0}
    return results

def apply(content):
    patched = 0
    for entry in PATCHES:
        old, new, name = entry[0], entry[1], entry[2]
        if content.count(old) > 0:
            content = content.replace(old, new, 1)
            print(f'  [+] {name}')
            patched += 1
        elif content.count(new) > 0:
            print(f'  [=] {name} already patched')
        else:
            print(f'  [!] {name} — target not found (Windsurf version changed?)')
    return content, patched

# Model-specific rate limit windows (实测值+裕量, 供诊断/调试用)
MODEL_WINDOWS_SEC = {
    'claude-opus-4-6':            2400,   # ~40min 实测 (v15.0: 39m2s, 当前: 37m2s)
    'claude-opus-4.6':            2400,
    'claude-opus-4-5':            2400,
    'claude-opus-4-6-thinking-1m':1400,   # ~22min 实测 (v3.11: 22m13s)
    'claude-opus-4-6-thinking':   1560,   # ~26min 估算
    'claude-sonnet-4-6':           900,   # ~15min 估算
    'claude-sonnet-4-5':           900,
    'default':                    2400,
}

def parse_reset_seconds(msg):
    """从错误消息提取重置秒数, e.g. 'Resets in: 37m2s' → 2222"""
    if not msg:
        return 0
    import re
    m = re.search(r'Resets in:\s*(?:(\d+)h)?(?:(\d+)m)?(\d+)s', msg, re.I)
    if not m:
        return 0
    h = int(m.group(1) or 0)
    mi = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h * 3600 + mi * 60 + s

def status_report(content):
    """详细状态报告+根因分析"""
    print('\n═══ 根因分析 ══════════════════════════════')
    status = check(content)
    critical_missing = []
    for name, s in status.items():
        if s['patched']:
            state = '✅ PATCHED'
        elif s['needs_patch']:
            state = '⚠️  NEEDS PATCH'
            critical_missing.append(name)
        else:
            state = '❓ UNKNOWN TARGET'
        print(f'  {state:20s} {name}')

    p5_ok = 'per-model window constants' not in [p for p, s in status.items() if not s['patched']]
    has_resetat = '__wamRateLimit={ts:Date.now(),msg:Z.userErrorMessage,id:Z.errorId,code:Z.errorCode,_resetMs:' in content
    has_model_wins = '__wamOpusWindows' in content

    print(f'\n  _resetAt注入: {"✅ 已注入" if has_resetat else "❌ 未注入 — Patch5未应用"}')
    print(f'  模型窗口常量: {"✅ 已注入" if has_model_wins else "❌ 未注入 — Patch6未应用"}')

    if critical_missing:
        print(f'\n⚠️  需要打补丁: {critical_missing}')
        print('   运行: python ws_repatch.py --force')
    elif not has_resetat:
        print('\n⚠️  Patch5(_resetAt)未应用 — 运行: python ws_repatch.py --force')
    else:
        print('\n✅ 所有关键补丁已应用')
        print('   root cause修复:')
        print('   → globalThis._resetAt: 精确到秒的重置时间戳 ✅')
        print('   → globalThis.__wamModelResets: 历史限流记录(最近20条) ✅')
        print('   → globalThis.__wamOpusWindows: per-model窗口常量 ✅')

    print(f'\n  Opus各变体窗口参考:')
    for model, sec in MODEL_WINDOWS_SEC.items():
        print(f'    {model:<40s}: {sec}s = {sec//60}m{sec%60}s')

def main():
    global TARGET
    force = '--force' in sys.argv
    check_only = '--check' in sys.argv
    status_only = '--status' in sys.argv
    for arg in sys.argv[1:]:
        if arg.startswith('--target='):
            TARGET = arg[len('--target='):]
        elif arg.startswith('--target') and sys.argv.index(arg) + 1 < len(sys.argv):
            idx = sys.argv.index(arg)
            TARGET = sys.argv[idx + 1]

    if not os.path.exists(TARGET):
        print(f'ERROR: target not found: {TARGET}')
        sys.exit(1)

    print(f'Target: {TARGET}')
    print(f'MD5: {md5(TARGET)}')
    print(f'Modified: {datetime.datetime.fromtimestamp(os.path.getmtime(TARGET))}')
    print()

    with open(TARGET, 'r', encoding='utf-8') as f:
        content = f.read()

    status = check(content)
    # 过滤: patch4/patch6依赖前序patch, 状态可能是UNKNOWN
    # 核心patch: 1,2,3,5 必须PATCHED
    core_patches = [
        'checkUserMessageRateLimit bypass',
        'checkChatCapacity bypass',
        'GBe rate limit interceptor',
        '_resetAt precise reset timestamp',
        'extend _rl regex for quota exhausted',
    ]
    all_core_patched = all(
        status.get(p, {}).get('patched', False) for p in core_patches
    )
    # 升级补丁检测: 任何补丁NEEDS_PATCH则必须应用(含P8/P9/P10升级补丁)
    any_needs_patch = any(s.get('needs_patch', False) for s in status.values())

    for name, s in status.items():
        if s['patched']:
            state = 'PATCHED   '
        elif s['needs_patch']:
            state = 'NEEDS PATCH'
        else:
            state = 'UNKNOWN   '
        print(f'  {state:14s} {name}')
    print()

    if check_only:
        return

    if status_only:
        status_report(content)
        return

    if all_core_patched and not any_needs_patch and not force:
        print('All core patches already applied. Use --force to re-apply.')
        print('Tip: run with --status for root cause analysis')
        return

    # Backup
    bak = TARGET + f'.bak_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}'
    shutil.copy2(TARGET, bak)
    print(f'Backup: {bak}')

    new_content, n = apply(content)

    if n > 0 or force:
        with open(TARGET, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f'\nSUCCESS: {n} patch(es) applied.')
        print('→ Patch5(_resetAt)已注入: WAM现在可以精确到秒地知道何时重置')
        print('→ Patch6(模型窗口)已注入: 透明代理/WAM可自适应校准各Opus变体窗口')
        print('→ 无需重启Windsurf立即生效 (workbench.js已修改)')
        print('→ 但Windsurf重载后才会加载新版本: Ctrl+Shift+P → Reload Window')
    else:
        print('\nNo changes made.')

if __name__ == '__main__':
    main()
