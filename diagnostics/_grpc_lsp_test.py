#!/usr/bin/env python3
"""LSP gRPC 接受性测试 — 验证 claude-opus-4-6 是否被服务端拒绝"""
import sqlite3, json, os, struct, urllib.request, urllib.error

STATE_DB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')
LSP_PORT = 42913

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

def ef_int(fn, v):
    return ev((fn << 3) | 0) + ev(v)

def grpc_frame(pb):
    return b'\x00' + struct.pack('>I', len(pb)) + pb

def parse_pb_strings(data):
    results = []
    pos = 0
    while pos < len(data):
        try:
            tag, pos = 0, pos
            while pos < len(data):
                b = data[pos]; pos += 1
                tag |= (b & 0x7F) << (7 * len(results))
                if not (b & 0x80): break
            # Simple parse
            break
        except: break
    # Just try to decode as text
    try:
        return data.decode('utf-8', errors='replace')
    except:
        return data.hex()


def get_api_key():
    conn = sqlite3.connect('file:' + STATE_DB + '?mode=ro', uri=True)
    auth = json.loads(conn.execute(
        "SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'"
    ).fetchone()[0])
    conn.close()
    return auth.get('apiKey', '')


def test_check_capacity(api_key, model_uid, port=LSP_PORT, content_type='application/connect+proto'):
    """CheckChatCapacity — Connect RPC (raw proto, no frame)"""
    meta_inner = ef_str(1, api_key)       # metadata.api_key = F1
    meta_field = ef_bytes(1, meta_inner)  # request.F1 = metadata
    request_pb = meta_field + ef_str(3, model_uid)

    url = f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/CheckChatCapacity'
    headers = {
        'Content-Type': content_type,
        'Accept': content_type,
        'Connect-Protocol-Version': '1',
    }
    req = urllib.request.Request(url, data=request_pb, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read()
            txt = raw.decode('utf-8', errors='replace')
            return {'status': resp.status, 'raw_hex': raw.hex(), 'txt': txt}
    except urllib.error.HTTPError as e:
        body = e.read(300).decode('utf-8', errors='replace')
        return {'http_error': e.code, 'body': body}
    except Exception as e:
        return {'error': str(e), 'type': type(e).__name__}


def test_grpc_connectivity(port=LSP_PORT):
    """测试 LSP 端口连通性 — 空请求"""
    url = f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/CheckChatCapacity'
    # Try Connect RPC with empty body
    for ct in ['application/connect+proto', 'application/proto', 'application/grpc-web+proto']:
        headers = {'Content-Type': ct, 'Accept': ct, 'Connect-Protocol-Version': '1'}
        body = grpc_frame(b'') if 'grpc-web' in ct else b''
        req = urllib.request.Request(url, data=body, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return f'HTTP {resp.status} [{ct}]'
        except urllib.error.HTTPError as e:
            resp_body = e.read(200).decode(errors='replace')
            if e.code != 500 or 'utf-32' not in resp_body:
                return f'HTTP {e.code} [{ct}]: {resp_body[:80]}'
        except Exception as e:
            return f'{type(e).__name__}: {e}'
    return 'all content-types failed'


if __name__ == '__main__':
    print('=' * 65)
    print(f'LSP gRPC 接受性测试 — port {LSP_PORT}')
    print('=' * 65)

    api_key = get_api_key()
    print(f'API Key: {api_key[:25]}...')

    print(f'\n── 连通性测试 ──')
    conn_result = test_grpc_connectivity()
    print(f'  {conn_result}')

    print(f'\n── CheckChatCapacity 测试 ──')
    models = [
        ('claude-opus-4-6', '目标模型'),
        ('claude-opus-4-5', '已在commandModels的Opus'),
        ('claude-3-5-sonnet-20241022', '基准对照'),
    ]
    for uid, desc in models:
        result = test_check_capacity(api_key, uid)
        status = result.get('status') or result.get('http_error') or result.get('type')
        txt = result.get('txt', result.get('body', result.get('error', '')))
        flag = result.get('flag', '?')
        # flag=0 = data frame, flag=128 = trailers
        flag_str = 'DATA' if flag == 0 else 'TRAILER' if flag == 128 else f'flag={flag}'
        print(f'\n  [{desc}] {uid}')
        print(f'    HTTP: {status} | frame: {flag_str}')
        print(f'    text: {txt[:200]}')
        if 'pb_hex' in result:
            print(f'    hex:  {result["pb_hex"][:80]}')
