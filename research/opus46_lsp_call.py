"""
opus46_lsp_call.py — 直接调用本地 Windsurf LSP，绕开所有前端
关键发现:
  - 本地 extension server 端口: 57400 (PID 31872) / 64956 (PID 54108)
  - CSRF header: x-codeium-csrf-token
  - CSRF tokens 已通过进程内存读取
  - 服务路径: /exa.language_server_pb.LanguageServerService/GetChatMessage

用法:
  python opus46_lsp_call.py              # 探测所有可用路由
  python opus46_lsp_call.py --chat       # 交互式对话
  python opus46_lsp_call.py "你的问题"   # 单次对话
"""
import sys, os, struct, http.client, socket, json, sqlite3, re, subprocess

DB_PATH  = r"C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb"
MODEL_ID = "claude-opus-4-6"

# ─── 实时获取 CSRF token ─────────────────────────────────────────────────────
import ctypes, ctypes.wintypes

k32 = ctypes.windll.kernel32
nt  = ctypes.windll.ntdll

def _read_mem(h, addr, size):
    buf  = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t(0)
    ok   = k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(read))
    return buf.raw[:read.value] if ok else None

def get_process_env(pid):
    h = k32.OpenProcess(0x0010 | 0x0400, False, pid)
    if not h:
        return {}
    try:
        pbi = ctypes.create_string_buffer(48)
        nt.NtQueryInformationProcess(h, 0, pbi, 48, None)
        peb_addr   = struct.unpack_from('Q', pbi, 8)[0]
        peb        = _read_mem(h, peb_addr, 0x400)
        if not peb: return {}
        pp_addr    = struct.unpack_from('Q', peb, 0x20)[0]
        params     = _read_mem(h, pp_addr, 0x500)
        if not params: return {}
        env_addr   = struct.unpack_from('Q', params, 0x80)[0]
        env_size   = min(struct.unpack_from('Q', params, 0x3F0)[0], 65536)
        env_block  = _read_mem(h, env_addr, env_size or 32768)
        if not env_block: return {}
        env_str    = env_block.decode('utf-16-le', errors='replace')
        result     = {}
        for entry in env_str.split('\x00'):
            if '=' in entry:
                k2, _, v2 = entry.partition('=')
                if k2.strip():
                    result[k2] = v2
        return result
    finally:
        k32.CloseHandle(h)

def find_ls_instances():
    """返回 [(port, csrf_token), ...] 所有活跃 LSP 实例"""
    try:
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             'Get-Process -Name language_server_windows_x64 -EA SilentlyContinue | Select-Object -ExpandProperty Id'],
            capture_output=True, text=True, timeout=10
        )
        pids = [int(x) for x in re.findall(r'\d+', r.stdout)]
    except:
        pids = [31872, 54108]
    
    instances = []
    for pid in pids:
        try:
            env    = get_process_env(pid)
            csrf   = env.get('WINDSURF_CSRF_TOKEN', '')
            if not csrf:
                continue
            # 从 cmdline 找 extension_server_port
            r2 = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 f'(Get-CimInstance Win32_Process -Filter "ProcessId={pid}").CommandLine'],
                capture_output=True, text=True, timeout=10
            )
            m = re.search(r'--extension_server_port\s+(\d+)', r2.stdout)
            port = int(m.group(1)) if m else 0
            if port:
                instances.append((port, csrf, pid))
                print(f"  PID {pid}: port={port} csrf={csrf}")
        except Exception as e:
            print(f"  PID {pid} error: {e}")
    return instances

# ─── Proto helpers ────────────────────────────────────────────────────────────
def varint(n):
    out = []
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80); n >>= 7
    out.append(n & 0x7F)
    return bytes(out)

def f_str(no, s):
    b = s.encode() if isinstance(s, str) else s
    return varint((no << 3)|2) + varint(len(b)) + b

def f_msg(no, m):
    return varint((no << 3)|2) + varint(len(m)) + m

def f_int(no, n):
    return varint((no << 3)|0) + varint(n)

def connect_frame(data):
    return b'\x00' + struct.pack('>I', len(data)) + data

# ─── HTTP 请求 ────────────────────────────────────────────────────────────────
def lsp_post(port, csrf, path, body_bytes, timeout=30):
    headers = {
        'Content-Type':             'application/connect+proto',
        'Accept':                   'application/connect+proto',
        'Connect-Protocol-Version': '1',
        'x-codeium-csrf-token':     csrf,
    }
    framed = connect_frame(body_bytes)
    conn   = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    conn.request('POST', path, framed, headers)
    r    = conn.getresponse()
    body = r.read(4096)
    return r.status, dict(r.headers), body

def get_api_key():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    row  = cur.fetchone(); conn.close()
    return json.loads(row[0]).get('apiKey', '')

# ─── 探测所有路由 ─────────────────────────────────────────────────────────────
def probe_routes(port, csrf):
    api_key = get_api_key()
    print(f"\n[probe] port={port} csrf={csrf[:8]}...")
    
    paths = [
        '/exa.language_server_pb.LanguageServerService/GetChatMessage',
        '/exa.language_server_pb.LanguageServerService/GetStatus',
        '/exa.language_server_pb.LanguageServerService/GetCompletions',
        '/exa.extension_server_pb.ExtensionServerService/GetStatus',
        '/exa.extension_server_pb.ExtensionServerService/GetChatMessage',
        '/windsurf/cascade/GetChatMessage',
    ]
    
    # 最小 proto body (field1=model, field2=prompt)
    min_body = f_str(1, MODEL_ID) + f_str(2, 'Say OK')
    
    for path in paths:
        try:
            s, hdrs, body = lsp_post(port, csrf, path, min_body, timeout=5)
            grpc_st = hdrs.get('connect-error-detail', hdrs.get('grpc-status', ''))
            print(f"  {path}")
            print(f"    HTTP {s} | body={body[:120]}")
        except Exception as e:
            print(f"  {path} → error: {e}")

# ─── 构建完整的 GetChatMessageRequest ────────────────────────────────────────
def build_chat_request(message, model=MODEL_ID, api_key=''):
    """
    GetChatMessageRequest proto 字段 (推测 + 逆向):
      field 1: metadata (message) — RequestMetadata
      field 2: editor_info (message) — EditorInfo  
      field 3: prompt / text (string)
      ...多种布局，逐一尝试
    """
    # Layout A: 简单 field1=model, field2=prompt
    layoutA = f_str(1, model) + f_str(2, message)
    
    # Layout B: RequestMetadata(field1) + model(field3) + messages(field5)
    meta = f_str(1, api_key[:40] if api_key else '') + f_str(2, 'windsurf')
    msg_inner = f_str(1, 'user') + f_str(2, message)
    layoutB = f_msg(1, meta) + f_str(3, model) + f_msg(5, msg_inner)
    
    # Layout C: model(field1) + system(field2) + user_msg(field3)
    layoutC = f_str(1, model) + f_str(3, message)
    
    return [layoutA, layoutB, layoutC]

def call_chat(port, csrf, message, model=MODEL_ID):
    """发送一条对话消息，返回响应"""
    api_key   = get_api_key()
    path      = '/exa.language_server_pb.LanguageServerService/GetChatMessage'
    layouts   = build_chat_request(message, model, api_key)
    
    for i, body in enumerate(layouts):
        try:
            s, hdrs, resp = lsp_post(port, csrf, path, body, timeout=20)
            print(f"  layout {i}: HTTP {s}, {len(resp)} bytes")
            if s == 200:
                return s, resp
            if s != 400:  # 400 = wrong proto format, keep trying
                return s, resp
        except Exception as e:
            print(f"  layout {i}: error {e}")
    return 0, b''

# ─── 主函数 ───────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 60)
    print("opus46 LSP Direct Call")
    print("=" * 60)
    
    # 获取所有 LSP 实例
    print("\n[init] 发现 LSP 实例...")
    instances = find_ls_instances()
    
    if not instances:
        print("[FAIL] 未找到活跃 LSP 实例")
        sys.exit(1)
    
    # 使用第一个实例
    port, csrf, pid = instances[0]
    print(f"\n[using] PID={pid} port={port} csrf={csrf}")
    
    if len(sys.argv) > 1 and sys.argv[1] not in ('--chat', '--probe'):
        # 单次对话
        msg = ' '.join(sys.argv[1:])
        print(f"\n[chat] → {MODEL_ID}: {msg[:50]}")
        s, body = call_chat(port, csrf, msg)
        print(f"Response: HTTP {s}")
        print(body[:500])
    
    elif '--chat' in sys.argv:
        # 交互式对话
        print(f"\n[interactive] 直连 {MODEL_ID} 通过本地 LSP")
        print("输入消息，Ctrl+C 退出\n")
        while True:
            try:
                msg = input("You: ").strip()
                if not msg: continue
                s, body = call_chat(port, csrf, msg)
                print(f"AI [{MODEL_ID}]: HTTP={s}, {len(body)}B → {body[:200]}\n")
            except KeyboardInterrupt:
                break
    
    else:
        # 默认: 探测所有路由
        probe_routes(port, csrf)
        
        # 然后测试一次真实对话
        print(f"\n[test] 发送测试消息到 {MODEL_ID}...")
        s, body = call_chat(port, csrf, "Reply with exactly: OPUS46_WORKING")
        print(f"\nResult: HTTP {s}")
        print(f"Body: {body[:500]}")
        
        if s == 200:
            print("\n✅ claude-opus-4-6 直接调用成功！")
        else:
            print(f"\n⚠ HTTP {s} — 需要调整请求格式")
            # 为诊断打印所有响应头
            print("Routes probed — see above for working paths")
