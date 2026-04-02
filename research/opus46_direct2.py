"""
opus46_direct2.py
关键发现:
  inference_api_server_url = https://inference.codeium.com  (不是 server.codeium.com!)
  extension_server_port = 64956 / 57400  (本地 LSP gRPC 端口)

策略:
  1. 直连本地 LSP 端口 — 绕过 Windsurf 前端
  2. 直连 inference.codeium.com — 直接推理调用
"""
import sys, json, sqlite3, struct, http.client, ssl, socket, re

DB_PATH = r"C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb"

# ─── Auth ─────────────────────────────────────────────────────────────────────
def get_api_key():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    row  = cur.fetchone(); conn.close()
    return json.loads(row[0]).get('apiKey', '')

# ─── Proto helpers ────────────────────────────────────────────────────────────
def varint(n):
    out = []
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n & 0x7F)
    return bytes(out)

def field_str(no, s):
    b = s.encode() if isinstance(s, str) else s
    return varint((no << 3) | 2) + varint(len(b)) + b

def field_msg(no, m):
    return varint((no << 3) | 2) + varint(len(m)) + m

def connect_frame(payload):
    return b'\x00' + struct.pack('>I', len(payload)) + payload

# ─── HTTP/2 helpers (Connect-RPC over HTTP/1.1) ───────────────────────────────
def grpc_post(host, path, api_key, body_bytes, timeout=20, port=443, use_ssl=True):
    headers = {
        'Content-Type':             'application/connect+proto',
        'Accept':                   'application/connect+proto',
        'Connect-Protocol-Version': '1',
        'Authorization':            f'Bearer {api_key}',
        'x-model-hint':             'claude-opus-4-6',
        'User-Agent':               'grpc-go/1.56.0',
    }
    framed = connect_frame(body_bytes)
    try:
        if use_ssl:
            ctx  = ssl.create_default_context()
            conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request('POST', path, framed, headers)
        r    = conn.getresponse()
        body = r.read(1000)
        return r.status, dict(r.headers), body
    except Exception as e:
        return 0, {}, str(e).encode()

# ─── Test 1: 本地 LSP 端口 ────────────────────────────────────────────────────
def test_local_lsp(api_key):
    print("\n=== Test 1: 本地 LSP 端口 (extension_server_port) ===")
    ports = [64956, 57400]
    # 先探测端口是否开放
    for port in ports:
        try:
            s = socket.socket()
            s.settimeout(2)
            result = s.connect_ex(('127.0.0.1', port))
            s.close()
            if result == 0:
                print(f"  端口 {port}: OPEN ✅")
            else:
                print(f"  端口 {port}: CLOSED ❌")
        except Exception as e:
            print(f"  端口 {port}: error {e}")

    # 尝试 gRPC 请求到这些端口
    paths = [
        '/exa.language_server_pb.LanguageServerService/GetChatMessage',
        '/exa.language_server_pb.LanguageServerService/GetStatus',
        '/exa.language_server_pb.LanguageServerService/GetCompletions',
        '/windsurf.LanguageServerService/GetChatMessage',
    ]
    min_body = field_str(1, 'claude-opus-4-6') + field_str(2, 'Say OK')

    for port in ports:
        for path in paths[:2]:  # only try top 2 paths per port
            s, hdrs, body = grpc_post('127.0.0.1', path, api_key, min_body,
                                       port=port, use_ssl=False, timeout=5)
            if s != 0:
                print(f"  port={port} path={path}")
                print(f"    HTTP {s}, body={body[:120]}")

# ─── Test 2: 直连 inference.codeium.com ──────────────────────────────────────
def test_inference_direct(api_key):
    print("\n=== Test 2: 直连 inference.codeium.com ===")
    HOST = 'inference.codeium.com'

    # 先 GET / 看 server info
    try:
        ctx  = ssl.create_default_context()
        conn = http.client.HTTPSConnection(HOST, 443, timeout=10, context=ctx)
        conn.request('GET', '/', headers={'Authorization': f'Bearer {api_key}'})
        r = conn.getresponse()
        body = r.read(500)
        print(f"  GET / → HTTP {r.status}: {body[:200]}")
    except Exception as e:
        print(f"  GET / error: {e}")

    # 试 gRPC 路径
    candidate_paths = [
        '/exa.language_server_pb.LanguageServerService/GetChatMessage',
        '/exa.language_server_pb.LanguageServerService/GetStatus',
        '/exa.chat_pb.ChatService/GetChatMessage',
        '/GetChatMessage',
        '/api/v1/chat',
    ]
    # 最小 payload: field1=model, field2=prompt
    min_body = field_str(1, 'claude-opus-4-6') + field_str(2, 'Say OK')

    for path in candidate_paths:
        s, hdrs, body = grpc_post(HOST, path, api_key, min_body, timeout=10)
        grpc_status = hdrs.get('grpc-status', hdrs.get('connect-error-detail', ''))
        print(f"  {path}")
        print(f"    HTTP {s}, grpc-status={grpc_status}, body={body[:100]}")

# ─── Test 3: 从 language_server_windows_x64.exe 进程找实际端口 ─────────────
def find_ls_ports():
    print("\n=== Test 3: 找语言服务器监听端口 ===")
    import subprocess, re
    try:
        r = subprocess.run(
            ['netstat', '-ano'],
            capture_output=True, text=True, timeout=10
        )
        lines = r.stdout.splitlines()
        print(f"  总连接数: {len(lines)}")
        # 找 LISTENING 127.0.0.1 端口
        lsp_ports = []
        for line in lines:
            if 'LISTENING' in line and '0.0.0.0:0' not in line:
                m = re.search(r'(?:127\.0\.0\.1|0\.0\.0\.0):(\d+)', line)
                if m:
                    port = int(m.group(1))
                    if 40000 < port < 70000:  # extension_server_port range
                        pid_m = re.search(r'\s+(\d+)\s*$', line)
                        pid = pid_m.group(1) if pid_m else '?'
                        lsp_ports.append((port, pid))
                        print(f"  port {port} PID={pid}")
        return lsp_ports
    except Exception as e:
        print(f"  error: {e}")
        return []

# ─── 主函数 ───────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    api_key = get_api_key()
    print(f"API key: {api_key[:25]}...")

    # 找语言服务器端口
    lsp_ports = find_ls_ports()

    # 测试本地 LSP
    test_local_lsp(api_key)

    # 测试 inference.codeium.com 直连
    test_inference_direct(api_key)

    print("\n=== 完成 ===")
