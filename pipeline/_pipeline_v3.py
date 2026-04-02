"""
Windsurf 全链路引擎 v3 — 万法归宗·道法自然·一推到底
====================================================
从邮箱之源到Pro Trial获取到监控使用 — 全链路自动化

Phase 0: 号池全景 (status/dashboard)
Phase 1: 邮箱之源 (Yahoo/Gmail/自建域名/GitHub — 继承v2)
Phase 2: 虚拟卡之源 (VCCWave/Privacy.com/Revolut API研究)
Phase 3: Windsurf注册+激活 (DrissionPage + turnstilePatch — 继承v2)
Phase 4: Pro升级 (虚拟卡 → Stripe支付流程)
Phase 5: 生命周期管理 (到期监控 → 自动补充 → 号池自愈)
Phase 6: 号池注入 (→ 无感切号VSIX)

用法:
  python _pipeline_v3.py status              # 号池全景 + 到期预警
  python _pipeline_v3.py monitor             # 启动生命周期监控(长驻)
  python _pipeline_v3.py inject              # 注入新账号到无感切号
  python _pipeline_v3.py vcard list          # 虚拟卡服务商列表
  python _pipeline_v3.py vcard check         # 检查可用虚拟卡API
  python _pipeline_v3.py autopilot           # 全自动驾驶(监控+注册+注入)
  python _pipeline_v3.py register [path]     # 注册1个(继承v2路径)
  python _pipeline_v3.py batch N [path]      # 批量注册N个
  python _pipeline_v3.py dashboard           # 启动Web Dashboard :19920
"""

import json, os, sys, time, random, string, re, base64, subprocess, hashlib, hmac
from pathlib import Path
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
CST = timezone(timedelta(hours=8))

# === 路径配置 ===
ACCT_FILE = Path(os.environ.get('APPDATA', '')) / 'Windsurf' / 'User' / 'globalStorage' / 'windsurf-login-accounts.json'
VSIX_ACCT_FILE = Path(os.environ.get('APPDATA', '')) / 'Windsurf' / 'User' / 'globalStorage' / 'zhouyoukang.windsurf-assistant' / 'windsurf-assistant-accounts.json'
RESULTS_FILE = SCRIPT_DIR / "_pipeline_v3_results.json"
LIFECYCLE_LOG = SCRIPT_DIR / "_lifecycle.log"
VCARD_CACHE = SCRIPT_DIR / "_vcard_cache.json"
PROXY_CANDIDATES = ["http://127.0.0.1:7890", "http://127.0.0.1:7897"]


def log(msg, ok=None, to_file=True):
    icon = "+" if ok is True else ("-" if ok is False else "*")
    ts = datetime.now(CST).strftime("%H:%M:%S")
    line = f"  [{ts}][{icon}] {msg}"
    print(line)
    if to_file:
        try:
            with open(LIFECYCLE_LOG, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now(CST).strftime('%Y-%m-%d')} {line}\n")
        except:
            pass


def load_accounts():
    """Load accounts from Windsurf login-helper file"""
    if ACCT_FILE.exists():
        try:
            return json.load(open(ACCT_FILE, 'r', encoding='utf-8'))
        except:
            pass
    return []


def save_accounts(accounts):
    """Save accounts back to Windsurf login-helper file"""
    ACCT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ACCT_FILE, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)


def load_results():
    if RESULTS_FILE.exists():
        try:
            return json.load(open(RESULTS_FILE, 'r', encoding='utf-8'))
        except:
            pass
    return []


def save_result(result):
    results = load_results()
    results.append(result)
    with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)


def find_proxy():
    for p in PROXY_CANDIDATES:
        try:
            ps = ['$ProgressPreference="SilentlyContinue"',
                  f'try {{ (Invoke-WebRequest -Uri "https://httpbin.org/ip" -Proxy "{p}" -TimeoutSec 5 -UseBasicParsing).StatusCode }} catch {{ "FAIL" }}']
            enc = base64.b64encode('\n'.join(ps).encode('utf-16-le')).decode()
            r = subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", enc],
                               capture_output=True, text=True, timeout=12, encoding='utf-8', errors='replace')
            if r.stdout.strip() and "FAIL" not in r.stdout:
                return p
        except:
            continue
    return PROXY_CANDIDATES[0]


# ============================================================
# PHASE 0: 号池全景 — Status
# ============================================================
def show_status():
    accounts = load_accounts()
    now_ms = time.time() * 1000
    now = datetime.now(CST)

    print(f"\n{'═' * 75}")
    print(f"  WINDSURF 号池全景 v3 — {now.strftime('%Y-%m-%d %H:%M:%S CST')}")
    print(f"{'═' * 75}")

    if not accounts:
        print("  号池为空! 请先注册账号。")
        print(f"  命令: python {Path(__file__).name} register")
        print(f"{'═' * 75}\n")
        return

    # Classify accounts
    real_accounts = [a for a in accounts if '@' in a.get('email', '') and 'example' not in a.get('email', '') and 'ex.com' not in a.get('email', '')]
    test_accounts = [a for a in accounts if a not in real_accounts]

    print(f"\n  总账号: {len(accounts)} (真实: {len(real_accounts)} | 测试: {len(test_accounts)})")

    # Plan distribution
    from collections import Counter
    plans = Counter(a.get('usage', {}).get('plan', '?') for a in real_accounts)
    print(f"  计划分布: {dict(plans)}")

    # Health stats
    healthy = low = exhausted = 0
    trial_days = []
    expiring_soon = []

    print(f"\n  {'Email':42} {'Plan':8} {'D%':>4} {'W%':>4} {'Eff%':>5} {'Days':>6} {'Status':>8}")
    print(f"  {'-' * 78}")

    for a in real_accounts:
        e = a.get('email', '?')
        u = a.get('usage', {})
        plan = u.get('plan', '?')
        dr = u.get('daily', {}).get('remaining', 0) if u.get('daily') else 0
        wr = u.get('weekly', {}).get('remaining', 0) if u.get('weekly') else 0
        eff = min(dr, wr)
        pe = u.get('planEnd', 0)
        days = max(0, (pe - now_ms) / 86400000) if pe else -1

        if days >= 0:
            trial_days.append(days)
        if 0 <= days <= 5:
            expiring_soon.append((e, days))

        if eff > 15:
            healthy += 1
            status = "🟢"
        elif eff > 5:
            healthy += 1
            status = "🟡"
        elif eff > 0:
            low += 1
            status = "🟠"
        else:
            exhausted += 1
            status = "🔴"

        email_display = e[:40] if len(e) > 40 else e
        days_str = f"{days:.1f}" if days >= 0 else "N/A"
        print(f"  {email_display:42} {plan:8} {dr:>4} {wr:>4} {eff:>5} {days_str:>6} {status:>8}")

    print(f"  {'-' * 78}")
    print(f"  健康: {healthy} | 低配额: {low} | 耗尽: {exhausted}")

    # Trial timeline
    if trial_days:
        trial_days.sort()
        print(f"\n  Trial剩余: {trial_days[0]:.1f} ~ {trial_days[-1]:.1f} 天")
        for d in [1, 3, 5, 7, 10, 14]:
            alive = sum(1 for t in trial_days if t > d)
            print(f"    {d}天后存活: {alive}/{len(trial_days)}")

    # Expiration alerts
    if expiring_soon:
        print(f"\n  ⚠️  即将到期 (≤5天):")
        for e, d in sorted(expiring_soon, key=lambda x: x[1]):
            print(f"    {e[:42]:42} {d:.1f}天")

    # Recommendations
    print(f"\n  {'─' * 40}")
    print(f"  推荐行动:")
    if len(real_accounts) < 10:
        print(f"    🔥 号池不足10个! 建议立即注册补充")
        print(f"       python {Path(__file__).name} batch 5")
    if expiring_soon:
        print(f"    ⏰ {len(expiring_soon)}个账号即将到期, 补充新账号")
    if exhausted > 0:
        print(f"    🔴 {exhausted}个账号配额耗尽, 等待重置或切换")
    if not expiring_soon and healthy >= 5:
        print(f"    ✅ 号池健康, 无需紧急操作")

    # Pipeline v3 results
    results = load_results()
    if results:
        print(f"\n  Pipeline v3 注册历史: {len(results)}条")
        for r in results[-5:]:
            print(f"    {r.get('timestamp', '?')[:19]} {r.get('email', '?')[:35]:35} {r.get('status', '?')}")

    print(f"\n{'═' * 75}\n")


# ============================================================
# PHASE 2: 虚拟卡之源 — Virtual Card Providers
# ============================================================

VCARD_PROVIDERS = [
    {
        "name": "Privacy.com",
        "url": "https://privacy.com",
        "api": "https://api.privacy.com/v1/card",
        "type": "real_debit",
        "cost": "Free (US bank required)",
        "region": "US only",
        "api_available": True,
        "notes": "Creates real virtual debit cards. Requires US bank account linking. API key from dashboard.",
        "auth": "API Key (Bearer token)",
        "endpoints": {
            "create_card": "POST /v1/card {type: 'SINGLE_USE', spend_limit: 100, spend_limit_duration: 'TRANSACTION'}",
            "list_cards": "GET /v1/card",
        },
    },
    {
        "name": "Revolut",
        "url": "https://www.revolut.com",
        "api": "https://b2b.revolut.com/api/1.0",
        "type": "real_debit",
        "cost": "Free with account",
        "region": "EU/UK",
        "api_available": True,
        "notes": "Virtual cards via Business API. Requires Revolut Business account.",
        "auth": "OAuth2",
        "endpoints": {
            "create_card": "POST /cards {virtual: true, holder_id: '...'}",
        },
    },
    {
        "name": "Wise (TransferWise)",
        "url": "https://wise.com",
        "api": "https://api.wise.com/v2",
        "type": "real_debit",
        "cost": "Free with balance",
        "region": "Global",
        "api_available": True,
        "notes": "Virtual debit cards. Requires Wise account with balance.",
        "auth": "API Key",
        "endpoints": {},
    },
    {
        "name": "VCCWave",
        "url": "https://vccwave.com",
        "api": None,
        "type": "virtual_prepaid",
        "cost": "Free (claimed)",
        "region": "Global",
        "api_available": False,
        "notes": "Web-based virtual card generator. No API. Manual use only.",
        "auth": None,
        "endpoints": {},
    },
    {
        "name": "Getsby",
        "url": "https://getsby.com",
        "api": None,
        "type": "prepaid",
        "cost": "Paid (€5+ load)",
        "region": "EU",
        "api_available": False,
        "notes": "Prepaid virtual Visa cards. No monthly fee but requires loading funds.",
        "auth": None,
        "endpoints": {},
    },
    {
        "name": "Namso Generator",
        "url": "https://namso-gen.com",
        "api": None,
        "type": "test_numbers",
        "cost": "Free",
        "region": "N/A",
        "api_available": False,
        "notes": "Generates Luhn-valid card numbers for TESTING ONLY. Will NOT pass real payment processors.",
        "auth": None,
        "endpoints": {},
    },
]


def luhn_checksum(card_number):
    """Calculate Luhn checksum digit"""
    digits = [int(d) for d in str(card_number)]
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    total = sum(odd_digits)
    for d in even_digits:
        total += sum(divmod(d * 2, 10))
    return total % 10


def generate_test_card(bin_prefix="4242424242", length=16):
    """Generate a Luhn-valid test card number (for testing ONLY — will not pass real payments)"""
    prefix = str(bin_prefix)
    remaining = length - len(prefix) - 1
    body = prefix + ''.join(random.choices('0123456789', k=remaining))
    # Calculate check digit
    for check in range(10):
        candidate = body + str(check)
        if luhn_checksum(candidate) == 0:
            return candidate
    return body + '0'


def show_vcard_list():
    """Show available virtual card providers"""
    print(f"\n{'═' * 70}")
    print(f"  虚拟卡服务商列表 — 道法自然")
    print(f"{'═' * 70}")
    print()
    print(f"  ⚠️  Windsurf Pro Trial 不需要信用卡! Trial是免费的。")
    print(f"  ⚠️  虚拟卡仅用于: Pro计划($20/月) / Extra Usage / 其他付费服务")
    print()

    for i, p in enumerate(VCARD_PROVIDERS, 1):
        api_icon = "✅" if p["api_available"] else "❌"
        print(f"  [{i}] {p['name']}")
        print(f"      URL:  {p['url']}")
        print(f"      类型: {p['type']} | 成本: {p['cost']} | 区域: {p['region']}")
        print(f"      API:  {api_icon} {p.get('api', 'N/A')}")
        print(f"      说明: {p['notes']}")
        if p.get('endpoints'):
            for name, endpoint in p['endpoints'].items():
                print(f"        {name}: {endpoint}")
        print()

    print(f"  {'─' * 40}")
    print(f"  推荐路径:")
    print(f"    1. Privacy.com — 最佳(美国用户), 免费创建一次性虚拟卡")
    print(f"    2. Revolut — 最佳(欧洲用户), 免费虚拟卡")
    print(f"    3. Wise — 全球可用, 需要余额")
    print(f"    4. 对于Trial轮换: 完全不需要任何卡!")
    print(f"\n{'═' * 70}\n")


def check_vcard_apis():
    """Check which virtual card APIs are reachable"""
    print(f"\n{'═' * 70}")
    print(f"  虚拟卡API可达性检查")
    print(f"{'═' * 70}\n")

    proxy = find_proxy()
    log(f"Using proxy: {proxy}")

    for p in VCARD_PROVIDERS:
        if not p.get('api'):
            print(f"  [{p['name']:20}] ❌ No API available")
            continue

        url = p['api']
        try:
            ps = ['$ProgressPreference="SilentlyContinue"',
                  f'try {{ $r = Invoke-WebRequest -Uri "{url}" -Method HEAD -TimeoutSec 8 -UseBasicParsing -Proxy "{proxy}"; $r.StatusCode }} catch {{ $_.Exception.Response.StatusCode.value__ }}']
            enc = base64.b64encode('\n'.join(ps).encode('utf-16-le')).decode()
            r = subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", enc],
                               capture_output=True, text=True, timeout=15,
                               encoding='utf-8', errors='replace')
            status = r.stdout.strip()
            if status and status.isdigit():
                code = int(status)
                icon = "✅" if code < 500 else "⚠️"
                print(f"  [{p['name']:20}] {icon} HTTP {code} — {url}")
            else:
                print(f"  [{p['name']:20}] ⚠️  Response: {status[:50]}")
        except Exception as e:
            print(f"  [{p['name']:20}] ❌ Error: {str(e)[:50]}")

    # Generate a test card for reference
    print(f"\n  {'─' * 40}")
    print(f"  测试卡号 (仅测试, 不可用于真实支付):")
    for prefix, brand in [("4242424242", "Visa"), ("5425233430", "Mastercard")]:
        card = generate_test_card(prefix)
        exp = f"{random.randint(1,12):02d}/{random.randint(26,30)}"
        cvv = f"{random.randint(100,999)}"
        print(f"    {brand}: {card} | Exp: {exp} | CVV: {cvv}")

    print(f"\n{'═' * 70}\n")


# ============================================================
# PHASE 5: 生命周期管理 — Lifecycle Monitor
# ============================================================

def analyze_lifecycle():
    """Analyze account lifecycle and return action recommendations"""
    accounts = load_accounts()
    now_ms = time.time() * 1000

    real = [a for a in accounts
            if '@' in a.get('email', '')
            and 'example' not in a.get('email', '')
            and 'ex.com' not in a.get('email', '')]

    stats = {
        'total': len(real),
        'healthy': 0,
        'low': 0,
        'exhausted': 0,
        'expiring_3d': [],
        'expiring_7d': [],
        'expired': [],
        'trial_days': [],
        'need_register': 0,
    }

    for a in real:
        u = a.get('usage', {})
        dr = u.get('daily', {}).get('remaining', 0) if u.get('daily') else 0
        wr = u.get('weekly', {}).get('remaining', 0) if u.get('weekly') else 0
        eff = min(dr, wr)
        pe = u.get('planEnd', 0)
        days = max(0, (pe - now_ms) / 86400000) if pe else -1

        if eff > 5:
            stats['healthy'] += 1
        elif eff > 0:
            stats['low'] += 1
        else:
            stats['exhausted'] += 1

        if days >= 0:
            stats['trial_days'].append(days)
            if days <= 0:
                stats['expired'].append(a.get('email', '?'))
            elif days <= 3:
                stats['expiring_3d'].append(a.get('email', '?'))
            elif days <= 7:
                stats['expiring_7d'].append(a.get('email', '?'))

    # Calculate how many new accounts needed
    target_pool = 10  # Minimum healthy pool size
    alive_in_7d = sum(1 for t in stats['trial_days'] if t > 7)
    stats['need_register'] = max(0, target_pool - alive_in_7d)

    return stats


def run_monitor(interval=300, auto_register=False):
    """
    Long-running lifecycle monitor.
    Checks account pool every `interval` seconds.
    Optionally triggers auto-registration when pool is low.
    """
    print(f"\n{'═' * 70}")
    print(f"  生命周期监控 — 道法自然·上善若水")
    print(f"  间隔: {interval}s | 自动注册: {'ON' if auto_register else 'OFF'}")
    print(f"  Ctrl+C 停止")
    print(f"{'═' * 70}\n")

    cycle = 0
    while True:
        cycle += 1
        now = datetime.now(CST)
        log(f"===== 周期 #{cycle} — {now.strftime('%H:%M:%S')} =====")

        stats = analyze_lifecycle()

        log(f"号池: {stats['total']}个 | 健康:{stats['healthy']} 低:{stats['low']} 耗尽:{stats['exhausted']}")

        if stats['trial_days']:
            min_d = min(stats['trial_days'])
            max_d = max(stats['trial_days'])
            log(f"Trial: {min_d:.1f}~{max_d:.1f}天")

        if stats['expired']:
            log(f"⚠️ 已过期: {len(stats['expired'])}个", False)
        if stats['expiring_3d']:
            log(f"⏰ 3天内到期: {len(stats['expiring_3d'])}个", False)
            for e in stats['expiring_3d']:
                log(f"  → {e}")
        if stats['expiring_7d']:
            log(f"📅 7天内到期: {len(stats['expiring_7d'])}个")

        if stats['need_register'] > 0:
            log(f"🔥 需补充: {stats['need_register']}个账号 (目标池>=10)")
            if auto_register:
                log("自动注册模式: 触发注册...", True)
                # Import v2 pipeline for registration
                try:
                    from _pipeline_v2 import path_yahoo, path_tempmail
                    log("尝试tempmail全自动注册...")
                    result = path_tempmail()
                    if result:
                        log(f"注册成功: {result.get('email')}", True)
                        save_result(result)
                        inject_to_vsix(result)
                    else:
                        log("tempmail注册失败, 需手动Yahoo注册", False)
                except Exception as e:
                    log(f"自动注册异常: {e}", False)
        else:
            log("✅ 号池充足, 无需操作", True)

        log(f"下次检查: {(now + timedelta(seconds=interval)).strftime('%H:%M:%S')}")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            log("监控已停止")
            break


# ============================================================
# PHASE 6: 号池注入 — Pool Injector
# ============================================================

def inject_to_vsix(account_data):
    """Inject a new account into the 无感切号 VSIX account file"""
    if not VSIX_ACCT_FILE.parent.exists():
        log(f"VSIX账号目录不存在: {VSIX_ACCT_FILE.parent}", False)
        return False

    # Load existing VSIX accounts
    vsix_accounts = []
    if VSIX_ACCT_FILE.exists():
        try:
            vsix_accounts = json.load(open(VSIX_ACCT_FILE, 'r', encoding='utf-8'))
            if not isinstance(vsix_accounts, list):
                vsix_accounts = []
        except:
            vsix_accounts = []

    email = account_data.get('email', '')
    if not email:
        log("账号无email字段", False)
        return False

    # Check if already exists
    existing_emails = {a.get('email', '') for a in vsix_accounts}
    if email in existing_emails:
        log(f"账号已存在于VSIX号池: {email}")
        return True

    # Format for VSIX
    vsix_entry = {
        "email": email,
        "password": account_data.get('password', account_data.get('windsurf_password', '')),
        "source": account_data.get('path', 'pipeline_v3'),
        "injected_at": datetime.now(CST).isoformat(),
    }

    vsix_accounts.append(vsix_entry)

    with open(VSIX_ACCT_FILE, 'w', encoding='utf-8') as f:
        json.dump(vsix_accounts, f, indent=2, ensure_ascii=False)

    log(f"已注入VSIX号池: {email}", True)
    return True


def inject_all_to_vsix():
    """Inject all accounts from login-helper to VSIX"""
    accounts = load_accounts()
    if not accounts:
        log("号池为空, 无可注入账号", False)
        return

    real = [a for a in accounts
            if '@' in a.get('email', '')
            and 'example' not in a.get('email', '')
            and 'ex.com' not in a.get('email', '')]

    log(f"准备注入 {len(real)} 个账号到无感切号...")
    injected = 0
    for a in real:
        if inject_to_vsix(a):
            injected += 1

    log(f"注入完成: {injected}/{len(real)}", True)

    # Also inject to main login-helper from v3 results
    results = load_results()
    new_results = [r for r in results if r.get('status') in ('registered', 'verified')]
    for r in new_results:
        if r.get('email') not in {a.get('email', '') for a in accounts}:
            accounts.append({
                'email': r['email'],
                'password': r.get('windsurf_password', r.get('password', '')),
                'loginCount': 0,
                'credits': 0,
                'usage': {'plan': 'Trial', 'mode': 'quota'},
            })
            log(f"已添加到login-helper: {r['email']}", True)

    save_accounts(accounts)


# ============================================================
# PHASE: Register (delegate to v2)
# ============================================================

def register_one(path='yahoo'):
    """Register one account using v2 pipeline"""
    log(f"启动注册 (路径: {path})...")

    # Import from v2
    v2_path = SCRIPT_DIR / "_pipeline_v2.py"
    if not v2_path.exists():
        log(f"Pipeline v2 不存在: {v2_path}", False)
        return None

    # Execute v2 pipeline
    cmd = f'python "{v2_path}" {path}'
    log(f"执行: {cmd}")

    try:
        r = subprocess.run(
            ["python", str(v2_path), path],
            cwd=str(SCRIPT_DIR),
            timeout=600,  # 10 minutes max
        )
        if r.returncode == 0:
            log("注册流程完成", True)
        else:
            log(f"注册流程退出码: {r.returncode}", False)
    except subprocess.TimeoutExpired:
        log("注册超时(10分钟)", False)
    except Exception as e:
        log(f"注册异常: {e}", False)


def batch_register(count, path='yahoo'):
    """Batch register multiple accounts"""
    log(f"批量注册: {count}个, 路径: {path}")

    for i in range(count):
        print(f"\n{'─' * 50} [{i+1}/{count}] {'─' * 50}")
        register_one(path)
        if i < count - 1:
            delay = random.uniform(10, 30)
            log(f"冷却 {delay:.0f}s...")
            time.sleep(delay)

    log(f"批量注册完成: {count}个", True)


# ============================================================
# DASHBOARD — Web Dashboard
# ============================================================

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Windsurf Pipeline v3 Dashboard</title>
<style>
:root { --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #c9d1d9;
        --accent: #58a6ff; --green: #3fb950; --yellow: #d29922; --red: #f85149; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 20px; }
h1 { color: var(--accent); margin-bottom: 20px; font-size: 1.5em; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 16px; margin-bottom: 24px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.card h3 { color: var(--accent); font-size: 0.9em; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px; }
.big-num { font-size: 2.5em; font-weight: bold; }
.green { color: var(--green); } .yellow { color: var(--yellow); } .red { color: var(--red); }
table { width: 100%; border-collapse: collapse; margin-top: 16px; }
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); font-size: 0.85em; }
th { color: var(--accent); font-weight: 600; }
.bar { height: 6px; border-radius: 3px; background: var(--border); overflow: hidden; }
.bar-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
.status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.actions { margin-top: 20px; }
.btn { display: inline-block; padding: 8px 16px; border-radius: 6px; background: var(--accent); color: #fff; border: none;
       cursor: pointer; font-size: 0.85em; margin-right: 8px; text-decoration: none; }
.btn:hover { opacity: 0.9; }
.btn-warn { background: var(--yellow); } .btn-danger { background: var(--red); }
.refresh-time { color: #8b949e; font-size: 0.8em; margin-top: 8px; }
</style>
</head>
<body>
<h1>Windsurf Pipeline v3 — Dashboard</h1>
<div id="app">Loading...</div>
<script>
async function loadData() {
  const r = await fetch('/api/status');
  const d = await r.json();
  render(d);
}
function render(d) {
  const app = document.getElementById('app');
  const accts = d.accounts || [];
  const real = accts.filter(a => a.email && !a.email.includes('example') && !a.email.includes('ex.com'));
  let healthy=0, low=0, exhausted=0, trialDays=[];
  const now = Date.now();
  real.forEach(a => {
    const u = a.usage||{};
    const dr = (u.daily||{}).remaining||0, wr = (u.weekly||{}).remaining||0;
    const eff = Math.min(dr, wr);
    if(eff>5) healthy++; else if(eff>0) low++; else exhausted++;
    const pe = u.planEnd||0;
    if(pe) trialDays.push(Math.max(0,(pe-now)/86400000));
  });
  trialDays.sort((a,b)=>a-b);
  const minD = trialDays.length? trialDays[0].toFixed(1):'N/A';
  const maxD = trialDays.length? trialDays[trialDays.length-1].toFixed(1):'N/A';
  const exp3 = trialDays.filter(t=>t<=3).length;

  app.innerHTML = `
    <div class="grid">
      <div class="card"><h3>Total Accounts</h3><div class="big-num">${real.length}</div></div>
      <div class="card"><h3>Healthy</h3><div class="big-num green">${healthy}</div></div>
      <div class="card"><h3>Low / Exhausted</h3><div class="big-num ${low+exhausted>0?'yellow':'green'}">${low} / ${exhausted}</div></div>
      <div class="card"><h3>Trial Days</h3><div class="big-num">${minD}~${maxD}</div>
        ${exp3>0?'<div class="red">'+exp3+' expiring in 3d!</div>':''}</div>
    </div>
    <div class="card">
      <h3>Account Pool</h3>
      <table>
        <tr><th>Email</th><th>Plan</th><th>Daily</th><th>Weekly</th><th>Effective</th><th>Days Left</th></tr>
        ${real.map(a => {
          const u=a.usage||{}, dr=(u.daily||{}).remaining||0, wr=(u.weekly||{}).remaining||0;
          const eff=Math.min(dr,wr), pe=u.planEnd||0;
          const days=pe?Math.max(0,(pe-now)/86400000).toFixed(1):'N/A';
          const color=eff>15?'green':eff>5?'yellow':'red';
          return '<tr><td>'+a.email.slice(0,38)+'</td><td>'+(u.plan||'?')+'</td>'+
            '<td><div class="bar"><div class="bar-fill '+color+'" style="width:'+dr+'%;background:var(--'+color+')"></div></div>'+dr+'%</td>'+
            '<td><div class="bar"><div class="bar-fill '+color+'" style="width:'+wr+'%;background:var(--'+color+')"></div></div>'+wr+'%</td>'+
            '<td class="'+color+'">'+eff+'%</td><td>'+days+'d</td></tr>';
        }).join('')}
      </table>
    </div>
    <div class="actions">
      <button class="btn" onclick="location.reload()">Refresh</button>
    </div>
    <div class="refresh-time">Last updated: ${new Date().toLocaleString()}</div>
  `;
}
loadData();
setInterval(loadData, 30000);
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/status':
            accounts = load_accounts()
            data = {'accounts': accounts, 'timestamp': datetime.now(CST).isoformat()}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode('utf-8'))

    def log_message(self, format, *args):
        pass  # Suppress request logs


def run_dashboard(port=19920):
    """Start web dashboard"""
    print(f"\n  Dashboard starting at http://127.0.0.1:{port}")
    print(f"  Ctrl+C to stop\n")
    server = HTTPServer(('127.0.0.1', port), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        print("\n  Dashboard stopped.")


# ============================================================
# AUTOPILOT — 全自动驾驶
# ============================================================

def autopilot():
    """
    全自动驾驶模式:
    1. 启动Dashboard (后台)
    2. 启动生命周期监控
    3. 号池不足时触发注册
    4. 新账号自动注入无感切号
    """
    print(f"\n{'═' * 70}")
    print(f"  AUTOPILOT — 全自动驾驶·道法自然")
    print(f"{'═' * 70}")
    print(f"  功能: 监控 + 自动注册 + 自动注入")
    print(f"  Dashboard: http://127.0.0.1:19920")
    print(f"  Ctrl+C 停止\n")

    # Start dashboard in background
    dash_thread = threading.Thread(target=run_dashboard, kwargs={'port': 19920}, daemon=True)
    dash_thread.start()
    log("Dashboard已启动: http://127.0.0.1:19920", True)

    # Start lifecycle monitor with auto-register
    run_monitor(interval=300, auto_register=True)


# ============================================================
# CLI Entry Point
# ============================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        show_status()
        return

    cmd = sys.argv[1].lower()

    if cmd == 'status':
        show_status()

    elif cmd == 'monitor':
        interval = int(sys.argv[2]) if len(sys.argv) >= 3 else 300
        auto = '--auto' in sys.argv
        run_monitor(interval=interval, auto_register=auto)

    elif cmd == 'inject':
        inject_all_to_vsix()

    elif cmd == 'vcard':
        subcmd = sys.argv[2] if len(sys.argv) >= 3 else 'list'
        if subcmd == 'list':
            show_vcard_list()
        elif subcmd == 'check':
            check_vcard_apis()
        else:
            show_vcard_list()

    elif cmd == 'register':
        path = sys.argv[2] if len(sys.argv) >= 3 else 'yahoo'
        register_one(path)

    elif cmd == 'batch':
        count = int(sys.argv[2]) if len(sys.argv) >= 3 else 1
        path = sys.argv[3] if len(sys.argv) >= 4 else 'yahoo'
        batch_register(count, path)

    elif cmd == 'dashboard':
        port = int(sys.argv[2]) if len(sys.argv) >= 3 else 19920
        run_dashboard(port)

    elif cmd == 'autopilot':
        autopilot()

    elif cmd == 'analyze':
        stats = analyze_lifecycle()
        print(json.dumps(stats, indent=2, ensure_ascii=False, default=str))

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == '__main__':
    main()
