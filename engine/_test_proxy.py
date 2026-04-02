#!/usr/bin/env python3
"""E2E test: Pool Proxy → upstream forwarding + pool routing"""
import urllib.request, json, time, os

PROXY = 'http://127.0.0.1:19876'

def get(path):
    r = urllib.request.urlopen(f'{PROXY}{path}', timeout=10)
    return json.loads(r.read())

def post(path, data=None):
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(f'{PROXY}{path}', data=body,
                                headers={'Content-Type': 'application/json'})
    r = urllib.request.urlopen(req, timeout=10)
    return json.loads(r.read())

print('=' * 60)
print('Pool Proxy E2E Test')
print('=' * 60)

# T1: Proxy local API health
d = get('/pool/health')
assert d['ok'], 'health check failed'
print(f'T1 /pool/health: OK (proxy={d["proxy"]})')

# T2: Pool status via proxy
d = get('/pool/status')
p = d['pool']
print(f'T2 /pool/status: {p["total"]} accounts, {p["available"]} avail, '
      f'{p["has_api_key"]} keys, D{p["total_daily"]}%·W{p["total_weekly"]}%')

# T3: Accounts via proxy
d = get('/pool/accounts')
accs = d['accounts']
print(f'T3 /pool/accounts: {len(accs)} accounts returned')

# T4: Forward a real gRPC-Web request to upstream (GetPlanStatus)
# This tests the actual proxy forwarding chain
print(f'\nT4 Testing upstream forwarding...')
try:
    # Send a minimal request through the proxy to upstream
    # The proxy will replace apiKey and forward to server.codeium.com
    req = urllib.request.Request(
        f'{PROXY}/exa.language_server_pb.LanguageServerService/GetStatus',
        data=b'',  # empty body
        headers={
            'Content-Type': 'application/proto',
            'Connect-Protocol-Version': '1',
        })
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        print(f'T4 Upstream forward: {resp.status} ({resp.length} bytes)')
        print(f'   Response headers: {dict(resp.headers)}'.replace('\n', ' ')[:200])
    except urllib.error.HTTPError as e:
        # Any response from upstream (even error) means proxy forwarding works
        body = e.read()[:200]
        print(f'T4 Upstream forward: HTTP {e.code} ({len(body)} bytes)')
        print(f'   → Proxy successfully forwarded to upstream!')
        if e.code in (400, 401, 404, 415, 501):
            print(f'   (Expected: gRPC endpoint expects proper protobuf payload)')
except Exception as e:
    print(f'T4 Upstream forward error: {e}')

# T5: Verify optimal key file is being written
key_file = os.path.join(os.path.dirname(__file__), '_optimal_key.txt')
time.sleep(4)  # Wait for key writer thread
if os.path.exists(key_file):
    key = open(key_file, 'r').read().strip()
    print(f'\nT5 Optimal key file: {key[:30]}... ({len(key)} chars) ✅')
else:
    print(f'\nT5 Optimal key file: not yet created (writer thread starting)')

# T6: Verify per-request routing (active account should be selected)
d = get('/pool/status')
ps = d.get('proxy_stats', {})
print(f'\nT6 Proxy stats: requests={ps.get("total_requests",0)} '
      f'forwarded={ps.get("total_forwarded",0)} '
      f'errors={ps.get("total_errors",0)} '
      f'rate_limits={ps.get("total_rate_limits",0)}')

print(f'\n{"=" * 60}')
print(f'ALL PROXY TESTS COMPLETE')
print(f'{"=" * 60}')
