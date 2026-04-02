"""独立进程: 从Gmail Spam提取最新Windsurf验证码, 打印到stdout"""
import sys, time, re, json
from pathlib import Path

def main():
    gmail_user = sys.argv[1] if len(sys.argv) > 1 else ""
    gmail_pw = sys.argv[2] if len(sys.argv) > 2 else ""
    known_codes = set(sys.argv[3].split(",")) if len(sys.argv) > 3 and sys.argv[3] else set()
    max_wait = int(sys.argv[4]) if len(sys.argv) > 4 else 120

    if not gmail_user or not gmail_pw:
        print("ERROR:missing_args", flush=True)
        return

    from DrissionPage import ChromiumOptions, ChromiumPage

    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    chrome = None
    for p in chrome_paths:
        if Path(p).exists():
            chrome = p; break

    co = ChromiumOptions()
    if chrome: co.set_browser_path(chrome)
    co.auto_port()
    co.headless(False)

    page = ChromiumPage(co)
    try:
        page.get("https://accounts.google.com/ServiceLogin?service=mail&continue=https://mail.google.com/mail/u/0/%23spam")
        time.sleep(3)

        if "accounts.google.com" in (page.url or ""):
            ei = page.ele('@type=email', timeout=8) or page.ele('tag:input@name=identifier', timeout=3)
            if ei:
                ei.input(gmail_user); time.sleep(0.5)
                for s in ['tag:button@text():下一步', 'tag:button@text():Next', '@id=identifierNext']:
                    try:
                        b = page.ele(s, timeout=2)
                        if b: b.click(); time.sleep(3); break
                    except: pass
            pi = page.ele('@type=password', timeout=10)
            if pi:
                pi.input(gmail_pw); time.sleep(0.5)
                for s in ['tag:button@text():下一步', 'tag:button@text():Next', '@id=passwordNext']:
                    try:
                        b = page.ele(s, timeout=2)
                        if b: b.click(); time.sleep(5); break
                    except: pass

        for _ in range(20):
            if "mail.google.com" in (page.url or ""): break
            time.sleep(1)

        if "mail.google.com" not in (page.url or ""):
            print("ERROR:gmail_login_failed", flush=True)
            return

        page.get("https://mail.google.com/mail/u/0/#spam")
        time.sleep(3)

        # 记录旧码
        html0 = page.html or ""
        old_codes = set(re.findall(r'\b(\d{6})\b', html0)) | known_codes

        start = time.time()
        while time.time() - start < max_wait:
            html = page.html or ""
            all_six = re.findall(r'\b(\d{6})\b', html)
            new_codes = [c for c in all_six if c not in old_codes]
            if new_codes:
                print(f"CODE:{new_codes[0]}", flush=True)
                return

            body_text = page.run_js("return document.body.innerText || '';") or ""
            if 'Verify' in body_text or 'Windsurf' in body_text:
                codes_js = re.findall(r'\b(\d{6})\b', body_text)
                new_js = [c for c in codes_js if c not in old_codes]
                if new_js:
                    print(f"CODE:{new_js[0]}", flush=True)
                    return

            elapsed = int(time.time() - start)
            print(f"WAIT:{elapsed}s/{max_wait}s", flush=True)
            page.get("https://mail.google.com/mail/u/0/#spam")
            time.sleep(8)

        print("ERROR:timeout", flush=True)
    except Exception as e:
        print(f"ERROR:{e}", flush=True)
    finally:
        try: page.quit()
        except: pass

if __name__ == "__main__":
    main()
