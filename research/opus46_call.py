"""
opus46_call.py — claude-opus-4-6 后端直接调用 (最终版)
已知完整 proto 结构:
  metadata.ideName           = "windsurf"
  metadata.ideVersion        = "1.9577.43"
  metadata.extensionVersion  = required
  metadata.apiKey            = api_key
  chatMessages[].messageId   = required string
  chatMessages[].role        = 1 (USER)
  chatMessages[].content     = string

用法:
  python opus46_call.py "你的问题"
  python opus46_call.py --chat
"""
import struct, http.client, json, sqlite3, sys, uuid, subprocess, re, ctypes

DB_PATH = r"C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb"
MODEL   = "claude-opus-4-6"

# ─── Auth ─────────────────────────────────────────────────────────────────────
def get_api_key():
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    row = cur.fetchone(); conn.close()
    return json.loads(row[0]).get('apiKey', '')

# ─── CSRF token from process env ─────────────────────────────────────────────
k32 = ctypes.windll.kernel32; nt = ctypes.windll.ntdll

def _read_mem(h, addr, size):
    buf = ctypes.create_string_buffer(size); read = ctypes.c_size_t(0)
    ok = k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(read))
    return buf.raw[:read.value] if ok else None

def get_process_env(pid):
    h = k32.OpenProcess(0x0010|0x0400, False, pid)
    if not h: return {}
    try:
        import struct as S
        pbi = ctypes.create_string_buffer(48)
        nt.NtQueryInformationProcess(h, 0, pbi, 48, None)
        peb_addr = S.unpack_from('Q', pbi, 8)[0]
        peb = _read_mem(h, peb_addr, 0x400)
        if not peb: return {}
        pp_addr = S.unpack_from('Q', peb, 0x20)[0]
        params = _read_mem(h, pp_addr, 0x500)
        if not params: return {}
        env_addr = S.unpack_from('Q', params, 0x80)[0]
        env_size = min(S.unpack_from('Q', params, 0x3F0)[0], 65536)
        env_block = _read_mem(h, env_addr, env_size or 32768)
        if not env_block: return {}
        result = {}
        for entry in env_block.decode('utf-16-le', errors='replace').split('\x00'):
            if '=' in entry:
                k2, _, v2 = entry.partition('=')
                if k2.strip(): result[k2] = v2
        return result
    finally:
        k32.CloseHandle(h)

def find_lsp(default_port=57407, default_csrf='18e67ec6-8a9b-4781-bcea-ac61a722a640'):
    """动态找 LSP 实例的实际 gRPC 端口 + CSRF token
    
    注意: extension_server_port 是 extension 监听 LS 回调的端口
          LS 自己的 gRPC 端口是通过 netstat 找到的
    """
    try:
        r = subprocess.run(
            ['powershell','-NoProfile','-Command',
             'Get-Process -Name language_server_windows_x64 -EA SilentlyContinue | Select-Object -ExpandProperty Id'],
            capture_output=True, text=True, timeout=8)
        pids = [int(x) for x in re.findall(r'\d+', r.stdout)]
    except: pids = []

    # 找每个 LS 进程实际监听的端口（via netstat）
    try:
        ns = subprocess.run(['netstat','-ano'], capture_output=True, timeout=8)
        ns_out = ns.stdout.decode('gbk', errors='replace')
    except: ns_out = ''

    for pid in pids:
        try:
            env = get_process_env(pid)
            csrf = env.get('WINDSURF_CSRF_TOKEN', '')
            if not csrf: continue
            # 找该 PID 的 LISTENING 端口（LS gRPC 端口）
            ls_ports = []
            for line in ns_out.splitlines():
                if 'LISTENING' in line and f' {pid}' in line:
                    m = re.search(r'127\.0\.0\.1:(\d+)', line)
                    if m:
                        port = int(m.group(1))
                        if 40000 < port < 70000:
                            ls_ports.append(port)
            # 过滤掉 extension_server_port (从 cmdline 获取)
            try:
                r2 = subprocess.run(
                    ['powershell','-NoProfile','-Command',
                     f'(Get-CimInstance Win32_Process -Filter "ProcessId={pid}").CommandLine'],
                    capture_output=True, text=True, timeout=8)
                ext_m = re.search(r'--extension_server_port\s+(\d+)', r2.stdout)
                ext_port = int(ext_m.group(1)) if ext_m else 0
            except: ext_port = 0
            # LS gRPC 端口 = listening ports EXCEPT extension_server_port
            grpc_ports = [p for p in ls_ports if p != ext_port]
            if grpc_ports:
                return grpc_ports[0], csrf
            elif ls_ports:
                return ls_ports[0], csrf
        except: pass
    return default_port, default_csrf

# ─── Connect-RPC JSON ─────────────────────────────────────────────────────────
def frame_json(d):
    b = json.dumps(d).encode('utf-8')
    return b'\x00' + struct.pack('>I', len(b)) + b

def post(port, csrf, payload, timeout=60):
    PATH = '/exa.language_server_pb.LanguageServerService/GetChatMessage'
    h = {'Content-Type':'application/connect+json',
         'Accept':'application/connect+json',
         'Connect-Protocol-Version':'1',
         'x-codeium-csrf-token': csrf}
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    conn.request('POST', PATH, frame_json(payload), h)
    r = conn.getresponse()
    # Read streaming response chunks
    chunks = []
    while True:
        flag_byte = r.read(1)
        if not flag_byte: break
        flag = flag_byte[0]
        length_bytes = r.read(4)
        if len(length_bytes) < 4: break
        length = struct.unpack('>I', length_bytes)[0]
        if length > 10_000_000: break  # sanity check
        chunk_data = r.read(length)
        chunks.append((flag, chunk_data))
        if flag == 2: break  # end-stream
    return r.status, chunks

def decode_chunks(chunks):
    messages = []
    for flag, data in chunks:
        try:
            obj = json.loads(data)
            messages.append((flag, obj))
        except:
            messages.append((flag, data))
    return messages

# ─── Build request ────────────────────────────────────────────────────────────
def build_request(messages, model=MODEL, api_key=''):
    """
    messages: list of {"role": "user"/"assistant", "content": str}
    """
    role_map = {"user": 1, "USER": 1, "assistant": 2, "ASSISTANT": 2}
    chat_msgs = []
    for i, m in enumerate(messages):
        role = m.get("role", "user")
        chat_msgs.append({
            "messageId": str(uuid.uuid4()),
            "role": role_map.get(role, 1),
            "content": m.get("content", ""),
        })
    return {
        "metadata": {
            "ideName": "windsurf",
            "ideVersion": "1.9577.43",
            "extensionVersion": "1.9577.43",
            "apiKey": api_key,
        },
        "chatMessages": chat_msgs,
        "model": model,
    }

def extract_text(messages_decoded):
    """从解码的响应提取文本内容"""
    text_parts = []
    for flag, obj in messages_decoded:
        if isinstance(obj, dict):
            if 'error' in obj:
                return None, obj['error']
            # Try to extract text from various response formats
            for key in ['text', 'content', 'message', 'response', 'delta']:
                if key in obj:
                    text_parts.append(str(obj[key]))
            # Try nested
            if 'choices' in obj:
                for c in obj.get('choices', []):
                    if isinstance(c, dict):
                        d = c.get('delta', c.get('message', {}))
                        if isinstance(d, dict):
                            text_parts.append(d.get('content', ''))
            # Print full obj for discovery
            if not text_parts:
                text_parts.append(json.dumps(obj)[:200])
    return ' '.join(text_parts).strip() or None, None

# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    api_key = get_api_key()
    port, csrf = find_lsp()
    print(f"LSP port={port} csrf={csrf[:8]}... api={api_key[:15]}...\n")

    args = sys.argv[1:]

    if '--chat' in args:
        print(f"Interactive chat → {MODEL}")
        print("Type message, Ctrl+C to exit\n")
        history = []
        while True:
            try:
                msg = input("You: ").strip()
                if not msg: continue
                history.append({"role": "user", "content": msg})
                req = build_request(history, MODEL, api_key)
                s, chunks = post(port, csrf, req)
                decoded = decode_chunks(chunks)
                text, err = extract_text(decoded)
                if err:
                    print(f"Error: {err}")
                else:
                    print(f"AI: {text}")
                    history.append({"role": "assistant", "content": text or ""})
            except KeyboardInterrupt:
                break
    else:
        # Single message
        msg = ' '.join(args) if args else "Reply with exactly: OPUS46_DIRECT_WORKS"
        print(f"→ {MODEL}: {msg[:60]}")
        req = build_request([{"role": "user", "content": msg}], MODEL, api_key)

        # Show request for debugging
        print(f"Request: {json.dumps(req, ensure_ascii=False)[:300]}\n")

        s, chunks = post(port, csrf, req, timeout=60)
        print(f"HTTP {s}, {len(chunks)} chunks")
        decoded = decode_chunks(chunks)

        text, err = extract_text(decoded)
        if err:
            code = err.get('code', '?')
            msg_err = err.get('message', '')
            print(f"\nError [{code}]: {msg_err[:500]}")
            if code == 'invalid_argument':
                print("\n[DEBUG] Full response chunks:")
                for flag, obj in decoded:
                    print(f"  flag={flag}: {obj}")
        else:
            print(f"\nResponse: {text}")
            if text and 'OPUS46' in text.upper():
                print("\n✅ claude-opus-4-6 直接调用成功！")
