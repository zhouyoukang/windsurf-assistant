#!/usr/bin/env python3
"""直接登录10个账号 + 注入最优账号到Windsurf"""
import json, requests, sqlite3, os, sys, time

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

PROXY = "http://127.0.0.1:7890"
PROXIES = {"https": PROXY, "http": PROXY}
FK = "AIzaSyDsOl-1XpT5err0Tcnx8FFod1H8gVGIycY"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

ACCOUNTS = [
    ("rothmanqio98996@yahoo.com", "5%7eIYoSQjuE"),
    ("jacobseef3217@yahoo.com", "h0#yE#qAjqOv"),
    ("workvmfd11668@yahoo.com", "^^766vYZqQqi"),
    ("lepekb98258@yahoo.com", "t&9OYudZUQH3"),
    ("harropfjmf89402@yahoo.com", "Dr44&QEUu*BG"),
    ("jaramjw8983709@yahoo.com", "Sa0!JfHlqm6%"),
    ("adoobuca7563@yahoo.com", "$7qIhZqfviEw"),
    ("zellxdyqr55610@yahoo.com", "!n!V&vNU6J@q"),
    ("klugeuxhdr49740@yahoo.com", "TPKY7Tx@*L&l"),
    ("tregreglsatu322@yahoo.com", "8Ckbfp!sDtIS"),
]

def proto_encode(s, field=1):
    d = s.encode("utf-8")
    tag = (field << 3) | 2
    ln = len(d)
    r = bytearray([tag])
    while ln > 0x7F:
        r.append((ln & 0x7F) | 0x80); ln >>= 7
    r.append(ln & 0x7F)
    r.extend(d)
    return bytes(r)

def proto_decode_str(data, field=1):
    idx = 0
    while idx < len(data):
        b = data[idx]; fn = b >> 3; wt = b & 7; idx += 1
        if wt == 2:
            ln = 0; sh = 0
            while idx < len(data):
                bb = data[idx]; idx += 1
                ln |= (bb & 0x7F) << sh; sh += 7
                if not (bb & 0x80): break
            val = data[idx:idx+ln]; idx += ln
            if fn == field:
                return val.decode("utf-8", errors="replace")
        elif wt == 0:
            while idx < len(data) and data[idx] & 0x80: idx += 1
            idx += 1
        elif wt == 5: idx += 4
        elif wt == 1: idx += 8
        else: break
    return None

# ── Phase 0: Test proxy ──
print("=== Phase 0: Proxy Test ===", flush=True)
try:
    r = requests.get("https://www.google.com", proxies=PROXIES, timeout=8)
    print(f"  Proxy OK (google={r.status_code})", flush=True)
except Exception as e:
    print(f"  Proxy FAIL: {e}", flush=True)
    print("  尝试无代理直连...", flush=True)
    PROXIES = {}

# ── Phase 1: Firebase Login ──
print("\n=== Phase 1: Firebase Login ===", flush=True)
results = []
for i, (email, pw) in enumerate(ACCOUNTS):
    tag = f"[{i+1:2d}/10]"
    try:
        r = requests.post(
            f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FK}",
            json={"email": email, "password": pw, "returnSecureToken": True},
            proxies=PROXIES, timeout=20
        )
        if r.status_code == 200:
            d = r.json()
            name = d.get("displayName", "")
            print(f"  {tag} OK {email} (name={name})", flush=True)
            results.append({
                "email": email, "password": pw,
                "idToken": d["idToken"],
                "refreshToken": d["refreshToken"],
                "displayName": name,
                "localId": d.get("localId", ""),
            })
        else:
            err = r.json().get("error", {}).get("message", "?")
            print(f"  {tag} FAIL {email}: {err}", flush=True)
    except Exception as e:
        print(f"  {tag} ERR {email}: {str(e)[:60]}", flush=True)

print(f"\n  Firebase: {len(results)}/{len(ACCOUNTS)} success", flush=True)
if not results:
    print("  全部失败! 退出.", flush=True)
    sys.exit(1)

# ── Phase 2: RegisterUser → apiKey ──
print("\n=== Phase 2: RegisterUser → apiKey ===", flush=True)
final = []
for acc in results:
    email = acc["email"]
    body = proto_encode(acc["idToken"], field=1)
    try:
        r = requests.post(
            "https://register.windsurf.com/exa.seat_management_pb.SeatManagementService/RegisterUser",
            data=body,
            headers={"Content-Type": "application/proto", "connect-protocol-version": "1"},
            proxies=PROXIES, timeout=20
        )
        if r.status_code == 200:
            ak = proto_decode_str(r.content, field=1)
            if ak and ak.startswith("sk-ws-"):
                acc["apiKey"] = ak
                final.append(acc)
                print(f"  OK {email}: {ak[:40]}...", flush=True)
            else:
                print(f"  PARSE_FAIL {email}", flush=True)
        else:
            print(f"  HTTP_{r.status_code} {email}", flush=True)
    except Exception as e:
        print(f"  ERR {email}: {str(e)[:50]}", flush=True)

print(f"\n  apiKey: {len(final)}/{len(results)} success", flush=True)
if not final:
    print("  全部失败! 退出.", flush=True)
    sys.exit(1)

# ── Phase 3: Save pool ──
pool_path = os.path.join(SCRIPT_DIR, "_accounts_pool.json")
with open(pool_path, "w", encoding="utf-8") as f:
    json.dump(final, f, ensure_ascii=False, indent=2)
print(f"\n  Saved: {pool_path}", flush=True)

# ── Phase 4: Inject best account ──
print("\n=== Phase 4: Inject to Windsurf ===", flush=True)
best = final[0]
db_paths = [
    os.path.expandvars(r"%APPDATA%\Windsurf\User\globalStorage\state.vscdb"),
    r"C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb",
]
injected = False
for db_path in db_paths:
    if not os.path.exists(db_path):
        continue
    print(f"  DB: {db_path}", flush=True)
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Update windsurfAuthStatus
        row = cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        if row:
            existing = json.loads(row[0])
            old_key = existing.get("apiKey", "?")[:30]
            existing["apiKey"] = best["apiKey"]
            cur.execute("UPDATE ItemTable SET value=? WHERE key='windsurfAuthStatus'",
                        (json.dumps(existing),))
            print(f"  apiKey: {old_key}... → {best['apiKey'][:30]}...", flush=True)

        # Update lastLoginEmail
        row2 = cur.execute("SELECT value FROM ItemTable WHERE key='codeium.windsurf'").fetchone()
        if row2:
            cw = json.loads(row2[0])
            cw["lastLoginEmail"] = best["email"]
            cur.execute("UPDATE ItemTable SET value=? WHERE key='codeium.windsurf'",
                        (json.dumps(cw),))

        conn.commit()
        conn.close()
        print(f"  INJECTED: {best['email']}", flush=True)
        injected = True
    except Exception as e:
        print(f"  DB error: {e}", flush=True)

# ── Phase 5: Ensure proxy settings ──
print("\n=== Phase 5: Proxy Settings ===", flush=True)
settings_paths = [
    os.path.expandvars(r"%APPDATA%\Windsurf\User\settings.json"),
    r"C:\Users\Administrator\AppData\Roaming\Windsurf\User\settings.json",
]
for sp in settings_paths:
    if not os.path.exists(sp):
        continue
    try:
        with open(sp, "r") as f:
            s = json.load(f)
        changed = False
        if s.get("http.proxy") != "http://127.0.0.1:7890":
            s["http.proxy"] = "http://127.0.0.1:7890"; changed = True
        if s.get("http.proxySupport") != "override":
            s["http.proxySupport"] = "override"; changed = True
        if s.get("http.proxyStrictSSL") is not False:
            s["http.proxyStrictSSL"] = False; changed = True
        if changed:
            with open(sp, "w") as f:
                json.dump(s, f, indent=2)
            print(f"  FIXED: {sp}", flush=True)
        else:
            print(f"  OK: {sp}", flush=True)
    except Exception as e:
        print(f"  ERR: {sp}: {e}", flush=True)

# ── Summary ──
print(f"\n{'='*50}", flush=True)
print(f"DONE", flush=True)
print(f"  Accounts: {len(final)}/{len(ACCOUNTS)} ready", flush=True)
if injected:
    print(f"  Active: {best['email']}", flush=True)
    print(f"  apiKey: {best['apiKey'][:40]}...", flush=True)
print(f"\n  >>> Ctrl+Shift+P → Reload Window <<<", flush=True)
print(f"{'='*50}", flush=True)

# Print all accounts summary
print("\n=== All Accounts ===", flush=True)
for i, a in enumerate(final):
    marker = " ★" if a["email"] == best["email"] else ""
    print(f"  [{i+1}] {a['email']}{marker}", flush=True)
