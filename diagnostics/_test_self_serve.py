#!/usr/bin/env python3
"""测试 server.self-serve.windsurf.com — 真实 API 服务端接受性"""
import sqlite3, json, os, base64, struct, urllib.request, urllib.error, re

STATE_DB = os.path.expandvars(r'%APPDATA%\\Windsurf\\User\\globalStorage\\state.vscdb')
API_SERVER = 'https://server.self-serve.windsurf.com'
INFERENCE_SERVER = 'https://inference.codeium.com'

def ev(v):
    r = []
    while True:
        b = v & 0x7F; v >>= 7
        r.append(b | 0x80 if v else b)
        if not v: break
    return bytes(r)

def ef_str(fn, s):
    d = s.encode('utf-8'); t = (fn << 3) | 2
    return ev(t) + ev(len(d)) + d

def ef_bytes(fn, b):
    t = (fn << 3) | 2
    return ev(t) + ev(len(b)) + b

def grpc_frame(pb):
    return b'\x00' + struct.pack('>I', len(pb)) + pb

def get_api_key():
    conn = sqlite3.connect('file:' + STATE_DB + '?mode=ro', uri=True)
    auth = json.loads(conn.execute(
        "SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'"
    ).fetchone()[0])
    conn.close()
    return auth.get('apiKey', ''), auth.get('userId', '')

def test_connect_rpc(server, method, request_pb, api_key):
    """Connect RPC (raw proto, no frame)"""
    service = 'exa.language_server_pb.LanguageServerService'
    url = f'{server}/{service}/{method}'
    headers = {
        'Content-Type': 'application/connect+proto',
        'Accept': 'application/connect+proto',
        'Connect-Protocol-Version': '1',
        'Authorization': f'Basic {api_key}',
        'X-Codeium-Key': api_key,
        'User-Agent': 'windsurf/1.9577.43',
    }
    req = urllib.request.Request(url, data=request_pb, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read(4000)
            return {'status': resp.status, 'headers': dict(resp.headers), 'body': raw}
    except urllib.error.HTTPError as e:
        return {'http_error': e.code, 'body': e.read(2000), 'headers': dict(e.headers)}
    except Exception as e:
        return {'error': str(e), 'type': type(e).__name__}

api_key, user_id = get_api_key()
print(f'API Key: {api_key[:25]}...')
print(f'User ID: {user_id}')
print(f'API Server: {API_SERVER}')

print("\n" + "="*65)
print("TEST 1: server.self-serve.windsurf.com — CheckChatCapacity")
print("="*65)

models_to_test = [
    ('claude-opus-4-6', '目标模型'),
    ('claude-opus-4-5', 'Opus 4.5 对照'),
    ('MODEL_CLAUDE_4_5_OPUS', 'Opus enum名称'),
]

for model_uid, desc in models_to_test:
    meta_inner = ef_str(1, api_key)
    meta_field = ef_bytes(1, meta_inner)
    request_pb = meta_field + ef_str(3, model_uid)
    
    result = test_connect_rpc(API_SERVER, 'CheckChatCapacity', request_pb, api_key)
    status = result.get('status') or result.get('http_error') or result.get('type')
    body = result.get('body', b'')
    if isinstance(body, bytes):
        body_str = body.decode('utf-8', errors='replace')
    else:
        body_str = str(body)
    print(f'\n  [{desc}] {model_uid}')
    print(f'    HTTP: {status}')
    print(f'    Body ({len(body_str)}B): {body_str[:300]}')

print("\n" + "="*65)
print("TEST 2: 尝试 grpc-web 格式")
print("="*65)

for model_uid, desc in [('claude-opus-4-6', '目标'), ('claude-opus-4-5', '对照')]:
    meta_inner = ef_str(1, api_key)
    meta_field = ef_bytes(1, meta_inner)
    request_pb = meta_field + ef_str(3, model_uid)
    body_with_frame = grpc_frame(request_pb)
    
    url = f'{API_SERVER}/exa.language_server_pb.LanguageServerService/CheckChatCapacity'
    headers = {
        'Content-Type': 'application/grpc-web+proto',
        'x-grpc-web': '1',
        'Accept': 'application/grpc-web+proto',
        'Authorization': f'Basic {api_key}',
        'X-Codeium-Key': api_key,
    }
    req = urllib.request.Request(url, data=body_with_frame, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read(4000)
            if len(raw) >= 5:
                flag = raw[0]
                length = struct.unpack('>I', raw[1:5])[0]
                pb = raw[5:5+min(length, len(raw)-5)]
                txt = pb.decode('utf-8', errors='replace')
                print(f'\n  {model_uid}: HTTP {resp.status}, flag={flag}, pb={pb[:80].hex()}, txt={txt[:200]}')
            else:
                print(f'  {model_uid}: HTTP {resp.status}, raw={raw.hex()[:100]}')
    except urllib.error.HTTPError as e:
        body = e.read(300).decode('utf-8', errors='replace')
        print(f'  {model_uid}: HTTP {e.code}: {body[:200]}')
    except Exception as e:
        print(f'  {model_uid}: {type(e).__name__}: {e}')

print("\n" + "="*65)
print("TEST 3: HTTPS 可达性检测")
print("="*65)
for server_url in [API_SERVER, INFERENCE_SERVER, 'https://server.codeium.com']:
    url = f'{server_url}/'
    req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.68.0'}, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read(200)
            print(f'  {server_url}: HTTP {resp.status}, {body.decode(errors="replace")[:100]}')
    except urllib.error.HTTPError as e:
        print(f'  {server_url}: HTTP {e.code}, {e.read(100).decode(errors="replace")[:80]}')
    except Exception as e:
        print(f'  {server_url}: {type(e).__name__}: {e}')

print("\n" + "="*65)
print("FIND: extension.js CSRF token 生成点")
print("="*65)
EXT_JS = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT_JS, 'r', encoding='utf-8', errors='replace') as f:
    ext = f.read()

# 找 activate 函数中的 CSRF token 生成
for pat in ['randomBytes', 'randomUUID', 'randomFill', 'generateKey']:
    hits = [(m.start(), ext[max(0,m.start()-150):m.start()+300])
            for m in re.finditer(pat, ext)]
    if hits:
        print(f'\n[{pat}] {len(hits)} hits:')
        # Show only hits near 'csrf' or 'token' or 'activate'
        for pos, ctx in hits:
            if any(x in ctx.lower() for x in ['csrf', 'token', 'activate', 'extension', 'start']):
                print(f'  @{pos}: {ctx[:250]}')
                print('  ---')
                break

print("\n=== DONE ===")
