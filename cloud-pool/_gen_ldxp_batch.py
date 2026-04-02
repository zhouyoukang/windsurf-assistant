#!/usr/bin/env python3
"""Generate batch codes for ldxp.cn upload + product listing data."""
import json, sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE = 'http://127.0.0.1:19880'
AK = 'test_admin_key_2026'

def req(method, path, body=None):
    hdrs = {'Content-Type': 'application/json', 'X-Admin-Key': AK}
    data = json.dumps(body).encode() if body else None
    r = Request(BASE + path, data=data, headers=hdrs, method=method)
    with urlopen(r, timeout=15) as resp:
        return json.loads(resp.read())

# Generate production batches
batches = [
    ('windsurf_trial', 50, 30),  # 50 trial codes, 30-day expiry
    ('windsurf_pro', 20, 30),    # 20 pro codes
    ('wam_1day', 100, 90),       # 100 WAM 1-day cards
    ('wam_3day', 50, 90),        # 50 WAM 3-day cards
    ('wam_7day', 30, 90),        # 30 WAM 7-day cards
]

print('=== ldxp.cn Batch Code Generation ===\n')
for product, count, days in batches:
    d = req('POST', '/api/admin/codes/generate',
            {'product': product, 'count': count, 'expires_days': days})
    if d.get('ok'):
        print(f'  {d["product_name"]}: {d["count"]} codes @ ¥{d["price_yuan"]:.2f} | batch={d["batch_id"]} expires={d["expires_at"][:10]}')
    else:
        print(f'  FAIL {product}: {d.get("error","")}')

# Export all available codes
print('\n=== Export Summary ===')
d = req('GET', '/api/admin/codes/export')
print(f'Total available: {d["total"]}')
for p, info in d.get('by_product', {}).items():
    print(f'  {p}: {info["count"]} codes @ ¥{info["price"]:.2f}')

# Product listing for ldxp.cn
print('\n=== ldxp.cn Product Listings ===')
products = req('GET', '/api/products')
listings = {
    'windsurf_trial': {
        'name': 'Windsurf 100额度 Trial独享账号【当天质保】',
        'price': '¥1.70',
        'description': '独享Windsurf Trial账号，100%日额度+100%周额度，发账号密码。\n兑换方式: 收到卡密后访问兑换页面输入卡密即可获取账号。\n质保: 当天有效，不要囤号。',
        'category': 'AI IDE账号',
    },
    'windsurf_pro': {
        'name': 'Windsurf 全模型独享账号 Trial【含热切换数据】',
        'price': '¥3.00',
        'description': '独享Windsurf Trial账号，含auth blob热切换数据，可配合无感换号工具使用。\n兑换方式: 收到卡密后访问兑换页面获取账号+热切换数据。',
        'category': 'AI IDE账号',
    },
    'wam_1day': {
        'name': '无感换号工具 1天卡【Win版】',
        'price': '¥0.20',
        'description': 'Windsurf无感换号工具1天使用权，号需自购。\n配合Windsurf小助手扩展使用，自动监测额度耗尽→秒切新号→零感知。',
        'category': '⚡️ 卡密',
    },
    'wam_3day': {
        'name': '无感换号工具 3天卡【Win版】',
        'price': '¥1.00',
        'description': '无感换号工具3天使用权。性价比之选。',
        'category': '⚡️ 卡密',
    },
    'wam_7day': {
        'name': '无感换号工具 7天卡【Win版】',
        'price': '¥2.00',
        'description': '无感换号工具7天使用权。重度用户推荐。',
        'category': '⚡️ 卡密',
    },
}

for pid, info in listings.items():
    pdata = products.get('products', {}).get(pid, {})
    print(f'\n--- {info["name"]} ---')
    print(f'  Price: {info["price"]}')
    print(f'  Category: {info["category"]}')
    print(f'  Description: {info["description"][:80]}...')

# Per-product export files
print('\n=== Per-Product Code Files ===')
for product in ['windsurf_trial', 'windsurf_pro', 'wam_1day', 'wam_3day', 'wam_7day']:
    d = req('GET', f'/api/admin/codes/export?product={product}')
    codes = d.get('codes', [])
    if codes:
        from pathlib import Path
        out = Path(__file__).parent / f'_ldxp_codes_{product}.txt'
        out.write_text('\n'.join(codes), encoding='utf-8')
        print(f'  {product}: {len(codes)} codes -> {out.name}')

print('\n=== Done! Upload .txt files to ldxp.cn merchant backend ===')
