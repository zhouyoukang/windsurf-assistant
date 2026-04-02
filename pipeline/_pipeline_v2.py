"""
Windsurf Pro Trial 全链路注册Pipeline v3 — 万法归宗·七行合一·上善若水
====================================================================
七条路径, 水流不息, 一条不通自动降级下一条:

  Path 1: 自建域名 (金 — 终极不封)     aiotvr.xyz + Cloudflare Email Routing
  Path 2: GitHub OAuth (木 — 绕过邮件)  GitHub账号一键注册, 无需邮件验证
  Path 3: Google OAuth (火 — 绕过邮件)  Google账号一键注册, 无需邮件验证
  Path 4: Yahoo半自动 (土 — 已验证)     脚本填表+人工CAPTCHA, 96账号皆此路
  Path 5: Outlook半自动 (水 — 备用)     类似Yahoo, 另一通道
  Path 6: tempmail.lol全自动 (雷 — v3)  API创建+注册+API收信, 零人工
  Path 7: Gmail+alias (风 — v3)         1个Gmail=∞个Windsurf, IMAP自动

用法:
  python _pipeline_v2.py status              # 号池+到期时间线
  python _pipeline_v2.py domain EMAIL        # Path 1: 用自建域名邮箱注册
  python _pipeline_v2.py github              # Path 2: GitHub OAuth注册
  python _pipeline_v2.py google              # Path 3: Google OAuth注册
  python _pipeline_v2.py yahoo               # Path 4: Yahoo半自动注册
  python _pipeline_v2.py outlook             # Path 5: Outlook半自动注册
  python _pipeline_v2.py tempmail            # Path 6: tempmail.lol全自动 ★
  python _pipeline_v2.py gmail EMAIL [N] [PW]# Path 7: Gmail+alias (PW=AppPassword)
  python _pipeline_v2.py batch N             # 批量注册N个(默认tempmail)
  python _pipeline_v2.py analyze             # 全链路分析
"""

import json, os, sys, time, random, string, re, html as html_mod, base64, subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone

SCRIPT_DIR = Path(__file__).parent
RESULTS_FILE = SCRIPT_DIR / "_pipeline_v2_results.json"
PROXY_CANDIDATES = ["http://127.0.0.1:7890", "http://127.0.0.1:7897"]
WINDSURF_REGISTER_URL = "https://windsurf.com/account/register"
WINDSURF_LOGIN_URL = "https://windsurf.com/account/login"
LH_PATHS = [
    r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\undefined_publisher.windsurf-login-helper\windsurf-login-accounts.json',
    r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\windsurf-login-accounts.json',
]
CST = timezone(timedelta(hours=8))

FIRST_NAMES = ["Alex","Jordan","Taylor","Morgan","Casey","Riley","Quinn","Avery",
    "Charlie","Dakota","Emerson","Finley","Harper","Jamie","Kendall","Logan",
    "Madison","Parker","Reese","Skyler","Blake","Drew","Eden","Gray"]
LAST_NAMES = ["Anderson","Brooks","Carter","Davis","Edwards","Fisher","Garcia",
    "Hughes","Irving","Jensen","Kim","Lee","Mitchell","Nelson","Ortiz",
    "Park","Quinn","Rivera","Smith","Turner"]


def log(msg, ok=None):
    icon = "+" if ok is True else ("-" if ok is False else "*")
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}][{icon}] {msg}")


def gen_password():
    chars = string.ascii_letters + string.digits + "!@#$"
    pw = (random.choice(string.ascii_uppercase) + random.choice(string.ascii_lowercase) +
          random.choice(string.digits) + random.choice("!@#$") +
          ''.join(random.choices(chars, k=12)))
    return ''.join(random.sample(pw, len(pw)))


def gen_username():
    return ''.join(random.choices(string.ascii_lowercase, k=random.randint(5, 8))) + \
           ''.join(random.choices(string.digits, k=random.randint(4, 7)))


def find_chrome():
    for p in [
        os.path.join(os.environ.get('PROGRAMFILES', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
    ]:
        if os.path.exists(p):
            return p
    return None


def find_proxy():
    for p in PROXY_CANDIDATES:
        try:
            ps = ['$ProgressPreference="SilentlyContinue"',
                  f'try {{ (Invoke-WebRequest -Uri "https://httpbin.org/ip" -Proxy "{p}" -TimeoutSec 8 -UseBasicParsing).Content }} catch {{ "FAIL" }}']
            enc = base64.b64encode('\n'.join(ps).encode('utf-16-le')).decode()
            r = subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", enc],
                               capture_output=True, text=True, timeout=15, encoding='utf-8', errors='replace')
            if r.stdout.strip() and "FAIL" not in r.stdout:
                return p
        except:
            continue
    return PROXY_CANDIDATES[0]


def load_lh_accounts():
    for p in LH_PATHS:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
    return []


def load_results():
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_result(result):
    results = load_results()
    results.append(result)
    with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)


def _kill_stale_chrome():
    """Kill orphan chrome processes to prevent turnstilePatch conflicts."""
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/NH"],
                           capture_output=True, text=True, timeout=5)
        count = r.stdout.count("chrome.exe")
        if count > 0:
            subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"],
                           capture_output=True, timeout=10)
            time.sleep(2)
            log(f"Killed {count} stale chrome processes", True)
    except Exception:
        pass


def setup_browser(with_turnstile=True, incognito=True, proxy=None, kill_stale=True):
    from DrissionPage import ChromiumOptions, ChromiumPage
    if kill_stale:
        _kill_stale_chrome()
    chrome = find_chrome()
    co = ChromiumOptions()
    if chrome:
        co.set_browser_path(chrome)
    if incognito:
        co.set_argument("--incognito")
    co.auto_port()
    co.headless(False)
    if proxy:
        co.set_argument(f"--proxy-server={proxy}")
    if with_turnstile:
        tp = SCRIPT_DIR / "_archive" / "turnstilePatch"
        if not tp.exists():
            tp = SCRIPT_DIR / "turnstilePatch"
        if tp.exists():
            co.set_argument("--allow-extensions-in-incognito")
            co.add_extension(str(tp))
            log("turnstilePatch loaded", True)
    page = ChromiumPage(co)
    if with_turnstile:
        time.sleep(3)
        log("Extension warm-up complete (3s)", True)
    return page


def wait_turnstile(page, max_wait=45):
    start = time.time()
    while time.time() - start < max_wait:
        try:
            body = (page.html or "").lower()
            if any(k in body for k in ["verify your email", "check your email", "dashboard",
                                        "welcome", "password", "already have"]):
                return True
            try:
                btn = page.ele('tag:button@text():Continue', timeout=1)
                if btn and not btn.attr('disabled'):
                    btn.click()
                    time.sleep(2)
                    return True
            except:
                pass
            try:
                btn = page.ele('@type=submit', timeout=1)
                if btn and not btn.attr('disabled'):
                    btn.click()
                    time.sleep(2)
                    return True
            except:
                pass
        except:
            pass
        time.sleep(1)
    return False


# ============================================================
# PATH 1: 自建域名邮箱 (终极方案)
# ============================================================
def path_custom_domain(email_address):
    """
    使用自建域名邮箱注册 (如 ws001@aiotvr.xyz)
    前置条件: 域名已配置Cloudflare Email Routing catch-all
    邮件会转发到你的主邮箱, 你需要从中获取验证链接
    """
    print("=" * 60)
    print("PATH 1: 自建域名邮箱注册 (金 — 终极不封)")
    print(f"  Email: {email_address}")
    print("=" * 60)

    fn = random.choice(FIRST_NAMES)
    ln = random.choice(LAST_NAMES)
    pw = gen_password()

    log("Launching browser with turnstilePatch...")
    page = setup_browser(with_turnstile=True)

    try:
        log(f"Navigating to {WINDSURF_REGISTER_URL}...")
        page.get(WINDSURF_REGISTER_URL)
        time.sleep(random.uniform(2, 4))

        log("Filling form...")
        for sel, val in [('@name=firstName', fn), ('@name=lastName', ln), ('@name=email', email_address)]:
            el = page.ele(sel, timeout=5)
            if el:
                el.input(val)
                time.sleep(random.uniform(0.3, 0.8))

        # Checkbox
        try:
            cb = page.ele('tag:input@type=checkbox', timeout=2)
            if cb and not cb.attr('checked'):
                cb.click()
        except:
            pass

        # Continue
        try:
            btn = page.ele('tag:button@text():Continue', timeout=3) or page.ele('@type=submit', timeout=2)
            if btn:
                btn.click()
                time.sleep(random.uniform(3, 5))
        except:
            pass

        log("Waiting for Turnstile...")
        wait_turnstile(page, 30)

        # Password step
        pi = page.ele('@type=password', timeout=5)
        if pi:
            pi.input(pw)
            time.sleep(0.5)
            try:
                pc = page.ele('@placeholder:Confirm', timeout=2)
                if pc:
                    pc.input(pw)
            except:
                pass
            sub = page.ele('@type=submit', timeout=2) or page.ele('tag:button@text():Continue', timeout=2)
            if sub:
                sub.click()
                time.sleep(3)
            log("Password set", True)
            wait_turnstile(page, 20)

        body = (page.html or "").lower()
        if any(k in body for k in ["verify your email", "check your email"]):
            log("Verification email stage reached!", True)
            print()
            print("=" * 60)
            print("⚡ 验证邮件已发送到你的域名邮箱!")
            print(f"   检查你的主邮箱收件箱 (Cloudflare转发)")
            print(f"   找到Windsurf/Codeium的验证邮件")
            print(f"   点击验证链接完成注册")
            print(f"   然后在此按Enter确认")
            print("=" * 60)
            input("\n按 Enter 确认已完成验证...")

            result = {
                "email": email_address, "password": pw,
                "first_name": fn, "last_name": ln,
                "path": "custom_domain", "status": "registered",
                "timestamp": datetime.now().isoformat(),
            }
            save_result(result)
            log(f"SUCCESS: {email_address}", True)
            return result

        log("Unknown state after form submission", False)
        print("  ⚡ 请检查浏览器并手动完成, 然后按Enter")
        input()
        result = {
            "email": email_address, "password": pw,
            "path": "custom_domain", "status": "manual",
            "timestamp": datetime.now().isoformat(),
        }
        save_result(result)
        return result

    except Exception as e:
        log(f"Error: {e}", False)
        import traceback; traceback.print_exc()
        return None
    finally:
        print("[*] Press Enter to close browser...")
        try: input()
        except: pass
        try: page.quit()
        except: pass


# ============================================================
# PATH 2: GitHub OAuth (绕过邮件验证)
# ============================================================
def path_github_oauth():
    """
    通过GitHub OAuth一键注册Windsurf
    前置条件: 已有GitHub账号并已登录 或 准备好GitHub凭据
    优势: 完全绕过邮件验证步骤
    """
    print("=" * 60)
    print("PATH 2: GITHUB OAUTH (木 — 绕过邮件验证)")
    print("=" * 60)
    print()
    print("  流程: 点击'Sign up with GitHub' → GitHub授权 → 完成")
    print("  需要: 已登录GitHub的浏览器会话 或 GitHub凭据")
    print()

    log("Launching browser (visible, non-incognito for GitHub cookies)...")
    # Non-incognito to preserve GitHub login session
    page = setup_browser(with_turnstile=False, incognito=False)

    try:
        log(f"Navigating to {WINDSURF_REGISTER_URL}...")
        page.get(WINDSURF_REGISTER_URL)
        time.sleep(3)

        # Click GitHub button
        log("Looking for GitHub OAuth button...")
        gh_btn = page.ele('tag:button@text():GitHub', timeout=5)
        if gh_btn:
            log("Clicking 'Sign up with GitHub'...", True)
            gh_btn.click()
            time.sleep(5)
        else:
            log("GitHub button not found!", False)
            return None

        # Check if we're on GitHub auth page or already redirected
        url = page.url
        log(f"Current URL: {url}")

        if "github.com" in url:
            log("On GitHub authorization page", True)
            # If logged in, should see authorize button
            try:
                auth_btn = page.ele('tag:button@text():Authorize', timeout=10)
                if auth_btn:
                    log("Clicking Authorize...", True)
                    auth_btn.click()
                    time.sleep(5)
            except:
                pass

            if "github.com/login" in page.url:
                log("GitHub login required", False)
                print()
                print("  ⚡ 请在GitHub登录页面输入你的GitHub凭据")
                print("  ⚡ 登录后授权Windsurf, 然后按Enter")
                input("\n按 Enter 确认已完成GitHub授权...")

        # Wait for redirect back to Windsurf
        for _ in range(10):
            if "windsurf.com" in page.url:
                break
            time.sleep(2)

        url = page.url
        body = (page.html or "").lower()
        if any(k in body for k in ["welcome", "dashboard", "get started"]) or "dashboard" in url:
            log("Registration via GitHub OAuth COMPLETE!", True)
            result = {
                "email": "(github_oauth)",
                "path": "github_oauth", "status": "registered",
                "timestamp": datetime.now().isoformat(),
                "url": url,
            }
            save_result(result)
            return result
        else:
            log(f"Final URL: {url}", False)
            print("  ⚡ 请检查浏览器状态并手动完成, 然后按Enter")
            input()
            result = {
                "email": "(github_oauth)",
                "path": "github_oauth", "status": "manual",
                "timestamp": datetime.now().isoformat(),
            }
            save_result(result)
            return result

    except Exception as e:
        log(f"Error: {e}", False)
        import traceback; traceback.print_exc()
        return None
    finally:
        print("[*] Press Enter to close browser...")
        try: input()
        except: pass
        try: page.quit()
        except: pass


# ============================================================
# PATH 3: Google OAuth (绕过邮件验证)
# ============================================================
def path_google_oauth():
    """
    通过Google OAuth一键注册Windsurf
    前置条件: 已有Google账号
    优势: 完全绕过邮件验证步骤
    """
    print("=" * 60)
    print("PATH 3: GOOGLE OAUTH (火 — 绕过邮件验证)")
    print("=" * 60)
    print()
    print("  流程: 点击'Sign up with Google' → Google选择账号 → 完成")
    print("  需要: Google账号")
    print()

    log("Launching browser (visible, non-incognito for Google cookies)...")
    page = setup_browser(with_turnstile=False, incognito=False)

    try:
        log(f"Navigating to {WINDSURF_REGISTER_URL}...")
        page.get(WINDSURF_REGISTER_URL)
        time.sleep(3)

        # Click Google button
        log("Looking for Google OAuth button...")
        g_btn = page.ele('tag:button@text():Google', timeout=5)
        if g_btn:
            log("Clicking 'Sign up with Google'...", True)
            g_btn.click()
            time.sleep(5)
        else:
            log("Google button not found!", False)
            return None

        url = page.url
        log(f"Current URL: {url}")

        if "accounts.google.com" in url:
            log("On Google account selection page", True)
            print()
            print("  ⚡ 请在Google页面选择或登录你的Google账号")
            print("  ⚡ 授权完成后按Enter")
            input("\n按 Enter 确认已完成Google授权...")

        # Wait for redirect
        for _ in range(10):
            if "windsurf.com" in page.url:
                break
            time.sleep(2)

        url = page.url
        body = (page.html or "").lower()
        if any(k in body for k in ["welcome", "dashboard", "get started"]) or "dashboard" in url:
            log("Registration via Google OAuth COMPLETE!", True)
            result = {
                "email": "(google_oauth)",
                "path": "google_oauth", "status": "registered",
                "timestamp": datetime.now().isoformat(),
            }
            save_result(result)
            return result
        else:
            log(f"Final URL: {url}", False)
            print("  ⚡ 请手动完成, 然后按Enter")
            input()
            result = {
                "email": "(google_oauth)",
                "path": "google_oauth", "status": "manual",
                "timestamp": datetime.now().isoformat(),
            }
            save_result(result)
            return result

    except Exception as e:
        log(f"Error: {e}", False)
        import traceback; traceback.print_exc()
        return None
    finally:
        print("[*] Press Enter to close browser...")
        try: input()
        except: pass
        try: page.quit()
        except: pass


# ============================================================
# PATH 4: Yahoo半自动 (已验证路径)
# ============================================================
def path_yahoo():
    """
    Phase 1: Yahoo账号创建 (半自动)
    Phase 2: 用Yahoo邮箱注册Windsurf (全自动)
    这是96个现有账号使用的路径, 已充分验证
    """
    print("=" * 60)
    print("PATH 4: YAHOO半自动 (土 — 已验证路径)")
    print("=" * 60)

    # Phase 1: Create Yahoo
    username = gen_username()
    email = f"{username}@yahoo.com"
    fn = random.choice(FIRST_NAMES)
    ln = random.choice(LAST_NAMES)
    yahoo_pw = gen_password()
    birth_m = str(random.randint(1, 12))
    birth_d = str(random.randint(1, 28))
    birth_y = str(random.randint(1985, 2002))

    print(f"\n  Phase 1: Yahoo Account Creation")
    print(f"  Name:     {fn} {ln}")
    print(f"  Username: {username}")
    print(f"  Email:    {email}")
    print(f"  Password: {yahoo_pw}")
    print(f"  Birth:    {birth_m}/{birth_d}/{birth_y}")
    print()

    log("Launching browser for Yahoo signup...")
    page = setup_browser(with_turnstile=False, incognito=True)

    try:
        page.get("https://login.yahoo.com/account/create")
        time.sleep(3)

        # Auto-fill
        for sel, val in [
            ("@id=usernamereg-firstName", fn),
            ("@id=usernamereg-lastName", ln),
            ("@id=usernamereg-yid", username),
            ("@id=usernamereg-password", yahoo_pw),
        ]:
            try:
                el = page.ele(sel, timeout=3)
                if el:
                    el.input(val)
                    time.sleep(random.uniform(0.3, 0.7))
            except:
                pass

        # Birth date
        for sel, val in [
            ("@id=usernamereg-month", birth_m),
            ("@id=usernamereg-day", birth_d),
            ("@id=usernamereg-year", birth_y),
        ]:
            try:
                el = page.ele(sel, timeout=2)
                if el:
                    el.input(val)
            except:
                pass

        log("Form auto-filled!", True)
        print()
        print("=" * 60)
        print("⚡ 手动完成:")
        print("   1. 检查表单 → 2. 处理CAPTCHA → 3. 点Continue")
        print("   4. 完成手机验证 → 5. 按Enter确认")
        print("=" * 60)
        input("\n按 Enter 确认Yahoo账号已创建...")

        page.quit()
        log("Yahoo Phase 1 complete", True)

        # Phase 2: Register Windsurf
        print(f"\nPhase 2: Windsurf Registration with {email}")
        ws_pw = gen_password()

        page = setup_browser(with_turnstile=True, incognito=True)
        page.get(WINDSURF_REGISTER_URL)
        time.sleep(random.uniform(2, 4))

        for sel, val in [('@name=firstName', fn), ('@name=lastName', ln), ('@name=email', email)]:
            el = page.ele(sel, timeout=5)
            if el:
                el.input(val)
                time.sleep(random.uniform(0.3, 0.8))

        try:
            cb = page.ele('tag:input@type=checkbox', timeout=2)
            if cb and not cb.attr('checked'):
                cb.click()
        except:
            pass

        try:
            btn = page.ele('tag:button@text():Continue', timeout=3) or page.ele('@type=submit', timeout=2)
            if btn:
                btn.click()
                time.sleep(random.uniform(3, 5))
        except:
            pass

        wait_turnstile(page, 30)

        # Password
        pi = page.ele('@type=password', timeout=5)
        if pi:
            pi.input(ws_pw)
            time.sleep(0.5)
            try:
                pc = page.ele('@placeholder:Confirm', timeout=2)
                if pc:
                    pc.input(ws_pw)
            except:
                pass
            sub = page.ele('@type=submit', timeout=2)
            if sub:
                sub.click()
                time.sleep(3)
            wait_turnstile(page, 20)

        # Verify email
        body = (page.html or "").lower()
        if any(k in body for k in ["verify your email", "check your email"]):
            log("Verification email sent to Yahoo!", True)
            # Open Yahoo Mail
            page.new_tab()
            page.get("https://mail.yahoo.com")
            time.sleep(3)

            if "login" in page.url.lower():
                log("Yahoo login needed...")
                try:
                    uid = page.ele('@name=username', timeout=5)
                    if uid:
                        uid.input(email)
                        time.sleep(0.5)
                        page.ele('@id=login-signin', timeout=3).click()
                        time.sleep(3)
                        pwd = page.ele('@name=password', timeout=5)
                        if pwd:
                            pwd.input(yahoo_pw)
                            time.sleep(0.5)
                            page.ele('@id=login-signin', timeout=3).click()
                            time.sleep(5)
                except:
                    pass

            print()
            print("  ⚡ 在Yahoo Mail中找到Windsurf验证邮件并点击链接")
            input("\n按 Enter 确认已完成验证...")

        result = {
            "email": email, "yahoo_password": yahoo_pw, "windsurf_password": ws_pw,
            "first_name": fn, "last_name": ln,
            "path": "yahoo", "status": "registered",
            "timestamp": datetime.now().isoformat(),
        }
        save_result(result)
        log(f"SUCCESS: {email}", True)
        return result

    except Exception as e:
        log(f"Error: {e}", False)
        import traceback; traceback.print_exc()
        return None
    finally:
        try: page.quit()
        except: pass


# ============================================================
# PATH 5: Outlook半自动 (备用)
# ============================================================
def path_outlook():
    """类似Yahoo, 使用Outlook/Hotmail"""
    print("=" * 60)
    print("PATH 5: OUTLOOK半自动 (水 — 备用路径)")
    print("=" * 60)

    username = gen_username()
    email = f"{username}@outlook.com"
    fn = random.choice(FIRST_NAMES)
    ln = random.choice(LAST_NAMES)
    outlook_pw = gen_password()

    print(f"\n  Email:    {email}")
    print(f"  Password: {outlook_pw}")
    print()

    log("Launching browser for Outlook signup...")
    page = setup_browser(with_turnstile=False, incognito=True)

    try:
        page.get("https://signup.live.com/signup")
        time.sleep(3)

        log("Form opened. Please fill and complete manually.", True)
        print()
        print("⚡ 手动完成Outlook注册:")
        print(f"   Email: {email}")
        print(f"   Password: {outlook_pw}")
        print("   完成后按Enter")
        input("\n按 Enter 确认Outlook账号已创建...")

        page.quit()

        # Phase 2: Same as Yahoo Phase 2
        ws_pw = gen_password()
        page = setup_browser(with_turnstile=True, incognito=True)
        page.get(WINDSURF_REGISTER_URL)
        time.sleep(3)

        for sel, val in [('@name=firstName', fn), ('@name=lastName', ln), ('@name=email', email)]:
            el = page.ele(sel, timeout=5)
            if el:
                el.input(val)
                time.sleep(0.5)

        try:
            cb = page.ele('tag:input@type=checkbox', timeout=2)
            if cb and not cb.attr('checked'):
                cb.click()
        except:
            pass

        try:
            btn = page.ele('tag:button@text():Continue', timeout=3)
            if btn:
                btn.click()
                time.sleep(4)
        except:
            pass

        wait_turnstile(page, 30)

        pi = page.ele('@type=password', timeout=5)
        if pi:
            pi.input(ws_pw)
            time.sleep(0.5)
            try:
                pc = page.ele('@placeholder:Confirm', timeout=2)
                if pc: pc.input(ws_pw)
            except: pass
            sub = page.ele('@type=submit', timeout=2)
            if sub:
                sub.click()
                time.sleep(3)
            wait_turnstile(page, 20)

        print("  ⚡ 检查Outlook收件箱找验证邮件, 完成后按Enter")
        input()

        result = {
            "email": email, "outlook_password": outlook_pw, "windsurf_password": ws_pw,
            "path": "outlook", "status": "registered",
            "timestamp": datetime.now().isoformat(),
        }
        save_result(result)
        return result

    except Exception as e:
        log(f"Error: {e}", False)
        return None
    finally:
        try: page.quit()
        except: pass


# ============================================================
# PATH 6: tempmail.lol 全自动 (v3新增 — 水·穿石)
# ============================================================
def _ps_http(method, url, body=None, headers=None, proxy=None, timeout=20):
    """PowerShell HTTP helper for API calls"""
    ps = ['$ProgressPreference="SilentlyContinue"']
    iwr = f'Invoke-WebRequest -Uri "{url}" -Method {method} -UseBasicParsing -TimeoutSec {timeout}'
    if proxy:
        iwr += f' -Proxy "{proxy}"'
    if body:
        escaped = body.replace('"', '`"')
        iwr += f' -Body "{escaped}" -ContentType "application/json"'
    if headers:
        h = "; ".join(f'"{k}"="{v}"' for k, v in headers.items())
        iwr += f' -Headers @{{{h}}}'
    ps.append(f'try {{ $r = ({iwr}).Content; if ($r -is [byte[]]) {{ [System.Text.Encoding]::UTF8.GetString($r) }} else {{ $r }} }} catch {{ Write-Output ("ERROR:" + $_.Exception.Message) }}')
    enc = base64.b64encode('\n'.join(ps).encode('utf-16-le')).decode()
    r = subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", enc],
                       capture_output=True, text=True, timeout=timeout + 25,
                       encoding='utf-8', errors='replace')
    out = r.stdout.strip()
    if not out or out.startswith("ERROR:"):
        raise RuntimeError(out or f"empty, stderr={r.stderr[:200]}")
    for i, ch in enumerate(out):
        if ch in ('{', '['):
            try:
                return json.loads(out[i:])
            except:
                continue
    return {"_raw": out[:500]}


TEMPMAIL_BLOCKED_DOMAINS = {
    "leadharbor.org", "hush2u.com", "moonairse.com",
    "guerrillamailblock.com", "guerrillamail.com", "sharklasers.com",
    "sharebot.net", "grr.la", "spam4.me", "pokemail.net",
}
TEMPMAIL_KNOWN_GOOD = {"cloudvxz.com", "sixthirtydance.org"}


def tempmail_create(proxy=None, max_retries=5):
    """Create a tempmail.lol inbox with domain pre-check, return {address, token}"""
    for attempt in range(max_retries):
        d = _ps_http("GET", "https://api.tempmail.lol/v2/inbox/create", proxy=proxy, timeout=15)
        if isinstance(d, dict) and d.get("address"):
            addr = d["address"]
            domain = addr.split("@")[-1] if "@" in addr else ""
            base_domain = ".".join(domain.split(".")[-2:]) if domain.count(".") >= 2 else domain

            if base_domain in TEMPMAIL_BLOCKED_DOMAINS:
                log(f"Attempt {attempt+1}: {addr} — domain BLOCKED ({base_domain}), retrying...", False)
                continue
            if base_domain in TEMPMAIL_KNOWN_GOOD:
                log(f"Attempt {attempt+1}: {addr} — domain KNOWN GOOD ✓", True)
            else:
                log(f"Attempt {attempt+1}: {addr} — domain UNKNOWN (trying anyway)", True)
            return {"address": addr, "token": d.get("token", "")}
    raise RuntimeError(f"All {max_retries} tempmail domains were blocked")


def tempmail_check(token, proxy=None, max_wait=180, interval=10):
    """Poll tempmail.lol for emails, return first email with Windsurf/Codeium link"""
    start = time.time()
    while time.time() - start < max_wait:
        try:
            d = _ps_http("GET", f"https://api.tempmail.lol/v2/inbox?token={token}",
                         proxy=proxy, timeout=15)
            emails = d.get("emails", []) if isinstance(d, dict) else (d if isinstance(d, list) else [])
            for em in emails:
                body_text = em.get("body", "") or em.get("html", "") or ""
                # Look for verification link
                links = re.findall(r'https?://[^\s"\'<>]+', body_text)
                for link in links:
                    if any(k in link.lower() for k in ["windsurf", "codeium", "verify", "confirm", "auth"]):
                        return {"link": link, "email_from": em.get("from", ""), "subject": em.get("subject", "")}
            elapsed = int(time.time() - start)
            log(f"Polling emails... {elapsed}s/{max_wait}s ({len(emails)} emails found)")
        except Exception as e:
            log(f"Poll error: {e}", False)
        time.sleep(interval)
    return None


def path_tempmail():
    """
    PATH 6: 全自动tempmail.lol注册 — 零人工干预
    v3 Playwright实测: 2w.cloudvxz.com域名未被Windsurf封禁
    流程: API创建邮箱 → DrissionPage填表 → Turnstile → 密码 → API获取验证邮件 → 点击链接
    """
    print("=" * 60)
    print("PATH 6: TEMPMAIL.LOL 全自动 (v3 — 水·穿石)")
    print("=" * 60)

    proxy = find_proxy()
    log(f"Proxy: {proxy}")

    # Step 1: Create tempmail inbox
    log("Creating tempmail.lol inbox...")
    try:
        inbox = tempmail_create(proxy)
    except Exception as e:
        log(f"Failed to create inbox: {e}", False)
        return None
    email = inbox["address"]
    token = inbox["token"]
    log(f"Email: {email}", True)

    fn = random.choice(FIRST_NAMES)
    ln = random.choice(LAST_NAMES)
    ws_pw = gen_password()

    # Step 2: Register on Windsurf
    log("Launching browser with turnstilePatch...")
    page = setup_browser(with_turnstile=True, incognito=True, proxy=proxy)

    try:
        log(f"Navigating to {WINDSURF_REGISTER_URL}...")
        page.get(WINDSURF_REGISTER_URL)
        time.sleep(random.uniform(2, 4))

        log(f"Filling form: {fn} {ln} / {email}")
        for sel, val in [('@name=firstName', fn), ('@name=lastName', ln), ('@name=email', email)]:
            el = page.ele(sel, timeout=5)
            if el:
                el.input(val)
                time.sleep(random.uniform(0.3, 0.8))

        try:
            cb = page.ele('tag:input@type=checkbox', timeout=2)
            if cb and not cb.attr('checked'):
                cb.click()
        except:
            pass

        try:
            btn = page.ele('tag:button@text():Continue', timeout=3) or page.ele('@type=submit', timeout=2)
            if btn:
                btn.click()
                time.sleep(random.uniform(3, 5))
        except:
            pass

        log("Waiting for Turnstile...")
        wait_turnstile(page, 30)

        # Password step
        pi = page.ele('@type=password', timeout=8)
        if pi:
            log("Password step reached!", True)
            pi.input(ws_pw)
            time.sleep(0.5)
            try:
                pc = page.ele('@placeholder:Confirm', timeout=2)
                if pc:
                    pc.input(ws_pw)
            except:
                pass
            sub = page.ele('@type=submit', timeout=2) or page.ele('tag:button@text():Continue', timeout=2)
            if sub:
                sub.click()
                time.sleep(3)
            log("Password set", True)
            wait_turnstile(page, 20)
        else:
            log("Password step NOT reached (domain may be blocked)", False)
            body = (page.html or "").lower()
            if "verify your email" in body:
                log("Jumped to verify without password — domain likely detected", False)

        # Step 3: Wait for page transition after password
        for _wait in range(15):
            body = (page.html or "").lower()
            if any(k in body for k in ["verify your email", "check your email", "dashboard", "welcome"]):
                break
            # Try clicking submit again if still on register page
            if _wait == 5:
                try:
                    sub2 = page.ele('@type=submit', timeout=1) or page.ele('tag:button@text():Continue', timeout=1)
                    if sub2 and not sub2.attr('disabled'):
                        sub2.click()
                        log("Re-clicked submit button", True)
                except:
                    pass
            time.sleep(2)
        
        body = (page.html or "").lower()
        if any(k in body for k in ["verify your email", "check your email"]):
            log("Verification email stage! Polling tempmail.lol API...", True)
            result_email = tempmail_check(token, proxy=proxy, max_wait=180, interval=8)

            if result_email:
                link = result_email["link"]
                log(f"Verification link found: {link[:80]}...", True)

                # Click verification link
                page.get(link)
                time.sleep(5)

                body2 = (page.html or "").lower()
                if any(k in body2 for k in ["verified", "welcome", "dashboard", "login", "password"]):
                    log("EMAIL VERIFIED! Registration complete!", True)
                else:
                    log(f"Post-verify page: {page.url}", True)

                result = {
                    "email": email, "windsurf_password": ws_pw,
                    "first_name": fn, "last_name": ln,
                    "path": "tempmail_auto", "status": "registered",
                    "tempmail_token": token,
                    "timestamp": datetime.now().isoformat(),
                }
                save_result(result)
                log(f"SUCCESS: {email}", True)
                return result
            else:
                log("No verification email received in 180s", False)
                log("Domain may be silently blocked by Windsurf", False)
        else:
            # Check if already completed (unlikely for new reg)
            log(f"Current URL: {page.url}")
            body = (page.html or "").lower()
            if any(k in body for k in ["dashboard", "welcome"]):
                log("Registration seems complete!", True)
                result = {
                    "email": email, "windsurf_password": ws_pw,
                    "path": "tempmail_auto", "status": "registered",
                    "timestamp": datetime.now().isoformat(),
                }
                save_result(result)
                return result

        return None

    except Exception as e:
        log(f"Error: {e}", False)
        import traceback; traceback.print_exc()
        return None
    finally:
        try: page.quit()
        except: pass


# ============================================================
# PATH 7: Gmail+alias 全自动 (v3新增 — 金·无限)
# ============================================================
def path_gmail_alias(base_email, index=1, app_password=None):
    """
    PATH 7: Gmail+alias注册 — 1个Gmail = ∞个Windsurf
    v3 Playwright实测: Gmail+alias通过密码步骤(服务端接受)
    base_email: yourname@gmail.com
    index: ws001, ws002, ...
    app_password: Gmail App Password for IMAP (如果提供则自动获取验证邮件)
    """
    prefix = base_email.split("@")[0]
    alias_email = f"{prefix}+ws{index:03d}@gmail.com"

    print("=" * 60)
    print("PATH 7: GMAIL+ALIAS (v3 — 金·无限)")
    print(f"  Base:  {base_email}")
    print(f"  Alias: {alias_email}")
    print("=" * 60)

    fn = random.choice(FIRST_NAMES)
    ln = random.choice(LAST_NAMES)
    ws_pw = gen_password()

    log("Launching browser with turnstilePatch...")
    proxy = find_proxy()
    page = setup_browser(with_turnstile=True, incognito=True, proxy=proxy)

    try:
        log(f"Navigating to {WINDSURF_REGISTER_URL}...")
        page.get(WINDSURF_REGISTER_URL)
        time.sleep(random.uniform(2, 4))

        log(f"Filling form: {fn} {ln} / {alias_email}")
        for sel, val in [('@name=firstName', fn), ('@name=lastName', ln), ('@name=email', alias_email)]:
            el = page.ele(sel, timeout=5)
            if el:
                el.input(val)
                time.sleep(random.uniform(0.3, 0.8))

        try:
            cb = page.ele('tag:input@type=checkbox', timeout=2)
            if cb and not cb.attr('checked'):
                cb.click()
        except:
            pass

        try:
            btn = page.ele('tag:button@text():Continue', timeout=3) or page.ele('@type=submit', timeout=2)
            if btn:
                btn.click()
                time.sleep(random.uniform(3, 5))
        except:
            pass

        log("Waiting for Turnstile...")
        wait_turnstile(page, 30)

        # Password step
        pi = page.ele('@type=password', timeout=8)
        if pi:
            log("Password step reached — Gmail+alias accepted!", True)
            pi.input(ws_pw)
            time.sleep(0.5)
            try:
                pc = page.ele('@placeholder:Confirm', timeout=2)
                if pc:
                    pc.input(ws_pw)
            except:
                pass
            sub = page.ele('@type=submit', timeout=2) or page.ele('tag:button@text():Continue', timeout=2)
            if sub:
                sub.click()
                time.sleep(3)
            log("Password set", True)
            wait_turnstile(page, 20)
        else:
            log("Password step NOT reached!", False)

        body = (page.html or "").lower()
        if any(k in body for k in ["verify your email", "check your email"]):
            log("Verification email sent!", True)

            if app_password:
                # Auto-fetch via IMAP
                log("Checking Gmail via IMAP...")
                link = _gmail_imap_get_verify_link(base_email, app_password, alias_email)
                if link:
                    log(f"Verification link: {link[:80]}...", True)
                    page.get(link)
                    time.sleep(5)
                    log("Verification link clicked!", True)
                    result = {
                        "email": alias_email, "windsurf_password": ws_pw,
                        "first_name": fn, "last_name": ln,
                        "path": "gmail_alias_auto", "status": "registered",
                        "base_email": base_email, "index": index,
                        "timestamp": datetime.now().isoformat(),
                    }
                    save_result(result)
                    log(f"SUCCESS: {alias_email}", True)
                    return result
                else:
                    log("Could not find verification email via IMAP", False)

            # Fallback: manual
            print()
            print("=" * 60)
            print(f"⚡ 验证邮件已发送到 {base_email}")
            print(f"   (Gmail+alias: {alias_email} → 送达 {base_email})")
            print(f"   找到Windsurf验证邮件 → 点击链接 → 按Enter")
            print("=" * 60)
            input("\n按 Enter 确认已完成验证...")

            result = {
                "email": alias_email, "windsurf_password": ws_pw,
                "first_name": fn, "last_name": ln,
                "path": "gmail_alias", "status": "registered",
                "base_email": base_email, "index": index,
                "timestamp": datetime.now().isoformat(),
            }
            save_result(result)
            log(f"SUCCESS: {alias_email}", True)
            return result

        return None

    except Exception as e:
        log(f"Error: {e}", False)
        import traceback; traceback.print_exc()
        return None
    finally:
        try: page.quit()
        except: pass


def _gmail_imap_get_verify_link(email, app_password, alias_email, max_wait=120):
    """Fetch Windsurf verification email from Gmail via IMAP"""
    try:
        import imaplib
        import email as email_lib
        from email.header import decode_header

        log("Connecting to Gmail IMAP...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email, app_password)
        mail.select("inbox")

        start = time.time()
        while time.time() - start < max_wait:
            # Search for recent Windsurf/Codeium emails
            _, data = mail.search(None, f'(TO "{alias_email}" UNSEEN)')
            if not data[0]:
                _, data = mail.search(None, '(FROM "codeium" UNSEEN)')
            if not data[0]:
                _, data = mail.search(None, '(FROM "windsurf" UNSEEN)')

            ids = data[0].split()
            for eid in reversed(ids[-5:]):
                _, msg_data = mail.fetch(eid, "(RFC822)")
                msg = email_lib.message_from_bytes(msg_data[0][1])
                body_text = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        ct = part.get_content_type()
                        if ct in ("text/plain", "text/html"):
                            body_text += part.get_payload(decode=True).decode(errors="replace")
                else:
                    body_text = msg.get_payload(decode=True).decode(errors="replace")

                links = re.findall(r'https?://[^\s"\'<>]+', body_text)
                for link in links:
                    if any(k in link.lower() for k in ["verify", "confirm", "auth", "windsurf", "codeium"]):
                        mail.logout()
                        return link

            time.sleep(10)

        mail.logout()
    except Exception as e:
        log(f"IMAP error: {e}", False)
    return None


# ============================================================
# Status & Analysis
# ============================================================
def show_status():
    accts = load_lh_accounts()
    now_ms = time.time() * 1000
    now = datetime.now()

    print(f"{'═' * 70}")
    print(f"WINDSURF 号池状态 — {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═' * 70}")
    print(f"总账号: {len(accts)}")

    from collections import Counter
    plans = Counter()
    d_list, w_list, trial_days = [], [], []
    healthy = low = exhausted = 0
    batches = {}

    for a in accts:
        u = a.get("usage", {})
        plan = u.get("plan", "?")
        plans[plan] += 1
        d = u.get("daily", {})
        w = u.get("weekly", {})
        dr = d.get("remaining", 100) if d else 100
        wr = w.get("remaining", 100) if w else 100
        d_list.append(dr)
        w_list.append(wr)
        eff = min(dr, wr)
        if eff > 5: healthy += 1
        elif eff > 0: low += 1
        else: exhausted += 1

        pe = u.get("planEnd", 0)
        if pe:
            dl = max(0, (pe - now_ms) / 86400000)
            trial_days.append(dl)
            exp = datetime.fromtimestamp(pe / 1000, tz=CST).strftime("%m-%d")
            batches.setdefault(exp, 0)
            batches[exp] += 1

    print(f"\n计划: {dict(plans.most_common())}")
    print(f"健康: {healthy} | 低配额: {low} | 耗尽: {exhausted}")
    if d_list:
        print(f"日配额平均: {sum(d_list)/len(d_list):.1f}% | 周配额平均: {sum(w_list)/len(w_list):.1f}%")
    if trial_days:
        trial_days.sort()
        print(f"\nTrial剩余: {trial_days[0]:.1f}~{trial_days[-1]:.1f}天 (平均{sum(trial_days)/len(trial_days):.1f}天)")
        print(f"\n到期时间线:")
        for d_threshold in [3, 5, 7, 10, 14]:
            alive = sum(1 for t in trial_days if t > d_threshold)
            print(f"  {d_threshold}天后存活: {alive}/{len(trial_days)}")
        print(f"\n批次分布:")
        for exp in sorted(batches):
            print(f"  {exp}: {batches[exp]}个")

    # Pipeline results
    results = load_results()
    if results:
        print(f"\nPipeline v2 注册记录: {len(results)}")
        for r in results[-5:]:
            print(f"  {r.get('email', '?'):35} path={r.get('path', '?')} status={r.get('status', '?')}")

    print(f"\n{'═' * 70}")


def show_analyze():
    print("=" * 70)
    print("WINDSURF 全链路分析 — 万法归宗")
    print("=" * 70)

    accts = load_lh_accounts()
    now_ms = time.time() * 1000
    trial_days = []
    for a in accts:
        pe = a.get("usage", {}).get("planEnd", 0)
        if pe:
            trial_days.append(max(0, (pe - now_ms) / 86400000))

    trial_days.sort()
    total = len(accts)
    in5 = sum(1 for t in trial_days if t <= 5)
    in10 = sum(1 for t in trial_days if t <= 10)

    print(f"""
号池: {total}个账号, 全部@yahoo.com
配额: 95健康, 日均93.5%, 周均94.0%
到期: {in5}个5天内到期, {in10}个10天内到期

═══ 瓶颈根因 ═══
注册流程: 表单 → Turnstile → 密码 → Turnstile → 邮件验证
                  ✅已解决                         ❌瓶颈在此
一次性邮箱: 全部被Windsurf静默封禁(6次测试0成功)
  - guerrillamailblock.com → 收到GM欢迎邮件, 无Windsurf验证邮件
  - sharebot.net (Mail.tm) → 120s超时无任何邮件
  - sixthirtydance.org (tempmail.lol) → 120s超时无任何邮件

═══ 五行突破路径 ═══

  金 Path 1: 自建域名 ⭐⭐⭐⭐⭐ (终极)
     aiotvr.xyz已有 → Cloudflare Email Routing(免费)
     catch-all → ws001@aiotvr.xyz, ws002@aiotvr.xyz...
     成本: $0(域名已有) | 自动化: 95% | 封禁风险: 极低

  木 Path 2: GitHub OAuth ⭐⭐⭐⭐ (快速)
     注册页有"Sign up with GitHub"按钮
     完全绕过邮件验证 → 0封禁风险
     瓶颈: 需要GitHub账号(免费, 无需手机号)
     批量: GitHub账号可批量创建

  火 Path 3: Google OAuth ⭐⭐⭐⭐ (快速)
     注册页有"Sign up with Google"按钮
     完全绕过邮件验证
     瓶颈: Google账号(需手机号验证)

  土 Path 4: Yahoo半自动 ⭐⭐⭐ (已验证)
     96个现有账号全走此路
     脚本填表 + 人工CAPTCHA + 手机验证
     耗时: ~5min/个

  水 Path 5: Outlook半自动 ⭐⭐ (备用)
     类似Yahoo, 另一通道

═══ 推荐行动 ═══

  紧急(今天):
    1. 配置aiotvr.xyz Cloudflare Email Routing catch-all
    2. 用ws001@aiotvr.xyz测试注册一个Windsurf账号
    3. 成功后批量: ws002~ws100@aiotvr.xyz

  快速验证:
    1. 创建一个新GitHub账号
    2. 用GitHub OAuth注册Windsurf
    3. 确认是否直接获得Pro Trial

  持续补充:
    1. Yahoo半自动每天创建几个
    2. 保持号池>50个活跃Trial

═══ 成本模型 ═══

  自建域名: $0/年(aiotvr.xyz已有) + 无限账号 = $0/账号
  Yahoo:    $0 + 5min人工/个 = 时间成本
  GitHub:   $0 + 2min/个 = 时间成本
  目标:     维持50+活跃Trial, 日均2000+条Sonnet消息
""")
    print("=" * 70)


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if cmd == "status":
        show_status()
    elif cmd == "analyze":
        show_analyze()
    elif cmd == "domain" and len(sys.argv) >= 3:
        path_custom_domain(sys.argv[2])
    elif cmd == "github":
        path_github_oauth()
    elif cmd == "google":
        path_google_oauth()
    elif cmd == "yahoo":
        path_yahoo()
    elif cmd == "outlook":
        path_outlook()
    elif cmd == "tempmail":
        path_tempmail()
    elif cmd == "gmail" and len(sys.argv) >= 3:
        base = sys.argv[2]
        idx = int(sys.argv[3]) if len(sys.argv) >= 4 else 1
        app_pw = sys.argv[4] if len(sys.argv) >= 5 else None
        path_gmail_alias(base, idx, app_pw)
    elif cmd == "batch":
        n = int(sys.argv[2]) if len(sys.argv) >= 3 else 1
        print(f"Batch registration: {n} accounts")
        print("Choose path: 1=domain 2=github 3=google 4=yahoo 5=outlook 6=tempmail 7=gmail")
        choice = input("Path [6]: ").strip() or "6"
        for i in range(n):
            print(f"\n{'─' * 40} Account {i+1}/{n} {'─' * 40}")
            if choice == "1":
                prefix = f"ws{i+1:03d}"
                domain = input(f"Domain [aiotvr.xyz]: ").strip() or "aiotvr.xyz"
                path_custom_domain(f"{prefix}@{domain}")
            elif choice == "2":
                path_github_oauth()
            elif choice == "3":
                path_google_oauth()
            elif choice == "4":
                path_yahoo()
            elif choice == "5":
                path_outlook()
            elif choice == "6":
                path_tempmail()
            elif choice == "7":
                base = input("Gmail base email: ").strip()
                app_pw = input("Gmail App Password (空=手动验证): ").strip() or None
                path_gmail_alias(base, i + 1, app_pw)
            time.sleep(random.uniform(5, 15))
    else:
        print(__doc__)
