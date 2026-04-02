#!/usr/bin/env python3
"""
Windsurf Credit Toolkit v2.0 — QUOTA额度监控+ACU模型矩阵+SWE委派
================================================================
道生一(BillingStrategy) → 一生二(CREDITS|QUOTA) → 二生三(daily+weekly+overage) → 三生万物(107模型ACU定价)

Commands:
  python credit_toolkit.py monitor     # 实时额度状态(QUOTA感知)
  python credit_toolkit.py models      # 107模型ACU成本矩阵
  python credit_toolkit.py delegate "任务描述" "步骤"  # 创建SWE委派任务
  python credit_toolkit.py recommend   # 优化建议
  python credit_toolkit.py serve       # HTTP Dashboard :19910
  python credit_toolkit.py test        # E2E自测

核心价值:
  - QUOTA感知: billingStrategy=QUOTA → daily%+weekly%+overage (3/18定价改革后)
  - 107模型ACU定价矩阵 (F3=ACU倍率, F24=ModelCostTier, 逆向自workbench.js)
  - SWE-1.5委派自动化 (ACU=0, 完全免费)
  - 效率优化建议 (基于v9.0逆向: sendMessage客户端门禁是死代码if(!1))
"""

import sqlite3, json, os, sys, time, re
from pathlib import Path
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

SCRIPT_DIR = Path(__file__).parent
VERSION = '3.0.0'
CNY_PER_USD = 7.25
XIANYU_PRO_CNY = 4.5

# ============================================================
# Model Cost Matrix (ACU逆向自workbench.js, F3=ACU倍率, F24=ModelCostTier)
# 107模型完整矩阵精选: 用户可见的Cascade下拉+高频模型
# ACU倍率: 0=免费, 0.5=低, 1.0=标准, 1.5=中, 2.0=高, 3.0+=旗舰
# ============================================================

MODEL_COSTS = {
    # === FREE (ACU=0, ModelCostTier=FREE(4)) ===
    'SWE-1.5':              {'m': 0,    'ctx': '200K', 'tier': 'free',     'note': 'ACU=0 委派首选'},
    'SWE-1.6':              {'m': 0,    'ctx': '200K', 'tier': 'free',     'note': 'ACU=0'},
    'SWE-1.5 Thinking':     {'m': 0,    'ctx': '200K', 'tier': 'free',     'note': 'ACU=0 推理版'},
    # === LOW (ACU≤0.5, ModelCostTier=LOW(1)) ===
    'Grok-3 mini Thinking': {'m': 0.125,'ctx': '128K', 'tier': 'budget',   'note': 'ACU=0.125'},
    'GPT-OSS 120B':         {'m': 0.25, 'ctx': '128K', 'tier': 'budget',   'note': 'ACU=0.25'},
    'GLM 4.7':              {'m': 0.25, 'ctx': '200K', 'tier': 'budget',   'note': 'ACU=0.25'},
    'SWE-1.5 Fast':         {'m': 0.5,  'ctx': '128K', 'tier': 'budget',   'note': 'ACU=0.5 快速执行'},
    'Kimi K2':              {'m': 0.5,  'ctx': '128K', 'tier': 'budget',   'note': 'ACU=0.5'},
    'Minimax M2.1':         {'m': 0.5,  'ctx': '200K', 'tier': 'budget',   'note': 'ACU=0.5'},
    'Codex Medium':         {'m': 0.5,  'ctx': '384K', 'tier': 'budget',   'note': 'ACU=0.5 GPT-5.1'},
    'Gemini 3 Flash':       {'m': 0.75, 'ctx': '1M',   'tier': 'budget',   'note': 'ACU=0.75 Minimal'},
    # === STANDARD (ACU=1.0, ModelCostTier=MED(2)/HIGH(3)) ===
    'GPT-4.1':              {'m': 1,    'ctx': '1M',   'tier': 'standard', 'note': 'ACU=1.0 通用'},
    'GPT-4o':               {'m': 1,    'ctx': '128K', 'tier': 'standard', 'note': 'ACU=1.0'},
    'Grok-3':               {'m': 1,    'ctx': '128K', 'tier': 'standard', 'note': 'ACU=1.0'},
    'Gemini 3 Flash Low':   {'m': 1,    'ctx': '1M',   'tier': 'standard', 'note': 'ACU=1.0'},
    'Gemini 3 Pro Low':     {'m': 1,    'ctx': '1M',   'tier': 'standard', 'note': 'ACU=1.0'},
    'Codex High':           {'m': 1,    'ctx': '384K', 'tier': 'standard', 'note': 'ACU=1.0 GPT-5.1'},
    # === MEDIUM (ACU=1.5~2.0) ===
    'Claude 4 Sonnet':      {'m': 1.5,  'ctx': '200K', 'tier': 'premium',  'note': 'ACU=1.5 编程主力'},
    'Claude 4.5 Sonnet':    {'m': 1.5,  'ctx': '200K', 'tier': 'premium',  'note': 'ACU=1.5 增强版'},
    'Codex Medium 5.2':     {'m': 1.5,  'ctx': '400K', 'tier': 'premium',  'note': 'ACU=1.5 GPT-5.2'},
    'GLM-5':                {'m': 1.5,  'ctx': '128K', 'tier': 'premium',  'note': 'ACU=1.5'},
    'Gemini 3 Flash High':  {'m': 1.75, 'ctx': '1M',   'tier': 'premium',  'note': 'ACU=1.75'},
    'Sonnet 4':             {'m': 2,    'ctx': '200K', 'tier': 'premium',  'note': 'ACU=2.0 强推理'},
    'Sonnet 4.5':           {'m': 2,    'ctx': '200K', 'tier': 'premium',  'note': 'ACU=2.0'},
    'Codex High 5.2':       {'m': 2,    'ctx': '400K', 'tier': 'premium',  'note': 'ACU=2.0 GPT-5.2'},
    'Gemini 3 Pro High':    {'m': 2,    'ctx': '1M',   'tier': 'premium',  'note': 'ACU=2.0'},
    'Codex High 5.3':       {'m': 2.5,  'ctx': '400K', 'tier': 'premium',  'note': 'ACU=2.5 GPT-5.3'},
    # === HIGH (ACU=3.0+) ===
    'Claude 4.5 Opus':      {'m': 3,    'ctx': '200K', 'tier': 'ultra',    'note': 'ACU=3.0 旗舰推理'},
    'Codex XHigh 5.2':      {'m': 3,    'ctx': '400K', 'tier': 'ultra',    'note': 'ACU=3.0'},
    'Codex XHigh 5.3':      {'m': 3,    'ctx': '400K', 'tier': 'ultra',    'note': 'ACU=3.0'},
    # === FLAGSHIP (ACU=4.0~6.0, ModelCostTier=HIGH(3)) ===
    'Codex Med Fast 5.2':   {'m': 2,    'ctx': '400K', 'tier': 'extreme',  'note': 'ACU=2.0 Priority'},
    'Codex High Fast 5.2':  {'m': 2,    'ctx': '400K', 'tier': 'extreme',  'note': 'ACU=2.0 Priority'},
    'Codex XHigh Fast 5.2': {'m': 4,    'ctx': '400K', 'tier': 'extreme',  'note': 'ACU=4.0 Priority'},
    'Codex Med Fast 5.3':   {'m': 4,    'ctx': '400K', 'tier': 'extreme',  'note': 'ACU=4.0 Priority'},
    'Codex High Fast 5.3':  {'m': 5,    'ctx': '400K', 'tier': 'extreme',  'note': 'ACU=5.0 Priority'},
    'Codex XHigh Fast 5.3': {'m': 6,    'ctx': '400K', 'tier': 'extreme',  'note': 'ACU=6.0 最贵'},
}

# ============================================================
# Anthropic API Pricing (Official 2026-03, $/MTok)
# ============================================================

ANTHROPIC_PRICING = {
  'Claude Opus 4.6':{'i':5,'o':25,'cw':6.25,'cr':0.5,'ctx':200000},
  'Claude Opus 4.6 1M':{'i':10,'o':37.5,'cw':12.5,'cr':1.0,'ctx':1000000},
  'Claude Opus 4.6 Thinking':{'i':5,'o':25,'cw':6.25,'cr':0.5,'ctx':200000},
  'Claude Opus 4.6 Fast':{'i':5,'o':25,'cw':6.25,'cr':0.5,'ctx':200000},
  'Claude Sonnet 4.6':{'i':3,'o':15,'cw':3.75,'cr':0.3,'ctx':200000},
  'Claude Sonnet 4.6 1M':{'i':6,'o':22.5,'cw':7.5,'cr':0.6,'ctx':1000000},
  'Claude Sonnet 4.6 Thinking':{'i':3,'o':15,'cw':3.75,'cr':0.3,'ctx':200000},
  'Claude Opus 4.5':{'i':5,'o':25,'cw':6.25,'cr':0.5,'ctx':200000},
  'Claude Opus 4.5 Thinking':{'i':5,'o':25,'cw':6.25,'cr':0.5,'ctx':200000},
  'Claude Sonnet 4.5':{'i':3,'o':15,'cw':3.75,'cr':0.3,'ctx':200000},
  'Claude Sonnet 4.5 Thinking':{'i':3,'o':15,'cw':3.75,'cr':0.3,'ctx':200000},
  'Claude Sonnet 4':{'i':3,'o':15,'cw':3.75,'cr':0.3,'ctx':200000},
  'Claude Haiku 4.5':{'i':1,'o':5,'cw':1.25,'cr':0.1,'ctx':200000},
  'Claude Haiku 3.5':{'i':0.8,'o':4,'cw':1.0,'cr':0.08,'ctx':200000},
}

WINDSURF_ACU = {
  'Claude Opus 4.6':6, 'Claude Opus 4.6 1M':10, 'Claude Opus 4.6 Thinking':8,
  'Claude Opus 4.6 Fast':24, 'Claude Sonnet 4.6':4, 'Claude Sonnet 4.6 1M':12,
  'Claude Sonnet 4.6 Thinking':6, 'Claude Opus 4.5':4, 'Claude Opus 4.5 Thinking':5,
  'Claude Sonnet 4.5':2, 'Claude Sonnet 4.5 Thinking':3,
  'Claude Sonnet 4':2, 'Claude Haiku 4.5':1, 'SWE-1.5':0, 'SWE-1.5 Fast':0.5,
}


def calc_cost(model, input_tok, output_tok, cache_r=0, cache_w=0):
    """Calculate API cost for given token counts."""
    p = ANTHROPIC_PRICING.get(model, ANTHROPIC_PRICING.get('Claude Sonnet 4.6', {'i':3,'o':15,'cw':3.75,'cr':0.3}))
    ic = input_tok/1e6*p['i']; oc = output_tok/1e6*p['o']
    crc = cache_r/1e6*p['cr']; cwc = cache_w/1e6*p['cw']
    t = ic+oc+crc+cwc
    return {'model':model, 'total_usd':round(t,4), 'total_cny':round(t*CNY_PER_USD,2),
            'input_cost':round(ic,4), 'output_cost':round(oc,4)}


def xianyu_compare(api_usd, xianyu_cny=XIANYU_PRO_CNY):
    """Compare API cost vs XianYu Pro account price."""
    api_cny = api_usd * CNY_PER_USD
    ratio = api_cny / xianyu_cny if xianyu_cny > 0 else 0
    return {'api_usd':round(api_usd,4), 'api_cny':round(api_cny,2),
            'xianyu':xianyu_cny, 'ratio':round(ratio,1)}


def read_current_model():
    """Read currently selected model from state.vscdb."""
    db = _find_state_db()
    if not db.exists(): return 'Unknown'
    try:
        conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        c = conn.cursor()
        for key in ['windsurf.selectedModel','windsurf.settings.selectedModel']:
            c.execute(f"SELECT value FROM ItemTable WHERE key='{key}'")
            row = c.fetchone()
            if row:
                conn.close()
                try:
                    d = json.loads(row[0])
                    return d.get('name', d.get('modelName', str(d)))
                except: return row[0]
        conn.close()
        return 'Unknown'
    except: return 'Unknown'


# ============================================================
# State Database Reader
# ============================================================

def _find_state_db():
    """Find Windsurf state.vscdb."""
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "Windsurf" / "User" / "globalStorage" / "state.vscdb",
        Path.home() / "AppData" / "Roaming" / "Windsurf" / "User" / "globalStorage" / "state.vscdb",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def read_plan_info():
    """Read cached plan info from state.vscdb."""
    db = _find_state_db()
    if not db.exists():
        return {'error': f'state.vscdb not found at {db}'}
    try:
        conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        c = conn.cursor()
        c.execute("SELECT value FROM ItemTable WHERE key='windsurf.settings.cachedPlanInfo'")
        row = c.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
        return {'error': 'cachedPlanInfo key not found'}
    except Exception as e:
        return {'error': str(e)}


def read_quota_status():
    """Read unified quota/credit status — QUOTA-first with CREDITS fallback.
    
    Returns dict with:
      billingStrategy: 'quota'|'credits'|'unknown'
      quota: {dailyRemaining, weeklyRemaining, overage, dailyReset, weeklyReset, effectiveRemaining}
      credits: {total, used, remaining, pct}  (legacy compat)
      plan: planName
      flow: {total, used}
      period: {start, end, daysRemaining}
    """
    info = read_plan_info()
    if 'error' in info:
        return {'error': info['error'], 'billingStrategy': 'unknown'}
    
    # Detect billing strategy
    # cachedPlanInfo may have billingStrategy directly or nested in planStatus.planInfo
    bs = info.get('billingStrategy', '')
    if not bs:
        pi = info.get('planStatus', {}).get('planInfo', {})
        bs_val = pi.get('billingStrategy', 0)
        bs = 'quota' if bs_val == 2 else 'credits' if bs_val == 1 else ''
    if not bs:
        # Heuristic: if quotaUsage exists, it's QUOTA
        if info.get('quotaUsage') or info.get('dailyQuotaRemainingPercent') is not None:
            bs = 'quota'
        else:
            bs = 'credits'
    
    # Extract QUOTA fields
    qu = info.get('quotaUsage', {})
    daily_r = qu.get('dailyRemainingPercent', info.get('dailyQuotaRemainingPercent'))
    weekly_r = qu.get('weeklyRemainingPercent', info.get('weeklyQuotaRemainingPercent'))
    overage = qu.get('overageBalanceMicros', info.get('overageBalanceMicros', 0))
    daily_reset = qu.get('dailyResetAtUnix', info.get('dailyQuotaResetAtUnix', 0))
    weekly_reset = qu.get('weeklyResetAtUnix', info.get('weeklyQuotaResetAtUnix', 0))
    
    # Effective remaining = min(daily, weekly) — matches Windsurf's vpe() function
    eff = None
    if daily_r is not None and weekly_r is not None:
        eff = min(daily_r, weekly_r)
    elif daily_r is not None:
        eff = daily_r
    elif weekly_r is not None:
        eff = weekly_r
    
    # Extract legacy CREDITS fields
    usage = info.get('usage', {})
    total = usage.get('messages', 0)
    used = usage.get('usedMessages', 0)
    remaining = usage.get('remainingMessages', 0)
    flow_total = usage.get('flowActions', 0)
    flow_used = usage.get('usedFlowActions', 0)
    
    # Period
    start_ts = info.get('startTimestamp', 0)
    end_ts = info.get('endTimestamp', 0)
    now = datetime.now()
    start_dt = datetime.fromtimestamp(start_ts / 1000) if start_ts else None
    end_dt = datetime.fromtimestamp(end_ts / 1000) if end_ts else None
    days_remaining = (end_dt - now).days if end_dt else None
    
    return {
        'billingStrategy': bs,
        'plan': info.get('planName', 'Unknown'),
        'quota': {
            'dailyRemaining': daily_r,
            'weeklyRemaining': weekly_r,
            'overage': overage,
            'overageUsd': round(overage / 1e6, 2) if overage else 0,
            'dailyResetUnix': daily_reset,
            'weeklyResetUnix': weekly_reset,
            'dailyResetStr': datetime.fromtimestamp(daily_reset).strftime('%m/%d %H:%M') if daily_reset and daily_reset > 0 else None,
            'weeklyResetStr': datetime.fromtimestamp(weekly_reset).strftime('%m/%d %H:%M') if weekly_reset and weekly_reset > 0 else None,
            'effectiveRemaining': eff,
        },
        'credits': {
            'total': total, 'used': used, 'remaining': remaining,
            'pct': round(used / total * 100, 1) if total > 0 else 0,
        },
        'flow': {'total': flow_total, 'used': flow_used},
        'period': {
            'start': start_dt.strftime('%Y-%m-%d') if start_dt else None,
            'end': end_dt.strftime('%Y-%m-%d') if end_dt else None,
            'daysRemaining': days_remaining,
        },
        'isQuota': bs == 'quota',
    }


def read_account_usages():
    """Read per-account usage data."""
    db = _find_state_db()
    if not db.exists():
        return []
    try:
        conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        c = conn.cursor()
        c.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'windsurf_auth-%-usages'")
        rows = c.fetchall()
        conn.close()
        accounts = []
        for key, val in rows:
            name = key.replace('windsurf_auth-', '').replace('-usages', '')
            try:
                data = json.loads(val)
            except Exception:
                data = val
            accounts.append({'name': name, 'data': data})
        return accounts
    except Exception as e:
        return [{'error': str(e)}]


# ============================================================
# Monitor Command
# ============================================================

def cmd_monitor():
    """Display current credit status."""
    info = read_plan_info()
    if 'error' in info:
        print(f"❌ {info['error']}")
        return info

    plan = info.get('planName', 'Unknown')
    usage = info.get('usage', {})
    total = usage.get('messages', 0)
    used = usage.get('usedMessages', 0)
    remaining = usage.get('remainingMessages', 0)
    flow_total = usage.get('flowActions', 0)
    flow_used = usage.get('usedFlowActions', 0)

    start_ts = info.get('startTimestamp', 0)
    end_ts = info.get('endTimestamp', 0)
    start_dt = datetime.fromtimestamp(start_ts / 1000) if start_ts else None
    end_dt = datetime.fromtimestamp(end_ts / 1000) if end_ts else None
    now = datetime.now()

    pct = (used / total * 100) if total > 0 else 0
    bar_len = 30
    filled = int(bar_len * pct / 100)
    bar = '█' * filled + '░' * (bar_len - filled)

    print('=' * 60)
    print(f'  Windsurf Credit Monitor v{VERSION}')
    print('=' * 60)
    print(f'  Plan: {plan}')
    if start_dt and end_dt:
        days_left = (end_dt - now).days
        print(f'  Period: {start_dt:%Y-%m-%d} → {end_dt:%Y-%m-%d} ({days_left}d left)')
    print()
    print(f'  Credits: [{bar}] {pct:.1f}%')
    print(f'  Used: {used:,} / {total:,}  |  Remaining: {remaining:,}')
    if flow_total > 0:
        print(f'  Flow Actions: {flow_used:,} / {flow_total:,}')
    print()

    # Daily burn rate
    if start_dt and used > 0:
        days_elapsed = max((now - start_dt).days, 1)
        daily_rate = used / days_elapsed
        days_left_at_rate = remaining / daily_rate if daily_rate > 0 else float('inf')
        print(f'  Daily burn rate: ~{daily_rate:.1f} credits/day')
        print(f'  Projected exhaustion: {days_left_at_rate:.0f} days')
        if end_dt:
            projected_total = daily_rate * (end_dt - start_dt).days
            print(f'  Projected total usage: {projected_total:.0f} / {total} by end of period')
    print()

    # Optimization tips
    print('  💡 Optimization Tips:')
    if pct > 50:
        print('  ⚠️  >50% used — switch to SWE-1.5/1.6 (0x) for routine tasks')
    if pct > 80:
        print('  🔴 >80% used — CRITICAL: use only free models until reset')
    print(f'  → SWE-1.5 = 0 credits (unlimited)')
    print(f'  → Opus规划(1cr) + SWE执行(0cr) + Opus验证(1cr) = 2cr total')
    print(f'  → vs 传统15-20cr per task = 5-10x savings')
    print('=' * 60)

    return {
        'plan': plan, 'total': total, 'used': used, 'remaining': remaining,
        'pct': pct, 'daily_rate': used / max((now - start_dt).days, 1) if start_dt else 0,
    }


# ============================================================
# Models Command
# ============================================================

def cmd_models():
    """Display model cost comparison."""
    print('=' * 70)
    print(f'  Model Cost Matrix (protobuf逆向, {len(MODEL_COSTS)} models)')
    print('=' * 70)
    print(f'  {"Model":<25} {"Cost":>6} {"Context":>8} {"Tier":<10} {"Note"}')
    print(f'  {"-"*25} {"-"*6} {"-"*8} {"-"*10} {"-"*20}')

    by_tier = {}
    for name, info in MODEL_COSTS.items():
        by_tier.setdefault(info['tier'], []).append((name, info))

    tier_order = ['free', 'budget', 'standard', 'premium', 'ultra', 'extreme']
    tier_icons = {'free': '🟢', 'budget': '🔵', 'standard': '⚪', 'premium': '🟡', 'ultra': '🟠', 'extreme': '🔴'}

    for tier in tier_order:
        models = by_tier.get(tier, [])
        if not models:
            continue
        for name, info in sorted(models, key=lambda x: x[1]['m']):
            icon = tier_icons.get(tier, '')
            cost_str = f"{info['m']}x" if info['m'] > 0 else 'FREE'
            print(f'  {icon} {name:<23} {cost_str:>6} {info["ctx"]:>8} {tier:<10} {info["note"]}')

    print()
    print('  📊 Cost per 25 invocations (1 prompt):')
    print('  → FREE models: 0 credits (unlimited prompts)')
    print('  → 1x models: 1 credit per prompt')
    print('  → 2x models: 2 credits per prompt')
    print('  → 4x models: 4 credits per prompt')
    print('  → 12x models: 12 credits per prompt (ONE prompt = 12 credits!)')
    print()
    print('  🏆 最优策略: Opus规划(4cr) → SWE-1.5执行(0cr) → Opus验证(4cr) = 8cr')
    print('     vs 纯Opus: 4cr × ~5 prompts = 20cr → 节省60%')
    print('     vs Sonnet+SWE: 2cr规划 + 0cr执行 + 2cr验证 = 4cr → 节省80%')
    print('=' * 70)


# ============================================================
# Delegate Command (SWE-1.5 Task Creation)
# ============================================================

DISPATCH_DIR = SCRIPT_DIR.parent.parent / '多模型协作' / 'dispatch'

DELEGATE_TEMPLATE = """# 委派任务 {task_id}

## 元信息
- **创建者**: 高层模型 (规划)
- **执行者**: SWE-1.5 (0x免费)
- **创建时间**: {created}
- **状态**: pending
- **积分节省**: ~{savings} credits

## 你的角色

你是SWE-1.5执行模型。精确执行以下任务。
遇到不确定的情况，在"执行结果"section记录问题并停止。

**约束**:
- 禁止修改 .windsurf/ 下规则文件
- 禁止修改 ~/.codeium/windsurf/ 配置
- 禁止交互式命令 (vim/nano/Read-Host/input())
- 网络命令加超时，国外资源加代理 `--proxy http://127.0.0.1:7890`
- 遇错2次停止报告

## 任务描述

{description}

## 精确步骤

{steps}

## 验证标准

{criteria}

## 执行结果 (SWE填写)

(待执行)
"""


def cmd_delegate(description, steps, criteria=None):
    """Create a SWE-1.5 delegation task."""
    DISPATCH_DIR.mkdir(parents=True, exist_ok=True)

    existing = list(DISPATCH_DIR.glob('task_*.md'))
    nums = [int(m.group(1)) for f in existing if (m := re.match(r'task_(\d+)', f.stem))]
    task_id = f'task_{(max(nums) + 1 if nums else 1):03d}'

    if not criteria:
        criteria = '- [ ] 任务完成\n- [ ] 无新错误引入\n- [ ] 代码可编译/运行'

    savings = 15  # estimated savings vs pure Opus

    content = DELEGATE_TEMPLATE.format(
        task_id=task_id,
        created=datetime.now().strftime('%Y-%m-%d %H:%M'),
        savings=savings,
        description=description.strip(),
        steps=steps.strip(),
        criteria=criteria.strip(),
    )

    task_file = DISPATCH_DIR / f'{task_id}.md'
    task_file.write_text(content, encoding='utf-8')
    task_path = str(task_file.resolve()).replace('\\', '/')

    print(f'✅ 任务创建: {task_id}')
    print(f'   文件: {task_path}')
    print(f'   预估节省: ~{savings} credits')
    print()
    print(f'📋 下一步:')
    print(f'   1. 切换模型到 SWE-1.5 (0 credits)')
    print(f'   2. 发送: 读取并精确执行 {task_path}')
    print(f'   3. SWE完成后切回高层模型验证结果')

    return {'task_id': task_id, 'file': task_path, 'savings': savings}


# ============================================================
# Recommend Command
# ============================================================

def cmd_recommend():
    """Generate optimization recommendations based on current state."""
    info = read_plan_info()
    print('=' * 60)
    print(f'  Credit Optimization Recommendations')
    print('=' * 60)

    if 'error' not in info:
        usage = info.get('usage', {})
        remaining = usage.get('remainingMessages', 0)
        total = usage.get('messages', 0)
        pct_used = ((total - remaining) / total * 100) if total > 0 else 0

        if pct_used > 80:
            urgency = '🔴 CRITICAL'
        elif pct_used > 50:
            urgency = '🟡 MODERATE'
        else:
            urgency = '🟢 HEALTHY'
        print(f'\n  Status: {urgency} ({pct_used:.0f}% used, {remaining} remaining)')

    print(f"""
  ━━━ Tier 0: 立即执行 (零成本) ━━━

  1. 🏆 SWE委派工作流
     Opus规划(1-4cr) → SWE-1.5执行(0cr) → Opus验证(1-4cr)
     节省: 5-10x (2-8cr vs 15-40cr)
     命令: python credit_toolkit.py delegate "描述" "步骤"

  2. 🆓 免费模型优先
     日常任务用: SWE-1.5 / SWE-1.6 / Gemini 3 Flash / Kimi K2.5
     所有0x模型 = 完全免费无限使用

  3. ⚡ Fast Context (code_search)
     1个code_search = 1 invocation = 替代5-10个read_file
     已在global_rules T1优先级

  ━━━ Tier 1: 行为优化 (已注入规则) ━━━

  4. 🔀 并行tool calls
     3个并行 = 1 invocation (vs 串行3 = 3 invocations)
     已在system prompt启用

  5. 📝 结构先行
     理解→设计→一次性正确实现
     避免重复错误循环 (Reddit最大痛点)

  ━━━ Tier 2: 技术突破 (P5实验) ━━━

  6. 🧪 ParallelRollout (实验性)
     P5 patch注入并行rollout配置
     理论: 2×25=50 invocations/prompt
     风险: 服务端可能忽略
     命令: python patch_continue_bypass.py (需Reload)
""")
    print('=' * 60)


# ============================================================
# HTTP Dashboard
# ============================================================

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>Windsurf Credit Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0a0a0f;color:#e0e0e0;padding:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px;max-width:1200px;margin:0 auto}
.card{background:#1a1a2e;border-radius:12px;padding:20px;border:1px solid #2a2a4e}
.card h3{color:#7b8cff;margin-bottom:12px;font-size:14px;text-transform:uppercase;letter-spacing:1px}
.metric{font-size:36px;font-weight:700;color:#fff}
.metric.free{color:#4ade80}
.metric.warn{color:#facc15}
.metric.danger{color:#ef4444}
.sub{font-size:13px;color:#888;margin-top:4px}
.bar{height:8px;background:#2a2a4e;border-radius:4px;margin:8px 0;overflow:hidden}
.bar-fill{height:100%;border-radius:4px;transition:width .3s}
.bar-fill.ok{background:linear-gradient(90deg,#4ade80,#22c55e)}
.bar-fill.warn{background:linear-gradient(90deg,#facc15,#f59e0b)}
.bar-fill.danger{background:linear-gradient(90deg,#ef4444,#dc2626)}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:6px 8px;text-align:left;border-bottom:1px solid #2a2a4e}
th{color:#7b8cff;font-weight:600}
.tier-free{color:#4ade80}.tier-budget{color:#60a5fa}.tier-standard{color:#e0e0e0}
.tier-premium{color:#facc15}.tier-ultra{color:#f97316}.tier-extreme{color:#ef4444}
h1{text-align:center;color:#7b8cff;margin-bottom:20px;font-size:20px}
.refresh{text-align:center;margin:16px 0;color:#555;font-size:12px}
</style></head><body>
<h1>⚡ Windsurf Credit Dashboard</h1>
<div class="refresh" id="ts">Loading...</div>
<div class="grid" id="grid"></div>
<script>
async function load(){
  const r=await fetch('/api/status');const d=await r.json();
  document.getElementById('ts').textContent='Updated: '+new Date().toLocaleTimeString();
  const g=document.getElementById('grid');
  const pct=d.total>0?((d.used/d.total)*100):0;
  const cls=pct>80?'danger':pct>50?'warn':'free';
  g.innerHTML=`
  <div class="card"><h3>Credits Status</h3>
    <div class="metric ${cls}">${d.remaining.toLocaleString()}</div>
    <div class="sub">remaining of ${d.total.toLocaleString()}</div>
    <div class="bar"><div class="bar-fill ${cls}" style="width:${pct}%"></div></div>
    <div class="sub">${pct.toFixed(1)}% used | Plan: ${d.plan}</div>
  </div>
  <div class="card"><h3>Burn Rate</h3>
    <div class="metric">${d.daily_rate.toFixed(1)}</div>
    <div class="sub">credits/day</div>
    <div class="sub" style="margin-top:8px">
      Projected exhaustion: ${d.days_left.toFixed(0)} days<br>
      Period ends: ${d.end_date||'N/A'}
    </div>
  </div>
  <div class="card"><h3>Optimization</h3>
    <div class="sub" style="line-height:1.8">
      🏆 <b>SWE-1.5</b> = 0 credits (unlimited)<br>
      💡 Opus plan + SWE exec + Opus verify = <b>2-8 cr</b><br>
      ⚠️ vs Pure Opus = <b>20-40 cr</b> per task<br>
      ⚡ Fast Context = 1 invocation = N searches<br>
      🔀 Parallel tools = 3→1 invocation
    </div>
  </div>
  <div class="card"><h3>Model Cost Matrix</h3>
    <table><tr><th>Model</th><th>Cost</th><th>Tier</th></tr>
    ${d.models.map(m=>`<tr><td>${m.name}</td><td class="tier-${m.tier}">${m.cost}</td><td class="tier-${m.tier}">${m.tier}</td></tr>`).join('')}
    </table>
  </div>`;
}
load();setInterval(load,30000);
</script></body></html>"""


class DashHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/dashboard':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())
        elif self.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            info = read_plan_info()
            usage = info.get('usage', {})
            total = usage.get('messages', 0)
            used = usage.get('usedMessages', 0)
            remaining = usage.get('remainingMessages', 0)
            start_ts = info.get('startTimestamp', 0)
            end_ts = info.get('endTimestamp', 0)
            now = datetime.now()
            start_dt = datetime.fromtimestamp(start_ts / 1000) if start_ts else now
            end_dt = datetime.fromtimestamp(end_ts / 1000) if end_ts else None
            days_elapsed = max((now - start_dt).days, 1)
            daily_rate = used / days_elapsed if used > 0 else 0
            days_left = remaining / daily_rate if daily_rate > 0 else 999

            models = [{'name': n, 'cost': f"{i['m']}x" if i['m'] > 0 else 'FREE', 'tier': i['tier']}
                      for n, i in sorted(MODEL_COSTS.items(), key=lambda x: x[1]['m'])]

            data = {
                'plan': info.get('planName', '?'), 'total': total, 'used': used,
                'remaining': remaining, 'daily_rate': daily_rate, 'days_left': days_left,
                'end_date': end_dt.strftime('%Y-%m-%d') if end_dt else None,
                'models': models, 'accounts': len(read_account_usages()),
            }
            self.wfile.write(json.dumps(data).encode())
        elif self.path == '/api/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok', 'version': VERSION}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass  # suppress logs


def cmd_serve(port=19910):
    """Start HTTP dashboard."""
    server = HTTPServer(('127.0.0.1', port), DashHandler)
    print(f'Credit Dashboard: http://127.0.0.1:{port}/')
    print(f'API: http://127.0.0.1:{port}/api/status')
    print('Press Ctrl+C to stop')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


# ============================================================
# E2E Self-Test
# ============================================================

def cmd_test():
    """Run E2E self-test."""
    print(f'Credit Toolkit v{VERSION} — E2E Test')
    print('=' * 50)
    results = []

    # T1: Read plan info
    try:
        info = read_plan_info()
        ok = 'error' not in info
        detail = f"plan={info.get('planName','?')}, remaining={info.get('usage',{}).get('remainingMessages','?')}" if ok else info.get('error','')
        results.append(('read_plan_info', ok, detail))
    except Exception as e:
        results.append(('read_plan_info', False, str(e)))

    # T2: Read accounts
    try:
        accts = read_account_usages()
        ok = isinstance(accts, list) and (len(accts) == 0 or 'error' not in accts[0])
        results.append(('read_accounts', ok, f'{len(accts)} accounts'))
    except Exception as e:
        results.append(('read_accounts', False, str(e)))

    # T3: Model matrix
    try:
        free = [n for n, i in MODEL_COSTS.items() if i['m'] == 0]
        results.append(('model_matrix', len(free) >= 4, f'{len(MODEL_COSTS)} models, {len(free)} free'))
    except Exception as e:
        results.append(('model_matrix', False, str(e)))

    # T4: Delegate (dry run)
    try:
        DISPATCH_DIR.mkdir(parents=True, exist_ok=True)
        test_id = '_test_credit_toolkit'
        test_file = DISPATCH_DIR / f'{test_id}.md'
        content = DELEGATE_TEMPLATE.format(
            task_id=test_id, created='test', savings=15,
            description='E2E test task', steps='1. Verify', criteria='- [ ] pass',
        )
        test_file.write_text(content, encoding='utf-8')
        ok = test_file.exists() and test_file.stat().st_size > 100
        results.append(('delegate_create', ok, f'{test_file.stat().st_size}B'))
        test_file.unlink()
    except Exception as e:
        results.append(('delegate_create', False, str(e)))

    # T5: Dashboard API (quick local test)
    try:
        import urllib.request
        port = 19911  # test port
        server = HTTPServer(('127.0.0.1', port), DashHandler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        time.sleep(0.3)
        resp = urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=3)
        data = json.loads(resp.read())
        ok = data.get('status') == 'ok'
        results.append(('dashboard_api', ok, json.dumps(data)))
        server.server_close()
    except Exception as e:
        results.append(('dashboard_api', False, str(e)))

    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, detail in results:
        icon = '✅' if ok else '❌'
        print(f'  {icon} {name}: {detail[:80]}')
    print(f'\n{passed}/{len(results)} PASS')
    return results


# ============================================================
# CLI Bridge Integration (Semi-Automated SWE Delegation)
# ============================================================

BRIDGE_URL = 'http://127.0.0.1:19850'

def _bridge_call(endpoint, method='GET', data=None):
    """Call CLI Bridge HTTP API."""
    import urllib.request
    url = f'{BRIDGE_URL}{endpoint}'
    req_data = json.dumps(data).encode() if data else None
    headers = {'Content-Type': 'application/json'} if data else {}
    try:
        req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {'error': str(e)}


def bridge_online():
    """Check if CLI Bridge is online."""
    r = _bridge_call('/api/health')
    return r.get('status') == 'ok'


def cmd_auto_delegate(description, steps, criteria=None):
    """Create task + inject into new Cascade conversation via CLI Bridge.
    
    Flow:
    1. Create task file (dispatch/)
    2. Open new Cascade conversation (CLI Bridge)
    3. Inject task instruction text
    4. Submit (the CURRENT model will execute)
    
    For 0-credit execution: switch to SWE-1.5 BEFORE running this.
    """
    # Step 0: Check CLI Bridge
    if not bridge_online():
        print('❌ CLI Bridge :19850 offline — falling back to manual delegation')
        return cmd_delegate(description, steps, criteria)

    # Step 1: Create task file
    result = cmd_delegate(description, steps, criteria)
    task_path = result.get('file', '')
    if not task_path:
        return result

    print()
    print('🔗 CLI Bridge detected — semi-automated injection available')
    print()
    print('⚠️  重要: 确保当前模型是 SWE-1.5 (0 credits)')
    print('   如果不是，请先在模型选择器中切换到 SWE-1.5')
    print()
    
    confirm = input('注入任务到新对话? (y/N): ').strip().lower()
    if confirm != 'y':
        print('已取消。手动执行: 切换SWE-1.5 → 发送任务文件路径')
        return result

    # Step 2: Open new conversation
    print('  📝 Opening new conversation...')
    r1 = _bridge_call('/api/execute', 'POST', {
        'command': 'windsurf.sendChatActionMessage',
        'args': [{'actionType': 17}]  # CHAT_NEW_CONVERSATION
    })
    if 'error' in r1:
        print(f'  ❌ New conversation failed: {r1["error"]}')
        return result
    time.sleep(1)

    # Step 3: Insert task instruction
    instruction = f'读取并精确执行此委派任务文件: {task_path}'
    print(f'  💬 Injecting: {instruction[:60]}...')
    r2 = _bridge_call('/api/execute', 'POST', {
        'command': 'windsurf.sendTextToChat',
        'args': [instruction]
    })
    if 'error' in r2:
        print(f'  ❌ Text injection failed: {r2["error"]}')
        return result
    time.sleep(0.5)

    # Step 4: Submit
    print('  🚀 Submitting...')
    r3 = _bridge_call('/api/execute', 'POST', {
        'command': 'workbench.action.chat.stopListeningAndSubmit'
    })

    print()
    print('✅ 任务已注入新对话！')
    print(f'   如果使用SWE-1.5: 0 credits consumed')
    print(f'   任务完成后切回当前对话验证结果')

    result['injected'] = True
    result['bridge_results'] = {'new_conv': r1, 'text': r2, 'submit': r3}
    return result


# ============================================================
# CLI Entry Point
# ============================================================

def cmd_cost():
    """Estimate daily token cost for current model."""
    model = read_current_model()
    quota = read_quota_status()
    print(f'=== Token Cost Analyzer (v{VERSION}) ===')
    print(f'Current model: {model}')
    print(f'Plan: {quota.get("plan","?")} | Daily: {quota.get("quota",{}).get("dailyRemaining","?")}%')
    msgs, avg_in, avg_out = 30, 4000, 2000
    cost = calc_cost(model if model in ANTHROPIC_PRICING else 'Claude Sonnet 4.6', msgs*avg_in, msgs*avg_out)
    mo = cost['total_usd'] * 30
    print(f'\nEstimated daily ({msgs} msgs): ${cost["total_usd"]:.4f} / ¥{cost["total_cny"]:.2f}')
    print(f'Monthly (x30): ${mo:.2f} / ¥{mo*CNY_PER_USD:.2f}')
    xc = xianyu_compare(mo)
    print(f'\nXianYu Pro: ¥{xc["xianyu"]}/account vs API ¥{xc["api_cny"]:.2f} = 1:{xc["ratio"]:.0f}')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'monitor'

    if cmd == 'monitor':
        cmd_monitor()
    elif cmd == 'models':
        cmd_models()
    elif cmd == 'cost':
        cmd_cost()
    elif cmd == 'delegate':
        desc = sys.argv[2] if len(sys.argv) > 2 else input('任务描述: ')
        steps = sys.argv[3] if len(sys.argv) > 3 else input('执行步骤: ')
        cmd_delegate(desc, steps)
    elif cmd == 'auto-delegate':
        desc = sys.argv[2] if len(sys.argv) > 2 else input('任务描述: ')
        steps = sys.argv[3] if len(sys.argv) > 3 else input('执行步骤: ')
        cmd_auto_delegate(desc, steps)
    elif cmd == 'recommend':
        cmd_recommend()
    elif cmd == 'serve':
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 19910
        cmd_serve(port)
    elif cmd == 'test':
        cmd_test()
    else:
        print(f'Credit Toolkit v{VERSION}')
        print('Commands: monitor | models | cost | delegate | auto-delegate | recommend | serve | test')
