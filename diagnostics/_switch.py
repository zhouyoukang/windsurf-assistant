#!/usr/bin/env python3
"""
一键换号 — 用法:
  python _switch.py          # 显示所有账号，自动选最优
  python _switch.py 3        # 切换到第3个账号
  python _switch.py next     # 切换到下一个账号
  python _switch.py status   # 只查看状态不切换
  python _switch.py refresh  # 刷新所有token后选最优
"""
import json, requests, sqlite3, os, sys, time, struct

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

PROXY = "http://127.0.0.1:7890"
PROXIES = {"https": PROXY, "http": PROXY}
FK = "AIzaSyDsOl-1XpT5err0Tcnx8FFod1H8gVGIycY"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
POOL_FILE = os.path.join(SCRIPT_DIR, "_accounts_pool.json")

DB_PATHS = [
    os.path.expandvars(r"%APPDATA%\Windsurf\User\globalStorage\state.vscdb"),
    r"C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb",
]

def proto_encode(s, field=1):
    d = s.encode("utf-8")
    tag = (field << 3) | 2; ln = len(d)
    r = bytearray([tag])
    while ln > 0x7F: r.append((ln & 0x7F) | 0x80); ln >>= 7
    r.append(ln & 0x7F); r.extend(d)
    return bytes(r)

def proto_str(data, field=1):
    idx = 0
    while idx < len(data):
        b = data[idx]; fn = b >> 3; wt = b & 7; idx += 1
        if wt == 2:
            ln = 0; sh = 0
            while idx < len(data):
                bb = data[idx]; idx += 1; ln |= (bb & 0x7F) << sh; sh += 7
                if not (bb & 0x80): break
            val = data[idx:idx+ln]; idx += ln
            if fn == field: return val.decode("utf-8", errors="replace")
        elif wt == 0:
            while idx < len(data) and data[idx] & 0x80: idx += 1
            idx += 1
        elif wt == 5: idx += 4
        elif wt == 1: idx += 8
        else: break
    return None

def get_current_account():
    """Read current account from state.vscdb"""
    for db in DB_PATHS:
        if not os.path.exists(db): continue
        try:
            conn = sqlite3.connect(db)
            cur = conn.cursor()
            r = cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
            r2 = cur.execute("SELECT value FROM ItemTable WHERE key='codeium.windsurf'").fetchone()
            conn.close()
            ak = json.loads(r[0]).get("apiKey", "") if r else ""
            em = json.loads(r2[0]).get("lastLoginEmail", "") if r2 else ""
            return ak, em, db
        except: pass
    return "", "", ""

def check_quota(api_key):
    """Check if account has quota via GetPlanStatus"""
    try:
        r = requests.post(
            "https://server.codeium.com/exa.api_server_pb.ApiServerService/GetPlanStatus",
            data=proto_encode(api_key), 
            headers={"Content-Type": "application/proto", "connect-protocol-version": "1"},
            proxies=PROXIES, timeout=10)
        if r.status_code == 200:
            # Look for "exhausted" pattern in response
            text = r.content.decode("utf-8", errors="replace").lower()
            if "exhaust" in text: return "exhausted"
            return "ok"
        return f"http_{r.status_code}"
    except: return "error"

def refresh_account(acc):
    """Refresh idToken and apiKey for an account"""
    rt = acc.get("refreshToken", "")
    if not rt: return False
    try:
        r = requests.post(
            f"https://securetoken.googleapis.com/v1/token?key={FK}",
            data={"grant_type": "refresh_token", "refresh_token": rt},
            proxies=PROXIES, timeout=15)
        if r.status_code != 200: return False
        d = r.json()
        acc["idToken"] = d["id_token"]
        acc["refreshToken"] = d.get("refresh_token", rt)
        
        # RegisterUser for fresh apiKey
        r2 = requests.post(
            "https://register.windsurf.com/exa.seat_management_pb.SeatManagementService/RegisterUser",
            data=proto_encode(d["id_token"]),
            headers={"Content-Type": "application/proto", "connect-protocol-version": "1"},
            proxies=PROXIES, timeout=15)
        if r2.status_code == 200:
            ak = proto_str(r2.content, 1)
            if ak and ak.startswith("sk-ws-"):
                acc["apiKey"] = ak
                return True
    except: pass
    return False

def inject(account, db_path=None):
    """Inject account into state.vscdb"""
    targets = [db_path] if db_path else DB_PATHS
    count = 0
    for db in targets:
        if not os.path.exists(db): continue
        try:
            conn = sqlite3.connect(db)
            cur = conn.cursor()
            r = cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
            if r:
                ex = json.loads(r[0]); ex["apiKey"] = account["apiKey"]
                cur.execute("UPDATE ItemTable SET value=? WHERE key='windsurfAuthStatus'", (json.dumps(ex),))
            r2 = cur.execute("SELECT value FROM ItemTable WHERE key='codeium.windsurf'").fetchone()
            if r2:
                cw = json.loads(r2[0]); cw["lastLoginEmail"] = account["email"]
                cur.execute("UPDATE ItemTable SET value=? WHERE key='codeium.windsurf'", (json.dumps(cw),))
            conn.commit(); conn.close(); count += 1
        except Exception as e:
            print(f"  DB error ({db}): {e}")
    return count > 0

def load_pool():
    with open(POOL_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_pool(pool):
    with open(POOL_FILE, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)

def main():
    if not os.path.exists(POOL_FILE):
        print(f"Pool not found: {POOL_FILE}")
        print("Run _do_login.py first.")
        return

    pool = load_pool()
    cur_ak, cur_em, cur_db = get_current_account()
    
    cmd = sys.argv[1] if len(sys.argv) > 1 else "auto"
    
    # Show status
    print(f"\n{'='*55}")
    print(f" Windsurf Account Pool — {len(pool)} accounts")
    print(f" Current: {cur_em or '(none)'}")
    print(f"{'='*55}")
    
    for i, a in enumerate(pool):
        ak = a.get("apiKey", "")
        is_current = (ak == cur_ak) or (a["email"] == cur_em)
        marker = " ★ ACTIVE" if is_current else ""
        name = a.get("displayName", "")
        name_str = f" ({name})" if name else ""
        print(f"  [{i+1:2d}] {a['email']}{name_str}{marker}")
    
    if cmd == "status":
        return
    
    # Determine target
    target_idx = None
    
    if cmd == "next":
        # Find current index, go to next
        for i, a in enumerate(pool):
            if a.get("apiKey") == cur_ak or a["email"] == cur_em:
                target_idx = (i + 1) % len(pool)
                break
        if target_idx is None:
            target_idx = 0
    elif cmd == "refresh":
        print("\n  Refreshing all accounts...", flush=True)
        for i, a in enumerate(pool):
            ok = refresh_account(a)
            status = "OK" if ok else "FAIL"
            print(f"    [{i+1}] {a['email']}: {status}", flush=True)
        save_pool(pool)
        print("  Pool refreshed & saved.", flush=True)
        # Auto-select best (first non-current with valid key)
        for i, a in enumerate(pool):
            if a.get("apiKey") and a.get("apiKey") != cur_ak:
                target_idx = i; break
        if target_idx is None:
            target_idx = 0
    elif cmd == "auto":
        # Pick first non-current account
        for i, a in enumerate(pool):
            if a.get("apiKey") and (a.get("apiKey") != cur_ak and a["email"] != cur_em):
                target_idx = i; break
        if target_idx is None:
            target_idx = 0
    else:
        try:
            target_idx = int(cmd) - 1
        except:
            print(f"\n  Unknown command: {cmd}")
            print("  Usage: _switch.py [N|next|status|refresh|auto]")
            return
    
    if target_idx is None or target_idx < 0 or target_idx >= len(pool):
        print(f"\n  Invalid index: {target_idx}")
        return
    
    target = pool[target_idx]
    print(f"\n  Switching to [{target_idx+1}] {target['email']}...")
    
    # Refresh token first
    print("  Refreshing token...", end=" ", flush=True)
    if refresh_account(target):
        save_pool(pool)
        print("OK", flush=True)
    else:
        print("using cached key", flush=True)
    
    # Inject
    if inject(target):
        print(f"\n  ✅ SWITCHED to: {target['email']}")
        print(f"     apiKey: {target['apiKey'][:40]}...")
        print(f"\n  >>> Ctrl+Shift+P → Reload Window <<<")
    else:
        print(f"\n  ❌ Injection failed")

if __name__ == "__main__":
    main()
