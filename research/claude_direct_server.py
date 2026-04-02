"""
claude_direct_server.py — 直连 server.codeium.com，彻底绕过本地 LS

彻底消除三大问题：
  ✗ CSRF token     → 不需要（直连不走本地代理）
  ✗ LS 端口检测    → 不需要（直连远端）
  ✗ WAM 轮换等待   → Key Vault 缓存，找到即用

协议：gRPC-Web + 二进制 protobuf → HTTPS server.codeium.com:443

用法：
  python claude_direct_server.py "你的问题"
  python claude_direct_server.py --model claude-opus-4-6 "问题"
  python claude_direct_server.py          # 交互模式
"""

import sys, os, io, json, struct, re, time, sqlite3, requests, grpc

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ── 常量 ──────────────────────────────────────────────────────────────────
SERVER   = "https://server.codeium.com"
SVC      = "/exa.language_server_pb.LanguageServerService"
DB_PATH    = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
AUTH_FILES = [
    r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\windsurf-auth.json',
    r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\cascade-auth.json',
]
VAULT      = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\claude_key.vault'
DEFAULT_MODEL = "claude-opus-4-6"

# gRPC channel (lazy-init)
_channel = None

def _get_channel():
    global _channel
    if _channel is None:
        _channel = grpc.secure_channel(
            'server.codeium.com:443',
            grpc.ssl_channel_credentials()
        )
    return _channel

# ── 二进制 protobuf 编码 ───────────────────────────────────────────────────
def _varint(n):
    b = bytearray()
    while True:
        bits = n & 0x7F; n >>= 7
        b.append(bits | (0x80 if n else 0))
        if not n: break
    return bytes(b)

def pb_str(f, s):
    e = s.encode('utf-8')
    return _varint((f << 3) | 2) + _varint(len(e)) + e

def pb_msg(f, data):
    return _varint((f << 3) | 2) + _varint(len(data)) + data

def pb_int(f, v):
    return _varint((f << 3) | 0) + _varint(v)

def pb_bool(f, v):
    return pb_int(f, 1 if v else 0)

# ── 二进制 protobuf 解码（提取所有字符串） ────────────────────────────────
def _pb_strings(data, depth=0):
    """递归提取 binary proto 中所有 UTF-8 字符串"""
    if depth > 20: return []
    strings = []; i = 0
    while i < len(data):
        try:
            tag = 0; shift = 0
            while i < len(data):
                b = data[i]; i += 1
                tag |= (b & 0x7F) << shift; shift += 7
                if not (b & 0x80): break
            if tag == 0: break
            wt = tag & 7
            if wt == 0:
                while i < len(data) and (data[i] & 0x80): i += 1
                i += 1
            elif wt == 2:
                ln = 0; shift = 0
                while i < len(data):
                    b = data[i]; i += 1
                    ln |= (b & 0x7F) << shift; shift += 7
                    if not (b & 0x80): break
                if i + ln <= len(data):
                    chunk = data[i:i+ln]; i += ln
                    try:
                        s = chunk.decode('utf-8')
                        if 4 < len(s) < 8000: strings.append(s)
                    except: pass
                    strings += _pb_strings(chunk, depth+1)
                else: break
            elif wt == 5: i += 4
            elif wt == 1: i += 8
            else: break
        except: break
    return strings

# ── Cascade 请求编码 ──────────────────────────────────────────────────────
def _meta(api_key):
    return (pb_str(1,  "Windsurf") +
            pb_str(2,  "1.108.2") +
            pb_str(3,  "3.14.2") +
            pb_str(4,  api_key) +
            pb_str(14, "https://server.codeium.com"))

def enc_init(key):
    return pb_msg(1, _meta(key)) + pb_bool(3, True)      # workspace_trusted = field 3

def enc_trust(key):
    return pb_msg(1, _meta(key)) + pb_bool(2, True)      # workspace_trusted = field 2

def enc_start(key):
    return pb_msg(1, _meta(key)) + pb_int(2, 1)          # source = USER(1) = field 2

def enc_send(key, cid, text, model):
    text_item    = pb_str(1, text)                        # TextItem.text = field 1
    planner_cfg  = pb_str(35, model)                      # requested_model_uid = field 35
    cascade_cfg  = pb_msg(1, planner_cfg)                 # CascadeConfig.planner_config = field 1
    return (pb_msg(1, _meta(key)) +
            pb_str(2, cid) +                              # cascade_id = field 2
            pb_msg(3, text_item) +                        # items = field 3
            pb_msg(5, cascade_cfg))                       # cascade_config = field 5

def enc_stream(cid):
    return pb_int(1, 1) + pb_str(2, cid)                 # protocol_version=1, id=cascadeId

# ── native gRPC 传输 (grpcio, HTTP/2) ───────────────────────────────────
def _call(method, body, api_key='', timeout=10):
    """Unary gRPC call, returns (grpc_status_code, raw_bytes_response)"""
    ch  = _get_channel()
    rpc = ch.unary_unary(
        f"{SVC}/{method}",
        request_serializer  = lambda x: x,
        response_deserializer = lambda x: x,
    )
    meta = [('authorization', f'Bearer {api_key}')] if api_key else []
    try:
        resp = rpc(body, timeout=timeout, metadata=meta)
        return 0, resp
    except grpc.RpcError as e:
        code = e.code().value[0] if hasattr(e.code(), 'value') else -1
        return code, b''

def _call_stream(method, body, api_key='', timeout=35):
    """Server-streaming gRPC call, yields raw bytes chunks"""
    ch  = _get_channel()
    rpc = ch.unary_stream(
        f"{SVC}/{method}",
        request_serializer  = lambda x: x,
        response_deserializer = lambda x: x,
    )
    meta = [('authorization', f'Bearer {api_key}')] if api_key else []
    try:
        for chunk in rpc(body, timeout=timeout, metadata=meta):
            yield chunk
    except grpc.RpcError:
        pass

# ── 认证 key 读取 ─────────────────────────────────────────────────────────────────
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)

def get_claude_key(verbose=False, **_):
    """优先从 windsurf-auth.json / cascade-auth.json 读取长式 auth key，
    这是用户个人的 Windsurf API key，直接对 server.codeium.com 有效。"""
    for fp in AUTH_FILES:
        try:
            d = json.load(open(fp))
            key = d.get('api_key') or d.get('authToken') or d.get('token', '')
            if key and len(key) > 40:   # long key (not short WAM)
                if verbose: print(f"[Auth] 从 {fp} 读取 key: {key[:30]}...", file=sys.stderr)
                return key
        except: pass
    # Fallback: WAM key from state.vscdb
    try:
        con = sqlite3.connect(DB_PATH)
        v   = con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        con.close()
        k = json.loads(v[0]).get('apiKey', '') if v else ''
        if k:
            if verbose: print(f"[Auth] 备用 WAM key: {k[:25]}...", file=sys.stderr)
            return k
    except: pass
    return ''

# ── 响应过滤 ──────────────────────────────────────────────────────────────
_NOISE = frozenset([
    'You are Cascade', 'The USER is interacting', 'communication_style',
    'tool_calling', 'making_code_changes', 'Before each tool call',
    'citation_guidelines', 'EXTREMELY IMPORTANT', 'No MEMORIES',
    'mcp_servers', 'read_file', 'run_command', 'grep_search',
    'write_to_file', 'additionalProperties', 'CodeContent',
    'CommandLine', 'SearchPath', 'CORTEX_', 'CASCADE_',
    'CHAT_MESSAGE_SOURCE', 'SECTION_OVERRIDE', 'REPLACE_TOOL',
    'kubectl', 'terraform', 'user_rules', 'ephemeral_message',
])

def _is_real_response(s, question):
    if len(s) < 6 or len(s) > 4000: return False
    if question[:30] in s: return False
    if any(n in s for n in _NOISE): return False
    return True

# ── 主 chat 函数 ──────────────────────────────────────────────────────────
def chat(message, model=DEFAULT_MODEL, verbose=False):
    """
    直连 server.codeium.com，返回 AI 响应。
    不需要本地 LS、不需要 CSRF、不需要端口检测。
    """
    # 1. 获取 Claude key
    key = get_claude_key(verbose=verbose)
    if not key:
        return "[ERROR] 未找到有 Claude 权限的 WAM key（120s 超时）"

    if verbose:
        print(f"[Direct] Key={key[:25]}... Model={model}", file=sys.stderr)

    # 2. 初始化 cascade
    try:
        _call("InitializeCascadePanelState", enc_init(key), key)
        _call("UpdateWorkspaceTrust",        enc_trust(key), key)
    except Exception as e:
        return f"[ERROR] 初始化失败: {e}"

    # 3. 启动 cascade session
    try:
        sc, resp = _call("StartCascade", enc_start(key), key)
        cid = None
        for s in _pb_strings(resp):
            if UUID_RE.match(s): cid = s; break
        if not cid:
            return f"[ERROR] StartCascade 未返回 cascadeId (sc={sc}, resp={resp[:30].hex()})"
    except Exception as e:
        return f"[ERROR] StartCascade 异常: {e}"

    if verbose:
        print(f"[Direct] cascadeId={cid}", file=sys.stderr)

    # 4. 发送消息
    try:
        _call("SendUserCascadeMessage", enc_send(key, cid, message, model), key)
    except Exception as e:
        return f"[ERROR] SendMessage 异常: {e}"

    # 5. 流式读取响应
    candidates = []; denied = False
    try:
        t0 = time.time()
        for chunk in _call_stream("StreamCascadeReactiveUpdates", enc_stream(cid), key, timeout=32):
            for s in _pb_strings(chunk):
                if 'permission_denied' in s.lower():
                    denied = True
                elif _is_real_response(s, message):
                    candidates.append(s)
            if denied or time.time()-t0 > 30: break
    except Exception as e:
        if verbose: print(f"[Direct] stream error: {e}", file=sys.stderr)

    if denied and not candidates:
        try: os.remove(VAULT)
        except: pass
        return "[RETRY] Claude key 权限已撤销，已清除缓存，请重新运行"

    if candidates:
        # deduplicate while preserving order
        seen_c = set(); uniq = []
        for s in candidates:
            key_ = s[:60]
            if key_ not in seen_c:
                seen_c.add(key_); uniq.append(s)
        return '\n'.join(uniq[:6])

    return "[No response — 请重试]"

# ── CLI ───────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    model = DEFAULT_MODEL
    args  = sys.argv[1:]
    if '--model' in args:
        i = args.index('--model')
        if i+1 < len(args): model = args[i+1]
        args = args[:i] + args[i+2:]

    print(f"Claude Direct Server Client | Model: {model}")
    print(f"Target: {SERVER} (no CSRF / no local LS)\n")

    if args:
        q = ' '.join(args)
        print(f"Q: {q}\n")
        ans = chat(q, model=model, verbose=True)
        print(f"\nA: {ans}")
    else:
        print("交互模式（exit 退出）\n")
        while True:
            try: q = input("You: ").strip()
            except (EOFError, KeyboardInterrupt): break
            if not q or q.lower() in ('exit','quit','q'): break
            print("AI: ...", end='\r')
            ans = chat(q, model=model, verbose=True)
            print(f"AI: {ans}\n")
