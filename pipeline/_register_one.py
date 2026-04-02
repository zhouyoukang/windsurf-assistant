"""
Register ONE Windsurf Pro Trial Account — E2E
==============================================
DrissionPage + turnstilePatch + GuerrillaMail
Visible mode (headless=False) for best Turnstile success
"""

import json, os, sys, time, random, string, base64, subprocess, re, html as html_mod
from pathlib import Path
from datetime import datetime, timedelta

SCRIPT_DIR = Path(__file__).parent
PROXY_CANDIDATES = ["http://127.0.0.1:7890", "http://127.0.0.1:7897"]
GUERRILLA_API = "https://api.guerrillamail.com/ajax.php"
REGISTER_URL = "https://windsurf.com/account/register"
BLOCKED_DOMAINS = ["tempmail.com", "throwaway.email", "guerrillamail.info", "sharklasers.com"]

FIRST_NAMES = ["Alex","Jordan","Taylor","Morgan","Casey","Riley","Quinn","Avery",
    "Charlie","Dakota","Emerson","Finley","Harper","Jamie","Kendall","Logan"]
LAST_NAMES = ["Anderson","Brooks","Carter","Davis","Edwards","Fisher","Garcia",
    "Hughes","Irving","Jensen","Kim","Lee","Mitchell","Nelson"]

MAIL_SERVICE_DOMAINS = ['guerrillamail', 'grr.la', 'sharklasers', 'mail.tm', 'dollicons']


def log(msg, ok=None):
    icon = "+" if ok is True else ("-" if ok is False else "*")
    print(f"  [{icon}] {msg}")


def ps_http(method, url, body=None, headers=None, proxy=None, timeout=15):
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
                       capture_output=True, text=True, timeout=timeout + 20,
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


# === Proxy ===
def find_proxy():
    for p in PROXY_CANDIDATES:
        try:
            d = ps_http("GET", f"{GUERRILLA_API}?f=get_email_address", proxy=p, timeout=10)
            if d.get("email_addr"):
                return p
        except:
            continue
    return PROXY_CANDIDATES[0]


# === tempmail.lol (cold domain — less likely blocked) ===
class TempMailLol:
    def __init__(self, proxy):
        self.proxy = proxy
        self.token = None
        self.address = None

    def create_inbox(self):
        d = ps_http("GET", "https://api.tempmail.lol/v2/inbox/create", proxy=self.proxy, timeout=20)
        if not isinstance(d, dict) or not d.get("address"):
            raise RuntimeError(f"tempmail.lol create failed: {d}")
        self.address = d["address"]
        self.token = d.get("token", "")
        log(f"tempmail.lol inbox: {self.address}", True)
        return self.address

    def wait_for_email(self, timeout=120, poll=5, subject_filter=None):
        if not self.token:
            return None
        start = time.time()
        while time.time() - start < timeout:
            try:
                d = ps_http("GET", f"https://api.tempmail.lol/v2/inbox?token={self.token}",
                            proxy=self.proxy, timeout=15)
                emails = d.get("emails", []) if isinstance(d, dict) else []
                for m in emails:
                    subj = m.get("subject", "")
                    sender = m.get("from", "")
                    if subject_filter and subject_filter.lower() not in subj.lower():
                        continue
                    return {
                        "mail_subject": subj,
                        "mail_from": sender,
                        "mail_body": m.get("body", ""),
                        "text": m.get("body", ""),
                        "_raw": m,
                    }
            except Exception as e:
                log(f"tempmail.lol poll error: {e}")
            elapsed = int(time.time() - start)
            if elapsed % 15 == 0 and elapsed > 0:
                log(f"Still waiting for email... ({elapsed}s/{timeout}s)")
            time.sleep(poll)
        return None


# === Mail.tm (fallback #2) ===
class MailTm:
    def __init__(self, proxy):
        self.proxy = proxy
        self.api = "https://api.mail.tm"
        self.token = None
        self.address = None

    def create_inbox(self):
        # Get active domains
        d = ps_http("GET", f"{self.api}/domains", proxy=self.proxy, timeout=30)
        members = d.get("hydra:member", []) if isinstance(d, dict) else (d if isinstance(d, list) else [])
        active = [x["domain"] for x in members if isinstance(x, dict) and x.get("isActive")]
        if not active:
            raise RuntimeError("No active Mail.tm domains")
        dom = active[0]
        pfx = "ws" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        addr = f"{pfx}@{dom}"
        pw = ''.join(random.choices(string.ascii_letters + string.digits, k=14))
        # Create account
        ps_http("POST", f"{self.api}/accounts",
                body=json.dumps({"address": addr, "password": pw}), proxy=self.proxy, timeout=30)
        # Get token
        tok = ps_http("POST", f"{self.api}/token",
                      body=json.dumps({"address": addr, "password": pw}), proxy=self.proxy, timeout=30)
        self.token = tok.get("token", "") if isinstance(tok, dict) else ""
        self.address = addr
        if not self.token:
            raise RuntimeError(f"Mail.tm token failed: {tok}")
        log(f"Mail.tm inbox: {addr} (domain: {dom})", True)
        return addr

    def wait_for_email(self, timeout=120, poll=5, subject_filter=None):
        if not self.token:
            return None
        start = time.time()
        seen_ids = set()
        while time.time() - start < timeout:
            try:
                d = ps_http("GET", f"{self.api}/messages?page=1",
                            headers={"Authorization": f"Bearer {self.token}"},
                            proxy=self.proxy, timeout=15)
                msgs = d.get("hydra:member", []) if isinstance(d, dict) else (d if isinstance(d, list) else [])
                for m in msgs:
                    mid = m.get("id", "")
                    if not mid or mid in seen_ids:
                        continue
                    seen_ids.add(mid)
                    subj = m.get("subject", "")
                    if subject_filter and subject_filter.lower() not in subj.lower():
                        continue
                    # Fetch full message
                    full = ps_http("GET", f"{self.api}/messages/{mid}",
                                   headers={"Authorization": f"Bearer {self.token}"},
                                   proxy=self.proxy, timeout=15)
                    # Normalize to same format as GuerrillaMail
                    return {
                        "mail_subject": full.get("subject", subj),
                        "mail_from": full.get("from", {}).get("address", "?"),
                        "mail_body": full.get("html", [full.get("text", "")]),
                        "text": full.get("text", ""),
                        "_raw": full,
                    }
            except Exception as e:
                log(f"Mail.tm poll error: {e}")
            elapsed = int(time.time() - start)
            if elapsed % 15 == 0 and elapsed > 0:
                log(f"Still waiting for email... ({elapsed}s/{timeout}s)")
            time.sleep(poll)
        return None


# === GuerrillaMail (fallback) ===
class GuerrillaMail:
    def __init__(self, proxy):
        self.proxy = proxy
        self.sid = None

    def _req(self, params):
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{GUERRILLA_API}?{qs}"
        if self.sid:
            url += f"&sid_token={self.sid}"
        d = ps_http("GET", url, proxy=self.proxy, timeout=15)
        if isinstance(d, dict) and "sid_token" in d:
            self.sid = d["sid_token"]
        return d

    def create_inbox(self):
        d = self._req({"f": "get_email_address"})
        addr = d.get("email_addr", "")
        domain = addr.split("@")[-1] if "@" in addr else ""
        if domain in BLOCKED_DOMAINS:
            log(f"Domain {domain} is blocked, retrying...", False)
            d = self._req({"f": "get_email_address"})
            addr = d.get("email_addr", "")
        return addr

    def wait_for_email(self, timeout=120, poll=5, subject_filter=None):
        start = time.time()
        seen_ids = set()
        while time.time() - start < timeout:
            d = self._req({"f": "check_email", "seq": "0"})
            for m in d.get("list", []):
                mid = m.get("mail_id", "")
                if not mid or mid in seen_ids:
                    continue
                seen_ids.add(mid)
                subj = m.get("mail_subject", "")
                sender = m.get("mail_from", "")
                # Skip GuerrillaMail's own welcome/system emails
                if "guerrillamail" in sender.lower() or "guerrilla mail" in subj.lower():
                    log(f"Skipping GuerrillaMail system email: {subj[:50]}")
                    continue
                if subject_filter and subject_filter.lower() not in subj.lower():
                    continue
                return self._req({"f": "fetch_email", "email_id": mid})
            elapsed = int(time.time() - start)
            if elapsed % 15 == 0 and elapsed > 0:
                log(f"Still waiting for verification email... ({elapsed}s/{timeout}s)")
            time.sleep(poll)
        return None


# === Verification extraction ===
def extract_verification_link(msg):
    text = msg.get("mail_body", "") or ""
    if isinstance(text, list):
        text = " ".join(str(x) for x in text)
    content = html_mod.unescape(str(text))
    all_urls = re.findall(r'https?://[^\s<>"\']+', content)
    all_urls = [re.sub(r'["\'>;\s]+$', '', u.rstrip('.')) for u in all_urls]
    ext_urls = [u for u in all_urls if not any(d in u.lower() for d in MAIL_SERVICE_DOMAINS)]
    ws = [u for u in ext_urls if ('windsurf' in u.lower() or 'codeium' in u.lower())
          and any(k in u.lower() for k in ['verify', 'confirm', 'activate', 'auth', 'token', 'code', 'callback', 'magic'])]
    if ws:
        return ws[0]
    ws_any = [u for u in ext_urls if 'windsurf' in u.lower() or 'codeium' in u.lower()]
    if ws_any:
        return ws_any[0]
    verify = [u for u in ext_urls if any(k in u.lower() for k in ['verify', 'confirm', 'activate', 'token', 'code'])]
    if verify:
        return verify[0]
    return ext_urls[0] if ext_urls else None


def extract_verification_code(msg):
    text = msg.get("mail_body", "") or ""
    if isinstance(text, list):
        text = " ".join(str(x) for x in text)
    content = html_mod.unescape(str(text))
    codes = re.findall(r'\b(\d{4,8})\b', content)
    return codes[0] if codes else None


# === Chrome detection ===
def find_chrome():
    candidates = [
        os.path.join(os.environ.get('PROGRAMFILES', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


# === Turnstile handler ===
def handle_turnstile(page, max_wait=30):
    log("Handling Turnstile...")
    start = time.time()
    while time.time() - start < max_wait:
        try:
            body = page.html if hasattr(page, 'html') else ""
            if any(k in body.lower() for k in ["verify your email", "check your email", "dashboard", "welcome back", "password"]):
                log("Page transitioned past Turnstile!", True)
                return True

            # Try to find and interact with Turnstile
            try:
                iframe = page.ele('tag:iframe@src:challenges.cloudflare.com', timeout=2)
                if iframe:
                    time.sleep(random.uniform(2, 4))
            except:
                pass

            # Check for Continue button
            try:
                btn = page.ele('tag:button@text():Continue', timeout=1)
                if btn and not btn.attr('disabled'):
                    log("Continue enabled, clicking...")
                    btn.click()
                    time.sleep(3)
                    return True
            except:
                pass

            # Check for submit button
            try:
                btn = page.ele('@type=submit', timeout=1)
                if btn and not btn.attr('disabled'):
                    log("Submit enabled, clicking...")
                    btn.click()
                    time.sleep(3)
                    return True
            except:
                pass

        except Exception as e:
            pass
        time.sleep(1)

    # Final attempt
    try:
        btn = page.ele('tag:button@text():Continue', timeout=2)
        if btn and not btn.attr('disabled'):
            btn.click()
            time.sleep(3)
            return True
    except:
        pass
    log("Turnstile timeout", False)
    return False


# === Main registration ===
def register(auto_close=False):
    print("=" * 60)
    print("WINDSURF ACCOUNT REGISTRATION — E2E")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Step 0: Setup
    log("Finding proxy...")
    proxy = find_proxy()
    log(f"Proxy: {proxy}", True)

    chrome = find_chrome()
    if not chrome:
        log("Chrome not found! Cannot proceed.", False)
        return None
    log(f"Chrome: {chrome}", True)

    tp = SCRIPT_DIR / "_archive" / "turnstilePatch"
    if not tp.exists():
        tp = SCRIPT_DIR / "turnstilePatch"
    log(f"turnstilePatch: {'FOUND' if tp.exists() else 'MISSING'}", tp.exists())

    # Step 1: Create email (tempmail.lol → Mail.tm → GuerrillaMail)
    print(f"\n[Step 1] Creating temporary email...")
    mail = None
    email = None
    providers = [
        ("tempmail.lol", lambda: TempMailLol(proxy)),
        ("Mail.tm", lambda: MailTm(proxy)),
        ("GuerrillaMail", lambda: GuerrillaMail(proxy)),
    ]
    for name, factory in providers:
        try:
            mail = factory()
            email = mail.create_inbox()
            if email:
                log(f"Using {name}: {email}", True)
                break
        except Exception as e:
            log(f"{name} failed: {e}", False)
            mail = None
            email = None
    if not email:
        log("Failed to create email!", False)
        return None
    log(f"Email: {email}", True)

    # Step 2: Generate identity
    fn = random.choice(FIRST_NAMES)
    ln = random.choice(LAST_NAMES)
    chars = string.ascii_letters + string.digits + "!@#$"
    pw = (random.choice(string.ascii_uppercase) + random.choice(string.ascii_lowercase) +
          random.choice(string.digits) + random.choice("!@#$") +
          ''.join(random.choices(chars, k=12)))
    pw = ''.join(random.sample(pw, len(pw)))
    print(f"\n[Step 2] Identity: {fn} {ln}")

    # Step 3: Launch browser
    print(f"\n[Step 3] Launching DrissionPage...")
    from DrissionPage import ChromiumOptions, ChromiumPage

    co = ChromiumOptions()
    co.set_browser_path(chrome)
    co.set_argument("--incognito")
    co.auto_port()
    co.headless(False)  # Visible for Turnstile

    if tp.exists():
        co.set_argument("--allow-extensions-in-incognito")
        co.add_extension(str(tp))
        log("turnstilePatch loaded", True)

    page = ChromiumPage(co)
    log("Browser launched", True)

    try:
        # Step 4: Navigate to register page
        print(f"\n[Step 4] Navigating to {REGISTER_URL}...")
        page.get(REGISTER_URL)
        time.sleep(random.uniform(2, 4))
        log("Register page loaded", True)

        # Step 5: Fill form
        print(f"\n[Step 5] Filling form...")
        for sel, val in [('@name=firstName', fn), ('@name=lastName', ln), ('@name=email', email)]:
            el = page.ele(sel)
            if el:
                el.input(val)
                time.sleep(random.uniform(0.3, 0.8))
        log(f"Form filled: {fn} {ln} / {email}", True)

        # Checkbox
        try:
            cb = page.ele('tag:input@type=checkbox')
            if cb and not cb.attr('checked'):
                cb.click()
                time.sleep(0.5)
        except:
            pass

        # Click Continue
        try:
            btn = page.ele('tag:button@text():Continue') or page.ele('@type=submit')
            if btn:
                btn.click()
                time.sleep(random.uniform(3, 5))
        except:
            pass

        # Step 6: Turnstile #1
        print(f"\n[Step 6] Turnstile #1...")
        handle_turnstile(page, 30)

        # Step 7: Password (wait longer, may need Turnstile to resolve first)
        print(f"\n[Step 7] Setting password...")
        pi = None
        for attempt in range(5):
            pi = page.ele('@type=password', timeout=3)
            if pi:
                break
            # Also try name-based selectors
            pi = page.ele('@name=password', timeout=2)
            if pi:
                break
            # Check if page has moved past this
            body_check = (page.html or "").lower()
            if any(k in body_check for k in ["verify your email", "check your email", "code"]):
                log("Already past password step (email-first flow?)", True)
                break
            log(f"Password field not found yet (attempt {attempt+1}/5)...", False)
            time.sleep(2)
        if pi:
            pi.input(pw)
            time.sleep(0.5)
            # Confirm password if exists
            try:
                pc = page.ele('@placeholder:Confirm password', timeout=2) or page.ele('@name=passwordConfirmation', timeout=2)
                if pc:
                    pc.input(pw)
                    time.sleep(0.5)
            except:
                pass
            # Submit
            sub = page.ele('@type=submit', timeout=2) or page.ele('tag:button@text():Continue', timeout=2)
            if sub:
                sub.click()
                time.sleep(random.uniform(2, 4))
            log("Password set", True)
        elif 'verify' not in (page.html or '').lower():
            log("No password field found and not at verification", False)

        # Step 8: Turnstile #2
        print(f"\n[Step 8] Turnstile #2...")
        handle_turnstile(page, 30)

        # Step 9: Check current state
        print(f"\n[Step 9] Checking registration result...")
        body = page.html or ""
        body_lower = body.lower()

        if any(k in body_lower for k in ["verify your email", "check your email", "confirmation", "sent", "code"]):
            log("Verification email stage reached!", True)
            status = "verification_pending"
        elif any(k in body_lower for k in ["welcome", "dashboard", "get started"]):
            log("Registration complete (no verification needed)!", True)
            status = "registered"
        elif any(k in body_lower for k in ["already", "exists", "duplicate"]):
            log("Email already registered", False)
            status = "duplicate"
        elif any(k in body_lower for k in ["error", "invalid", "failed"]):
            log(f"Error detected in page", False)
            status = "error"
        else:
            # Take screenshot for debugging
            ss = str(SCRIPT_DIR / f"_reg_debug_{int(time.time())}.png")
            try:
                page.get_screenshot(path=ss)
                log(f"Unknown state. Screenshot: {ss}", False)
            except:
                log("Unknown state, screenshot failed", False)
            status = "unknown"

        # Step 10: Wait for verification email
        if status == "verification_pending":
            print(f"\n[Step 10] Waiting for verification email (180s)...")
            msg = mail.wait_for_email(timeout=180, poll=3)
            if msg:
                # DEBUG: Dump raw email content
                raw_body = msg.get("mail_body", "")
                raw_subject = msg.get("mail_subject", msg.get("subject", "?"))
                raw_from = msg.get("mail_from", msg.get("from", "?"))
                log(f"Email received! Subject: {raw_subject}", True)
                log(f"From: {raw_from}")
                
                # Save raw email for debugging
                debug_file = SCRIPT_DIR / f"_email_debug_{int(time.time())}.json"
                with open(debug_file, 'w', encoding='utf-8') as df:
                    json.dump(msg, df, indent=2, ensure_ascii=False, default=str)
                log(f"Raw email saved: {debug_file}")
                
                # Show snippet of body
                body_preview = str(raw_body)[:500] if raw_body else "(empty)"
                log(f"Body preview: {body_preview[:200]}")

                link = extract_verification_link(msg)
                code = extract_verification_code(msg)
                if link:
                    log(f"Verification link found: {link[:80]}...", True)
                    try:
                        ps_http("GET", link, proxy=proxy, timeout=15)
                        log("Verification link clicked!", True)
                        status = "verified"
                    except Exception as e:
                        log(f"Link click failed: {e}", False)
                        # Try opening in browser
                        try:
                            page.get(link)
                            time.sleep(5)
                            log("Opened link in browser instead", True)
                            status = "verified_browser"
                        except:
                            status = "link_failed"
                elif code:
                    log(f"Verification code: {code}", True)
                    # Try to input code on page
                    try:
                        for i, digit in enumerate(code):
                            inp = page.ele(f'@data-index={i}', timeout=2)
                            if inp:
                                inp.input(digit)
                                time.sleep(0.3)
                        log("Code entered", True)
                        time.sleep(3)
                        handle_turnstile(page, 15)
                        status = "verified"
                    except:
                        log("Could not enter code on page", False)
                        status = "code_found"
                else:
                    log("No link/code extracted. Check _email_debug_*.json", False)
                    status = "email_no_link"
            else:
                log("No verification email within timeout", False)
                status = "no_email"

        # Result
        print(f"\n{'=' * 60}")
        result = {
            "email": email,
            "password": pw,
            "first_name": fn,
            "last_name": ln,
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "engine": "drission",
        }

        if status in ("verified", "registered"):
            print(f"✅ SUCCESS: {email}")
            print(f"   Password: {pw}")
            print(f"   Status: {status}")
        else:
            print(f"⚠️ RESULT: {email}")
            print(f"   Password: {pw}")
            print(f"   Status: {status}")
        print(f"{'=' * 60}")

        # Save result
        out = SCRIPT_DIR / "_register_results.json"
        existing = []
        if out.exists():
            with open(out, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        existing.append(result)
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        log(f"Result saved to {out}", True)

        return result

    except Exception as e:
        log(f"Registration error: {e}", False)
        import traceback
        traceback.print_exc()
        return None
    finally:
        if not auto_close:
            print("\n[*] Browser is open. Press Enter to close...")
            try:
                input()
            except:
                pass
        try:
            page.quit()
        except:
            pass


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-wait", action="store_true", help="Skip Enter prompt, auto-close browser")
    args = ap.parse_args()
    register(auto_close=args.no_wait)
