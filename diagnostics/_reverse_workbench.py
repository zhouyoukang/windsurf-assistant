#!/usr/bin/env python3
"""Reverse engineer workbench.desktop.main.js + extension.js — 完全逆向认证+模型请求链路"""
import re, json, os, sys

WB = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
OUT = os.path.join(os.path.dirname(__file__), '_reverse_workbench_results.json')

results = {}

# ============================================================
# PART A: workbench.desktop.main.js
# ============================================================
print("=" * 70)
print("REVERSE ENGINEERING: workbench.desktop.main.js")
print("=" * 70)

with open(WB, 'r', encoding='utf-8', errors='replace') as f:
    wb = f.read()
print(f"  Size: {len(wb):,} chars")

# A1. gRPC service type names
services = re.findall(r'typeName:"([^"]+)"', wb)
unique_services = sorted(set(s for s in services if '.' in s))
print(f"\n[A1] gRPC Service Types ({len(unique_services)}):")
for s in unique_services[:40]:
    print(f"  {s}")
results['grpc_services'] = unique_services

# A2. RPC method names
rpc_methods = re.findall(r'name:"(\w+)",I:\w+,O:\w+,kind:', wb)
unique_rpc = sorted(set(rpc_methods))
print(f"\n[A2] RPC Methods ({len(unique_rpc)}):")
for m in unique_rpc[:50]:
    print(f"  {m}")
results['rpc_methods'] = unique_rpc

# A3. Server URLs
urls = set(re.findall(r'https?://[a-z0-9.-]+\.(?:codeium|windsurf|exafunction)\.com[^"\'`\s]*', wb))
print(f"\n[A3] Server URLs ({len(urls)}):")
for u in sorted(urls):
    print(f"  {u}")
results['server_urls'] = sorted(urls)

# A4. Authorization/API key injection
auth_hits = []
for m in re.finditer(r'(?:Authorization|x-api-key|api[_-]?key|bearer).{0,200}', wb, re.IGNORECASE):
    ctx = m.group()[:150]
    if any(k in ctx.lower() for k in ['header', 'set', 'append', 'authorization', 'bearer']):
        auth_hits.append(ctx)
print(f"\n[A4] Auth Header Injection ({len(auth_hits)} hits):")
for h in auth_hits[:8]:
    print(f"  {h[:130]}")
results['auth_injection'] = [h[:150] for h in auth_hits[:15]]

# A5. Transport creation (gRPC-Web / Connect)
transports = []
for m in re.finditer(r'(?:createGrpcWebTransport|createConnectTransport|grpcTransport|connectTransport)\([^)]{0,300}\)', wb):
    transports.append(m.group()[:200])
print(f"\n[A5] Transport Creation ({len(transports)}):")
for t in transports[:8]:
    print(f"  {t[:180]}")
results['transports'] = [t[:200] for t in transports[:10]]

# A6. Interceptors (middleware for auth)
interceptor_defs = []
for m in re.finditer(r'interceptors?\s*[=:]\s*\[([^\]]{0,500})\]', wb):
    interceptor_defs.append(m.group()[:200])
print(f"\n[A6] Interceptor Definitions ({len(interceptor_defs)}):")
for i in interceptor_defs[:5]:
    print(f"  {i[:180]}")
results['interceptors'] = [i[:200] for i in interceptor_defs[:10]]

# A7. BillingStrategy + ModelCostTier + ModelPricingType enums
for enum_name in ['BillingStrategy', 'ModelCostTier', 'ModelPricingType', 'GracePeriodStatus']:
    idx = wb.find(f'"{enum_name}"')
    if idx < 0:
        idx = wb.find(enum_name)
    if idx >= 0:
        region = wb[max(0, idx-500):idx+800]
        vals = re.findall(r'(\w+)\[\1\.(\w+)=(\d+)\]="(\w+)"', region)
        if vals:
            print(f"\n[A7] Enum {enum_name}:")
            enum_vals = []
            for _, name, num, _ in vals:
                print(f"  {name} = {num}")
                enum_vals.append((name, int(num)))
            results[f'enum_{enum_name}'] = enum_vals

# A8. Quota/ACU key variables
quota_vars = {}
for pat in ['quotaRemaining', 'percentRemaining', 'dailyQuota', 'weeklyQuota',
            'quota_exhausted', 'acuCost', 'creditCost', 'acuMultiplier',
            'overageBalanceMicros', 'billingStrategy', 'monthlyAcuLimit',
            'cumulativeTokensAtStep', 'checkChatCapacity', 'checkUserMessageRateLimit',
            'sendCascadeInput', 'WRITE_CHAT_INSUFFICIENT', 'quotaCostBasisPoints',
            'isCapacityLimited', 'INSUFFICIENT_CASCADE_CREDITS']:
    idx = wb.find(pat)
    if idx >= 0:
        snippet = wb[max(0,idx-50):idx+120].replace('\n',' ')
        quota_vars[pat] = {'offset': idx, 'ctx': snippet[:150]}
        
print(f"\n[A8] Quota/ACU Variables ({len(quota_vars)}):")
for name, info in sorted(quota_vars.items()):
    print(f"  @{info['offset']:>10} {name}: ...{info['ctx'][:100]}...")
results['quota_vars'] = {k: v['offset'] for k, v in quota_vars.items()}

# A9. Rate limit mechanism
rl_patterns = []
for m in re.finditer(r'checkUserMessageRateLimit.{0,300}', wb):
    rl_patterns.append(m.group()[:200])
print(f"\n[A9] Rate Limit Check ({len(rl_patterns)} hits):")
for r in rl_patterns[:3]:
    print(f"  {r[:180]}")
results['rate_limit'] = [r[:200] for r in rl_patterns[:5]]

# A10. sendCascadeInput — the actual model request entry point
send_patterns = []
for m in re.finditer(r'sendCascadeInput.{0,400}', wb):
    send_patterns.append(m.group()[:300])
print(f"\n[A10] sendCascadeInput ({len(send_patterns)} hits):")
for s in send_patterns[:3]:
    print(f"  {s[:200]}")

# ============================================================
# PART B: extension.js
# ============================================================
print("\n" + "=" * 70)
print("REVERSE ENGINEERING: extension.js")
print("=" * 70)

with open(EXT, 'r', encoding='utf-8', errors='replace') as f:
    ext = f.read()
print(f"  Size: {len(ext):,} chars")

# B1. gRPC services in extension
ext_services = re.findall(r'typeName:"([^"]+)"', ext)
ext_unique = sorted(set(s for s in ext_services if '.' in s))
print(f"\n[B1] Extension gRPC Services ({len(ext_unique)}):")
for s in ext_unique[:20]:
    print(f"  {s}")
results['ext_grpc_services'] = ext_unique

# B2. Extension RPC methods
ext_rpc = re.findall(r'name:"(\w+)",I:\w+,O:\w+,kind:', ext)
ext_rpc_unique = sorted(set(ext_rpc))
print(f"\n[B2] Extension RPC Methods ({len(ext_rpc_unique)}):")
for m in ext_rpc_unique[:30]:
    print(f"  {m}")
results['ext_rpc_methods'] = ext_rpc_unique

# B3. API key usage in extension
ext_apikey = []
for m in re.finditer(r'apiKey.{0,150}', ext):
    ext_apikey.append(m.group()[:120])
print(f"\n[B3] apiKey in Extension ({len(ext_apikey)} hits):")
for a in ext_apikey[:5]:
    print(f"  {a[:110]}")

# B4. Server URL patterns
ext_urls = set(re.findall(r'https?://[a-z0-9.-]+\.(?:codeium|windsurf|exafunction)\.com[^"\'`\s]*', ext))
print(f"\n[B4] Extension Server URLs ({len(ext_urls)}):")
for u in sorted(ext_urls):
    print(f"  {u}")
results['ext_server_urls'] = sorted(ext_urls)

# B5. Quota check flow
for pat_name, pat in [('billingStrategy', r'billingStrategy.{0,200}'),
                       ('dailyRemainingPercent', r'dailyRemainingPercent.{0,200}'),
                       ('checkChatCapacity', r'checkChatCapacity.{0,200}'),
                       ('GetPlanStatus', r'GetPlanStatus.{0,200}')]:
    hits = re.findall(pat, ext)
    if hits:
        print(f"\n[B5] {pat_name} ({len(hits)} hits):")
        for h in hits[:2]:
            print(f"  {h[:150]}")

# Save
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"\n=== Saved to {OUT} ===")
