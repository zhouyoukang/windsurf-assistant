#!/usr/bin/env python3
"""Set merchant config on cloud pool server via localhost."""
import json, subprocess, sys

config = {
    "merchant_name": "周老板",
    "merchant_phone": "18368624112",
    "merchant_device": "OnePlus NE2210 158377ff",
    "alipay_name": "周*康",
    "alipay_account": "18368624112",
    "alipay_note": "请备注订单号",
    "wechat_name": "周*康",
    "wechat_account": "18368624112",
    "wechat_note": "请备注订单号",
}

body = json.dumps(config, ensure_ascii=False)
cmd = f"""curl -s -X POST http://127.0.0.1:19880/api/admin/merchant-config -H 'Content-Type: application/json' -H 'X-Admin-Key: d7e895be64192470b373eb8664fd80bc442c38817adc99e9' -d '{body}'"""

# Run via SSH on server
r = subprocess.run(["ssh", "-o", "ConnectTimeout=10", "aliyun", cmd],
                   capture_output=True, text=True, timeout=20)
print("SET:", r.stdout.strip())

# Verify
cmd2 = "curl -s http://127.0.0.1:19880/api/admin/merchant-config -H 'X-Admin-Key: d7e895be64192470b373eb8664fd80bc442c38817adc99e9'"
r2 = subprocess.run(["ssh", "-o", "ConnectTimeout=10", "aliyun", cmd2],
                    capture_output=True, text=True, timeout=20)
print("GET:", r2.stdout.strip()[:500])

# Test P2P init with payment instructions
cmd3 = """curl -s -X POST http://127.0.0.1:19880/api/p2p/init -H 'Content-Type: application/json' -d '{"device_id":"DEV-E00039E0","w_credits":100,"method":"alipay"}'"""
r3 = subprocess.run(["ssh", "-o", "ConnectTimeout=10", "aliyun", cmd3],
                    capture_output=True, text=True, timeout=20)
print("P2P:", r3.stdout.strip()[:500])

# Test redeem (generate + redeem)
cmd4 = """curl -s -X POST http://127.0.0.1:19880/api/admin/codes/generate -H 'Content-Type: application/json' -H 'X-Admin-Key: d7e895be64192470b373eb8664fd80bc442c38817adc99e9' -d '{"product":"windsurf_trial","count":1,"expires_days":30}'"""
r4 = subprocess.run(["ssh", "-o", "ConnectTimeout=10", "aliyun", cmd4],
                    capture_output=True, text=True, timeout=20)
d4 = json.loads(r4.stdout) if r4.stdout else {}
code = d4.get('codes', [''])[0]
print("GEN:", code)

if code:
    cmd5 = f"""curl -s -X POST http://127.0.0.1:19880/api/redeem -H 'Content-Type: application/json' -d '{{"code":"{code}"}}'"""
    r5 = subprocess.run(["ssh", "-o", "ConnectTimeout=10", "aliyun", cmd5],
                        capture_output=True, text=True, timeout=20)
    print("REDEEM:", r5.stdout.strip()[:300])
