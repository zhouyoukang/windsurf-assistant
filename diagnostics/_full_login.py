"""
Windsurf全流程登录 + 高效换号体系
1. Firebase登录10个新账号 → idToken → apiKey
2. 查询配额 → 选最优账号
3. 注入state.vscdb → 实际登录
4. 构建一键换号体系
"""
import json, requests, sqlite3, os, sys, time, base64, struct, shutil
from datetime import datetime

PROXY = "http://127.0.0.1:7890"
PROXIES = {"https": PROXY, "http": PROXY}
FIREBASE_KEY = "AIzaSyDsOl-1XpT5err0Tcnx8FFod1H8gVGIycY"

# Auto-detect DB path
DB_CANDIDATES = [
    os.path.expandvars(r"%APPDATA%\Windsurf\User\globalStorage\state.vscdb"),
    r"C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb",
]
DB_PATH = None
for p in DB_CANDIDATES:
    if os.path.exists(p):
        DB_PATH = p
        break

SETTINGS_CANDIDATES = [
    os.path.expandvars(r"%APPDATA%\Windsurf\User\settings.json"),
    r"C:\Users\Administrator\AppData\Roaming\Windsurf\User\settings.json",
]
SETTINGS_PATH = None
for p in SETTINGS_CANDIDATES:
    if os.path.exists(p):
        SETTINGS_PATH = p
        break

ACCOUNTS_FILE = os.path.join(os.path.dirname(__file__), "_accounts_pool.json")

# 10 new accounts
NEW_ACCOUNTS = [
    {"email": "rothmanqio98996@yahoo.com", "password": "5%7eIYoSQjuE"},
    {"email": "jacobseef3217@yahoo.com", "password": "h0#yE#qAjqOv"},
    {"email": "workvmfd11668@yahoo.com", "password": "^^766vYZqQqi"},
    {"email": "lepekb98258@yahoo.com", "password": "t&9OYudZUQH3"},
    {"email": "harropfjmf89402@yahoo.com", "password": "Dr44&QEUu*BG"},
    {"email": "jaramjw8983709@yahoo.com", "password": "Sa0!JfHlqm6%"},
    {"email": "adoobuca7563@yahoo.com", "password": "$7qIhZqfviEw"},
    {"email": "zellxdyqr55610@yahoo.com", "password": "!n!V&vNU6J@q"},
    {"email": "klugeuxhdr49740@yahoo.com", "password": "TPKY7Tx@*L&l"},
    {"email": "tregreglsatu322@yahoo.com", "password": "8Ckbfp!sDtIS"},
]


def encode_proto_string(value, field_num=1):
    """Encode a string as protobuf field"""
    data = value.encode("utf-8")
    tag = (field_num << 3) | 2
    length = len(data)
    result = bytearray()
    result.append(tag)
    while length > 0x7F:
        result.append((length & 0x7F) | 0x80)
        length >>= 7
    result.append(length & 0x7F)
    result.extend(data)
    return bytes(result)


def decode_proto_string(data, field_num=1):
    """Decode a string from protobuf field"""
    idx = 0
    while idx < len(data):
        if idx >= len(data):
            break
        byte = data[idx]
        fn = byte >> 3
        wt = byte & 0x07
        idx += 1
        if wt == 0:  # varint
            while idx < len(data) and data[idx] & 0x80:
                idx += 1
            idx += 1
        elif wt == 2:  # length-delimited
            length = 0
            shift = 0
            while idx < len(data):
                b = data[idx]
                idx += 1
                length |= (b & 0x7F) << shift
                shift += 7
                if not (b & 0x80):
                    break
            value = data[idx:idx + length]
            idx += length
            if fn == field_num:
                return value.decode("utf-8", errors="replace")
        elif wt == 5:  # 32-bit
            idx += 4
        elif wt == 1:  # 64-bit
            idx += 8
        else:
            break
    return None


def firebase_login(email, password):
    """Firebase signInWithPassword → idToken + refreshToken"""
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_KEY}"
    r = requests.post(url, json={
        "email": email,
        "password": password,
        "returnSecureToken": True
    }, proxies=PROXIES, timeout=20)

    if r.status_code == 200:
        d = r.json()
        return {
            "idToken": d["idToken"],
            "refreshToken": d["refreshToken"],
            "localId": d.get("localId", ""),
            "displayName": d.get("displayName", ""),
        }
    else:
        err = r.json().get("error", {}).get("message", r.text[:200])
        return {"error": err}


def register_user(id_token):
    """RegisterUser → apiKey"""
    body = encode_proto_string(id_token, field_num=1)
    r = requests.post(
        "https://register.windsurf.com/exa.seat_management_pb.SeatManagementService/RegisterUser",
        data=body,
        headers={
            "Content-Type": "application/proto",
            "connect-protocol-version": "1",
        },
        proxies=PROXIES,
        timeout=20
    )
    if r.status_code == 200:
        api_key = decode_proto_string(r.content, field_num=1)
        return api_key
    return None


def get_plan_status(api_key):
    """GetPlanStatus → quota info"""
    body = encode_proto_string(api_key, field_num=1)
    try:
        r = requests.post(
            "https://server.codeium.com/exa.api_server_pb.ApiServerService/GetPlanStatus",
            data=body,
            headers={
                "Content-Type": "application/proto",
                "connect-protocol-version": "1",
            },
            proxies=PROXIES,
            timeout=15
        )
        if r.status_code == 200:
            # Parse proto response for quota fields
            # Look for percentage values (float32 encoded as fixed32)
            content = r.content
            # Try to find plan name and quota info by scanning
            result = {"raw_len": len(content)}

            # Decode all string fields
            idx = 0
            strings_found = []
            while idx < len(content):
                if idx >= len(content):
                    break
                byte = content[idx]
                fn = byte >> 3
                wt = byte & 0x07
                idx += 1
                if wt == 0:
                    val = 0
                    shift = 0
                    while idx < len(content):
                        b = content[idx]
                        idx += 1
                        val |= (b & 0x7F) << shift
                        shift += 7
                        if not (b & 0x80):
                            break
                elif wt == 2:
                    length = 0
                    shift = 0
                    while idx < len(content):
                        b = content[idx]
                        idx += 1
                        length |= (b & 0x7F) << shift
                        shift += 7
                        if not (b & 0x80):
                            break
                    value = content[idx:idx + length]
                    idx += length
                    try:
                        s = value.decode("utf-8")
                        if s.isprintable() and len(s) > 1:
                            strings_found.append((fn, s))
                    except:
                        pass
                elif wt == 5:
                    if idx + 4 <= len(content):
                        fval = struct.unpack('<f', content[idx:idx+4])[0]
                        idx += 4
                    else:
                        break
                elif wt == 1:
                    idx += 8
                else:
                    break

            for fn, s in strings_found:
                if "Trial" in s or "Pro" in s or "Free" in s:
                    result["plan"] = s
                elif s.startswith("sk-ws-"):
                    pass  # skip apiKey echo

            return result
        return {"error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"error": str(e)[:100]}


def login_all_accounts():
    """Login all 10 accounts and get apiKeys"""
    print("=" * 60)
    print("Phase 1: Firebase登录 + RegisterUser获取apiKey")
    print("=" * 60)

    results = []
    for i, acc in enumerate(NEW_ACCOUNTS):
        email = acc["email"]
        password = acc["password"]
        print(f"\n[{i+1}/10] {email}...")

        # Firebase login
        fb = firebase_login(email, password)
        if "error" in fb:
            print(f"  ❌ Firebase: {fb['error']}")
            results.append({"email": email, "password": password, "error": fb["error"]})
            continue

        print(f"  ✅ Firebase OK (name: {fb.get('displayName', '?')})")

        # RegisterUser
        api_key = register_user(fb["idToken"])
        if not api_key:
            print(f"  ❌ RegisterUser failed")
            results.append({"email": email, "password": password, "error": "RegisterUser failed"})
            continue

        print(f"  ✅ apiKey: {api_key[:35]}...")

        account_data = {
            "email": email,
            "password": password,
            "apiKey": api_key,
            "idToken": fb["idToken"],
            "refreshToken": fb["refreshToken"],
            "localId": fb.get("localId", ""),
            "displayName": fb.get("displayName", ""),
            "loginTime": datetime.now().isoformat(),
            "quotaDaily": 100,
            "quotaWeekly": 100,
        }

        # Get plan status
        plan = get_plan_status(api_key)
        if "plan" in plan:
            account_data["plan"] = plan["plan"]
            print(f"  ✅ Plan: {plan.get('plan', '?')}")

        results.append(account_data)

    # Count successes
    ok = [r for r in results if "apiKey" in r]
    fail = [r for r in results if "error" in r]
    print(f"\n{'='*60}")
    print(f"登录结果: ✅ {len(ok)}/10 成功, ❌ {len(fail)}/10 失败")
    if fail:
        for f in fail:
            print(f"  ❌ {f['email']}: {f.get('error','?')}")

    # Save to file
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n账号池已保存: {ACCOUNTS_FILE}")

    return results


def inject_account(account):
    """Inject account auth into state.vscdb"""
    if not DB_PATH:
        print("  ❌ state.vscdb not found")
        return False

    print(f"\n{'='*60}")
    print(f"Phase 2: 注入认证 → {account['email']}")
    print(f"{'='*60}")

    # Read current auth status
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Read existing windsurfAuthStatus to preserve structure
    row = cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
    if row:
        existing = json.loads(row[0])
        print(f"  当前账号: {existing.get('apiKey', '?')[:30]}...")
    else:
        existing = {}

    # Update apiKey
    existing["apiKey"] = account["apiKey"]
    new_val = json.dumps(existing)

    cur.execute("UPDATE ItemTable SET value=? WHERE key='windsurfAuthStatus'", (new_val,))

    # Update codeium.windsurf lastLoginEmail
    row2 = cur.execute("SELECT value FROM ItemTable WHERE key='codeium.windsurf'").fetchone()
    if row2:
        cw = json.loads(row2[0])
        cw["lastLoginEmail"] = account["email"]
        cur.execute("UPDATE ItemTable SET value=? WHERE key='codeium.windsurf'", (json.dumps(cw),))

    conn.commit()
    conn.close()

    print(f"  ✅ apiKey已注入: {account['apiKey'][:35]}...")
    print(f"  ✅ lastLoginEmail: {account['email']}")
    return True


def ensure_proxy_settings():
    """Ensure proxy settings are correct"""
    if not SETTINGS_PATH:
        print("  ⚠️ settings.json not found")
        return

    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        settings = json.load(f)

    changed = False
    if settings.get("http.proxy") != "http://127.0.0.1:7890":
        settings["http.proxy"] = "http://127.0.0.1:7890"
        changed = True
    if settings.get("http.proxySupport") != "override":
        settings["http.proxySupport"] = "override"
        changed = True
    if settings.get("http.proxyStrictSSL") != False:
        settings["http.proxyStrictSSL"] = False
        changed = True

    if changed:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        print(f"  ✅ 代理设置已修复: {SETTINGS_PATH}")
    else:
        print(f"  ✅ 代理设置已正确")


def build_switcher(accounts):
    """Build the account switcher script"""
    ok_accounts = [a for a in accounts if "apiKey" in a]
    if not ok_accounts:
        print("  ❌ No valid accounts to build switcher")
        return

    switcher_path = os.path.join(os.path.dirname(__file__), "_switch_account.py")
    script = f'''"""
一键换号脚本 — 用法: python _switch_account.py [账号序号1-{len(ok_accounts)}]
无参数则显示所有账号状态并选择最优账号自动切换
"""
import json, sqlite3, os, sys, requests, struct, time

PROXY = "http://127.0.0.1:7890"
PROXIES = {{"https": PROXY, "http": PROXY}}
FIREBASE_KEY = "AIzaSyDsOl-1XpT5err0Tcnx8FFod1H8gVGIycY"
ACCOUNTS_FILE = os.path.join(os.path.dirname(__file__), "_accounts_pool.json")

DB_CANDIDATES = [
    os.path.expandvars(r"%APPDATA%\\Windsurf\\User\\globalStorage\\state.vscdb"),
    r"C:\\Users\\Administrator\\AppData\\Roaming\\Windsurf\\User\\globalStorage\\state.vscdb",
]
DB_PATH = None
for p in DB_CANDIDATES:
    if os.path.exists(p):
        DB_PATH = p
        break

def encode_proto_string(value, field_num=1):
    data = value.encode("utf-8")
    tag = (field_num << 3) | 2
    length = len(data)
    result = bytearray()
    result.append(tag)
    while length > 0x7F:
        result.append((length & 0x7F) | 0x80)
        length >>= 7
    result.append(length & 0x7F)
    result.extend(data)
    return bytes(result)

def refresh_token(rt):
    url = f"https://securetoken.googleapis.com/v1/token?key={{FIREBASE_KEY}}"
    r = requests.post(url, data={{"grant_type":"refresh_token","refresh_token":rt}}, proxies=PROXIES, timeout=15)
    if r.status_code == 200:
        d = r.json()
        return d.get("id_token"), d.get("refresh_token", rt)
    return None, rt

def get_quota(api_key):
    """Quick quota check via GetPlanStatus"""
    body = encode_proto_string(api_key, field_num=1)
    try:
        r = requests.post(
            "https://server.codeium.com/exa.api_server_pb.ApiServerService/GetPlanStatus",
            data=body,
            headers={{"Content-Type":"application/proto","connect-protocol-version":"1"}},
            proxies=PROXIES, timeout=10
        )
        return r.status_code == 200
    except:
        return False

def switch_to(account):
    if not DB_PATH:
        print("❌ state.vscdb not found")
        return False
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    row = cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
    existing = json.loads(row[0]) if row else {{}}
    existing["apiKey"] = account["apiKey"]
    cur.execute("UPDATE ItemTable SET value=? WHERE key='windsurfAuthStatus'", (json.dumps(existing),))
    
    row2 = cur.execute("SELECT value FROM ItemTable WHERE key='codeium.windsurf'").fetchone()
    if row2:
        cw = json.loads(row2[0])
        cw["lastLoginEmail"] = account["email"]
        cur.execute("UPDATE ItemTable SET value=? WHERE key='codeium.windsurf'", (json.dumps(cw),))
    conn.commit()
    conn.close()
    return True

def main():
    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        accounts = json.load(f)
    
    ok = [a for a in accounts if "apiKey" in a]
    
    print("\\n=== Windsurf账号池 ===")
    for i, a in enumerate(ok):
        status = "✅" if get_quota(a["apiKey"]) else "⚠️"
        print(f"  [{{i+1}}] {{status}} {{a['email'][:25]}}... plan={{a.get('plan','?')}}")
    
    # Select account
    if len(sys.argv) > 1:
        idx = int(sys.argv[1]) - 1
    else:
        # Auto-select: find first working account
        idx = 0
        for i, a in enumerate(ok):
            if get_quota(a["apiKey"]):
                idx = i
                break
    
    if 0 <= idx < len(ok):
        target = ok[idx]
        print(f"\\n切换到: {{target['email']}}")
        if switch_to(target):
            print("✅ 已注入! 请 Ctrl+Shift+P → Reload Window")
        else:
            print("❌ 注入失败")
    else:
        print(f"❌ 无效序号 (1-{{len(ok)}})")

if __name__ == "__main__":
    main()
'''

    with open(switcher_path, "w", encoding="utf-8") as f:
        f.write(script)
    print(f"\n  ✅ 换号脚本: {switcher_path}")
    print(f"  用法: python _switch_account.py [1-{len(ok_accounts)}]")


def main():
    print("🔧 Windsurf全流程登录 · 高效换号体系")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   用户: {os.environ.get('USERNAME', '?')}")
    print(f"   DB: {DB_PATH}")
    print(f"   Settings: {SETTINGS_PATH}")
    print()

    # Step 0: Ensure proxy
    ensure_proxy_settings()

    # Step 1: Login all accounts
    results = login_all_accounts()

    # Step 2: Select best and inject
    ok_accounts = [r for r in results if "apiKey" in r]
    if ok_accounts:
        # Select first good account
        best = ok_accounts[0]
        inject_account(best)

        # Step 3: Build switcher
        print(f"\n{'='*60}")
        print("Phase 3: 构建换号体系")
        print(f"{'='*60}")
        build_switcher(results)

        # Summary
        print(f"\n{'='*60}")
        print("📋 完成总结")
        print(f"{'='*60}")
        print(f"  ✅ {len(ok_accounts)}/10 账号登录成功")
        print(f"  ✅ 当前注入: {best['email']}")
        print(f"  ✅ apiKey: {best['apiKey'][:35]}...")
        print(f"  ✅ 换号脚本已生成")
        print()
        print("  👉 请在Windsurf中 Ctrl+Shift+P → Reload Window")
        print("  👉 重载后即可使用新账号")
        print(f"  👉 换号: python _switch_account.py [1-{len(ok_accounts)}]")
    else:
        print("\n  ❌ 所有账号登录失败，请检查网络/代理")


if __name__ == "__main__":
    main()
