#!/usr/bin/env python3
"""Check quota status for all 10 accounts"""
import json, requests, sys, os

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

PROXY = "http://127.0.0.1:7890"
PROXIES = {"https": PROXY, "http": PROXY}
POOL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_accounts_pool.json")

def proto_encode(s, field=1):
    d = s.encode("utf-8"); tag = (field << 3) | 2; ln = len(d)
    r = bytearray([tag])
    while ln > 0x7F: r.append((ln & 0x7F) | 0x80); ln >>= 7
    r.append(ln & 0x7F); r.extend(d)
    return bytes(r)

pool = json.load(open(POOL_FILE, "r", encoding="utf-8"))
print(f"Checking {len(pool)} accounts...\n", flush=True)

valid = 0
for i, a in enumerate(pool):
    ak = a.get("apiKey", "")
    email = a["email"]
    try:
        r = requests.post(
            "https://server.codeium.com/exa.api_server_pb.ApiServerService/GetPlanStatus",
            data=proto_encode(ak),
            headers={"Content-Type": "application/proto", "connect-protocol-version": "1"},
            proxies=PROXIES, timeout=10
        )
        if r.status_code == 200:
            txt = r.content.decode("utf-8", "replace")
            if "exhaust" in txt.lower():
                status = "EXHAUSTED"
            else:
                status = "VALID"
                valid += 1
                if "Trial" in txt:
                    status = "VALID/Trial"
        else:
            status = f"HTTP_{r.status_code}"
    except Exception as e:
        status = f"ERR:{str(e)[:40]}"

    icon = "✅" if "VALID" in status else "❌"
    print(f"  {icon} [{i+1:2d}] {status:15s} {email}", flush=True)

print(f"\nResult: {valid}/{len(pool)} accounts valid", flush=True)
