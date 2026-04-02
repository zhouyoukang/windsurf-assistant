"""
Gmail+alias 无限注册引擎 — 万法归宗·道法自然·一推到底
=========================================================
道之本: Gmail+alias = 虚拟卡等价物
  → 1个Gmail账号 = 无限Windsurf账号 (zero cost, forever)
  → user+ws001@gmail.com ... user+ws999@gmail.com → 全部送达 user@gmail.com
  → 每个alias = 一张"虚拟注册卡" = 一个14天Pro Trial

突破路线:
  Layer 0: Gmail+alias邮箱 (用户@gmail.com → 无限alias)
  Layer 1: DrissionPage + turnstilePatch (Turnstile已解决)
  Layer 2: Gmail IMAP自动获取验证邮件 (自动化)
  Layer 3: 注入无感切号号池 (windsurf-assistant-accounts.json)
  Layer 4: 生命周期监控 + 自动补充

用法:
  python _gmail_alias_engine.py status          # 引擎状态 + 号池概览
  python _gmail_alias_engine.py register        # 注册下一个alias (自动递增)
  python _gmail_alias_engine.py batch N         # 批量注册N个
  python _gmail_alias_engine.py inject          # 注入已注册账号到无感切号
  python _gmail_alias_engine.py monitor         # 守护进程: 低于阈值自动补充
  python _gmail_alias_engine.py check-imap      # 验证Gmail IMAP连通性
  python _gmail_alias_engine.py reset-index N  # 重置alias索引起点

配置 (secrets.env):
  GMAIL_BASE=yourname@gmail.com
  GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx  (Gmail App Password, 16位)
  GMAIL_ALIAS_INDEX=1                     (下一个alias起始索引, 自动维护)
  GMAIL_ALIAS_PREFIX=ws                   (alias前缀, 默认ws → ws001,ws002...)
"""

import json, os, sys, time, random, string, re, imaplib, email as email_lib
import base64, subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone
from email.header import decode_header

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
CST = timezone(timedelta(hours=8))

# === 文件路径 ===
SECRETS_ENV = Path(r'e:\道\道生一\一生二\secrets.env')
STATE_FILE = SCRIPT_DIR / "_gmail_alias_state.json"
RESULTS_FILE = SCRIPT_DIR / "_gmail_alias_results.json"
LOG_FILE = SCRIPT_DIR / "_gmail_alias.log"

# 无感切号 VSIX账号文件 (zhouyoukang.windsurf-assistant)
VSIX_ACCT_FILE = (
    Path(os.environ.get('APPDATA', '')) / 'Windsurf' / 'User' / 'globalStorage'
    / 'zhouyoukang.windsurf-assistant' / 'windsurf-assistant-accounts.json'
)
# Login Helper账号文件
LH_ACCT_FILE = (
    Path(os.environ.get('APPDATA', '')) / 'Windsurf' / 'User' / 'globalStorage'
    / 'windsurf-login-accounts.json'
)

WINDSURF_REGISTER_URL = "https://windsurf.com/account/register"
PROXY_CANDIDATES = ["http://127.0.0.1:7890", "http://127.0.0.1:7897"]

FIRST_NAMES = [
    "Alex","Jordan","Taylor","Morgan","Casey","Riley","Quinn","Avery",
    "Charlie","Dakota","Emerson","Finley","Harper","Jamie","Kendall","Logan",
    "Madison","Parker","Reese","Skyler","Blake","Drew","Eden","Gray","Sam",
    "River","Phoenix","Sage","Rowan","Hayden","Cameron","Peyton","Elliot",
]
LAST_NAMES = [
    "Anderson","Brooks","Carter","Davis","Edwards","Fisher","Garcia",
    "Hughes","Irving","Jensen","Kim","Lee","Mitchell","Nelson","Ortiz",
    "Park","Quinn","Rivera","Smith","Turner","Walker","Young","Zhang",
    "Moore","Taylor","White","Harris","Martin","Thompson","Jackson",
]


# ============================================================
# 工具函数
# ============================================================

def log(msg, ok=None, to_file=True):
    icon = "+" if ok is True else ("-" if ok is False else "*")
    ts = datetime.now(CST).strftime("%H:%M:%S")
    line = f"  [{ts}][{icon}] {msg}"
    print(line)
    if to_file:
        try:
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now(CST).strftime('%Y-%m-%d')} {line}\n")
        except Exception:
            pass


def load_secrets():
    secrets = {}
    for path in [SECRETS_ENV, Path('secrets.env'), PROJECT_ROOT / 'secrets.env']:
        if path.exists():
            for line in open(path, 'r', encoding='utf-8'):
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    secrets[k.strip()] = v.strip().strip('"').strip("'")
            break
    for key in ['GMAIL_BASE', 'GMAIL_APP_PASSWORD', 'GMAIL_ALIAS_INDEX', 'GMAIL_ALIAS_PREFIX']:
        if key in os.environ:
            secrets[key] = os.environ[key]
    return secrets


def load_state():
    if STATE_FILE.exists():
        try:
            return json.load(open(STATE_FILE, 'r', encoding='utf-8'))
        except Exception:
            pass
    return {"next_index": 1, "registered": [], "failed": []}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def load_results():
    if RESULTS_FILE.exists():
        try:
            return json.load(open(RESULTS_FILE, 'r', encoding='utf-8'))
        except Exception:
            pass
    return []


def save_result(result):
    results = load_results()
    results.append(result)
    with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)


def gen_password():
    chars = string.ascii_letters + string.digits + "!@#$"
    pw = (random.choice(string.ascii_uppercase) + random.choice(string.ascii_lowercase) +
          random.choice(string.digits) + random.choice("!@#$") +
          ''.join(random.choices(chars, k=12)))
    return ''.join(random.sample(pw, len(pw)))


def find_proxy():
    for p in PROXY_CANDIDATES:
        try:
            ps = [
                '$ProgressPreference="SilentlyContinue"',
                f'try {{ (Invoke-WebRequest -Uri "https://httpbin.org/ip" -Proxy "{p}" -TimeoutSec 5 -UseBasicParsing).StatusCode }} catch {{ "FAIL" }}',
            ]
            enc = base64.b64encode('\n'.join(ps).encode('utf-16-le')).decode()
            r = subprocess.run(
                ["powershell", "-NoProfile", "-EncodedCommand", enc],
                capture_output=True, text=True, timeout=12,
                encoding='utf-8', errors='replace',
            )
            if r.stdout.strip() and "FAIL" not in r.stdout:
                return p
        except Exception:
            continue
    return PROXY_CANDIDATES[0]


def find_chrome():
    for p in [
        os.path.join(os.environ.get('PROGRAMFILES', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
    ]:
        if os.path.exists(p):
            return p
    return None


def kill_stale_chrome():
    try:
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True, timeout=8)
        time.sleep(1.5)
    except Exception:
        pass


# ============================================================
# IMAP Gmail 验证邮件获取
# ============================================================

def imap_get_verify_link(base_email, app_password, alias_email, max_wait=150, interval=8):
    """
    通过Gmail IMAP自动获取Windsurf验证链接
    alias_email用于精准匹配To字段 (因为Gmail将alias送达主收件箱)
    """
    log(f"IMAP: 连接 imap.gmail.com ...")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(base_email, app_password)
        mail.select("INBOX")
        log("IMAP: 登录成功", True)
    except imaplib.IMAP4.error as e:
        log(f"IMAP: 登录失败 — {e}", False)
        log("  提示: 需要Gmail App Password (不是账号密码)", False)
        log("  生成: Google账号 → 安全 → 两步验证 → 应用专用密码", False)
        return None
    except Exception as e:
        log(f"IMAP: 连接失败 — {e}", False)
        return None

    start = time.time()
    attempt = 0
    try:
        while time.time() - start < max_wait:
            attempt += 1
            elapsed = int(time.time() - start)
            log(f"IMAP: 轮询收件箱... {elapsed}s/{max_wait}s (第{attempt}次)")

            # 多策略搜索 (Gmail IMAP搜索To字段不稳定，多管齐下)
            search_queries = [
                f'(TO "{alias_email}" UNSEEN)',
                '(FROM "noreply@codeium.com" UNSEEN)',
                '(FROM "noreply@windsurf.com" UNSEEN)',
                '(SUBJECT "verify" UNSEEN)',
                '(SUBJECT "Verify" UNSEEN)',
                '(SUBJECT "confirm" UNSEEN)',
            ]

            found_link = None
            for query in search_queries:
                try:
                    _, data = mail.search(None, query)
                    ids = data[0].split() if data[0] else []
                    if not ids:
                        continue
                    # 检查最近5封
                    for eid in reversed(ids[-5:]):
                        try:
                            _, msg_data = mail.fetch(eid, "(RFC822)")
                            raw = msg_data[0][1]
                            msg = email_lib.message_from_bytes(raw)

                            # 提取body
                            body_text = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    ct = part.get_content_type()
                                    if ct in ("text/plain", "text/html"):
                                        try:
                                            body_text += part.get_payload(decode=True).decode(errors="replace")
                                        except Exception:
                                            pass
                            else:
                                try:
                                    body_text = msg.get_payload(decode=True).decode(errors="replace")
                                except Exception:
                                    body_text = str(msg.get_payload())

                            # 搜索验证链接
                            links = re.findall(r'https?://[^\s"\'<>\]]+', body_text)
                            for link in links:
                                link = link.rstrip('.,;)')
                                if any(k in link.lower() for k in [
                                    "verify", "confirm", "auth", "windsurf", "codeium",
                                    "register", "activate", "validate"
                                ]):
                                    # 确认是Windsurf/Codeium的链接
                                    if any(d in link for d in [
                                        "windsurf.com", "codeium.com", "withcodeium.com"
                                    ]):
                                        found_link = link
                                        break
                                if found_link:
                                    break
                        except Exception:
                            continue
                    if found_link:
                        break
                except Exception:
                    continue

            if found_link:
                log(f"IMAP: 验证链接找到! {found_link[:80]}...", True)
                try:
                    mail.logout()
                except Exception:
                    pass
                return found_link

            time.sleep(interval)

    except Exception as e:
        log(f"IMAP: 轮询异常 — {e}", False)
    finally:
        try:
            mail.logout()
        except Exception:
            pass

    log(f"IMAP: {max_wait}s内未收到验证邮件", False)
    return None


def check_imap_connectivity(base_email, app_password):
    """验证IMAP连通性和凭据"""
    print(f"\n{'═' * 60}")
    print("  IMAP连通性检查 — Gmail App Password验证")
    print(f"{'═' * 60}\n")
    print(f"  邮箱: {base_email}")
    print(f"  密码: {'*' * len(app_password) if app_password else '(未配置)'}\n")

    try:
        log("连接 imap.gmail.com:993 ...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        log("TCP连接成功", True)
        mail.login(base_email, app_password)
        log("IMAP登录成功!", True)

        # 检查收件箱
        mail.select("INBOX")
        _, data = mail.search(None, "ALL")
        ids = data[0].split()
        log(f"收件箱邮件数: {len(ids)}", True)

        # 检查最近邮件
        if ids:
            _, msg_data = mail.fetch(ids[-1], "(RFC822)")
            msg = email_lib.message_from_bytes(msg_data[0][1])
            subj_raw = msg.get("Subject", "(无主题)")
            from_raw = msg.get("From", "(无发件人)")
            log(f"最新邮件 — From: {from_raw[:50]}", True)
            log(f"           Subject: {subj_raw[:50]}", True)

        mail.logout()
        print(f"\n  ✅ IMAP连通性验证通过! Gmail+alias引擎就绪。")
        return True

    except imaplib.IMAP4.error as e:
        print(f"\n  ❌ IMAP认证失败: {e}")
        print(f"\n  解决方案:")
        print(f"    1. 确保Gmail已开启两步验证")
        print(f"    2. 生成应用专用密码: myaccount.google.com → 安全 → 两步验证 → 应用专用密码")
        print(f"    3. 在secrets.env中设置: GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx")
        return False
    except Exception as e:
        print(f"\n  ❌ 连接失败: {e}")
        return False
    finally:
        print(f"\n{'═' * 60}\n")


# ============================================================
# 浏览器注册
# ============================================================

def setup_browser(with_turnstile=True, incognito=True, proxy=None, kill_chrome=True):
    from DrissionPage import ChromiumOptions, ChromiumPage
    if kill_chrome:
        kill_stale_chrome()
    chrome = find_chrome()
    co = ChromiumOptions()
    if chrome:
        co.set_browser_path(chrome)
    if incognito:
        co.set_argument("--incognito")
    co.auto_port()
    co.headless(False)
    if proxy:
        co.set_argument(f"--proxy-server={proxy.replace('http://', '')}")
    if with_turnstile:
        # turnstilePatch路径探测
        for tp_path in [
            SCRIPT_DIR / "_archive" / "turnstilePatch",
            SCRIPT_DIR / "turnstilePatch",
            PROJECT_ROOT / "turnstilePatch",
        ]:
            if tp_path.exists():
                co.set_argument("--allow-extensions-in-incognito")
                co.add_extension(str(tp_path))
                log(f"turnstilePatch加载: {tp_path}", True)
                break
        else:
            log("未找到turnstilePatch目录，Turnstile需手动处理", False)
    page = ChromiumPage(co)
    if with_turnstile:
        time.sleep(3)
        log("扩展预热完成(3s)", True)
    return page


def wait_for_page_progress(page, max_wait=50):
    """等待页面进入下一阶段 (Turnstile → 密码 / 验证邮件)"""
    start = time.time()
    while time.time() - start < max_wait:
        try:
            body = (page.html or "").lower()
            if any(k in body for k in ["verify your email", "check your email", "verification email"]):
                return "verify"
            if any(k in body for k in ["dashboard", "welcome to windsurf", "get started"]):
                return "done"
            if "password" in body and ("confirm" in body or "set your" in body):
                return "password"
            if "already have an account" in body or "sign in" in body:
                return "exists"
            # 点击可用的Continue/Submit
            for sel in ['tag:button@text():Continue', '@type=submit']:
                try:
                    btn = page.ele(sel, timeout=1)
                    if btn and not btn.attr('disabled'):
                        btn.click()
                        time.sleep(2)
                        break
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(1)
    return "timeout"


def register_with_alias(alias_email, ws_password, proxy=None):
    """
    用Gmail+alias注册Windsurf账号
    返回: (status, page)  status: "verify"|"done"|"exists"|"blocked"|"error"
    verify时page保持打开(调用方负责quit), 其余情况page已quit
    """
    fn = random.choice(FIRST_NAMES)
    ln = random.choice(LAST_NAMES)

    log(f"注册: {alias_email} ({fn} {ln})")
    page = None
    try:
        page = setup_browser(with_turnstile=True, incognito=True, proxy=proxy)
        log(f"浏览器就绪, 导航至注册页...")
        page.get(WINDSURF_REGISTER_URL)
        time.sleep(random.uniform(2.5, 4))

        # 填写表单
        for sel, val in [('@name=firstName', fn), ('@name=lastName', ln), ('@name=email', alias_email)]:
            try:
                el = page.ele(sel, timeout=5)
                if el:
                    el.input(val)
                    time.sleep(random.uniform(0.3, 0.7))
            except Exception:
                pass

        # 勾选Terms
        try:
            cb = page.ele('tag:input@type=checkbox', timeout=2)
            if cb and not cb.attr('checked'):
                cb.click()
                time.sleep(0.3)
        except Exception:
            pass

        # 点击Continue
        for sel in ['tag:button@text():Continue', '@type=submit']:
            try:
                btn = page.ele(sel, timeout=3)
                if btn:
                    btn.click()
                    time.sleep(random.uniform(3, 5))
                    break
            except Exception:
                pass

        log("等待Turnstile验证...")
        state = wait_for_page_progress(page, max_wait=40)
        log(f"页面状态: {state}")

        # 检查邮箱是否被拒绝 (密码步骤跳过 = Gmail+alias被封)
        body = (page.html or "").lower()
        if "verify" in state or ("verify your email" in body) or ("check your email" in body):
            # 已经到验证邮件阶段 — 但还没设置密码?
            # 这种情况意味着邮箱被静默跳过了 (一次性邮箱行为)
            if not any(k in body for k in ["password"]):
                log("⚠️ 密码步骤被跳过 — Gmail+alias可能被检测为临时邮箱", False)
                try:
                    if page: page.quit()
                except Exception: pass
                return ("blocked", None)

        # 密码步骤
        pw_input = page.ele('@type=password', timeout=8)
        if pw_input:
            log("密码步骤到达 — Gmail+alias被服务端接受!", True)
            pw_input.input(ws_password)
            time.sleep(0.5)

            # 确认密码
            try:
                pw_confirm = page.ele('@placeholder:Confirm', timeout=3)
                if not pw_confirm:
                    pw_confirm = page.ele('css:input[type=password]:nth-child(2)', timeout=2)
                if pw_confirm:
                    pw_confirm.input(ws_password)
            except Exception:
                pass

            # 提交
            for sel in ['@type=submit', 'tag:button@text():Continue', 'tag:button@text():Sign up']:
                try:
                    btn = page.ele(sel, timeout=3)
                    if btn:
                        btn.click()
                        time.sleep(3)
                        break
                except Exception:
                    pass

            log("密码已提交, 被动等待验证码页面...")
            # 被动等待 — 不点击任何按钮，等turnstilePatch自动解决
            VERIFY_KEYWORDS = [
                "verify your email", "check your email", "verification email",
                "we've sent", "we sent", "sent an email", "sent to your",
                "check your inbox", "inbox", "email address", "confirmation",
                "please verify", "almost done", "one more step",
            ]
            DONE_KEYWORDS = ["dashboard", "welcome to windsurf", "get started",
                             "open windsurf", "cascade", "you're all set"]

            found_verify = False
            for attempt in range(45):  # 45秒被动轮询
                time.sleep(1)
                try:
                    body2 = (page.html or "").lower()
                    url2 = page.url or ""
                    if any(k in body2 for k in VERIFY_KEYWORDS):
                        log("验证码页面到达!", True)
                        found_verify = True
                        return ("verify", page)  # 保持browser打开
                    if any(k in body2 for k in DONE_KEYWORDS):
                        log("注册直接完成!", True)
                        try: page.quit()
                        except Exception: pass
                        return ("done", None)
                    # 如果 URL发生变化且已离开register页
                    if "register" not in url2 and "windsurf.com" in url2 and attempt > 5:
                        log(f"URL已跳转: {url2}", True)
                        try: page.quit()
                        except Exception: pass
                        return ("done", None)
                except Exception:
                    pass

            # 超时后记录页面实际内容(调试用)
            try:
                body_dbg = (page.html or "")[:500].lower()
                log(f"超时,实际页面内容: ...{body_dbg[100:300]}...", False)
            except Exception:
                pass
            log(f"未知状态, URL: {page.url}", False)
            try: page.quit()
            except Exception: pass
            return ("error", None)
        else:
            # 检查是否直接完成
            body = (page.html or "").lower()
            if any(k in body for k in ["verify your email", "check your email"]):
                # 无密码步骤但到了验证 → 可能被跳过
                log("到达验证邮件页但无密码步骤 — 可能被服务端拒绝", False)
                try: page.quit()
                except Exception: pass
                return ("blocked", None)
            elif any(k in body for k in ["dashboard", "welcome"]):
                log("注册完成!", True)
                try: page.quit()
                except Exception: pass
                return ("done", None)
            else:
                log(f"密码步骤未出现, 状态未知: {page.url}", False)
                try: page.quit()
                except Exception: pass
                return ("error", None)

    except Exception as e:
        log(f"注册异常: {e}", False)
        import traceback; traceback.print_exc()
        try:
            if page: page.quit()
        except Exception: pass
        return ("error", None)


# ============================================================
# 验证码提取与输入 (Windsurf用6位验证码, 邮件进Spam)
# ============================================================

def _get_verify_code_from_gmail(reg_page, gmail_user, gmail_password, max_wait=180):
    """
    用subprocess独立进程提取Gmail Spam验证码
    完全进程隔离 = 注册浏览器零干扰 = React页面状态保持
    """
    log("从Gmail Spam提取验证码(subprocess隔离)...")

    # 收集已知旧验证码(从results文件)
    known = set()
    try:
        for r in load_results():
            vc = r.get('verify_code', '')
            if vc: known.add(vc)
    except Exception: pass

    checker = SCRIPT_DIR / "_gmail_code_check.py"
    if not checker.exists():
        log(f"验证码检查脚本不存在: {checker}", False)
        return None

    python = sys.executable
    known_str = ",".join(known) if known else ""
    cmd = [python, str(checker), gmail_user, gmail_password, known_str, str(max_wait)]

    log(f"启动独立进程取码 (最长{max_wait}s)...")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, encoding='utf-8', errors='replace')
        code = None
        while True:
            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                break
            line = line.strip()
            if not line:
                continue
            if line.startswith("CODE:"):
                code = line.split(":", 1)[1]
                log(f"验证码找到: {code} ✅", True)
                break
            elif line.startswith("WAIT:"):
                log(f"等待验证码... {line[5:]}")
            elif line.startswith("ERROR:"):
                log(f"取码错误: {line[6:]}", False)
                break

        # 等进程结束
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

        return code
    except Exception as e:
        log(f"subprocess异常: {e}", False)
        return None


def _enter_verify_code(page, code):
    """在Windsurf验证码页面输入6位码 — 纯JS方案(绕过DrissionPage DOM缓存)"""
    log(f"输入验证码: {code}")
    try:
        time.sleep(2)
        url = page.url or ""
        log(f"当前页面: {url[:80]}")

        # 先用JS诊断页面状态
        diag = page.run_js("""
            return {
                url: location.href,
                inputCount: document.querySelectorAll('input').length,
                buttonCount: document.querySelectorAll('button').length,
                bodyText: (document.body?.innerText || '').substring(0, 300),
                hasVerify: (document.body?.innerText || '').includes('erif'),
            };
        """)
        log(f"JS诊断: inputs={diag.get('inputCount',0)}, buttons={diag.get('buttonCount',0)}, hasVerify={diag.get('hasVerify',False)}")
        if diag.get('bodyText'):
            log(f"页面文本: {diag['bodyText'][:150]}")

        # 纯JS方案: 查找并填入验证码
        result = page.run_js(f"""
            var code = '{code}';
            var filled = false;

            // 策略A: 查找所有可见input
            var inputs = Array.from(document.querySelectorAll('input'));
            var visible = inputs.filter(function(inp) {{
                return inp.type !== 'hidden' && inp.type !== 'checkbox' &&
                       inp.type !== 'radio' && inp.type !== 'submit' &&
                       inp.type !== 'password' && inp.offsetParent !== null;
            }});

            if (visible.length >= 6) {{
                // OTP风格: 6+个输入框各填1位
                for (var i = 0; i < Math.min(6, visible.length); i++) {{
                    var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(visible[i], code[i]);
                    visible[i].dispatchEvent(new Event('input', {{bubbles: true}}));
                    visible[i].dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
                filled = true;
            }} else if (visible.length >= 1) {{
                // 单输入框
                var inp = visible[0];
                var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                setter.call(inp, code);
                inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                filled = true;
            }}

            return {{filled: filled, visibleCount: visible.length}};
        """)
        log(f"JS填入结果: {result}")

        if result and result.get('filled'):
            log("验证码已通过JS填入", True)
            time.sleep(1)

            # JS点击提交按钮
            page.run_js("""
                var btns = document.querySelectorAll('button');
                for (var b of btns) {
                    var t = (b.innerText || '').toLowerCase();
                    if (t.includes('verify') || t.includes('submit') || t.includes('continue') || t.includes('confirm')) {
                        b.click();
                        break;
                    }
                }
            """)
            time.sleep(6)

            # 检查结果
            check = page.run_js("return {url: location.href, text: (document.body?.innerText||'').substring(0,300)};")
            check_url = (check.get('url', '') if check else '').lower()
            check_text = (check.get('text', '') if check else '').lower()
            log(f"验证后URL: {check_url[:80]}")

            if any(k in check_text for k in ['dashboard', 'welcome', 'get started', 'success', 'verified', 'you can now']):
                log("验证成功! ✅", True)
                return True
            elif "register" not in check_url and "windsurf.com" in check_url:
                log("页面已跳转 ✅", True)
                return True
            else:
                log(f"验证后状态: {check_text[:100]}")
                return True  # 乐观
        else:
            log(f"JS未能填入验证码 (visible inputs: {result.get('visibleCount', 0) if result else '?'})", False)
            return False

    except Exception as e:
        log(f"输入验证码异常: {e}", False)
        import traceback; traceback.print_exc()
        return False


# ============================================================
# Gmail Web 自动验证 (DrissionPage, 无需IMAP/AppPassword)
# ============================================================

def _gmail_login(page, gmail_user, gmail_password):
    """Gmail登录 (ServiceLogin → 标准视图)，返回是否成功"""
    page.get("https://accounts.google.com/ServiceLogin?service=mail&continue=https://mail.google.com/mail/u/0/")
    time.sleep(3)
    if "accounts.google.com" not in (page.url or ""):
        return "mail.google.com" in (page.url or "")
    try:
        ei = page.ele('@type=email', timeout=8) or page.ele('tag:input@name=identifier', timeout=3)
        if ei:
            ei.input(gmail_user)
            time.sleep(0.5)
            for s in ['tag:button@text():下一步', 'tag:button@text():Next', '@id=identifierNext']:
                try:
                    b = page.ele(s, timeout=2)
                    if b: b.click(); time.sleep(3); break
                except Exception: pass
    except Exception as e:
        log(f"邮箱输入失败: {e}", False); return False
    try:
        pi = page.ele('@type=password', timeout=10)
        if pi:
            pi.input(gmail_password); time.sleep(0.5)
            for s in ['tag:button@text():下一步', 'tag:button@text():Next', '@id=passwordNext']:
                try:
                    b = page.ele(s, timeout=2)
                    if b: b.click(); time.sleep(5); break
                except Exception: pass
            log("Gmail登录提交", True)
        else:
            log("未找到密码框", False); return False
    except Exception as e:
        log(f"密码失败: {e}", False); return False
    for _ in range(25):
        if "mail.google.com" in (page.url or ""): return True
        time.sleep(1)
    log(f"Gmail超时, URL: {page.url}", False)
    return False


def verify_pending_accounts(gmail_user, gmail_password, proxy=None):
    """
    Gmail基本HTML视图(/h/) + DrissionPage自动验证
    基本HTML = 服务端渲染 = 无虚拟DOM = 100%可靠
    """
    results = load_results()
    pending = [r for r in results if r.get('status') == 'pending_verify']
    if not pending:
        print("\n  ✅ 没有待验证账号")
        return 0

    print(f"\n{'═' * 70}")
    print(f"  Gmail基本HTML自动验证 v3 — 水利万物而不争")
    print(f"  待验证: {len(pending)} 个账号")
    print(f"{'═' * 70}\n")

    from DrissionPage import ChromiumOptions, ChromiumPage
    kill_stale_chrome()
    chrome = find_chrome()
    co = ChromiumOptions()
    if chrome: co.set_browser_path(chrome)
    co.auto_port()
    co.headless(False)
    if proxy: co.set_argument(f"--proxy-server={proxy.replace('http://', '')}")

    page = ChromiumPage(co)
    verified = 0
    VALID_DOMAINS = ['windsurf.com', 'codeium.com', 'withcodeium.com']

    try:
        # Step 1: 登录Gmail
        log("登录Gmail...")
        if not _gmail_login(page, gmail_user, gmail_password):
            log("Gmail登录失败", False)
            page.quit()
            return 0
        log("Gmail已登录", True)

        # Step 2: 切到基本HTML视图搜索验证邮件
        # 基本HTML搜索URL: /h/?s=q&q=搜索词
        search_terms = [
            "from:codeium.com",
            "from:windsurf.com",
            "subject:verify email",
        ]
        verify_links = []

        for term in search_terms:
            if len(verify_links) >= 5:
                break
            log(f"基本HTML搜索: {term}")
            import urllib.parse
            q = urllib.parse.quote(term)
            page.get(f"https://mail.google.com/mail/u/0/h/?s=q&q={q}")
            time.sleep(3)

            html = page.html or ""

            # 基本HTML视图中邮件列表是简单<table>，每行有<a>链接到邮件详情
            # 找所有邮件详情链接 (格式: /h/xxxxx/?th=xxxx&v=c)
            mail_links = re.findall(r'/mail/u/0/h/[^"\'>\s]+(?:th=[^"\'>\s]+)', html)
            if not mail_links:
                # 也试试其他模式
                mail_links = re.findall(r'/h/[^"\'>\s]*\?[^"\'>\s]*th=[^"\'>\s]*', html)
            log(f"找到 {len(mail_links)} 封邮件链接")

            # 逐一打开邮件，提取验证链接
            seen_ths = set()
            for ml in mail_links[:10]:
                # 去重(同一邮件可能多个链接)
                th_match = re.search(r'th=([0-9a-f]+)', ml)
                if th_match:
                    th = th_match.group(1)
                    if th in seen_ths: continue
                    seen_ths.add(th)

                full_url = f"https://mail.google.com{ml}" if ml.startswith('/') else ml
                try:
                    page.get(full_url)
                    time.sleep(2)
                    mail_html = page.html or ""

                    # 从邮件正文提取Windsurf/Codeium域名链接
                    for domain in VALID_DOMAINS:
                        pattern = rf'https?://(?:www\.)?{re.escape(domain)}/[^\s"\'<>&;]+'
                        found = re.findall(pattern, mail_html)
                        for link in found:
                            link = link.rstrip('.,;)\'\">')
                            if any(s in link.lower() for s in ['unsubscribe', '.png', '.jpg', '.css', 'logo', 'icon']):
                                continue
                            if link not in verify_links:
                                verify_links.append(link)
                                log(f"✓ 验证链接: {link[:90]}", True)
                except Exception as e:
                    log(f"打开邮件异常: {e}", False)

        # 如果基本HTML也没找到，从标准视图用JS提取
        if not verify_links:
            log("基本HTML未找到链接, 尝试JS提取...")
            page.get("https://mail.google.com/mail/u/0/#search/from%3Acodeium.com+OR+from%3Awindsurf.com")
            time.sleep(5)
            try:
                js_result = page.run_js("""
                    var links = [];
                    document.querySelectorAll('a[href]').forEach(function(a) {
                        var h = a.href;
                        if (h && (h.includes('windsurf.com') || h.includes('codeium.com') || h.includes('withcodeium.com'))) {
                            if (!h.includes('unsubscribe') && !h.includes('.png') && !h.includes('.css')) {
                                links.push(h);
                            }
                        }
                    });
                    return [...new Set(links)];
                """)
                if js_result:
                    for link in js_result:
                        if link not in verify_links:
                            verify_links.append(link)
                            log(f"✓ JS提取: {link[:90]}", True)
            except Exception as e:
                log(f"JS提取异常: {e}", False)

        # 过滤: 优先验证相关链接
        final_links = []
        for link in verify_links:
            lk = link.lower()
            if any(k in lk for k in ['verify', 'confirm', 'auth', 'validate', 'activate', 'token', 'code=']):
                final_links.append(link)
            elif len(link) > 80:
                final_links.append(link)
        if not final_links:
            final_links = verify_links

        # Step 3: 逐一打开验证链接
        if final_links:
            log(f"\n共 {len(final_links)} 个验证链接")
            for i, link in enumerate(final_links):
                try:
                    log(f"验证 {i+1}/{len(final_links)}: {link[:70]}...")
                    page.get(link)
                    time.sleep(5)
                    body = (page.html or "").lower()
                    url = (page.url or "").lower()
                    if any(k in body for k in ['verified', 'success', 'confirmed', 'welcome',
                                                'dashboard', 'get started', 'open windsurf',
                                                'email has been verified', 'you can now']):
                        log("验证成功! ✅", True)
                        verified += 1
                    elif any(k in body for k in ['expired', 'invalid link']):
                        log("链接已过期", False)
                    elif any(k in url for k in ['windsurf.com', 'codeium.com']):
                        log("已跳转Windsurf/Codeium ✅", True)
                        verified += 1
                    else:
                        log(f"状态不确定: {page.url[:80]}")
                except Exception as e:
                    log(f"链接失败: {e}", False)
        else:
            log("未找到任何Windsurf/Codeium验证链接", False)
            log("⚠ 可能原因: 验证邮件在垃圾箱/未送达/已过期", False)
            log("  → 手动检查: Gmail收件箱 + 垃圾箱", False)
            log("  → 或重新注册: python _gmail_alias_engine.py batch 5", False)

        # Step 4: 更新状态
        if verified > 0:
            results = load_results()
            updated = 0
            for r in results:
                if r.get('status') == 'pending_verify':
                    r['status'] = 'registered'
                    r['verified_at'] = datetime.now(CST).isoformat()
                    r['path'] = 'gmail_web_verify'
                    updated += 1
            with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            log(f"已更新 {updated} 个账号状态为 registered", True)
            injected = 0
            for r in results:
                if r.get('status') == 'registered':
                    if inject_to_pool(r):
                        injected += 1
            if injected:
                log(f"已注入 {injected} 个账号到号池", True)

    except Exception as e:
        log(f"验证异常: {e}", False)
        import traceback; traceback.print_exc()
    finally:
        try: page.quit()
        except Exception: pass

    print(f"\n{'═' * 70}")
    print(f"  验证完成: {verified} 个链接已处理")
    pa = len([r for r in load_results() if r.get('status') == 'pending_verify'])
    print(f"  剩余待验证: {pa}")
    print(f"{'═' * 70}\n")
    return verified


# ============================================================
# 号池注入
# ============================================================

def inject_to_pool(account_data):
    """将新注册的账号注入无感切号号池"""
    email = account_data.get('email', '')
    if not email:
        return False

    injected_any = False

    # 1) 注入 windsurf-assistant (无感切号VSIX)
    if VSIX_ACCT_FILE.parent.exists():
        vsix_accts = []
        if VSIX_ACCT_FILE.exists():
            try:
                vsix_accts = json.load(open(VSIX_ACCT_FILE, 'r', encoding='utf-8'))
                if not isinstance(vsix_accts, list):
                    vsix_accts = []
            except Exception:
                vsix_accts = []

        existing = {a.get('email', '') for a in vsix_accts}
        if email not in existing:
            vsix_accts.append({
                "email": email,
                "password": account_data.get('windsurf_password', ''),
                "source": "gmail_alias",
                "addedAt": datetime.now(CST).isoformat(),
            })
            with open(VSIX_ACCT_FILE, 'w', encoding='utf-8') as f:
                json.dump(vsix_accts, f, indent=2, ensure_ascii=False)
            log(f"注入无感切号: {email}", True)
            injected_any = True
        else:
            log(f"已存在于无感切号: {email}")
    else:
        log(f"无感切号VSIX目录不存在: {VSIX_ACCT_FILE.parent}", False)

    # 2) 注入 Login Helper
    if LH_ACCT_FILE.parent.exists():
        lh_accts = []
        if LH_ACCT_FILE.exists():
            try:
                lh_accts = json.load(open(LH_ACCT_FILE, 'r', encoding='utf-8'))
                if not isinstance(lh_accts, list):
                    lh_accts = []
            except Exception:
                lh_accts = []

        existing_lh = {a.get('email', '') for a in lh_accts}
        if email not in existing_lh:
            lh_accts.append({
                "email": email,
                "password": account_data.get('windsurf_password', ''),
                "usage": {"plan": "Trial"},
                "source": "gmail_alias",
                "addedAt": datetime.now(CST).isoformat(),
            })
            with open(LH_ACCT_FILE, 'w', encoding='utf-8') as f:
                json.dump(lh_accts, f, indent=2, ensure_ascii=False)
            log(f"注入LoginHelper: {email}", True)
            injected_any = True

    return injected_any


# ============================================================
# 核心注册流程 (单次)
# ============================================================

def register_one(base_email, app_password, index, prefix="ws", proxy=None, manual_verify=False, no_wait=False):
    """
    注册一个Gmail+alias账号 (v2: 验证码流程)
    Windsurf用6位验证码(非链接), 验证邮件进Gmail Spam
    流程: 注册→验证码页→Gmail Spam取码→输入码→完成
    """
    secrets = load_secrets()
    gmail_pw = secrets.get('UNIFIED_PASSWORD', '') or 'wsy057066wsy'
    alias_email = f"{base_email.split('@')[0]}+{prefix}{index:03d}@gmail.com"
    ws_password = gen_password()

    print(f"\n{'─' * 65}")
    print(f"  Gmail+alias注册 v2 — 道法自然·验证码流程")
    print(f"  Alias: {alias_email}")
    print(f"  Index: {index} | Prefix: {prefix}")
    print(f"{'─' * 65}\n")

    # Step 1: 浏览器注册
    reg_status, reg_page = register_with_alias(alias_email, ws_password, proxy=proxy)

    if reg_status in ("blocked", "error"):
        log(f"注册结果: {reg_status}", False)
        return {"email": alias_email, "status": reg_status, "index": index,
                "timestamp": datetime.now(CST).isoformat()}

    if reg_status == "done":
        result = {
            "email": alias_email, "windsurf_password": ws_password,
            "base_email": base_email, "index": index,
            "path": "gmail_alias_direct", "status": "registered",
            "timestamp": datetime.now(CST).isoformat(),
        }
        save_result(result)
        inject_to_pool(result)
        return result

    # Step 2: 验证码流程 (reg_status == "verify", reg_page保持打开)
    if reg_status == "verify" and reg_page:
        log("验证码页面到达, 启动Gmail Spam取码...", True)

        # 用独立进程从Gmail Spam提取验证码
        code = _get_verify_code_from_gmail(reg_page, base_email, gmail_pw, max_wait=180)

        if code:
            # 在注册浏览器中用JS弹窗显示验证码, 用户手动输入
            try:
                reg_page.run_js(f"document.title = 'CODE: {code}';")
                reg_page.run_js(f"""
                    var div = document.createElement('div');
                    div.style = 'position:fixed;top:0;left:0;right:0;z-index:999999;background:#1a73e8;color:white;padding:20px;text-align:center;font-size:28px;font-family:monospace;';
                    div.innerHTML = '验证码: <b>{code}</b> — 请在下方输入框填入此码';
                    document.body.prepend(div);
                """)
                log(f"验证码 {code} 已显示在浏览器顶部", True)
            except Exception:
                pass

            print(f"\n{'█' * 60}")
            print(f"  ✅ 验证码已获取: {code}")
            print(f"  📋 请在打开的浏览器中输入此验证码")
            print(f"  💡 验证码已显示在浏览器页面顶部")
            print(f"{'█' * 60}")

            # 等待用户完成验证(轮询页面URL变化)
            log("等待用户输入验证码并提交...")
            verified = False
            for wait in range(120):  # 最多等2分钟
                time.sleep(2)
                try:
                    check = reg_page.run_js("return {url: location.href, text: (document.body?.innerText||'').substring(0,200)};")
                    cur_url = (check.get('url', '') if check else '').lower()
                    cur_text = (check.get('text', '') if check else '').lower()
                    if any(k in cur_text for k in ['dashboard', 'welcome', 'get started', 'open windsurf', 'success']):
                        log("用户验证成功! ✅", True)
                        verified = True
                        break
                    if "register" not in cur_url and "windsurf.com" in cur_url and wait > 5:
                        log(f"页面已跳转: {cur_url[:60]} ✅", True)
                        verified = True
                        break
                except Exception:
                    pass
                if wait % 15 == 0 and wait > 0:
                    log(f"仍在等待用户输入... {wait*2}s")

            try: reg_page.quit()
            except Exception: pass

            status = "registered" if verified else "pending_verify"
            result = {
                "email": alias_email, "windsurf_password": ws_password,
                "base_email": base_email, "index": index,
                "path": "gmail_alias_code_semi",
                "status": status,
                "verify_code": code,
                "timestamp": datetime.now(CST).isoformat(),
            }
            save_result(result)
            if verified:
                inject_to_pool(result)
                log(f"✅ 注册+验证完成: {alias_email}", True)
            return result
        else:
            try: reg_page.quit()
            except Exception: pass
            log("Gmail验证码提取失败, 保存pending_verify", False)
            result = {
                "email": alias_email, "windsurf_password": ws_password,
                "base_email": base_email, "index": index,
                "path": "gmail_alias_code_timeout", "status": "pending_verify",
                "timestamp": datetime.now(CST).isoformat(),
            }
            save_result(result)
            return result

    # 兜底
    try:
        if reg_page: reg_page.quit()
    except Exception: pass
    return None


# ============================================================
# 批量注册
# ============================================================

def batch_register(n, base_email, app_password, prefix="ws", manual_verify=False,
                   no_wait=False, delay_min=8, delay_max=20):
    """
    批量注册N个Gmail+alias账号
    自动递增index, 成功/失败均记录状态
    """
    print(f"\n{'═' * 70}")
    print(f"  Gmail+alias 批量注册 — 万法归宗")
    print(f"  数量: {n} | Base: {base_email} | Prefix: {prefix}")
    mode = '不等待(稍后统一验证)' if no_wait else ('手动验证' if manual_verify else '自动IMAP验证')
    print(f"  模式: {mode}")
    print(f"{'═' * 70}\n")

    state = load_state()
    start_index = state.get("next_index", 1)
    proxy = find_proxy()
    log(f"代理: {proxy}")

    success = 0
    failed = 0
    blocked = 0

    for i in range(n):
        idx = start_index + i
        print(f"\n{'▓' * 20} 账号 {i+1}/{n} (index={idx}) {'▓' * 20}")

        result = register_one(
            base_email, app_password, idx, prefix=prefix,
            proxy=proxy, manual_verify=manual_verify, no_wait=no_wait,
        )

        if result:
            status = result.get("status", "")
            if status in ("registered",):
                success += 1
                state["registered"].append({"email": result["email"], "index": idx,
                                             "ts": result["timestamp"]})
                log(f"✅ 成功 {success}/{n}: {result['email']}", True)
            elif status == "blocked":
                blocked += 1
                state["failed"].append({"index": idx, "reason": "blocked",
                                        "ts": datetime.now(CST).isoformat()})
                log(f"🚫 被封 {blocked}: index={idx}", False)
                # 被封时暂停更长时间
                delay = random.uniform(30, 60)
                log(f"冷却 {delay:.0f}s (被封冷却)...")
                time.sleep(delay)
                continue
            elif status == "pending_verify":
                success += 1  # 注册成功但验证待手动
                state["registered"].append({"email": result["email"], "index": idx,
                                             "ts": result["timestamp"]})
            else:
                failed += 1
                state["failed"].append({"index": idx, "reason": "error",
                                        "ts": datetime.now(CST).isoformat()})
        else:
            failed += 1
            state["failed"].append({"index": idx, "reason": "null_result",
                                    "ts": datetime.now(CST).isoformat()})

        # 更新状态
        state["next_index"] = idx + 1
        save_state(state)

        # 随机延迟 (防封禁)
        if i < n - 1:
            delay = random.uniform(delay_min, delay_max)
            log(f"延迟 {delay:.1f}s 后继续...")
            time.sleep(delay)

    print(f"\n{'═' * 70}")
    print(f"  批量注册完成")
    print(f"  ✅ 成功: {success} | ❌ 失败: {failed} | 🚫 被封: {blocked}")
    print(f"  下次起始索引: {state['next_index']}")
    print(f"  总已注册: {len(state.get('registered', []))}")
    print(f"{'═' * 70}\n")

    return {"success": success, "failed": failed, "blocked": blocked}


# ============================================================
# 状态展示
# ============================================================

def show_status():
    secrets = load_secrets()
    state = load_state()
    results = load_results()
    now = datetime.now(CST)

    print(f"\n{'═' * 70}")
    print(f"  Gmail+alias 引擎状态 — {now.strftime('%Y-%m-%d %H:%M:%S CST')}")
    print(f"{'═' * 70}\n")

    # 配置检查
    base_email = secrets.get('GMAIL_BASE', '')
    app_pw = secrets.get('GMAIL_APP_PASSWORD', '')
    print(f"  配置状态:")
    print(f"    GMAIL_BASE:         {'✅ ' + base_email if base_email else '❌ 未配置'}")
    print(f"    GMAIL_APP_PASSWORD: {'✅ 已配置(' + str(len(app_pw)) + '字符)' if app_pw else '❌ 未配置'}")
    print(f"    代理:               {find_proxy()}")

    # 引擎状态
    print(f"\n  引擎状态:")
    print(f"    下一alias索引:  ws{state.get('next_index', 1):03d}")
    print(f"    已注册总数:     {len(state.get('registered', []))}")
    print(f"    失败记录:       {len(state.get('failed', []))}")

    # 注册记录
    if results:
        print(f"\n  最近注册记录 (最新5条):")
        for r in results[-5:]:
            ts = r.get('timestamp', '?')[:19]
            email = r.get('email', '?')
            status = r.get('status', '?')
            path = r.get('path', '?')
            print(f"    {ts}  {email:45}  {status:15}  {path}")

    # 号池状态
    print(f"\n  号池状态:")
    if LH_ACCT_FILE.exists():
        try:
            accts = json.load(open(LH_ACCT_FILE, 'r', encoding='utf-8'))
            now_ms = time.time() * 1000
            trial_days = []
            gmail_count = 0
            for a in accts:
                if 'gmail' in a.get('email', ''):
                    gmail_count += 1
                pe = a.get('usage', {}).get('planEnd', 0)
                if pe:
                    trial_days.append(max(0, (pe - now_ms) / 86400000))
            print(f"    Login Helper总账号: {len(accts)}")
            print(f"    Gmail+alias账号:    {gmail_count}")
            if trial_days:
                trial_days.sort()
                alive_7d = sum(1 for t in trial_days if t > 7)
                alive_3d = sum(1 for t in trial_days if t <= 3)
                print(f"    Trial剩余范围:      {trial_days[0]:.1f}~{trial_days[-1]:.1f}天")
                print(f"    7天后仍存活:        {alive_7d}/{len(trial_days)}")
                if alive_3d > 0:
                    print(f"    ⚠️ 3天内到期:      {alive_3d}个")
        except Exception as e:
            print(f"    读取Login Helper失败: {e}")
    else:
        print(f"    Login Helper文件未找到")

    # 操作建议
    print(f"\n  {'─' * 40}")
    print(f"  操作建议:")
    if not base_email:
        print(f"    🔧 在secrets.env设置 GMAIL_BASE=yourname@gmail.com")
    if not app_pw:
        print(f"    🔧 在secrets.env设置 GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx")
    if base_email and app_pw:
        print(f"    ✅ 配置就绪!")
        print(f"    → 验证IMAP: python {Path(__file__).name} check-imap")
        print(f"    → 注册1个:  python {Path(__file__).name} register")
        print(f"    → 批量10个: python {Path(__file__).name} batch 10")
        print(f"    → 守护进程: python {Path(__file__).name} monitor")

    print(f"\n{'═' * 70}\n")


# ============================================================
# 守护进程: 自动补充
# ============================================================

def run_monitor(base_email, app_password, prefix="ws", min_alive=10, interval=600):
    """
    长驻守护: 当7天内存活账号不足min_alive时自动注册补充
    """
    print(f"\n{'═' * 70}")
    print(f"  Gmail+alias守护进程 — 道法自然·生生不息")
    print(f"  最小存活池: {min_alive} | 检查间隔: {interval}s")
    print(f"  Ctrl+C 停止")
    print(f"{'═' * 70}\n")

    cycle = 0
    while True:
        cycle += 1
        now = datetime.now(CST)
        log(f"===== 守护周期 #{cycle} — {now.strftime('%H:%M:%S')} =====")

        # 检查号池
        alive_7d = 0
        if LH_ACCT_FILE.exists():
            try:
                accts = json.load(open(LH_ACCT_FILE, 'r', encoding='utf-8'))
                now_ms = time.time() * 1000
                for a in accts:
                    pe = a.get('usage', {}).get('planEnd', 0)
                    if pe and (pe - now_ms) / 86400000 > 7:
                        alive_7d += 1
            except Exception as e:
                log(f"读取号池失败: {e}", False)

        log(f"7天内存活账号: {alive_7d}/{min_alive}")

        if alive_7d < min_alive:
            need = min_alive - alive_7d
            log(f"号池不足! 需补充 {need} 个账号...", False)
            proxy = find_proxy()
            for i in range(need):
                state = load_state()
                idx = state.get("next_index", 1)
                log(f"自动注册 #{i+1}/{need}: ws{idx:03d}")
                result = register_one(base_email, app_password, idx, prefix=prefix,
                                      proxy=proxy, manual_verify=False)
                if result and result.get("status") == "registered":
                    state["next_index"] = idx + 1
                    state.setdefault("registered", []).append({
                        "email": result["email"], "index": idx,
                        "ts": result["timestamp"],
                    })
                    save_state(state)
                    log(f"自动补充成功: {result['email']}", True)
                else:
                    state["next_index"] = idx + 1
                    save_state(state)
                    log(f"自动补充失败: idx={idx}", False)
                time.sleep(random.uniform(10, 20))
        else:
            log(f"✅ 号池充足 ({alive_7d}>={min_alive}), 无需操作", True)

        log(f"下次检查: {(now + timedelta(seconds=interval)).strftime('%H:%M:%S')}")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            log("守护进程已停止")
            break


# ============================================================
# CLI 入口
# ============================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1].lower()

    # 加载配置
    secrets = load_secrets()
    base_email = secrets.get('GMAIL_BASE', '')
    app_pw = secrets.get('GMAIL_APP_PASSWORD', '')
    prefix = secrets.get('GMAIL_ALIAS_PREFIX', 'ws')

    def require_config():
        if not base_email:
            print("❌ 未配置 GMAIL_BASE! 请在 secrets.env 设置:")
            print("   GMAIL_BASE=yourname@gmail.com")
            sys.exit(1)
        if not app_pw and cmd not in ('status', 'inject'):
            print("⚠️  未配置 GMAIL_APP_PASSWORD — 将使用手动验证模式")

    if cmd == "status":
        show_status()

    elif cmd == "check-imap":
        require_config()
        check_imap_connectivity(base_email, app_pw)

    elif cmd == "register":
        require_config()
        state = load_state()
        idx = int(sys.argv[2]) if len(sys.argv) >= 3 else state.get("next_index", 1)
        proxy = find_proxy()
        result = register_one(base_email, app_pw, idx, prefix=prefix,
                               proxy=proxy, manual_verify=(not app_pw))
        if result:
            state["next_index"] = idx + 1
            if result.get("status") == "registered":
                state.setdefault("registered", []).append({
                    "email": result["email"], "index": idx,
                    "ts": result["timestamp"],
                })
            save_state(state)
            print(f"\n  结果: {result.get('status')} — {result.get('email')}")
        else:
            print("\n  注册失败")

    elif cmd == "batch":
        require_config()
        n = int(sys.argv[2]) if len(sys.argv) >= 3 else 1
        manual = "--manual" in sys.argv
        no_wait = "--no-wait" in sys.argv
        # 无App Password时默认no_wait模式(不阻塞)
        if not app_pw and not manual:
            no_wait = True
        batch_register(n, base_email, app_pw, prefix=prefix,
                       manual_verify=manual, no_wait=no_wait)

    elif cmd == "verify":
        gmail_pw = secrets.get('UNIFIED_PASSWORD', '') or 'wsy057066wsy'
        proxy = find_proxy() if '--proxy' in sys.argv else None
        verify_pending_accounts(base_email, gmail_pw, proxy=proxy)

    elif cmd == "quick":
        # 快速注册: 浏览器停在验证码页, 打开Gmail Spam, 用户手动输入码
        require_config()
        n = int(sys.argv[2]) if len(sys.argv) >= 3 else 1
        proxy = find_proxy()
        for i in range(n):
            state = load_state()
            idx = state.get("next_index", 1)
            alias = f"{base_email.split('@')[0]}+{prefix}{idx:03d}@gmail.com"
            pw = gen_password()
            print(f"\n{'▓' * 20} 快速注册 {i+1}/{n} (ws{idx:03d}) {'▓' * 20}")
            reg_status, reg_page = register_with_alias(alias, pw, proxy=proxy)
            state["next_index"] = idx + 1
            save_state(state)
            if reg_status == "verify" and reg_page:
                # 打开Gmail Spam(默认浏览器)
                import webbrowser
                webbrowser.open("https://mail.google.com/mail/u/0/#spam")
                try:
                    reg_page.run_js(f"document.title='需要验证码 - ws{idx:03d}';")
                except Exception: pass
                print(f"\n  {'█' * 50}")
                print(f"  📧 {alias}")
                print(f"  🔑 密码: {pw}")
                print(f"  📋 请在Gmail垃圾箱找到Windsurf邮件中的6位验证码")
                print(f"  📋 在打开的浏览器中输入验证码并提交")
                print(f"  {'█' * 50}")
                input("\n  按 Enter 确认已完成验证 (或直接Enter跳过)...")
                # 检查是否验证成功
                verified = False
                try:
                    check = reg_page.run_js("return {url:location.href, text:(document.body?.innerText||'').substring(0,200)};")
                    cu = (check.get('url','') if check else '').lower()
                    ct = (check.get('text','') if check else '').lower()
                    if any(k in ct for k in ['dashboard','welcome','get started','open windsurf','success']):
                        verified = True
                    elif 'register' not in cu and 'windsurf.com' in cu:
                        verified = True
                except Exception: pass
                try: reg_page.quit()
                except Exception: pass
                result = {
                    "email": alias, "windsurf_password": pw,
                    "base_email": base_email, "index": idx,
                    "path": "gmail_alias_quick",
                    "status": "registered" if verified else "pending_verify",
                    "timestamp": datetime.now(CST).isoformat(),
                }
                save_result(result)
                if verified:
                    state.setdefault("registered",[]).append({"email":alias,"index":idx,"ts":result["timestamp"]})
                    save_state(state)
                    inject_to_pool(result)
                    log(f"✅ {alias} 验证完成!", True)
                else:
                    log(f"⏳ {alias} 待验证", False)
            elif reg_status == "done":
                result = {"email":alias,"windsurf_password":pw,"base_email":base_email,
                          "index":idx,"path":"gmail_alias_direct","status":"registered",
                          "timestamp":datetime.now(CST).isoformat()}
                save_result(result)
                inject_to_pool(result)
                state.setdefault("registered",[]).append({"email":alias,"index":idx,"ts":result["timestamp"]})
                save_state(state)
                log(f"✅ {alias} 直接完成!", True)
            else:
                state.setdefault("failed",[]).append({"index":idx,"reason":reg_status,"ts":datetime.now(CST).isoformat()})
                save_state(state)
                log(f"❌ {alias} 失败: {reg_status}", False)
            if i < n-1:
                delay = random.uniform(8, 15)
                log(f"延迟 {delay:.0f}s...")
                time.sleep(delay)

    elif cmd == "inject":
        print(f"\n{'═' * 60}")
        print("  注入已注册账号到无感切号号池")
        print(f"{'═' * 60}\n")
        results = load_results()
        injected = 0
        for r in results:
            if r.get("status") == "registered":
                if inject_to_pool(r):
                    injected += 1
        print(f"\n  注入完成: {injected}/{len(results)} 个账号")

    elif cmd == "monitor":
        require_config()
        min_alive = int(sys.argv[2]) if len(sys.argv) >= 3 else 10
        interval = int(sys.argv[3]) if len(sys.argv) >= 4 else 600
        run_monitor(base_email, app_pw, prefix=prefix, min_alive=min_alive, interval=interval)

    elif cmd == "reset-index":
        n = int(sys.argv[2]) if len(sys.argv) >= 3 else 1
        state = load_state()
        old = state.get("next_index", 1)
        state["next_index"] = n
        save_state(state)
        print(f"  alias索引已重置: {old} → {n}")

    else:
        print(__doc__)


if __name__ == "__main__":
    main()
