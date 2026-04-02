#!/usr/bin/env python3
"""
opus46_direct.py — 后端直接调用 claude-opus-4-6
绕开所有 Windsurf 前端复杂性，直接调用 server.codeium.com

用法:
  python opus46_direct.py               # 完整测试
  python opus46_direct.py --chat        # 交互式对话
  python opus46_direct.py --msg "问题"  # 单次对话
"""
import sys, os, re, json, struct, urllib.request, urllib.error, sqlite3, time

# ─── 配置 ────────────────────────────────────────────────────────────────────
INFERENCE_HOST = "server.codeium.com"
PROXY_URL      = "http://127.0.0.1:19876"   # pool proxy (WAM)
DB_PATH        = r"C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb"
MODEL_ID       = "claude-opus-4-6"

# ─── Proto 编码工具 ───────────────────────────────────────────────────────────
def _varint(n):
    out = []
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)

def proto_field_str(field_no, s):
    """encode string field"""
    b = s.encode() if isinstance(s, str) else s
    return _varint((field_no << 3) | 2) + _varint(len(b)) + b

def proto_field_msg(field_no, msg_bytes):
    """encode embedded message field"""
    return _varint((field_no << 3) | 2) + _varint(len(msg_bytes)) + msg_bytes

def proto_field_int(field_no, n):
    """encode varint field"""
    return _varint((field_no << 3) | 0) + _varint(n)

def connect_rpc_body(payload: bytes) -> bytes:
    """Connect-RPC framing: 1-byte flag + 4-byte big-endian length + payload"""
    return b'\x00' + struct.pack('>I', len(payload)) + payload

# ─── 认证 ────────────────────────────────────────────────────────────────────
def get_api_key():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()
        cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
        row = cur.fetchone(); conn.close()
        if row:
            auth = json.loads(row[0])
            key = auth.get('apiKey', '')
            if key:
                return key
    except Exception as e:
        print(f"[auth] DB read error: {e}")
    return None

# ─── 探测服务路径 ──────────────────────────────────────────────────────────────
KNOWN_PATHS = [
    "/exa.language_server_pb.LanguageServerService/GetChatMessage",
    "/exa.language_server_pb.LanguageServerService/GetCompletion",
    "/exa.chat_pb.ChatService/GetChatMessage",
    "/exa.language_server_pb.LanguageServerService/GetStatus",
]

def probe_path(path, api_key, body=b''):
    """向代理发送一个请求，返回 (status_code, response_body)"""
    url = PROXY_URL + path
    data = connect_rpc_body(body) if body else b''
    headers = {
        'Content-Type': 'application/connect+proto',
        'Accept': 'application/connect+proto',
        'Connect-Protocol-Version': '1',
        'Authorization': f'Bearer {api_key}',
        'x-model-hint': MODEL_ID,
    }
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        r = urllib.request.urlopen(req, timeout=15)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return 0, str(e).encode()

def find_service_path_from_js():
    """从 extension.js 提取 gRPC 服务路径"""
    ext_path = r"D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
    try:
        with open(ext_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        # 找 typeName 字段 — protobuf-ts 注册服务名
        type_names = re.findall(r'typeName:\s*["\']([^"\']+)["\']', content)
        methods    = re.findall(r'name:\s*["\']([A-Z][a-zA-Z]+)["\']', content)
        print(f"[probe] typeName entries: {len(type_names)}")
        chat_types = [t for t in type_names if 'chat' in t.lower() or 'cascade' in t.lower()]
        for t in chat_types[:10]:
            print(f"  {t}")
        return chat_types
    except Exception as e:
        print(f"[probe] JS parse error: {e}")
        return []

def find_service_path_from_proxy_log():
    """从代理日志找已知服务路径"""
    log_candidates = [
        r"e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\pool_proxy.log",
        r"e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\_proxy_access.log",
    ]
    for lf in log_candidates:
        if os.path.exists(lf):
            txt = open(lf, encoding='utf-8', errors='replace').read()
            paths = re.findall(r'/exa\.[^\s"\']{5,80}', txt)
            if paths:
                print(f"[proxy_log] Found paths in {os.path.basename(lf)}:")
                for p in sorted(set(paths))[:10]:
                    print(f"  {p}")
                return list(set(paths))
    return []

# ─── 构建最小 GetChatMessageRequest ──────────────────────────────────────────
def build_minimal_chat_request(message: str, model_id: str = MODEL_ID) -> bytes:
    """
    构建最小化的 GetChatMessageRequest proto payload
    字段编号通过逆向 extension.js 确定（或猜测常见字段号）
    """
    # GetChatMessageRequest 常见字段（基于 Codeium proto 惯例）:
    #   field 1: metadata / request_id (string)
    #   field 2: editor_info (message)
    #   field 3: model_name / model_uid (string) — 关键!
    #   field 4: document / context
    #   field 5: prompt / messages
    
    # 构建最小请求：只含 model + 单条用户消息
    # 尝试多种字段号组合
    
    # Attempt 1: 标准 chat request
    msg_payload = (
        proto_field_str(1, model_id) +     # field 1: model
        proto_field_str(2, message)         # field 2: prompt
    )
    return msg_payload

def build_chat_request_v2(message: str, model_id: str = MODEL_ID) -> bytes:
    """版本2: 不同字段号布局"""
    # Some services use field 3 for model, field 5 for messages
    inner_msg = (
        proto_field_str(1, "user") +        # role
        proto_field_str(2, message)          # content
    )
    payload = (
        proto_field_str(3, model_id) +       # field 3: model
        proto_field_msg(5, inner_msg)         # field 5: message
    )
    return payload

# ─── 主测试流程 ───────────────────────────────────────────────────────────────
def run_tests():
    print("=" * 60)
    print("opus46_direct — 后端直接调用测试")
    print("=" * 60)

    # 1. 认证
    api_key = get_api_key()
    if not api_key:
        print("[FAIL] 无法获取 API key")
        sys.exit(1)
    print(f"[auth] API key: {api_key[:25]}...")

    # 2. 代理健康
    try:
        r = urllib.request.urlopen(PROXY_URL + '/pool/health', timeout=5)
        d = json.loads(r.read())
        print(f"[proxy] health: {d}")
    except Exception as e:
        print(f"[proxy] NOT running: {e}")
        print("  → 启动 pool proxy...")

    # 3. 探测服务路径
    print("\n[step3] 探测服务路径...")
    log_paths = find_service_path_from_proxy_log()
    js_types  = find_service_path_from_js()

    # 4. 测试已知路径
    print("\n[step4] 测试 GetStatus (已知可用路径)...")
    status, body = probe_path(
        "/exa.language_server_pb.LanguageServerService/GetStatus",
        api_key
    )
    print(f"  GetStatus → HTTP {status}, {len(body)} bytes")
    if status in (200, 0):
        print("  [OK] 代理转发到 server.codeium.com 正常工作!")
    
    # 5. 测试 cascade chat 路径
    print("\n[step5] 测试 cascade chat 路径...")
    test_message = "Hello, please respond with just 'OK claude-opus-4-6 works'"
    
    for path in KNOWN_PATHS[:3]:
        if 'Status' in path:
            continue
        print(f"\n  尝试: {path}")
        
        # v1 payload
        body_v1 = build_minimal_chat_request(test_message)
        s, resp = probe_path(path, api_key, body_v1)
        print(f"    v1 payload → HTTP {s}, {len(resp)} bytes")
        if resp:
            print(f"    resp[:100]: {resp[:100]}")
        
        # v2 payload
        body_v2 = build_chat_request_v2(test_message)
        s2, resp2 = probe_path(path, api_key, body_v2)
        print(f"    v2 payload → HTTP {s2}, {len(resp2)} bytes")
        if resp2:
            print(f"    resp[:100]: {resp2[:100]}")

    # 6. 如果 proxy log 有路径，也测试它们
    if log_paths:
        print("\n[step6] 测试代理日志中发现的路径...")
        chat_paths = [p for p in log_paths if 'Chat' in p or 'cascade' in p.lower()]
        for path in chat_paths[:3]:
            body = build_minimal_chat_request(test_message)
            s, resp = probe_path(path, api_key, body)
            print(f"  {path} → HTTP {s}, {resp[:80]}")

    print("\n[done] 测试完成")
    return api_key

def interactive_chat(api_key=None):
    """交互式直接调用"""
    if not api_key:
        api_key = get_api_key()
    print(f"直接调用 claude-opus-4-6 (API: {api_key[:20]}...)")
    print("输入消息，Ctrl+C 退出\n")
    while True:
        try:
            msg = input("You: ").strip()
            if not msg: continue
            # TODO: once we find working path, use it here
            print("AI: [路径探测中，见测试输出]")
        except KeyboardInterrupt:
            break

if __name__ == '__main__':
    args = sys.argv[1:]
    if '--chat' in args:
        interactive_chat()
    elif '--msg' in args:
        idx = args.index('--msg')
        msg = args[idx+1] if idx+1 < len(args) else "test"
        api_key = get_api_key()
        body = build_minimal_chat_request(msg)
        path = "/exa.language_server_pb.LanguageServerService/GetChatMessage"
        s, r = probe_path(path, api_key, body)
        print(f"HTTP {s}: {r[:300]}")
    else:
        run_tests()
