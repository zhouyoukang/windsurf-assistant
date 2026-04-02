"""find_api_path.py — 找 Windsurf cascade API 路径"""
import re, os, sys, subprocess, socket, http.client, ssl, json, sqlite3

EXT_JS = r"D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
DB_PATH = r"C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb"

def get_api_key():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    row = cur.fetchone(); conn.close()
    auth = json.loads(row[0])
    return auth.get('apiKey', '')

def scan_js_service_paths():
    """从 extension.js 找所有 service typeName"""
    print("[JS] 扫描 extension.js 服务路径...")
    with open(EXT_JS, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    
    # 找所有 typeName 值
    type_names = re.findall(r'typeName:\s*["\']([^"\']+)["\']', content)
    print(f"  typeName 总数: {len(type_names)}")
    for t in sorted(set(type_names)):
        print(f"  {t}")
    
    # 找 GetChatMessage 附近的上下文
    print("\n[JS] GetChatMessage 附近 500 字节:")
    idx = content.find('GetChatMessage')
    if idx >= 0:
        region = content[max(0, idx-300):idx+400]
        # 找 typeName 和 serverStreamingName
        print(repr(region))
    
    # 找所有 name: "Get..." 模式
    method_names = re.findall(r'name:\s*["\']([A-Z][a-zA-Z]{3,})["\']', content)
    print(f"\n[JS] 方法名 (前20): {method_names[:20]}")
    
    return type_names

def probe_direct(host, path, api_key, body=b'', timeout=10):
    """直接 HTTPS 请求到 host/path"""
    ctx = ssl.create_default_context()
    try:
        conn = http.client.HTTPSConnection(host, 443, timeout=timeout, context=ctx)
        headers = {
            'Content-Type': 'application/connect+proto',
            'Accept': 'application/connect+proto',
            'Connect-Protocol-Version': '1',
            'Authorization': f'Bearer {api_key}',
            'x-request-id': 'test-opus46',
        }
        conn.request('POST', path, body, headers)
        resp = conn.getresponse()
        body_resp = resp.read(500)
        return resp.status, body_resp
    except Exception as e:
        return 0, str(e).encode()[:200]

def find_local_lsp_ports():
    """找本地 LSP 端口 (Windsurf extension 监听的)"""
    print("\n[LSP] 找本地监听端口...")
    try:
        r = subprocess.run(
            ['netstat', '-ano'],
            capture_output=True, text=True, timeout=10
        )
        lines = r.stdout.splitlines()
        # 找 127.0.0.1 listening ports (排除已知的)
        known = {19876, 19877, 19850, 9903, 9876}
        for line in lines:
            if 'LISTENING' in line and '127.0.0.1' in line:
                m = re.search(r'127\.0\.0\.1:(\d+)', line)
                if m:
                    port = int(m.group(1))
                    if port not in known and 1000 < port < 65000:
                        print(f"  localhost:{port} LISTENING — {line.strip()}")
    except Exception as e:
        print(f"  error: {e}")

def probe_inference_paths(api_key):
    """直连 server.codeium.com 测试所有候选路径"""
    HOST = 'server.codeium.com'
    print(f"\n[DIRECT] 直连 {HOST}...")
    
    candidates = [
        '/exa.language_server_pb.LanguageServerService/GetChatMessage',
        '/exa.language_server_pb.LanguageServerService/GetStatus',
        '/exa.language_server_pb.LanguageServerService/GetCompletion',
        '/exa.chat_pb.ChatService/GetChatMessage',
        '/exa.chat_pb.ChatService/Chat',
        '/api/chat',
        '/v1/chat/completions',
        '/windsurf/cascade/chat',
    ]
    
    for path in candidates:
        s, body = probe_direct(HOST, path, api_key)
        print(f"  {path} → HTTP {s}: {body[:80]}")

def probe_windsurf_fedstart(api_key):
    """测试 windsurf.fedstart.com/_route/api_server"""
    HOST = 'windsurf.fedstart.com'
    print(f"\n[ROUTE] 测试 {HOST}/_route/api_server ...")
    ctx = ssl.create_default_context()
    try:
        conn = http.client.HTTPSConnection(HOST, 443, timeout=10, context=ctx)
        conn.request('GET', '/_route/api_server', headers={
            'Authorization': f'Bearer {api_key}'
        })
        resp = conn.getresponse()
        body = resp.read(500)
        print(f"  HTTP {resp.status}: {body}")
    except Exception as e:
        print(f"  error: {e}")

if __name__ == '__main__':
    api_key = get_api_key()
    print(f"API key: {api_key[:25]}...")
    
    # 1. 从 JS 找服务路径
    type_names = scan_js_service_paths()
    
    # 2. 找本地 LSP 端口
    find_local_lsp_ports()
    
    # 3. 直连 inference 测试
    probe_inference_paths(api_key)
    
    # 4. 测试路由发现
    probe_windsurf_fedstart(api_key)
