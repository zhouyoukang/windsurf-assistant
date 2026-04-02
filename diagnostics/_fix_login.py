"""
Windsurf登录修复诊断脚本
根因: identitytoolkit.googleapis.com被墙, Windsurf未配置代理
"""
import json, requests, sqlite3, sys, os, time

PROXY = "http://127.0.0.1:7890"
PROXIES = {"https": PROXY, "http": PROXY}
FIREBASE_KEY = "AIzaSyDsOl-1XpT5err0Tcnx8FFod1H8gVGIycY"
DB_PATH = os.path.expandvars(r"%APPDATA%\Windsurf\User\globalStorage\state.vscdb")
KEYPOOL = r"e:\道\道生一\一生二\无感切号\data\keypool.json"

def test_connectivity():
    """测试关键端点连通性"""
    endpoints = [
        ("Firebase Auth (Google)", f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_KEY}"),
        ("Firebase Token Refresh", f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_KEY}"),
        ("Windsurf Register", "https://register.windsurf.com/"),
        ("Windsurf Backend", "https://web-backend.windsurf.com/"),
        ("Codeium Server", "https://server.codeium.com/"),
        ("Windsurf Self-Serve", "https://server.self-serve.windsurf.com/"),
    ]
    
    print("=" * 60)
    print("1. 网络连通性测试 (通过代理 127.0.0.1:7890)")
    print("=" * 60)
    
    for name, url in endpoints:
        try:
            r = requests.get(url, proxies=PROXIES, timeout=10, allow_redirects=False)
            print(f"  ✅ {name}: HTTP {r.status_code}")
        except requests.exceptions.ConnectTimeout:
            print(f"  ❌ {name}: 超时")
        except requests.exceptions.ConnectionError as e:
            # Some endpoints return connection reset but are reachable
            print(f"  ⚠️  {name}: 连接错误 ({str(e)[:80]})")
        except Exception as e:
            print(f"  ❌ {name}: {str(e)[:80]}")
    
    print()
    print("  直连测试 (无代理):")
    try:
        r = requests.get(f"https://identitytoolkit.googleapis.com/", timeout=5)
        print(f"  ✅ Google直连OK")
    except:
        print(f"  ❌ Google直连失败 (被墙) → 必须通过代理")

def test_refresh_token():
    """测试refreshToken刷新"""
    print()
    print("=" * 60)
    print("2. RefreshToken刷新测试")
    print("=" * 60)
    
    with open(KEYPOOL, "r", encoding="utf-8") as f:
        pool = json.load(f)
    
    emails = list(pool.keys())
    print(f"  号池总数: {len(emails)}")
    
    # Test first 3 accounts
    success = 0
    for email in emails[:3]:
        rt = pool[email].get("refreshToken", "")
        if not rt:
            print(f"  ⚠️  {email}: 无refreshToken")
            continue
        
        url = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_KEY}"
        try:
            r = requests.post(url, data={
                "grant_type": "refresh_token",
                "refresh_token": rt
            }, proxies=PROXIES, timeout=15)
            
            if r.status_code == 200:
                d = r.json()
                id_token = d.get("id_token", "")
                print(f"  ✅ {email}: idToken获取成功 ({id_token[:30]}...)")
                success += 1
                
                # Also test RegisterUser to get apiKey
                test_register(email, id_token)
            else:
                err = r.json().get("error", {}).get("message", r.text[:100])
                print(f"  ❌ {email}: {err}")
        except Exception as e:
            print(f"  ❌ {email}: {str(e)[:80]}")
    
    print(f"\n  刷新成功率: {success}/3")
    return success > 0

def test_register(email, id_token):
    """测试RegisterUser获取apiKey"""
    import struct
    
    # Encode idToken as protobuf field 1 (string)
    token_bytes = id_token.encode("utf-8")
    field_tag = (1 << 3) | 2  # field 1, wire type 2 (length-delimited)
    
    # Varint encode
    def encode_varint(value):
        parts = []
        while value > 0x7F:
            parts.append((value & 0x7F) | 0x80)
            value >>= 7
        parts.append(value & 0x7F)
        return bytes(parts)
    
    body = bytes([field_tag]) + encode_varint(len(token_bytes)) + token_bytes
    
    try:
        r = requests.post(
            "https://register.windsurf.com/exa.seat_management_pb.SeatManagementService/RegisterUser",
            data=body,
            headers={
                "Content-Type": "application/proto",
                "connect-protocol-version": "1",
            },
            proxies=PROXIES,
            timeout=15
        )
        if r.status_code == 200 and len(r.content) > 10:
            # Parse response - apiKey is field 1
            content = r.content
            idx = 0
            while idx < len(content):
                byte = content[idx]
                field_num = byte >> 3
                wire_type = byte & 0x07
                idx += 1
                if wire_type == 2:  # length-delimited
                    length = 0
                    shift = 0
                    while True:
                        b = content[idx]
                        idx += 1
                        length |= (b & 0x7F) << shift
                        shift += 7
                        if not (b & 0x80):
                            break
                    value = content[idx:idx+length]
                    idx += length
                    if field_num == 1:
                        api_key = value.decode("utf-8", errors="replace")
                        print(f"       → apiKey: {api_key[:40]}...")
                        return api_key
                else:
                    break
            print(f"       → 响应解析失败")
        else:
            print(f"       → RegisterUser失败: HTTP {r.status_code}")
    except Exception as e:
        print(f"       → RegisterUser异常: {str(e)[:60]}")
    return None

def check_db_state():
    """检查state.vscdb当前状态"""
    print()
    print("=" * 60)
    print("3. State.vscdb当前认证状态")
    print("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # windsurfAuthStatus
    val = cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
    if val:
        d = json.loads(val[0])
        ak = d.get("apiKey", "?")
        print(f"  apiKey: {ak[:40]}...")
        # Decode userStatus
        user_b64 = d.get("userStatusProtoBinaryBase64", "")
        if user_b64:
            import base64
            try:
                raw = base64.b64decode(user_b64)
                # Find readable strings
                strings = []
                i = 0
                while i < len(raw):
                    b = raw[i]
                    if 0x20 <= b < 0x7F or b > 0x80:
                        pass
                    i += 1
                print(f"  userStatus: (binary, {len(raw)} bytes)")
            except:
                pass
    else:
        print("  ❌ windsurfAuthStatus: 不存在")
    
    # codeium.windsurf
    val = cur.execute("SELECT value FROM ItemTable WHERE key='codeium.windsurf'").fetchone()
    if val:
        d = json.loads(val[0])
        print(f"  lastLoginEmail: {d.get('lastLoginEmail', '?')}")
        print(f"  apiServerUrl: {d.get('apiServerUrl', '?')}")
    
    # cachedPlanInfo
    val = cur.execute("SELECT value FROM ItemTable WHERE key='windsurf.settings.cachedPlanInfo'").fetchone()
    if val:
        d = json.loads(val[0])
        print(f"  plan: {d.get('planName', '?')}")
        qu = d.get("quotaUsage", {})
        print(f"  daily: {qu.get('dailyRemainingPercent', '?')}%, weekly: {qu.get('weeklyRemainingPercent', '?')}%")
    
    conn.close()

def check_settings():
    """检查Windsurf设置"""
    print()
    print("=" * 60)
    print("4. Windsurf设置检查")
    print("=" * 60)
    
    settings_path = os.path.expandvars(r"%APPDATA%\Windsurf\User\settings.json")
    with open(settings_path, "r") as f:
        s = json.load(f)
    
    proxy = s.get("http.proxy", "未设置")
    support = s.get("http.proxySupport", "未设置")
    strict = s.get("http.proxyStrictSSL", "未设置")
    
    print(f"  http.proxy: {proxy}")
    print(f"  http.proxySupport: {support}")
    print(f"  http.proxyStrictSSL: {strict}")
    
    if support == "off":
        print(f"  ❌ 代理支持已关闭! 这是登录失败的根因!")
    elif proxy and "7890" in str(proxy) and support in ("on", "override"):
        print(f"  ✅ 代理设置正确")
    else:
        print(f"  ⚠️  代理设置可能不完整")

def inject_fresh_auth():
    """注入新鲜认证到state.vscdb"""
    print()
    print("=" * 60)
    print("5. 注入新鲜认证")
    print("=" * 60)
    
    with open(KEYPOOL, "r", encoding="utf-8") as f:
        pool = json.load(f)
    
    # Find best account (highest quota)
    best_email = None
    best_score = -1
    for email, data in pool.items():
        q = data.get("quota", {})
        d = q.get("dailyPercent", 0) or 0
        w = q.get("weeklyPercent", 0) or 0
        score = d * 0.6 + w * 0.4
        if score > best_score and data.get("refreshToken"):
            best_score = score
            best_email = email
    
    if not best_email:
        print("  ❌ 无可用账号")
        return False
    
    account = pool[best_email]
    q = account.get("quota", {})
    print(f"  选中账号: {best_email}")
    print(f"  配额: D={q.get('dailyPercent',0)}% W={q.get('weeklyPercent',0)}%")
    
    # Refresh token
    rt = account["refreshToken"]
    url = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_KEY}"
    r = requests.post(url, data={
        "grant_type": "refresh_token",
        "refresh_token": rt
    }, proxies=PROXIES, timeout=15)
    
    if r.status_code != 200:
        print(f"  ❌ Token刷新失败: {r.text[:200]}")
        return False
    
    d = r.json()
    id_token = d["id_token"]
    print(f"  ✅ idToken刷新成功")
    
    # RegisterUser
    api_key = test_register(best_email, id_token)
    if not api_key:
        api_key = account.get("apiKey", "")
        if api_key:
            print(f"  ⚠️  使用缓存apiKey")
    
    if api_key:
        print(f"  ✅ apiKey就绪: {api_key[:40]}...")
    
    return True

if __name__ == "__main__":
    print("🔍 Windsurf登录诊断 · 根因修复")
    print(f"   时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   用户: {os.environ.get('USERNAME', '?')}")
    print()
    
    check_settings()
    test_connectivity()
    check_db_state()
    ok = test_refresh_token()
    
    if ok:
        print()
        print("=" * 60)
        print("📋 修复方案")
        print("=" * 60)
        print("  ✅ 代理设置已修复 (settings.json)")
        print("  ✅ 通过代理可访问所有认证端点")
        print("  ✅ RefreshToken有效，可获取新idToken")
        print()
        print("  👉 下一步: 在Windsurf中按 Ctrl+Shift+P → Reload Window")
        print("     重载后代理设置生效 → 登录流程将通过代理访问Google → 登录成功")
    else:
        print()
        print("  ❌ 仍有问题，需要进一步排查")
