"""
零成本邮箱注册引擎 — 道之根·万法归宗
========================================
三层降级：手机SIM真号 → Gmail别名 → 免费临时邮箱
全部零成本，无需任何付费API Key。

用法:
  python _zero_cost_engine.py status          # 检查所有资源状态
  python _zero_cost_engine.py phone           # 手机连接+SIM信息
  python _zero_cost_engine.py gmail-test      # Gmail IMAP连通性
  python _zero_cost_engine.py register        # 零成本注册1个Windsurf账号
  python _zero_cost_engine.py register --n=5  # 批量注册5个
"""

import json, os, sys, time, random, string, re, subprocess, imaplib
import email as email_lib
from pathlib import Path
from datetime import datetime, timedelta, timezone

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
CST = timezone(timedelta(hours=8))

SECRETS_ENV = PROJECT_ROOT / "secrets.env"
if not SECRETS_ENV.exists():
    for drive in ["E:", "V:", "D:"]:
        p = Path(drive) / "道" / "道生一" / "一生二" / "secrets.env"
        if p.exists():
            SECRETS_ENV = p
            break

ADB_EXE = None
for p in [PROJECT_ROOT / "scrcpy" / "adb.exe",
          Path(os.environ.get('LOCALAPPDATA', '')) / "Android" / "Sdk" / "platform-tools" / "adb.exe",
          Path("E:/道/道生一/一生二/scrcpy/adb.exe"),
          Path("D:/道/道生一/一生二/scrcpy/adb.exe")]:
    if p.exists():
        ADB_EXE = str(p)
        break


def log(msg, ok=None):
    icon = "+" if ok is True else ("-" if ok is False else "*")
    ts = datetime.now(CST).strftime("%H:%M:%S")
    print(f"  [{ts}][{icon}] {msg}")


def load_secrets():
    secrets = {}
    if SECRETS_ENV.exists():
        for line in open(SECRETS_ENV, 'r', encoding='utf-8'):
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                secrets[k.strip()] = v.strip().strip('"').strip("'")
    return secrets

SECRETS = load_secrets()


def adb(*args, timeout=10):
    if not ADB_EXE:
        return "", False
    try:
        r = subprocess.run([ADB_EXE] + list(args), capture_output=True,
                           text=True, timeout=timeout, encoding='utf-8', errors='replace')
        return r.stdout.strip(), r.returncode == 0
    except Exception as e:
        return str(e), False


def adb_devices():
    out, ok = adb("devices")
    devs = []
    if ok:
        for line in out.splitlines():
            if "\tdevice" in line:
                devs.append(line.split("\t")[0])
    return devs


def phone_connected():
    return len(adb_devices()) > 0


def screenstream_url():
    import urllib.request
    for port in range(8080, 8100):
        url = f"http://127.0.0.1:{port}"
        try:
            urllib.request.urlopen(f"{url}/status", timeout=1)
            return url
        except:
            pass
    return None


# ============================================================
# Layer 1: 手机SIM短信桥
# ============================================================

class PhoneSMSBridge:
    """ADB/ScreenStream读取手机SIM短信验证码，零成本替代SMS-Activate"""

    def __init__(self):
        self.phone_number = None
        self.ss_url = screenstream_url()
        if self.ss_url:
            log(f"ScreenStream: {self.ss_url}", True)
        if phone_connected():
            self._detect_sim()

    def _detect_sim(self):
        # 方法1: service call iphonesubinfo 15 → Parcel格式
        out, ok = adb("shell", "service", "call", "iphonesubinfo", "15")
        if ok and "Parcel" in out:
            # Parcel输出: '1.5.6.0.' → 提取所有单字符数字
            chars = re.findall(r"'(.+?)'", out)
            if chars:
                raw = ''.join(chars)
                digits = re.sub(r'[^0-9+]', '', raw)
                if len(digits) >= 8:
                    self.phone_number = digits
        # 方法2: dumpsys telephony
        if not self.phone_number:
            out, ok = adb("shell", "dumpsys", "telephony.registry")
            if ok:
                m = re.search(r'mLine1Number=(\+?\d+)', out)
                if m:
                    self.phone_number = m.group(1)
        # 方法3: getprop
        if not self.phone_number:
            out, ok = adb("shell", "getprop", "gsm.sim.operator.numeric")
            if ok and out:
                log(f"SIM运营商: {out}")
        if self.phone_number:
            log(f"SIM号码: {self.phone_number}", True)

    @property
    def available(self):
        return phone_connected() or self.ss_url is not None

    def get_number(self, service="yahoo", country="us"):
        if not self.available:
            raise RuntimeError("手机未连接")
        return {"activation_id": "phone_sim", "number": self.phone_number or "MANUAL"}

    def get_sms_code(self, activation_id=None, timeout=120, keyword=None):
        log(f"等待短信验证码 (最长{timeout}s)...")
        start = time.time()
        seen = set()
        while time.time() - start < timeout:
            code = self._try_notification(keyword) or self._try_sms_db(keyword, seen)
            if code:
                log(f"验证码: {code}", True)
                return code
            elapsed = int(time.time() - start)
            if elapsed > 0 and elapsed % 15 == 0:
                log(f"等待中... ({elapsed}s/{timeout}s)")
            time.sleep(3)
        log("超时", False)
        return None

    def _try_notification(self, keyword=None):
        if not self.ss_url:
            return None
        try:
            import urllib.request
            r = urllib.request.urlopen(f"{self.ss_url}/notifications/read", timeout=3)
            for n in reversed(json.loads(r.read())[-10:]):
                text = n.get("text", "") + " " + n.get("title", "")
                codes = re.findall(r'\b(\d{4,8})\b', text)
                if codes and (not keyword or keyword.lower() in text.lower()):
                    return codes[0]
        except:
            pass
        return None

    def _try_sms_db(self, keyword=None, seen=None):
        if seen is None:
            seen = set()
        out, ok = adb("shell", "content", "query", "--uri", "content://sms/inbox",
                       "--projection", "_id:body:date:address",
                       "--sort", "date DESC")
        if not ok:
            return None
        for line in out.splitlines():
            m_id = re.search(r'_id=(\d+)', line)
            m_body = re.search(r'body=(.+?)(?:,\s*date=|$)', line)
            if m_id and m_body:
                sid, body = m_id.group(1), m_body.group(1)
                if sid in seen:
                    continue
                seen.add(sid)
                codes = re.findall(r'\b(\d{4,8})\b', body)
                if codes and (not keyword or keyword.lower() in body.lower()):
                    return codes[0]
        return None

    def cancel(self, activation_id=None):
        pass

    def get_balance(self):
        return float('inf')


# ============================================================
# Layer 2: Gmail别名提供器
# ============================================================

class GmailAliasProvider:
    """Gmail +tag别名 + IMAP读取验证邮件，一个Gmail=无限注册"""

    def __init__(self, gmail=None, app_password=None):
        self.gmail = gmail or SECRETS.get('PHONE_GOOGLE_ACCOUNT', '')
        self.app_password = app_password or SECRETS.get('GMAIL_APP_PASSWORD', '')

    @property
    def available(self):
        return bool(self.gmail) and bool(self.app_password)

    def create_inbox(self):
        tag = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        local = self.gmail.split('@')[0]
        alias = f"{local}+ws{tag}@gmail.com"
        log(f"Gmail别名: {alias}", True)
        return alias

    def wait_for_email(self, timeout=120, poll=8, subject_filter=None):
        if not self.available:
            log("需配置GMAIL_APP_PASSWORD", False)
            return None
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            mail.login(self.gmail, self.app_password)
            mail.select("INBOX")
            log("Gmail IMAP已连接", True)
        except Exception as e:
            log(f"IMAP失败: {e}", False)
            return None

        start = time.time()
        try:
            while time.time() - start < timeout:
                for crit in ['(FROM "codeium" UNSEEN)', '(FROM "windsurf" UNSEEN)',
                             '(SUBJECT "verify" UNSEEN)']:
                    try:
                        _, data = mail.search(None, crit)
                        for eid in reversed(data[0].split()[-3:]):
                            _, md = mail.fetch(eid, "(RFC822)")
                            msg = email_lib.message_from_bytes(md[0][1])
                            subj = str(msg.get("Subject", ""))
                            if subject_filter and subject_filter.lower() not in subj.lower():
                                continue
                            body_text = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    if part.get_content_type() in ("text/plain", "text/html"):
                                        pl = part.get_payload(decode=True)
                                        if pl:
                                            body_text += pl.decode(errors="replace")
                            else:
                                pl = msg.get_payload(decode=True)
                                if pl:
                                    body_text = pl.decode(errors="replace")
                            mail.store(eid, '+FLAGS', '\\Seen')
                            log(f"收到邮件: {subj[:50]}", True)
                            return {"mail_subject": subj, "mail_from": str(msg.get("From", "")),
                                    "mail_body": body_text, "text": body_text}
                    except:
                        pass
                elapsed = int(time.time() - start)
                if elapsed > 0 and elapsed % 20 == 0:
                    log(f"等待邮件... ({elapsed}s/{timeout}s)")
                time.sleep(poll)
        finally:
            try:
                mail.logout()
            except:
                pass
        return None


# ============================================================
# 资源状态总览
# ============================================================

def status():
    print("\n" + "=" * 60)
    print("  零成本注册引擎 — 资源状态")
    print("=" * 60)

    # ADB
    print("\n[ADB]")
    log(f"adb.exe: {ADB_EXE or 'NOT FOUND'}", ADB_EXE is not None)
    devs = adb_devices()
    log(f"设备: {devs if devs else '无'}", len(devs) > 0)

    # ScreenStream
    print("\n[ScreenStream]")
    ss = screenstream_url()
    log(f"API: {ss or '未发现'}", ss is not None)

    # Phone SMS
    print("\n[手机SIM短信桥]")
    bridge = PhoneSMSBridge()
    log(f"可用: {bridge.available}", bridge.available)
    log(f"号码: {bridge.phone_number or '未获取'}", bridge.phone_number is not None)

    # Gmail
    print("\n[Gmail别名]")
    gmail = GmailAliasProvider()
    log(f"Gmail: {gmail.gmail or '未配置'}", bool(gmail.gmail))
    log(f"IMAP: {'已配置' if gmail.app_password else '未配置GMAIL_APP_PASSWORD'}", gmail.available)
    if gmail.gmail:
        sample = gmail.create_inbox()
        log(f"示例别名: {sample}")

    # Secrets
    print("\n[secrets.env]")
    log(f"路径: {SECRETS_ENV}", SECRETS_ENV.exists())
    has_captcha = bool(SECRETS.get('CAPTCHA_API_KEY'))
    has_sms = bool(SECRETS.get('SMS_API_KEY'))
    log(f"CAPTCHA_API_KEY: {'有' if has_captcha else '无(不需要)'}")
    log(f"SMS_API_KEY: {'有' if has_sms else '无(用手机SIM替代)'}")

    # 推荐路径
    print("\n[推荐注册路径]")
    if bridge.available:
        log("🥇 手机SIM真号 → Yahoo注册 → Windsurf注册 (完全零成本)", True)
    if gmail.available:
        log("🥈 Gmail别名 → Windsurf注册 (零成本, 无需Yahoo)", True)
    elif gmail.gmail:
        log("🥈 Gmail别名 → 需配置GMAIL_APP_PASSWORD后可用", False)
        log("   步骤: Google账号 → 安全 → 两步验证 → 应用密码")
        log(f"   然后在secrets.env添加: GMAIL_APP_PASSWORD=xxxx")
    log("🥉 临时邮箱(tempmail.lol/Mail.tm) → Windsurf注册 (已有)", True)

    print("\n" + "=" * 60)

    # 下一步行动
    print("\n[下一步行动]")
    actions = []
    if not bridge.available:
        actions.append("1. 连接OnePlus手机(USB) + 开启USB调试 + 启动ScreenStream")
    if not gmail.available and gmail.gmail:
        actions.append("2. 配置Gmail应用密码: secrets.env → GMAIL_APP_PASSWORD=xxxx")
    if not actions:
        actions.append("所有资源就绪! 运行: python _zero_cost_engine.py register")
    for a in actions:
        print(f"  → {a}")
    print()


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "status":
        status()
    elif cmd == "phone":
        bridge = PhoneSMSBridge()
        if bridge.available:
            print(f"手机已连接, 号码: {bridge.phone_number}")
            print("测试读取最近短信...")
            code = bridge.get_sms_code(timeout=5)
            print(f"最近验证码: {code or '无'}")
        else:
            print("手机未连接。请:")
            print("  1. USB线连接OnePlus手机")
            print("  2. 手机设置 → 开发者选项 → USB调试 → 开")
            print("  3. 手机上安装并启动ScreenStream")
    elif cmd == "gmail-test":
        g = GmailAliasProvider()
        if not g.gmail:
            print("未配置Gmail。在secrets.env添加PHONE_GOOGLE_ACCOUNT")
        elif not g.app_password:
            print(f"Gmail: {g.gmail}")
            print("需配置应用密码:")
            print("  1. 访问 https://myaccount.google.com/apppasswords")
            print("  2. 生成应用密码")
            print(f"  3. secrets.env添加: GMAIL_APP_PASSWORD=生成的密码")
        else:
            print(f"测试Gmail IMAP: {g.gmail}")
            try:
                m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
                m.login(g.gmail, g.app_password)
                m.select("INBOX")
                _, d = m.search(None, "ALL")
                total = len(d[0].split())
                m.logout()
                print(f"✅ IMAP连接成功! 收件箱: {total}封")
                alias = g.create_inbox()
                print(f"✅ 示例别名: {alias}")
            except Exception as e:
                print(f"❌ IMAP失败: {e}")
    elif cmd == "register":
        print("零成本注册Windsurf — 即将对接_register_one.py")
        print("请先运行 status 确认资源就绪")
        status()
    else:
        print(__doc__)
