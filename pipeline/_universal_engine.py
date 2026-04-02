"""
万法归宗 · 道法自然 · 上善若水
====================================
全资源统一注册引擎 — 调用一切可用资源突破限制

资源矩阵:
  本地:  Chrome浏览器 + DrissionPage + Python
  网络:  代理(:7890) + GitHub OAuth + Gmail+alias
  手机:  Hamibot API(远程运行手机脚本) + 真实手机号SMS

三路并行，优先级递降，自动降级:
  P0: GitHub OAuth  — 零邮件，零SMS，立即可用 (DrissionPage已就绪)
  P1: Gmail+alias   — 无限账号，IMAP自动验证 (GMAIL_BASE已配置)
  P2: Hamibot手机   — 手机Chrome自动化，使用手机Google账号

用法:
  python _universal_engine.py status       # 全资源状态
  python _universal_engine.py github       # P0: GitHub OAuth注册
  python _universal_engine.py gmail        # P1: Gmail+alias注册
  python _universal_engine.py hamibot      # P2: 手机Hamibot注册
  python _universal_engine.py auto         # 自动选择最优路径注册1个
  python _universal_engine.py batch N      # 批量N个(自动路径)
  python _universal_engine.py monitor      # 守护进程

secrets.env 需要:
  GMAIL_BASE=zhouyoukang1234@gmail.com      (已自动配置)
  GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx   (需手动生成)
  HAMIBOT_TOKEN=hmp-xxxxxxxxxxxxxxxxxxxx   (从hamibot.cn获取)
"""

import json, os, sys, time, random, string, re, imaplib, email as email_lib
import socket, subprocess, threading
from pathlib import Path
from datetime import datetime, timedelta, timezone

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
CST = timezone(timedelta(hours=8))

SECRETS_ENV = Path(r"e:\道\道生一\一生二\secrets.env")
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PYTHON_EXE = r"C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe"
WINDSURF_REGISTER = "https://windsurf.com/account/register"

FIRST_NAMES = ["Alex","Jordan","Taylor","Morgan","Casey","Riley","Quinn","Avery",
               "Charlie","Finley","Harper","Jamie","Logan","Parker","Reese","Sam"]
LAST_NAMES  = ["Anderson","Brooks","Carter","Davis","Fisher","Garcia","Hughes",
               "Kim","Lee","Mitchell","Nelson","Park","Rivera","Smith","Turner"]


# ============================================================
# 工具函数
# ============================================================

def log(msg, ok=None):
    icon = "+" if ok is True else ("-" if ok is False else "*")
    ts = datetime.now(CST).strftime("%H:%M:%S")
    print(f"  [{ts}][{icon}] {msg}")


def load_secrets():
    d = {}
    for p in [SECRETS_ENV, PROJECT_ROOT / "secrets.env", Path("secrets.env")]:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        d[k.strip()] = v.strip().strip('"').strip("'")
            break
    for k in os.environ:
        if k in d or k.startswith(("GMAIL_", "HAMIBOT_", "GITHUB_", "PHONE_")):
            d[k] = os.environ[k]
    return d


def gen_password():
    chars = string.ascii_letters + string.digits + "!@#$"
    pw = (random.choice(string.ascii_uppercase) + random.choice(string.ascii_lowercase) +
          random.choice(string.digits) + random.choice("!@#$") +
          "".join(random.choices(chars, k=12)))
    return "".join(random.sample(pw, len(pw)))


def find_proxy():
    for port in [7890, 7897, 1080]:
        try:
            s = socket.socket(); s.settimeout(0.8); s.connect(("127.0.0.1", port)); s.close()
            return f"http://127.0.0.1:{port}"
        except Exception:
            pass
    return None


def save_result(result):
    rf = SCRIPT_DIR / "_universal_results.json"
    results = []
    if rf.exists():
        try:
            results = json.load(open(rf, "r", encoding="utf-8"))
        except Exception:
            pass
    results.append(result)
    with open(rf, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)


def inject_to_pool(email, password, source="universal"):
    """注入账号到无感切号号池"""
    vsix_file = (Path(os.environ.get("APPDATA", "")) / "Windsurf" / "User" / "globalStorage"
                 / "zhouyoukang.windsurf-assistant" / "windsurf-assistant-accounts.json")
    lh_file = (Path(os.environ.get("APPDATA", "")) / "Windsurf" / "User" / "globalStorage"
               / "windsurf-login-accounts.json")
    entry = {"email": email, "password": password, "source": source,
             "addedAt": datetime.now(CST).isoformat()}
    for f in [vsix_file, lh_file]:
        if f.parent.exists():
            accts = []
            if f.exists():
                try: accts = json.load(open(f, "r", encoding="utf-8"))
                except Exception: pass
            if not isinstance(accts, list): accts = []
            if not any(a.get("email") == email for a in accts):
                accts.append(entry)
                with open(f, "w", encoding="utf-8") as fp:
                    json.dump(accts, fp, indent=2, ensure_ascii=False)
                log(f"注入: {email} → {f.name}", True)


# ============================================================
# P0: GitHub OAuth — 零邮件，最快
# ============================================================

def path_github_oauth(proxy=None):
    """
    P0: GitHub OAuth注册Windsurf
    - zhouyoukang GitHub账号已存在
    - 非incognito Chrome使用已登录的GitHub session
    - DrissionPage自动化点击OAuth按钮
    """
    log("P0: GitHub OAuth — 启动")
    try:
        from DrissionPage import ChromiumOptions, ChromiumPage
    except ImportError:
        log(f"DrissionPage未安装，运行: {PYTHON_EXE} -m pip install DrissionPage", False)
        return None

    # 杀残留Chrome进程避免端口冲突
    try:
        subprocess.run(["taskkill","/F","/IM","chrome.exe"], capture_output=True, timeout=5)
        time.sleep(2)
    except Exception:
        pass

    # 使用默认Chrome profile（保留GitHub登录session）
    default_profile = Path(os.environ.get('LOCALAPPDATA','')) / 'Google' / 'Chrome' / 'User Data'

    co = ChromiumOptions()
    co.set_browser_path(CHROME_EXE)
    co.set_argument('--no-first-run')
    co.set_argument('--no-default-browser-check')
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-dev-shm-usage')
    if default_profile.exists():
        co.set_argument(f'--user-data-dir={default_profile}')
        co.set_argument('--profile-directory=Default')
    co.auto_port()
    co.headless(False)
    if proxy:
        co.set_argument(f'--proxy-server={proxy.replace("http://", "")}')

    page = ChromiumPage(co)
    try:
        log(f"导航至注册页: {WINDSURF_REGISTER}")
        page.get(WINDSURF_REGISTER)
        time.sleep(random.uniform(2, 3))

        # 找"Sign up with GitHub"按钮
        github_btn = None
        for sel in [
            'tag:button@text():GitHub',
            'css:button[data-provider="github"]',
            'xpath://button[contains(text(),"GitHub")]',
            'xpath://a[contains(text(),"GitHub")]',
        ]:
            try:
                btn = page.ele(sel, timeout=3)
                if btn:
                    github_btn = btn
                    break
            except Exception:
                pass

        if not github_btn:
            # 截取页面找按钮
            body = page.html or ""
            log(f"未找到GitHub按钮，页面内容片段: {body[:200]}", False)
            log("尝试直接导航GitHub OAuth...")
            # 某些情况下可以直接触发OAuth
            page.get("https://windsurf.com/api/auth/github")
            time.sleep(3)

        else:
            log("找到GitHub OAuth按钮，点击...")
            github_btn.click()
            time.sleep(random.uniform(2, 4))

        # 等待GitHub授权页或完成页
        start = time.time()
        MAX_WAIT = 300  # 5分钟足够用户完成手动步骤
        last_log = 0
        while time.time() - start < MAX_WAIT:
            url = page.url or ""
            body = (page.html or "").lower()
            elapsed = int(time.time() - start)

            # GitHub登录页 — 等待用户登录
            if "github.com/login" in url or "github.com/session" in url:
                if elapsed - last_log >= 15:
                    log(f"等待GitHub登录... ({elapsed}s) 请在浏览器完成登录")
                    last_log = elapsed
                time.sleep(3)
                continue

            # GitHub OAuth授权页 — 自动点击Authorize
            if "github.com/login/oauth" in url or ("github.com" in url and "authorize" in url):
                log("GitHub OAuth授权页 — 自动点击Authorize...")
                for sel in [
                    'css:input[value="Authorize"]',
                    'css:button[type=submit]',
                    'xpath://button[contains(text(),"Authorize")]',
                    'xpath://input[@type="submit"]',
                ]:
                    try:
                        btn = page.ele(sel, timeout=2)
                        if btn:
                            btn.click()
                            log("Authorize按钮已点击", True)
                            time.sleep(3)
                            break
                    except Exception:
                        pass

            # Windsurf注册成功
            if any(k in body for k in ["dashboard", "welcome to windsurf", "get started",
                                        "cascade", "open windsurf"]):
                log("GitHub OAuth注册成功!", True)
                email = "github_oauth_" + datetime.now(CST).strftime("%H%M%S") + "@github"
                result = {
                    "email": email, "path": "github_oauth", "status": "registered",
                    "timestamp": datetime.now(CST).isoformat(),
                }
                save_result(result)
                inject_to_pool(email, "", source="github_oauth")
                log(f"已保存+注入: {email}", True)
                log("请采集WAM快照: python 010-道引擎_DaoEngine\\wam_engine.py harvest")
                return result

            # Windsurf错误
            if "already have an account" in body or "sign in" in body:
                log("账号已存在或需要登录 Windsurf")

            if elapsed - last_log >= 20:
                log(f"等待中... URL={url[:60]} ({elapsed}s)")
                last_log = elapsed

            time.sleep(2)

        log(f"GitHub OAuth超时({MAX_WAIT}s)", False)
        return None

    except Exception as e:
        log(f"GitHub OAuth异常: {e}", False)
        import traceback; traceback.print_exc()
        return None
    finally:
        try: page.quit()
        except Exception: pass


# ============================================================
# P1: Gmail+alias — 无限账号
# ============================================================

def path_gmail_alias(secrets, index=None):
    """P1: Gmail+alias注册，调用已有引擎"""
    engine = SCRIPT_DIR / "_gmail_alias_engine.py"
    if not engine.exists():
        log("_gmail_alias_engine.py 未找到", False)
        return None

    base_email = secrets.get("GMAIL_BASE", "")
    app_pw = secrets.get("GMAIL_APP_PASSWORD", "")

    if not base_email:
        log("GMAIL_BASE 未配置", False)
        return None

    if not app_pw:
        log("GMAIL_APP_PASSWORD 未配置 — 降级手动验证模式")

    cmd = [PYTHON_EXE, str(engine)]
    if index:
        cmd += ["register", str(index)]
    else:
        cmd += ["register"]

    log(f"调用Gmail+alias引擎: index={index or 'auto'}")
    try:
        r = subprocess.run(cmd, timeout=300, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0:
            log("Gmail+alias注册完成", True)
            return {"path": "gmail_alias", "status": "registered",
                    "timestamp": datetime.now(CST).isoformat()}
        else:
            log("Gmail+alias引擎返回错误", False)
            return None
    except subprocess.TimeoutExpired:
        log("Gmail+alias超时(300s)", False)
        return None
    except Exception as e:
        log(f"Gmail+alias异常: {e}", False)
        return None


# ============================================================
# P2: Hamibot 手机自动化
# ============================================================

HAMIBOT_API = "https://hamibot.cn/api/v1"
HAMIBOT_SCRIPT_WINDSURF = """
// Hamibot Script: Windsurf Google OAuth Registration
// 在手机Chrome上通过Google账号注册Windsurf
// 需要: 手机上已登录Google账号

var url = "https://windsurf.com/account/register";
console.log("导航至注册页: " + url);

// 打开Chrome
app.startActivity({
    action: "android.intent.action.VIEW",
    data: url,
    packageName: "com.android.chrome"
});
sleep(5000);

// 等待页面加载
var maxWait = 30000;
var start = Date.now();

while (Date.now() - start < maxWait) {
    sleep(2000);
    // 查找Google注册按钮
    var googleBtn = text("Sign up with Google").findOne(3000);
    if (!googleBtn) googleBtn = textContains("Google").findOne(1000);
    if (googleBtn) {
        console.log("找到Google OAuth按钮，点击...");
        googleBtn.click();
        sleep(5000);
        
        // 等待Google账号选择
        var accountBtn = textContains("@gmail.com").findOne(10000);
        if (accountBtn) {
            console.log("选择Google账号: " + accountBtn.text());
            accountBtn.click();
            sleep(3000);
        }
        
        // 等待授权完成
        var continueBtn = text("Continue").findOne(5000);
        if (continueBtn) {
            continueBtn.click();
            sleep(3000);
        }
        
        console.log("Google OAuth流程完成!");
        hamibot.setResult({success: true, timestamp: new Date().toISOString()});
        break;
    }
}

hamibot.exit();
"""


def hamibot_get_devices(token, proxies=None):
    """获取Hamibot设备列表"""
    try:
        import requests as req
        r = req.get(
            f"{HAMIBOT_API}/robots",
            headers={"Authorization": token, "Content-Type": "application/json"},
            timeout=15, proxies=proxies,
        )
        if r.status_code == 200:
            return r.json()
        log(f"Hamibot devices HTTP {r.status_code}: {r.text[:200]}", False)
        return None
    except Exception as e:
        log(f"Hamibot API错误: {e}", False)
        return None


def hamibot_create_script(token, script_content, name="windsurf_oauth", proxies=None):
    """创建/更新Hamibot开发脚本"""
    try:
        import requests as req
        # 先获取现有dev scripts
        r = req.get(
            f"{HAMIBOT_API}/devscripts",
            headers={"Authorization": token},
            timeout=15, proxies=proxies,
        )
        if r.status_code == 200:
            scripts = r.json().get("data", {}).get("items", [])
            for s in scripts:
                if s.get("name") == name:
                    log(f"已有脚本: {name} (id={s.get('_id')})", True)
                    return s.get("_id")

        # 创建新脚本
        payload = {"name": name, "script": script_content}
        r = req.post(
            f"{HAMIBOT_API}/devscripts",
            json=payload,
            headers={"Authorization": token},
            timeout=15, proxies=proxies,
        )
        if r.status_code in (200, 201):
            sid = r.json().get("data", {}).get("_id", "")
            log(f"脚本已创建: {sid}", True)
            return sid
        log(f"创建脚本失败 HTTP {r.status_code}: {r.text[:200]}", False)
        return None
    except Exception as e:
        log(f"Hamibot创建脚本异常: {e}", False)
        return None


def hamibot_run_script(token, script_id, robot_id, proxies=None):
    """在指定设备上运行脚本"""
    try:
        import requests as req
        payload = {"robots": [{"_id": robot_id}]}
        r = req.post(
            f"{HAMIBOT_API}/devscripts/{script_id}/run",
            json=payload,
            headers={"Authorization": token},
            timeout=15, proxies=proxies,
        )
        if r.status_code in (200, 201, 204):
            log(f"脚本已发送至设备 {robot_id}", True)
            return True
        log(f"运行脚本失败 HTTP {r.status_code}: {r.text[:200]}", False)
        return False
    except Exception as e:
        log(f"Hamibot运行脚本异常: {e}", False)
        return False


def path_hamibot(secrets, proxy_url=None):
    """P2: Hamibot手机自动化注册Windsurf"""
    token = secrets.get("HAMIBOT_TOKEN", "")
    if not token:
        log("HAMIBOT_TOKEN 未配置", False)
        log("获取方式: hamibot.cn → 设置 → 个人访问令牌 → 生成令牌(hmp-xxx)", False)
        log("然后在 secrets.env 添加: HAMIBOT_TOKEN=hmp-xxxxxxxxxx", False)
        return None

    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

    log("P2: Hamibot手机自动化")

    # 获取设备列表
    log("获取Hamibot设备列表...")
    devices_resp = hamibot_get_devices(token, proxies)
    if not devices_resp:
        log("无法获取设备列表", False)
        return None

    items = devices_resp.get("data", {}).get("items", [])
    if not items:
        log("无在线设备! 请确保手机已开启Hamibot并在线", False)
        return None

    for d in items:
        name = d.get("name", "?")
        status = d.get("online", False)
        log(f"  设备: {name} | 在线: {status}")

    # 选第一个在线设备
    online = [d for d in items if d.get("online")]
    if not online:
        log("无在线设备", False)
        return None
    robot = online[0]
    robot_id = robot.get("_id", "")
    log(f"选择设备: {robot.get('name')} ({robot_id})", True)

    # 创建/上传脚本
    log("上传Windsurf注册脚本...")
    script_id = hamibot_create_script(token, HAMIBOT_SCRIPT_WINDSURF, proxies=proxies)
    if not script_id:
        return None

    # 运行脚本
    log("在手机上执行脚本...")
    ok = hamibot_run_script(token, script_id, robot_id, proxies=proxies)
    if ok:
        log("脚本已发送! 手机将自动打开Chrome完成Google OAuth注册", True)
        log("注册完成后需手动采集WAM快照:", True)
        log("  python 010-道引擎_DaoEngine\\wam_engine.py harvest", True)
        result = {
            "path": "hamibot_phone", "device": robot.get("name"),
            "status": "script_sent", "timestamp": datetime.now(CST).isoformat(),
        }
        save_result(result)
        return result
    return None


# ============================================================
# 自动路径选择
# ============================================================

def auto_register(secrets, proxy_url=None):
    """按优先级自动选择最优注册路径"""
    log("=== 万法归宗·自动路径选择 ===")

    gmail_base = secrets.get("GMAIL_BASE", "")
    gmail_pw = secrets.get("GMAIL_APP_PASSWORD", "")
    hamibot_token = secrets.get("HAMIBOT_TOKEN", "")
    github_acct = secrets.get("PHONE_GITHUB_ACCOUNT", "")

    log(f"可用路径:")
    log(f"  P0 GitHub OAuth: {'✅' if github_acct else '❌ 需PHONE_GITHUB_ACCOUNT'}")
    log(f"  P1 Gmail+alias:  {'✅ 全自动' if (gmail_base and gmail_pw) else ('⚠️ 手动验证' if gmail_base else '❌ 需GMAIL_BASE')}")
    log(f"  P2 Hamibot手机:  {'✅' if hamibot_token else '❌ 需HAMIBOT_TOKEN'}")

    # P0: GitHub OAuth (最快，零邮件)
    if github_acct:
        log("\n▶ 尝试 P0: GitHub OAuth...")
        result = path_github_oauth(proxy=proxy_url)
        if result and result.get("status") == "registered":
            return result

    # P1: Gmail+alias
    if gmail_base:
        log("\n▶ 尝试 P1: Gmail+alias...")
        result = path_gmail_alias(secrets)
        if result and result.get("status") == "registered":
            return result

    # P2: Hamibot
    if hamibot_token:
        log("\n▶ 尝试 P2: Hamibot手机...")
        result = path_hamibot(secrets, proxy_url)
        if result:
            return result

    log("所有路径均失败", False)
    return None


# ============================================================
# 状态展示
# ============================================================

def show_status(secrets):
    proxy = find_proxy()
    now = datetime.now(CST)

    print(f"\n{'═' * 65}")
    print(f"  万法归宗 · 全资源状态 — {now.strftime('%Y-%m-%d %H:%M:%S CST')}")
    print(f"{'═' * 65}\n")

    # 网络
    print("  [网络]")
    print(f"    代理:    {proxy or '❌ 无代理'}")
    for port, name in [(9870, "无感切号Hub"), (19443, "透明代理")]:
        try:
            s = socket.socket(); s.settimeout(0.5); s.connect(("127.0.0.1", port)); s.close()
            print(f"    :{port} {name}: RUNNING ✓")
        except Exception:
            print(f"    :{port} {name}: stopped")

    # 注册路径
    print("\n  [注册路径]")
    checks = [
        ("P0 GitHub OAuth", secrets.get("PHONE_GITHUB_ACCOUNT", ""), "PHONE_GITHUB_ACCOUNT"),
        ("P1 Gmail Base",   secrets.get("GMAIL_BASE", ""),            "GMAIL_BASE"),
        ("P1 Gmail AppPW",  secrets.get("GMAIL_APP_PASSWORD", ""),    "GMAIL_APP_PASSWORD"),
        ("P2 Hamibot Token",secrets.get("HAMIBOT_TOKEN", ""),         "HAMIBOT_TOKEN"),
    ]
    for name, val, key in checks:
        if val and val not in ("xxx", "your_key_here"):
            masked = val[:4] + "****" if len(val) > 8 else "✓"
            print(f"    {name:22}: ✅ {masked}")
        else:
            print(f"    {name:22}: ❌ 未配置 ({key})")

    # 手机资源
    print("\n  [手机资源]")
    phones = [("主号", "PHONE_PRIMARY"), ("副号", "PHONE_SECONDARY"),
              ("Hamibot账号", "HAMIBOT_ACCOUNT")]
    for label, key in phones:
        v = secrets.get(key, "")
        if v:
            print(f"    {label}: ✅ {v[:3]}****{v[-2:]}")
        else:
            print(f"    {label}: —")

    # 号池
    print("\n  [号池]")
    lh = (Path(os.environ.get("APPDATA","")) / "Windsurf" / "User" / "globalStorage"
          / "windsurf-login-accounts.json")
    if lh.exists():
        try:
            accts = json.load(open(lh, "r", encoding="utf-8"))
            now_ms = time.time() * 1000
            trial_d = []
            for a in accts:
                pe = a.get("usage", {}).get("planEnd", 0)
                if pe: trial_d.append(max(0, (pe - now_ms) / 86400000))
            alive7 = sum(1 for t in trial_d if t > 7)
            exp3 = sum(1 for t in trial_d if t <= 3)
            print(f"    总账号: {len(accts)} | 7天后存活: {alive7} | 3天内到期: {exp3}")
        except Exception:
            print(f"    读取失败")

    # 行动建议
    print(f"\n  [立即行动]")
    if secrets.get("PHONE_GITHUB_ACCOUNT"):
        print(f"    🥇 python _universal_engine.py github   # P0 GitHub OAuth")
    if secrets.get("GMAIL_BASE") and not secrets.get("GMAIL_APP_PASSWORD"):
        print(f"    🔧 配置 GMAIL_APP_PASSWORD 后运行:")
        print(f"       python _gmail_alias_engine.py check-imap")
        print(f"       python _gmail_alias_engine.py batch 20")
    if secrets.get("GMAIL_BASE") and secrets.get("GMAIL_APP_PASSWORD"):
        print(f"    🥈 python _universal_engine.py batch 20 # Gmail+alias批量")
    if not secrets.get("HAMIBOT_TOKEN"):
        print(f"    🔧 配置 HAMIBOT_TOKEN: hamibot.cn → 设置 → 个人访问令牌")

    print(f"\n{'═' * 65}\n")


# ============================================================
# CLI
# ============================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1].lower()
    secrets = load_secrets()
    proxy = find_proxy()
    log(f"代理: {proxy or '无'}")

    if cmd == "status":
        show_status(secrets)

    elif cmd == "github":
        result = path_github_oauth(proxy=proxy)
        print(f"\n  结果: {result}")

    elif cmd == "gmail":
        idx = int(sys.argv[2]) if len(sys.argv) >= 3 else None
        result = path_gmail_alias(secrets, index=idx)
        print(f"\n  结果: {result}")

    elif cmd == "hamibot":
        result = path_hamibot(secrets, proxy_url=proxy)
        print(f"\n  结果: {result}")

    elif cmd == "auto":
        result = auto_register(secrets, proxy_url=proxy)
        print(f"\n  最终结果: {result}")

    elif cmd == "batch":
        n = int(sys.argv[2]) if len(sys.argv) >= 3 else 3
        print(f"\n  批量注册 {n} 个账号 — 万法归宗")
        success = 0
        for i in range(n):
            print(f"\n{'▓' * 15} {i+1}/{n} {'▓' * 15}")
            r = auto_register(secrets, proxy_url=proxy)
            if r and r.get("status") in ("registered", "script_sent"):
                success += 1
            delay = random.uniform(8, 20)
            if i < n - 1:
                log(f"延迟 {delay:.1f}s...")
                time.sleep(delay)
        print(f"\n  完成: {success}/{n} 成功")

    elif cmd == "monitor":
        min_alive = int(sys.argv[2]) if len(sys.argv) >= 3 else 10
        interval = int(sys.argv[3]) if len(sys.argv) >= 4 else 600
        print(f"\n  守护进程: 维持 {min_alive}+ 存活账号, 间隔 {interval}s\n")
        cycle = 0
        while True:
            cycle += 1
            log(f"=== 周期 #{cycle} ===")
            lh = (Path(os.environ.get("APPDATA","")) / "Windsurf" / "User" / "globalStorage"
                  / "windsurf-login-accounts.json")
            alive7 = 0
            if lh.exists():
                try:
                    accts = json.load(open(lh,"r",encoding="utf-8"))
                    now_ms = time.time()*1000
                    alive7 = sum(1 for a in accts
                                 if (a.get("usage",{}).get("planEnd",0)-now_ms)/86400000 > 7)
                except Exception: pass
            log(f"7天存活: {alive7}/{min_alive}")
            if alive7 < min_alive:
                need = min_alive - alive7
                log(f"不足! 补充 {need} 个...")
                for _ in range(need):
                    auto_register(secrets, proxy_url=proxy)
                    time.sleep(random.uniform(10,20))
            else:
                log("✅ 充足")
            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                log("停止")
                break

    else:
        print(__doc__)


if __name__ == "__main__":
    main()
