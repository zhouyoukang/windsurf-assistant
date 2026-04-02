#!/usr/bin/env python3
"""Verify all 10 accounts: correct endpoint + idToken"""
import json, requests, sys, os, struct

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

PROXY = "http://127.0.0.1:7890"
PROXIES = {"https": PROXY, "http": PROXY}
POOL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_accounts_pool.json")

PLAN_URLS = [
    "https://server.codeium.com/exa.seat_management_pb.SeatManagementService/GetPlanStatus",
    "https://web-backend.windsurf.com/exa.seat_management_pb.SeatManagementService/GetPlanStatus",
]
HEADERS = {"Content-Type": "application/proto", "connect-protocol-version": "1"}

def proto_encode(s, field=1):
    d = s.encode("utf-8"); tag = (field << 3) | 2; ln = len(d)
    r = bytearray([tag])
    while ln > 0x7F: r.append((ln & 0x7F) | 0x80); ln >>= 7
    r.append(ln & 0x7F); r.extend(d)
    return bytes(r)

def read_varint(data, pos):
    result = 0; shift = 0
    while pos < len(data):
        b = data[pos]; pos += 1
        result |= (b & 0x7f) << shift
        if not (b & 0x80): break
        shift += 7
    return result, pos

def parse_plan(buf):
    """Extract readable strings from plan status proto"""
    strings = []
    i = 0
    while i < len(buf) - 2:
        if buf[i] & 0x07 == 2:
            pos = i + 1
            try:
                L, pos2 = read_varint(buf, pos)
                if 0 < L < 100 and pos2 + L <= len(buf):
                    s = buf[pos2:pos2+L].decode("utf-8")
                    if all(0x20 <= ord(c) <= 0x7e for c in s) and len(s) > 2:
                        strings.append(s)
            except: pass
        i += 1
    return strings

pool = json.load(open(POOL_FILE, "r", encoding="utf-8"))
print(f"Verifying {len(pool)} accounts...\n", flush=True)

valid = 0
for i, a in enumerate(pool):
    email = a["email"]
    id_token = a.get("idToken", "")
    if not id_token:
        print(f"  ❌ [{i+1:2d}] NO_TOKEN     {email}", flush=True)
        continue

    body = proto_encode(id_token, field=1)
    status = "FAIL"
    plan_info = ""

    for url in PLAN_URLS:
        try:
            r = requests.post(url, data=body, headers=HEADERS, proxies=PROXIES, timeout=12)
            if r.status_code == 200 and len(r.content) > 10:
                strings = parse_plan(r.content)
                plan_str = ", ".join(s for s in strings if s not in (email,) and not s.startswith("sk-ws-"))
                plan_info = plan_str[:60] if plan_str else f"({len(r.content)}B)"
                status = "VALID"
                valid += 1
                break
            elif r.status_code == 200:
                status = "EMPTY_RESP"
        except Exception as e:
            status = f"ERR"
            continue

    icon = "✅" if status == "VALID" else "❌"
    print(f"  {icon} [{i+1:2d}] {status:12s} {email}  {plan_info}", flush=True)

print(f"\nResult: {valid}/{len(pool)} valid", flush=True)
