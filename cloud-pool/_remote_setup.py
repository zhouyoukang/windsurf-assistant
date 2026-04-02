#!/usr/bin/env python3
"""Remote setup: runs ON the cloud server via SSH stdin pipe."""
import json
from urllib.request import Request, urlopen

BASE = 'http://127.0.0.1:19880'
AK = 'd7e895be64192470b373eb8664fd80bc442c38817adc99e9'

def req(method, path, body=None):
    hdrs = {'Content-Type': 'application/json', 'X-Admin-Key': AK}
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body else None
    r = Request(BASE + path, data=data, headers=hdrs, method=method)
    with urlopen(r, timeout=15) as resp:
        return json.loads(resp.read())

# 1. Set merchant config
print('=== Merchant Config ===')
d = req('POST', '/api/admin/merchant-config', {
    'merchant_name': '周老板',
    'merchant_phone': '18368624112',
    'merchant_device': 'OnePlus NE2210 158377ff',
    'alipay_name': '周*康',
    'alipay_account': '18368624112',
    'alipay_note': '请备注订单号',
    'wechat_name': '周*康',
    'wechat_account': '18368624112',
    'wechat_note': '请备注订单号',
})
print('SET:', d)

# 2. Verify
d2 = req('GET', '/api/admin/merchant-config')
print('GET:', json.dumps(d2, ensure_ascii=False)[:400])

# 3. P2P init with payment instructions
print('\n=== P2P Init ===')
d3 = req('POST', '/api/p2p/init', {'device_id': 'DEV-E00039E0', 'w_credits': 100, 'method': 'alipay'})
print('P2P:', json.dumps(d3, ensure_ascii=False)[:400])

# 4. Generate + redeem test
print('\n=== Redeem E2E ===')
d4 = req('POST', '/api/admin/codes/generate', {'product': 'windsurf_trial', 'count': 1, 'expires_days': 30})
code = d4.get('codes', [''])[0]
print('GEN:', code)
if code:
    d5 = req('POST', '/api/redeem', {'code': code})
    print('REDEEM:', json.dumps(d5, ensure_ascii=False)[:300])

# 5. Health
print('\n=== Health ===')
d6 = req('GET', '/api/health')
print('HEALTH:', d6)
