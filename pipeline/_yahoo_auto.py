"""
Yahoo全自动注册引擎 — 水·穿石·层层递进
==========================================
Phase 1: Yahoo邮箱创建 (CAPTCHA服务 + SMS验证服务)
Phase 2: Windsurf注册 (DrissionPage + turnstilePatch)
Phase 3: 邮件验证 (IMAP自动获取)
Phase 4: 注入号池

CAPTCHA服务:
  - 2Captcha ($1/1000, 支持FunCaptcha/Arkose Labs)
  - CapSolver (AI解决, 更快, 支持FunCaptcha)
  - Anti-Captcha (类似2Captcha)

SMS验证服务:
  - SMS-Activate (sms-activate.org, ~$0.10/号, 全球号码)
  - 5sim.net (~$0.05/号, 便宜)
  - TextVerified (US号码, 稍贵)

用法:
  python _yahoo_auto.py                    # 交互式注册1个
  python _yahoo_auto.py --batch 5          # 批量注册5个
  python _yahoo_auto.py --captcha 2captcha # 指定CAPTCHA服务
  python _yahoo_auto.py --sms smsactivate  # 指定SMS服务
  python _yahoo_auto.py --full-auto        # 全自动(需配置API Key)

环境变量 (或 secrets.env):
  CAPTCHA_API_KEY     — 2Captcha/CapSolver API Key
  CAPTCHA_SERVICE     — 2captcha | capsolver | anticaptcha (默认: 2captcha)
  SMS_API_KEY         — SMS-Activate/5sim API Key
  SMS_SERVICE         — smsactivate | 5sim | textverified (默认: smsactivate)
"""

import json, os, sys, time, random, string, re, base64, subprocess, imaplib
from pathlib import Path
from datetime import datetime, timedelta, timezone

SCRIPT_DIR = Path(__file__).parent
CST = timezone(timedelta(hours=8))

# === Load secrets ===
SECRETS_ENV = Path(__file__).parent.parent / "secrets.env"
if not SECRETS_ENV.exists():
    for _drv in ["E:", "V:", "D:"]:
        _p = Path(_drv) / "道" / "道生一" / "一生二" / "secrets.env"
        if _p.exists():
            SECRETS_ENV = _p
            break


def load_secrets():
    """Load API keys from secrets.env"""
    secrets = {}
    if SECRETS_ENV.exists():
        for line in open(SECRETS_ENV, 'r', encoding='utf-8'):
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                secrets[k.strip()] = v.strip().strip('"').strip("'")
    # Also check env vars
    for key in ['CAPTCHA_API_KEY', 'CAPTCHA_SERVICE', 'SMS_API_KEY', 'SMS_SERVICE']:
        if key in os.environ:
            secrets[key] = os.environ[key]
    return secrets


SECRETS = load_secrets()
PROXY_CANDIDATES = ["http://127.0.0.1:7890", "http://127.0.0.1:7897"]

FIRST_NAMES = ["Alex","Jordan","Taylor","Morgan","Casey","Riley","Quinn","Avery",
    "Charlie","Dakota","Emerson","Finley","Harper","Jamie","Kendall","Logan",
    "Madison","Parker","Reese","Skyler","Blake","Drew","Eden","Gray"]
LAST_NAMES = ["Anderson","Brooks","Carter","Davis","Edwards","Fisher","Garcia",
    "Hughes","Irving","Jensen","Kim","Lee","Mitchell","Nelson","Ortiz",
    "Park","Quinn","Rivera","Smith","Turner"]

WINDSURF_REGISTER_URL = "https://windsurf.com/account/register"


def log(msg, ok=None):
    icon = "+" if ok is True else ("-" if ok is False else "*")
    ts = datetime.now(CST).strftime("%H:%M:%S")
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


def ps_http(method, url, body=None, headers=None, proxy=None, timeout=20):
    """PowerShell HTTP helper"""
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


def find_proxy():
    for p in PROXY_CANDIDATES:
        try:
            ps = ['$ProgressPreference="SilentlyContinue"',
                  f'try {{ (Invoke-WebRequest -Uri "https://httpbin.org/ip" -Proxy "{p}" -TimeoutSec 5 -UseBasicParsing).StatusCode }} catch {{ "FAIL" }}']
            enc = base64.b64encode('\n'.join(ps).encode('utf-16-le')).decode()
            r = subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", enc],
                               capture_output=True, text=True, timeout=12,
                               encoding='utf-8', errors='replace')
            if r.stdout.strip() and "FAIL" not in r.stdout:
                return p
        except:
            continue
    return PROXY_CANDIDATES[0]


# ============================================================
# CAPTCHA Solving Services
# ============================================================

class CaptchaSolver:
    """Base class for CAPTCHA solving services"""

    def __init__(self, api_key, proxy=None):
        self.api_key = api_key
        self.proxy = proxy

    def solve_funcaptcha(self, public_key, page_url, surl=None):
        raise NotImplementedError

    def solve_turnstile(self, site_key, page_url):
        raise NotImplementedError

    def get_balance(self):
        raise NotImplementedError


class TwoCaptchaSolver(CaptchaSolver):
    """2Captcha API integration (https://2captcha.com)"""

    BASE = "https://2captcha.com"

    def solve_funcaptcha(self, public_key, page_url, surl=None):
        """Solve FunCaptcha/Arkose Labs (used by Yahoo)"""
        log(f"2Captcha: Submitting FunCaptcha task...")
        params = {
            "key": self.api_key,
            "method": "funcaptcha",
            "publickey": public_key,
            "pageurl": page_url,
            "json": "1",
        }
        if surl:
            params["surl"] = surl

        # Submit task
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        result = ps_http("GET", f"{self.BASE}/in.php?{qs}", proxy=self.proxy)

        if not isinstance(result, dict) or result.get("status") != 1:
            raise RuntimeError(f"2Captcha submit failed: {result}")

        task_id = result["request"]
        log(f"2Captcha: Task {task_id} submitted, polling...")

        # Poll for result (max 120s)
        for _ in range(24):
            time.sleep(5)
            r = ps_http("GET",
                        f"{self.BASE}/res.php?key={self.api_key}&action=get&id={task_id}&json=1",
                        proxy=self.proxy)
            if isinstance(r, dict):
                if r.get("status") == 1:
                    log(f"2Captcha: Solved!", True)
                    return r["request"]
                elif r.get("request") == "CAPCHA_NOT_READY":
                    continue
                else:
                    raise RuntimeError(f"2Captcha error: {r}")

        raise RuntimeError("2Captcha: Timeout after 120s")

    def solve_turnstile(self, site_key, page_url):
        """Solve Cloudflare Turnstile"""
        log(f"2Captcha: Submitting Turnstile task...")
        params = {
            "key": self.api_key,
            "method": "turnstile",
            "sitekey": site_key,
            "pageurl": page_url,
            "json": "1",
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        result = ps_http("GET", f"{self.BASE}/in.php?{qs}", proxy=self.proxy)

        if not isinstance(result, dict) or result.get("status") != 1:
            raise RuntimeError(f"2Captcha submit failed: {result}")

        task_id = result["request"]
        log(f"2Captcha: Task {task_id} submitted...")

        for _ in range(24):
            time.sleep(5)
            r = ps_http("GET",
                        f"{self.BASE}/res.php?key={self.api_key}&action=get&id={task_id}&json=1",
                        proxy=self.proxy)
            if isinstance(r, dict):
                if r.get("status") == 1:
                    log(f"2Captcha: Turnstile solved!", True)
                    return r["request"]
                elif r.get("request") == "CAPCHA_NOT_READY":
                    continue
                else:
                    raise RuntimeError(f"2Captcha error: {r}")

        raise RuntimeError("2Captcha: Turnstile timeout")

    def get_balance(self):
        r = ps_http("GET",
                     f"{self.BASE}/res.php?key={self.api_key}&action=getbalance&json=1",
                     proxy=self.proxy)
        if isinstance(r, dict):
            return float(r.get("request", 0))
        return 0


class CapSolverSolver(CaptchaSolver):
    """CapSolver API integration (https://capsolver.com)"""

    BASE = "https://api.capsolver.com"

    def solve_funcaptcha(self, public_key, page_url, surl=None):
        log("CapSolver: Submitting FunCaptcha task...")
        task = {
            "type": "FunCaptchaTaskProxyLess",
            "websitePublicKey": public_key,
            "websiteURL": page_url,
        }
        if surl:
            task["funcaptchaApiJSSubdomain"] = surl

        body = json.dumps({"clientKey": self.api_key, "task": task})
        result = ps_http("POST", f"{self.BASE}/createTask", body=body, proxy=self.proxy)

        if not isinstance(result, dict) or result.get("errorId", 1) != 0:
            raise RuntimeError(f"CapSolver submit failed: {result}")

        task_id = result.get("taskId")
        if not task_id:
            # CapSolver sometimes returns solution directly
            solution = result.get("solution", {})
            if solution.get("token"):
                log("CapSolver: Instant solve!", True)
                return solution["token"]
            raise RuntimeError(f"CapSolver: No taskId in response: {result}")

        log(f"CapSolver: Task {task_id}, polling...")
        for _ in range(24):
            time.sleep(5)
            body = json.dumps({"clientKey": self.api_key, "taskId": task_id})
            r = ps_http("POST", f"{self.BASE}/getTaskResult", body=body, proxy=self.proxy)
            if isinstance(r, dict):
                status = r.get("status", "")
                if status == "ready":
                    token = r.get("solution", {}).get("token", "")
                    if token:
                        log("CapSolver: Solved!", True)
                        return token
                elif status == "processing":
                    continue
                else:
                    raise RuntimeError(f"CapSolver error: {r}")

        raise RuntimeError("CapSolver: Timeout")

    def get_balance(self):
        body = json.dumps({"clientKey": self.api_key})
        r = ps_http("POST", f"{self.BASE}/getBalance", body=body, proxy=self.proxy)
        if isinstance(r, dict):
            return float(r.get("balance", 0))
        return 0


# ============================================================
# SMS Verification Services
# ============================================================

class SMSProvider:
    """Base class for SMS verification services"""

    def __init__(self, api_key, proxy=None):
        self.api_key = api_key
        self.proxy = proxy

    def get_number(self, service="yahoo", country="us"):
        raise NotImplementedError

    def get_sms_code(self, activation_id, timeout=120):
        raise NotImplementedError

    def cancel(self, activation_id):
        raise NotImplementedError

    def get_balance(self):
        raise NotImplementedError


class SMSActivateProvider(SMSProvider):
    """SMS-Activate API (https://sms-activate.org)"""

    BASE = "https://api.sms-activate.org/stubs/handler_api.php"
    # Yahoo service code = "yh" on sms-activate
    SERVICE_MAP = {"yahoo": "yh", "google": "go", "github": "gh", "outlook": "ho"}

    def get_number(self, service="yahoo", country="us"):
        svc = self.SERVICE_MAP.get(service, service)
        # Country codes: us=187, cn=0, ru=0, in=22
        country_map = {"us": "187", "uk": "16", "ru": "0", "cn": "0", "in": "22"}
        cc = country_map.get(country, "187")

        r = ps_http("GET",
                     f"{self.BASE}?api_key={self.api_key}&action=getNumber&service={svc}&country={cc}",
                     proxy=self.proxy)
        if isinstance(r, dict) and r.get("_raw", "").startswith("ACCESS_NUMBER"):
            # Response: ACCESS_NUMBER:ID:NUMBER
            parts = r["_raw"].split(":")
            if len(parts) >= 3:
                return {"activation_id": parts[1], "number": parts[2]}
        elif isinstance(r, str) and r.startswith("ACCESS_NUMBER"):
            parts = r.split(":")
            return {"activation_id": parts[1], "number": parts[2]}
        raise RuntimeError(f"SMS-Activate get_number failed: {r}")

    def get_sms_code(self, activation_id, timeout=120):
        start = time.time()
        while time.time() - start < timeout:
            r = ps_http("GET",
                        f"{self.BASE}?api_key={self.api_key}&action=getStatus&id={activation_id}",
                        proxy=self.proxy)
            raw = r.get("_raw", str(r)) if isinstance(r, dict) else str(r)
            if "STATUS_OK" in raw:
                # Response: STATUS_OK:CODE
                code = raw.split(":")[-1].strip()
                return code
            elif "STATUS_WAIT_CODE" in raw:
                pass  # Still waiting
            elif "STATUS_CANCEL" in raw:
                raise RuntimeError("SMS activation cancelled")
            time.sleep(5)
        return None

    def cancel(self, activation_id):
        ps_http("GET",
                f"{self.BASE}?api_key={self.api_key}&action=setStatus&id={activation_id}&status=8",
                proxy=self.proxy)

    def get_balance(self):
        r = ps_http("GET",
                     f"{self.BASE}?api_key={self.api_key}&action=getBalance",
                     proxy=self.proxy)
        raw = r.get("_raw", str(r)) if isinstance(r, dict) else str(r)
        if "ACCESS_BALANCE" in raw:
            return float(raw.split(":")[-1].strip())
        return 0


class FiveSimProvider(SMSProvider):
    """5sim.net API (https://5sim.net)"""

    BASE = "https://5sim.net/v1"
    SERVICE_MAP = {"yahoo": "yahoo", "google": "google", "github": "github"}

    def get_number(self, service="yahoo", country="usa"):
        svc = self.SERVICE_MAP.get(service, service)
        country_map = {"us": "usa", "uk": "england", "ru": "russia", "cn": "china"}
        cc = country_map.get(country, country)

        r = ps_http("GET",
                     f"{self.BASE}/user/buy/activation/{cc}/any/{svc}",
                     headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
                     proxy=self.proxy)
        if isinstance(r, dict) and r.get("phone"):
            return {"activation_id": str(r["id"]), "number": r["phone"]}
        raise RuntimeError(f"5sim get_number failed: {r}")

    def get_sms_code(self, activation_id, timeout=120):
        start = time.time()
        while time.time() - start < timeout:
            r = ps_http("GET",
                        f"{self.BASE}/user/check/{activation_id}",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        proxy=self.proxy)
            if isinstance(r, dict):
                sms_list = r.get("sms", [])
                if sms_list:
                    code = sms_list[0].get("code", "")
                    if code:
                        return code
            time.sleep(5)
        return None

    def get_balance(self):
        r = ps_http("GET", f"{self.BASE}/user/profile",
                     headers={"Authorization": f"Bearer {self.api_key}"},
                     proxy=self.proxy)
        if isinstance(r, dict):
            return float(r.get("balance", 0))
        return 0


# ============================================================
# Browser Setup
# ============================================================

def find_chrome():
    for p in [
        os.path.join(os.environ.get('PROGRAMFILES', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
    ]:
        if os.path.exists(p):
            return p
    return None


def setup_browser(with_turnstile=True, incognito=True, proxy=None):
    from DrissionPage import ChromiumOptions, ChromiumPage
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
# Yahoo Full-Auto Registration
# ============================================================

# Yahoo FunCaptcha public key (extracted from Yahoo signup page)
YAHOO_FUNCAPTCHA_KEY = "B5B07C8C-2A0F-4202-8D2F-0DBBB25BA498"
YAHOO_SIGNUP_URL = "https://login.yahoo.com/account/create"


def create_yahoo_email(captcha_solver=None, sms_provider=None, proxy=None):
    """
    Phase 1: Create Yahoo email account.
    
    Three modes:
    1. FULL AUTO: captcha_solver + sms_provider → zero human intervention
    2. SEMI AUTO: captcha_solver only → human handles phone verification  
    3. MANUAL: no services → human handles CAPTCHA + phone
    """
    username = gen_username()
    email = f"{username}@yahoo.com"
    fn = random.choice(FIRST_NAMES)
    ln = random.choice(LAST_NAMES)
    yahoo_pw = gen_password()
    birth_m = str(random.randint(1, 12))
    birth_d = str(random.randint(1, 28))
    birth_y = str(random.randint(1985, 2002))

    mode = "FULL AUTO" if (captcha_solver and sms_provider) else \
           "SEMI AUTO" if captcha_solver else "MANUAL"

    print(f"\n{'═' * 60}")
    print(f"  YAHOO 账号创建 — {mode}")
    print(f"  Name:     {fn} {ln}")
    print(f"  Username: {username}")
    print(f"  Email:    {email}")
    print(f"  Password: {yahoo_pw}")
    print(f"  Birth:    {birth_m}/{birth_d}/{birth_y}")
    print(f"{'═' * 60}\n")

    log("Launching browser for Yahoo signup...")
    page = setup_browser(with_turnstile=False, incognito=True, proxy=proxy)

    sms_activation = None
    try:
        page.get(YAHOO_SIGNUP_URL)
        time.sleep(random.uniform(2, 4))

        # Auto-fill form
        field_map = [
            ("@id=usernamereg-firstName", fn),
            ("@id=usernamereg-lastName", ln),
            ("@id=usernamereg-yid", username),
            ("@id=usernamereg-password", yahoo_pw),
        ]
        for sel, val in field_map:
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

        # Phone number
        if sms_provider:
            log("Getting virtual phone number...")
            try:
                num_data = sms_provider.get_number(service="yahoo", country="us")
                phone = num_data["number"]
                sms_activation = num_data["activation_id"]
                log(f"Virtual number: {phone}", True)

                # Fill phone number
                try:
                    phone_input = page.ele("@id=usernamereg-phone", timeout=3)
                    if phone_input:
                        phone_input.input(phone)
                        time.sleep(0.5)
                except:
                    pass
            except Exception as e:
                log(f"SMS provider error: {e}", False)
                log("Falling back to manual phone entry")
                sms_provider = None

        # Click Continue / Submit
        try:
            btn = page.ele("@id=reg-submit-button", timeout=3)
            if not btn:
                btn = page.ele("tag:button@text():Continue", timeout=2)
            if not btn:
                btn = page.ele("@type=submit", timeout=2)
            if btn:
                btn.click()
                time.sleep(random.uniform(3, 5))
                log("Continue clicked", True)
        except:
            pass

        # Handle CAPTCHA (FunCaptcha/Arkose Labs)
        body = (page.html or "").lower()
        if "funcaptcha" in body or "arkoselabs" in body or "captcha" in body:
            if captcha_solver:
                log("FunCaptcha detected, solving via API...")
                try:
                    token = captcha_solver.solve_funcaptcha(
                        YAHOO_FUNCAPTCHA_KEY,
                        YAHOO_SIGNUP_URL,
                    )
                    # Inject token via JavaScript
                    page.run_js(f"""
                        var callback = document.querySelector('[data-callback]');
                        if (callback) callback.setAttribute('data-token', '{token}');
                        // Try ArkoseEnforcement API
                        if (window.ArkoseEnforcement) {{
                            window.ArkoseEnforcement.setToken('{token}');
                        }}
                    """)
                    time.sleep(2)
                    log("FunCaptcha token injected!", True)
                except Exception as e:
                    log(f"CAPTCHA solving failed: {e}", False)
                    log("Please solve CAPTCHA manually in browser")
                    input("\n按 Enter 确认CAPTCHA已解决...")
            else:
                log("FunCaptcha detected — please solve manually", False)
                input("\n按 Enter 确认CAPTCHA已解决...")

        # Handle phone verification SMS
        body = (page.html or "").lower()
        if "phone" in body or "verify" in body or "code" in body:
            if sms_provider and sms_activation:
                log("Waiting for SMS verification code...")
                code = sms_provider.get_sms_code(sms_activation, timeout=120)
                if code:
                    log(f"SMS code received: {code}", True)
                    # Find code input and fill
                    try:
                        code_input = page.ele("@id=verification-code-field", timeout=3)
                        if not code_input:
                            code_input = page.ele("@name=code", timeout=2)
                        if not code_input:
                            code_input = page.ele("tag:input@type=tel", timeout=2)
                        if code_input:
                            code_input.input(code)
                            time.sleep(0.5)
                            # Click verify
                            verify_btn = page.ele("tag:button@text():Verify", timeout=2)
                            if not verify_btn:
                                verify_btn = page.ele("@type=submit", timeout=2)
                            if verify_btn:
                                verify_btn.click()
                                time.sleep(3)
                            log("SMS code submitted!", True)
                    except Exception as e:
                        log(f"Code input failed: {e}", False)
                else:
                    log("No SMS code received in 120s", False)
                    log("Please complete phone verification manually")
                    input("\n按 Enter 确认手机验证已完成...")
            else:
                log("Phone verification required — please complete manually", False)
                print("  ⚡ 完成手机验证后按Enter")
                input()

        # Wait for account creation confirmation
        time.sleep(3)
        body = (page.html or "").lower()
        current_url = page.url

        if "yahoo.com" in current_url and any(k in body for k in ["welcome", "inbox", "done", "account created"]):
            log("Yahoo account created successfully!", True)
        else:
            log("Check browser for Yahoo account status...")
            if mode != "FULL AUTO":
                print("  ⚡ 确认Yahoo账号已创建后按Enter")
                input()

        page.quit()

        return {
            "email": email,
            "password": yahoo_pw,
            "first_name": fn,
            "last_name": ln,
            "birth": f"{birth_m}/{birth_d}/{birth_y}",
            "sms_activation": sms_activation,
            "mode": mode,
        }

    except Exception as e:
        log(f"Yahoo creation error: {e}", False)
        import traceback; traceback.print_exc()
        if sms_activation and sms_provider:
            try:
                sms_provider.cancel(sms_activation)
            except:
                pass
        return None
    finally:
        try:
            page.quit()
        except:
            pass


# ============================================================
# Windsurf Registration with Yahoo Email
# ============================================================

def register_windsurf(email, fn, ln, proxy=None):
    """Phase 2: Register Windsurf with Yahoo email"""
    ws_pw = gen_password()

    print(f"\n{'═' * 60}")
    print(f"  WINDSURF 注册 — {email}")
    print(f"{'═' * 60}\n")

    log("Launching browser with turnstilePatch...")
    page = setup_browser(with_turnstile=True, incognito=True, proxy=proxy)

    try:
        page.get(WINDSURF_REGISTER_URL)
        time.sleep(random.uniform(2, 4))

        # Fill form
        for sel, val in [('@name=firstName', fn), ('@name=lastName', ln), ('@name=email', email)]:
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

        # Password
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
            wait_turnstile(page, 20)

        # Check for verification email stage
        body = (page.html or "").lower()
        if any(k in body for k in ["verify your email", "check your email"]):
            log("Verification email sent to Yahoo!", True)
            return {"windsurf_password": ws_pw, "status": "verification_pending", "page": page}

        if any(k in body for k in ["dashboard", "welcome", "get started"]):
            log("Registration complete without email verification!", True)
            page.quit()
            return {"windsurf_password": ws_pw, "status": "registered"}

        log("Unknown registration state", False)
        page.quit()
        return {"windsurf_password": ws_pw, "status": "unknown"}

    except Exception as e:
        log(f"Windsurf registration error: {e}", False)
        try:
            page.quit()
        except:
            pass
        return None


# ============================================================
# Yahoo IMAP Verification
# ============================================================

def verify_via_yahoo_imap(email, password, max_wait=180):
    """Phase 3: Get Windsurf verification link from Yahoo Mail via IMAP"""
    log(f"Connecting to Yahoo IMAP for {email}...")
    try:
        mail = imaplib.IMAP4_SSL("imap.mail.yahoo.com", 993)
        mail.login(email, password)
        mail.select("INBOX")
        log("Yahoo IMAP connected!", True)

        import email as email_lib

        start = time.time()
        while time.time() - start < max_wait:
            # Search for Windsurf/Codeium verification emails
            for search_criteria in [
                '(FROM "codeium" UNSEEN)',
                '(FROM "windsurf" UNSEEN)',
                '(SUBJECT "verify" UNSEEN)',
            ]:
                try:
                    _, data = mail.search(None, search_criteria)
                    ids = data[0].split()
                    for eid in reversed(ids[-5:]):
                        _, msg_data = mail.fetch(eid, "(RFC822)")
                        msg = email_lib.message_from_bytes(msg_data[0][1])
                        body_text = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                ct = part.get_content_type()
                                if ct in ("text/plain", "text/html"):
                                    payload = part.get_payload(decode=True)
                                    if payload:
                                        body_text += payload.decode(errors="replace")
                        else:
                            payload = msg.get_payload(decode=True)
                            if payload:
                                body_text = payload.decode(errors="replace")

                        # Extract verification link
                        links = re.findall(r'https?://[^\s"\'<>]+', body_text)
                        for link in links:
                            if any(k in link.lower() for k in ["verify", "confirm", "auth", "windsurf", "codeium"]):
                                mail.logout()
                                log(f"Verification link found!", True)
                                return link
                except:
                    pass

            elapsed = int(time.time() - start)
            if elapsed % 30 == 0:
                log(f"Waiting for verification email... ({elapsed}s/{max_wait}s)")
            time.sleep(10)

        mail.logout()
        log("No verification email received", False)
        return None

    except Exception as e:
        log(f"IMAP error: {e}", False)
        return None


# ============================================================
# Full Pipeline: Yahoo → Windsurf → Verify → Inject
# ============================================================

def full_pipeline(captcha_service=None, sms_service=None):
    """Complete end-to-end pipeline"""
    proxy = find_proxy()
    log(f"Proxy: {proxy}")

    # Initialize services
    captcha_solver = None
    sms_provider = None

    captcha_key = SECRETS.get('CAPTCHA_API_KEY', '')
    sms_key = SECRETS.get('SMS_API_KEY', '')

    if captcha_key:
        svc = captcha_service or SECRETS.get('CAPTCHA_SERVICE', '2captcha')
        if svc == 'capsolver':
            captcha_solver = CapSolverSolver(captcha_key, proxy)
        else:
            captcha_solver = TwoCaptchaSolver(captcha_key, proxy)
        try:
            bal = captcha_solver.get_balance()
            log(f"CAPTCHA service ({svc}): Balance ${bal:.2f}", True)
        except Exception as e:
            log(f"CAPTCHA service check failed: {e}", False)
            captcha_solver = None

    if sms_key:
        svc = sms_service or SECRETS.get('SMS_SERVICE', 'smsactivate')
        if svc == '5sim':
            sms_provider = FiveSimProvider(sms_key, proxy)
        else:
            sms_provider = SMSActivateProvider(sms_key, proxy)
        try:
            bal = sms_provider.get_balance()
            log(f"SMS service ({svc}): Balance ${bal:.2f}", True)
        except Exception as e:
            log(f"SMS service check failed: {e}", False)
            sms_provider = None

    # 零成本降级：无付费SMS时，使用手机SIM短信桥
    if not sms_provider:
        try:
            from _zero_cost_engine import PhoneSMSBridge
            bridge = PhoneSMSBridge()
            if bridge.available:
                sms_provider = bridge
                log(f"手机SIM短信桥已激活 (号码: {bridge.phone_number or 'ADB'})", True)
        except Exception as e:
            log(f"PhoneSMSBridge不可用: {e}")

    # Phase 1: Create Yahoo email
    print(f"\n{'━' * 60}")
    print(f"  Phase 1: Yahoo邮箱创建")
    print(f"{'━' * 60}")

    yahoo = create_yahoo_email(
        captcha_solver=captcha_solver,
        sms_provider=sms_provider,
        proxy=proxy,
    )
    if not yahoo:
        log("Yahoo创建失败, 流程终止", False)
        return None

    email = yahoo["email"]
    yahoo_pw = yahoo["password"]
    fn = yahoo["first_name"]
    ln = yahoo["last_name"]

    # Phase 2: Register Windsurf
    print(f"\n{'━' * 60}")
    print(f"  Phase 2: Windsurf注册")
    print(f"{'━' * 60}")

    ws = register_windsurf(email, fn, ln, proxy=proxy)
    if not ws:
        log("Windsurf注册失败", False)
        return None

    ws_pw = ws["windsurf_password"]
    page = ws.get("page")

    # Phase 3: Email verification
    if ws["status"] == "verification_pending":
        print(f"\n{'━' * 60}")
        print(f"  Phase 3: 邮件验证")
        print(f"{'━' * 60}")

        # Try IMAP first
        link = verify_via_yahoo_imap(email, yahoo_pw, max_wait=180)
        if link:
            log(f"Verification link: {link[:80]}...", True)
            if page:
                try:
                    page.get(link)
                    time.sleep(5)
                    log("Verification link clicked in browser!", True)
                except:
                    pass
            # Also click via HTTP
            try:
                ps_http("GET", link, proxy=proxy, timeout=15)
                log("Verification link also accessed via HTTP", True)
            except:
                pass
        else:
            log("IMAP获取失败, 请手动验证", False)
            if page:
                # Open Yahoo Mail in browser
                page.new_tab()
                page.get("https://mail.yahoo.com")
                time.sleep(3)
                print("  ⚡ 在Yahoo Mail中找到Windsurf验证邮件并点击链接")
                input("\n按 Enter 确认已完成验证...")

    if page:
        try:
            page.quit()
        except:
            pass

    # Phase 4: Save result
    result = {
        "email": email,
        "yahoo_password": yahoo_pw,
        "windsurf_password": ws_pw,
        "first_name": fn,
        "last_name": ln,
        "path": "yahoo_auto_v3",
        "status": "registered",
        "mode": yahoo.get("mode", "MANUAL"),
        "timestamp": datetime.now(CST).isoformat(),
    }

    # Save to v3 results
    results_file = SCRIPT_DIR / "_pipeline_v3_results.json"
    results = []
    if results_file.exists():
        try:
            results = json.load(open(results_file, 'r', encoding='utf-8'))
        except:
            pass
    results.append(result)
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Phase 5: Inject to pool
    print(f"\n{'━' * 60}")
    print(f"  Phase 5: 注入号池")
    print(f"{'━' * 60}")

    # Inject to login-helper
    acct_file = Path(os.environ.get('APPDATA', '')) / 'Windsurf' / 'User' / 'globalStorage' / 'windsurf-login-accounts.json'
    if acct_file.exists():
        accounts = json.load(open(acct_file, 'r', encoding='utf-8'))
    else:
        accounts = []

    accounts.append({
        'email': email,
        'password': ws_pw,
        'loginCount': 0,
        'credits': 0,
        'usage': {'plan': 'Trial', 'mode': 'quota'},
    })
    with open(acct_file, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)
    log(f"已注入login-helper: {email}", True)

    # Inject to VSIX
    vsix_file = Path(os.environ.get('APPDATA', '')) / 'Windsurf' / 'User' / 'globalStorage' / 'zhouyoukang.windsurf-assistant' / 'windsurf-assistant-accounts.json'
    if vsix_file.parent.exists():
        vsix_accts = []
        if vsix_file.exists():
            try:
                vsix_accts = json.load(open(vsix_file, 'r', encoding='utf-8'))
            except:
                pass
        if not isinstance(vsix_accts, list):
            vsix_accts = []
        vsix_accts.append({
            "email": email,
            "password": ws_pw,
            "source": "yahoo_auto_v3",
            "injected_at": datetime.now(CST).isoformat(),
        })
        with open(vsix_file, 'w', encoding='utf-8') as f:
            json.dump(vsix_accts, f, indent=2, ensure_ascii=False)
        log(f"已注入VSIX号池: {email}", True)

    print(f"\n{'═' * 60}")
    print(f"  ✅ 全链路完成!")
    print(f"  Email:       {email}")
    print(f"  Yahoo PW:    {yahoo_pw}")
    print(f"  Windsurf PW: {ws_pw}")
    print(f"  Status:      {result['status']}")
    print(f"  Mode:        {result['mode']}")
    print(f"{'═' * 60}\n")

    return result


# ============================================================
# CLI
# ============================================================

def show_service_status():
    """Show CAPTCHA and SMS service availability"""
    print(f"\n{'═' * 60}")
    print(f"  服务状态检查")
    print(f"{'═' * 60}\n")

    captcha_key = SECRETS.get('CAPTCHA_API_KEY', '')
    sms_key = SECRETS.get('SMS_API_KEY', '')

    print(f"  CAPTCHA_API_KEY: {'✅ Configured' if captcha_key else '❌ Not set'}")
    print(f"  CAPTCHA_SERVICE: {SECRETS.get('CAPTCHA_SERVICE', '2captcha (default)')}")
    print(f"  SMS_API_KEY:     {'✅ Configured' if sms_key else '❌ Not set'}")
    print(f"  SMS_SERVICE:     {SECRETS.get('SMS_SERVICE', 'smsactivate (default)')}")

    if not captcha_key and not sms_key:
        print(f"\n  ⚠️  未配置API Key, 将使用手动模式 (MANUAL)")
        print(f"  配置方法:")
        print(f"    1. 在 secrets.env 中添加:")
        print(f"       CAPTCHA_API_KEY=your_2captcha_key")
        print(f"       SMS_API_KEY=your_smsactivate_key")
        print(f"    2. 或设置环境变量")
        print(f"\n  CAPTCHA服务:")
        print(f"    2Captcha: https://2captcha.com ($1/1000 CAPTCHAs)")
        print(f"    CapSolver: https://capsolver.com (AI-based, faster)")
        print(f"\n  SMS服务:")
        print(f"    SMS-Activate: https://sms-activate.org (~$0.10/号)")
        print(f"    5sim: https://5sim.net (~$0.05/号)")

    proxy = find_proxy()
    print(f"\n  Proxy: {proxy}")
    print(f"{'═' * 60}\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Yahoo全自动注册引擎")
    parser.add_argument("--batch", type=int, default=1, help="批量注册数量")
    parser.add_argument("--captcha", default=None, help="CAPTCHA服务: 2captcha|capsolver")
    parser.add_argument("--sms", default=None, help="SMS服务: smsactivate|5sim")
    parser.add_argument("--full-auto", action="store_true", help="全自动模式")
    parser.add_argument("--status", action="store_true", help="检查服务状态")
    args = parser.parse_args()

    if args.status:
        show_service_status()
        sys.exit(0)

    print(f"\n{'═' * 60}")
    print(f"  Yahoo全自动注册引擎 v3 — 道法自然·万法归宗")
    print(f"  Time: {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S CST')}")
    print(f"  Batch: {args.batch}")
    print(f"{'═' * 60}")

    show_service_status()

    for i in range(args.batch):
        if args.batch > 1:
            print(f"\n{'━' * 40} [{i+1}/{args.batch}] {'━' * 40}")

        result = full_pipeline(
            captcha_service=args.captcha,
            sms_service=args.sms,
        )

        if result:
            log(f"Account {i+1} complete: {result['email']}", True)
        else:
            log(f"Account {i+1} failed", False)

        if i < args.batch - 1:
            delay = random.uniform(15, 45)
            log(f"Cooling down {delay:.0f}s...")
            time.sleep(delay)

    print(f"\n  Done. Total: {args.batch}")
