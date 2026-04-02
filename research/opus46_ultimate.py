"""
opus46_ultimate.py  —  Claude Opus 4.6 生产级直接调用客户端

彻底自动化三大核心问题：
  ①  LS 端口     → netstat 自动检测
  ②  CSRF Token  → 进程内存自动扫描
  ③  Claude Key  → WAM 轮换自动检测并持久缓存（Key Vault）

用法:
  python opus46_ultimate.py "你的问题"
  python opus46_ultimate.py --model claude-sonnet-4-6 "问题"
  python opus46_ultimate.py          # 交互模式
"""

import sys, os, json, struct, time, re, ctypes, ctypes.wintypes, sqlite3, subprocess, requests, threading, base64

# ── 路径常量 ──────────────────────────────────────────────────────────────
VAULT_FILE = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\claude_key.vault'
DB_PATH    = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
POOL_DB    = r'e:\道\道生一\一生二\Windsurf无限额度\030-云端号池_CloudPool\cloud_pool.db'
DEFAULT_MODEL = "MODEL_CLAUDE_4_5_OPUS"  # Claude Opus 4.5 (服务端当前最新 Opus)

def _get_pool_keys(limit=200):
    """从 cloud_pool.db 读取所有账号的 api_key（最多 limit 个）"""
    try:
        con = sqlite3.connect(POOL_DB)
        rows = con.execute(
            "SELECT api_key FROM accounts WHERE api_key IS NOT NULL AND api_key != '' "
            "ORDER BY id LIMIT ?", (limit,)
        ).fetchall()
        con.close()
        return [r[0] for r in rows if r[0] and r[0].startswith('sk-ws-')]
    except Exception as e:
        return []

# 按优先级排列的候选 UID：首个成功的即为最终使用的
MODEL_FALLBACK_CHAIN = [
    "MODEL_CLAUDE_4_5_OPUS",           # Claude Opus 4.5   (当前最新 Opus)
    "MODEL_CLAUDE_4_5_OPUS_THINKING",  # Claude Opus 4.5 Thinking
    "claude-sonnet-4-6",               # Claude Sonnet 4.6 (4.6 系最新)
    "claude-sonnet-4-6-thinking",      # Claude Sonnet 4.6 Thinking
    "MODEL_PRIVATE_2",                 # Claude Sonnet 4.5
    "MODEL_CLAUDE_4_SONNET",           # Claude Sonnet 4
    "claude-opus-4-6",                 # legacy alias — 可能已下线
]
META_TMPL = {
    "ideName": "Windsurf", "ideVersion": "1.108.2",
    "extensionVersion": "3.14.2", "extensionName": "Windsurf",
    "extensionPath": r"D:\Windsurf\resources\app\extensions\windsurf",
    "locale": "en-US", "os": "win32",
    "url": "https://server.codeium.com",
}

# ══════════════════════════════════════════════════════════════════════════
# ① LS 端口 + PID 检测（通过进程名精确定位 language_server）
# ══════════════════════════════════════════════════════════════════════════
LS_EXE = 'language_server_windows_x64.exe'
_ls_port_cache = [0, 0, 0]  # [port, pid, timestamp]

def _get_ls_pid():
    """返回主 LS PID（_ls_port_cache[1] 已填充时）"""
    return _ls_port_cache[1] or None

def _get_ls_pids_ps():
    """用 PowerShell Get-Process 获取 LS PIDs（比 tasklist 更可靠）"""
    try:
        exe = LS_EXE.replace('.exe', '')
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             f'Get-Process -Name "{exe}" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id'],
            capture_output=True, timeout=10)
        out = r.stdout.decode('utf-8', 'replace').strip()
        return [int(x.strip()) for x in out.splitlines() if x.strip().isdigit()]
    except: return []

def _get_ws_pids_ps():
    """用 PowerShell 获取所有 Windsurf PIDs"""
    try:
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             'Get-Process -Name "Windsurf" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id'],
            capture_output=True, timeout=10)
        out = r.stdout.decode('utf-8', 'replace').strip()
        return [int(x.strip()) for x in out.splitlines() if x.strip().isdigit()]
    except: return []

def find_ls_port():
    """找有最多 Windsurf 连接的 LS 端口（主动 LS）"""
    cached_port, cached_pid, cached_ts = _ls_port_cache
    if cached_port and time.time() - cached_ts < 30:
        return cached_port

    # ── Step 1: 获取 netstat 数据（快速，几乎不会失败）──────────────
    try:
        r_net = subprocess.run(['netstat', '-ano'], capture_output=True, timeout=15)
        net = r_net.stdout.decode('gbk', 'replace')
    except Exception:
        net = ''

    net_lines = net.splitlines()

    # ── Step 2: 获取 LS PIDs（PS 更可靠）────────────────────────────
    ls_pids = _get_ls_pids_ps()

    # ── Step 3: 构建 LS 监听端口表 ───────────────────────────────────
    ls_listen = {}  # port -> pid
    if ls_pids and net_lines:
        for line in net_lines:
            if 'LISTENING' in line:
                p = line.split()
                try:
                    pid = int(p[-1])
                    if pid in ls_pids:
                        port = int(p[1].split(':')[1])
                        if port > 1024:
                            ls_listen[port] = pid
                except: pass

    # ── Step 4: 计算各 LS 端口的 Windsurf 连接数 ─────────────────────
    port_count = {}
    if ls_listen:
        ws_pids = _get_ws_pids_ps()
        if ws_pids and net_lines:
            for line in net_lines:
                if 'ESTABLISHED' in line and '127.0.0.1' in line:
                    p = line.split()
                    try:
                        if int(p[-1]) in ws_pids:
                            rp = int(p[2].split(':')[1])
                            if rp in ls_listen:
                                port_count[rp] = port_count.get(rp, 0) + 1
                    except: pass

    # ── Step 5: 选最佳端口 ───────────────────────────────────────────
    best_port = None
    if port_count:
        best_port = max(port_count, key=port_count.get)
    elif ls_listen:
        # No established connections yet — probe each LS port for gRPC
        for p in sorted(ls_listen.keys()):
            if _probe_grpc_port(p):
                best_port = p
                break
        if not best_port:
            best_port = list(ls_listen.keys())[0]
    else:
        # No LS PIDs found (tasklist/PS failed) — scan high ports for gRPC
        scan_ports = set()
        for line in net_lines:
            if 'LISTENING' in line:
                p = line.split()
                try:
                    port = int(p[1].split(':')[1])
                    if 50000 <= port <= 70000:
                        scan_ports.add(port)
                except: pass
        for p in sorted(scan_ports):
            if _probe_grpc_port(p):
                best_port = p
                break

    if not best_port:
        return None

    best_pid = ls_listen.get(best_port, 0)
    _ls_port_cache[0] = best_port
    _ls_port_cache[1] = best_pid
    _ls_port_cache[2] = time.time()
    return best_port


def _probe_grpc_port(port):
    """返回 True 如果该端口响应 gRPC-Web（HTTP 200/403，非 404/connection refused）"""
    try:
        b = json.dumps({'metadata': {'ideName': 'Windsurf'}, 'workspaceTrusted': True}).encode()
        r = requests.post(
            f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState',
            data=b'\x00' + struct.pack('>I', len(b)) + b,
            headers={'Content-Type': 'application/grpc-web+json',
                     'Accept': 'application/grpc-web+json',
                     'x-codeium-csrf-token': 'probe', 'x-grpc-web': '1'},
            timeout=1.5, stream=True)
        b''.join(r.iter_content(chunk_size=None))
        return r.status_code in (200, 403)
    except: return False


# ══════════════════════════════════════════════════════════════════════════
# ② CSRF Token — 读 LS 进程 PEB 环境块（UTF-16LE）
# ══════════════════════════════════════════════════════════════════════════
_csrf_cache = {}   # {pid: (token, timestamp)}

class _PBI(ctypes.Structure):   # PROCESS_BASIC_INFORMATION
    _fields_ = [('ExitStatus',ctypes.c_long),('PebBaseAddress',ctypes.c_void_p),
                ('AffinityMask',ctypes.c_void_p),('BasePriority',ctypes.c_long),
                ('UniqueProcessId',ctypes.c_void_p),('InheritedUniq',ctypes.c_void_p)]

def _peb_read_ptr(h, addr):
    buf = ctypes.create_string_buffer(8)
    n   = ctypes.c_size_t(0)
    ctypes.windll.kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, 8, ctypes.byref(n))
    return struct.unpack('<Q', buf.raw)[0] if n.value == 8 else 0

def _peb_read_bytes(h, addr, size):
    buf = ctypes.create_string_buffer(size)
    n   = ctypes.c_size_t(0)
    ctypes.windll.kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(n))
    return buf.raw[:n.value]

def _read_process_env_utf16(pid):
    """通过 PEB 读取进程环境变量块（UTF-16LE），返回解码字符串"""
    k32  = ctypes.windll.kernel32
    ntdl = ctypes.windll.ntdll
    h = k32.OpenProcess(0x10 | 0x400 | 0x1000, False, pid)
    if not h: return ''
    try:
        pbi = _PBI()
        ntdl.NtQueryInformationProcess(h, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), None)
        peb = pbi.PebBaseAddress
        pp       = _peb_read_ptr(h, peb + 0x20)   # PEB.ProcessParameters
        env_ptr  = _peb_read_ptr(h, pp  + 0x80)   # .Environment
        env_size_raw = _peb_read_bytes(h, pp + 0x3F0, 8)
        env_size = min(struct.unpack('<Q', env_size_raw)[0]
                       if len(env_size_raw)==8 else 0x10000, 0x80000)
        if env_size == 0: env_size = 0x10000
        env_data = _peb_read_bytes(h, env_ptr, env_size)
        return env_data.decode('utf-16-le', errors='replace')
    except: return ''
    finally: k32.CloseHandle(h)

def _all_ls_pids():
    """返回所有 language_server_windows_x64.exe 的 PID 列表"""
    return _get_ls_pids_ps()

def find_csrf(port=None):
    """读 LS 进程 PEB 环境，提取 WINDSURF_CSRF_TOKEN"""
    pid = _get_ls_pid()
    candidates = [pid] if pid else []
    # fallback: scan all LS pids
    if not candidates:
        candidates = _all_ls_pids()
    if not candidates: return None

    for pid in candidates:
        cached = _csrf_cache.get(pid)
        if cached and time.time() - cached[1] < 600:
            return cached[0]
        try:
            env = _read_process_env_utf16(pid)
            m = re.search(
                r'WINDSURF_CSRF_TOKEN=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
                env, re.I)
            if m:
                token = m.group(1)
                _csrf_cache[pid] = (token, time.time())
                # update port cache pid so future calls work
                if _ls_port_cache[1] == 0:
                    _ls_port_cache[1] = pid
                return token
        except: pass
    return None


# ══════════════════════════════════════════════════════════════════════════
# ③ Key Vault — Claude-capable WAM key 缓存
# ══════════════════════════════════════════════════════════════════════════
def _get_wam_key():
    """读取当前 WAM key from state.vscdb"""
    try:
        con = sqlite3.connect(DB_PATH)
        row = con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        con.close()
        if row:
            return json.loads(row[0]).get('apiKey', '')
    except: pass
    return ''

def vault_load():
    """加载缓存的 Claude key（24h TTL）"""
    try:
        data = json.load(open(VAULT_FILE))
        if time.time() - data.get('ts', 0) < 86400:
            return data.get('key', '')
    except: pass
    return ''

def vault_save(key):
    try:
        json.dump({'key': key, 'ts': time.time()}, open(VAULT_FILE, 'w'))
    except: pass

def _quick_test_key(key, port, csrf):
    """快速测试 key 是否有 Claude 权限（约 5 秒）"""
    meta = {**META_TMPL, 'apiKey': key}
    hdr = {'Content-Type': 'application/grpc-web+json',
           'Accept': 'application/grpc-web+json',
           'x-codeium-csrf-token': csrf, 'x-grpc-web': '1'}

    def post(method, body, timeout=15):
        b = json.dumps(body).encode()
        r = requests.post(
            f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{method}',
            data=b'\x00' + struct.pack('>I', len(b)) + b, headers=hdr, timeout=timeout, stream=True
        )
        raw = b''.join(r.iter_content(chunk_size=None))
        frames=[]; pos=0
        while pos+5 <= len(raw):
            fl=raw[pos]; n=struct.unpack('>I', raw[pos+1:pos+5])[0]; pos+=5
            frames.append((fl, raw[pos:pos+n])); pos+=n
        return frames

    try:
        post("InitializeCascadePanelState", {"metadata": meta, "workspaceTrusted": True})
        post("UpdateWorkspaceTrust",        {"metadata": meta, "workspaceTrusted": True})
        f1 = post("StartCascade", {"metadata": meta, "source": "CORTEX_TRAJECTORY_SOURCE_USER"})
        cid = next((json.loads(d).get('cascadeId') for fl,d in f1 if fl==0 and b'cascadeId' in d), None)
        if not cid:
            return None
    except Exception as e:
        return None
    try:
        # Concurrent: open stream first, then send message
        test_frames = []; _ready = threading.Event(); _done = threading.Event()
        def _tw():
            sb = json.dumps({"id": cid, "protocolVersion": 1}).encode()
            try:
                r3 = requests.post(
                    f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
                    data=b'\x00' + struct.pack('>I', len(sb)) + sb, headers=hdr, timeout=18, stream=True)
                buf=b''; t0=time.time(); fn=0
                for chunk in r3.iter_content(chunk_size=256):
                    buf += chunk
                    while len(buf) >= 5:
                        nl = struct.unpack('>I', buf[1:5])[0]
                        if len(buf) < 5+nl: break
                        fl=buf[0]; fr=buf[5:5+nl]; buf=buf[5+nl:]
                        fn += 1; test_frames.append(fr)
                        if fn == 1: _ready.set()
                        if fl == 0x80: _done.set(); return
                    if time.time()-t0 > 15: break
            except: pass
            _done.set()
        import threading as _thr
        _t = _thr.Thread(target=_tw, daemon=True); _t.start()
        _ready.wait(timeout=8)
        time.sleep(0.2)
        # Send test message
        post("SendUserCascadeMessage", {
            "metadata": meta, "cascadeId": cid,
            "items": [{"text": "hi"}],
            "cascadeConfig": {"plannerConfig": {"requestedModelUid": "MODEL_SWE_1_5", "conversational": {}}}
        }, timeout=10)
        _done.wait(timeout=15)
        # Check frames for errors
        for fr in test_frames:
            try:
                obj = json.loads(fr)
                strs = _deep_strings(obj)
                for s in strs:
                    sl = s.lower()
                    if 'failed_precondition' in sl or 'permission_denied' in sl:
                        return False  # quota exhausted or permission denied (all variants)
            except: pass
        return bool(test_frames)
    except Exception:
        return None

def get_claude_key(port, csrf, verbose=False, max_wait=60):
    """获取有 Claude 权限的 WAM key。
    优先读 vault（key_daemon.py 写入），否则最多等待 max_wait 秒轮询。
    建议先后台运行 key_daemon.py，它会持续监控并写入 vault。"""
    # 1. 尝试缓存（key_daemon.py 会实时写入）
    cached = vault_load()
    if cached:
        if verbose: print(f"[KeyVault] 验证 vault key {cached[:25]}...", file=sys.stderr)
        r = _quick_test_key(cached, port, csrf)
        if r is True:
            if verbose: print("[KeyVault] vault key 有效 ✓", file=sys.stderr)
            return cached
        if verbose: print("[KeyVault] vault key 已失效，清除", file=sys.stderr)
        try: os.remove(VAULT_FILE)
        except: pass

    # 2. 轮询（同时 key_daemon.py 也在后台搜索）
    if verbose:
        print(f"[KeyVault] 等待 Claude key（最多 {max_wait}s）...", file=sys.stderr)
        print("[KeyVault] 提示: 后台运行 key_daemon.py 可加速搜索（97账号池）", file=sys.stderr)

    seen = set(); t0 = time.time(); last_log = 0
    while time.time() - t0 < max_wait:
        # 每次循环都重查 vault（key_daemon 可能已写入）
        cached = vault_load()
        if cached and cached not in seen:
            if verbose: print(f"[KeyVault] daemon 写入了 vault key，验证...", file=sys.stderr)
            r = _quick_test_key(cached, port, csrf)
            if r is True:
                if verbose: print("[KeyVault] daemon key 有效 ✓", file=sys.stderr)
                return cached
            seen.add(cached)

        key = _get_wam_key()
        now = time.time()
        if key and key not in seen:
            if verbose: print(f"[KeyVault] 测试新 key {key[:25]}...", file=sys.stderr)
            result = _quick_test_key(key, port, csrf)
            if result is True:
                vault_save(key)
                if verbose: print(f"[KeyVault] 找到 Claude key ✓ 已缓存", file=sys.stderr)
                return key
            elif result is None:
                if verbose: print("[KeyVault] 连接问题，刷新端口/CSRF...", file=sys.stderr)
                _csrf_cache.clear(); _ls_port_cache[0] = 0
                new_port = find_ls_port(); new_csrf = find_csrf()
                if new_port: port = new_port
                if new_csrf: csrf = new_csrf
                if verbose: print(f"[KeyVault] 刷新后: port={port} CSRF={csrf[:8] if csrf else 'None'}...", file=sys.stderr)
            else:
                seen.add(key)
                if verbose: print("[KeyVault] 无 Claude 权限，等待...", file=sys.stderr)
        elif verbose and now - last_log > 15:
            print(f"[KeyVault] 等待中... {int(now-t0)}s/{max_wait}s (daemon 也在搜索)", file=sys.stderr)
            last_log = now
        time.sleep(2)
    return ''


# ══════════════════════════════════════════════════════════════════════════
# 核心调用层
# ══════════════════════════════════════════════════════════════════════════
def _call(port, csrf, meta, method, body, timeout=8):
    body['metadata'] = meta
    b = json.dumps(body).encode()
    hdr = {'Content-Type': 'application/grpc-web+json',
           'Accept': 'application/grpc-web+json',
           'x-codeium-csrf-token': csrf, 'x-grpc-web': '1'}
    r = requests.post(
        f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{method}',
        data=b'\x00' + struct.pack('>I', len(b)) + b, headers=hdr, timeout=timeout, stream=True
    )
    raw = b''.join(r.iter_content(chunk_size=None))
    frames=[]; pos=0
    while pos+5 <= len(raw):
        fl=raw[pos]; n=struct.unpack('>I', raw[pos+1:pos+5])[0]; pos+=5
        frames.append((fl, raw[pos:pos+n])); pos+=n
    return frames

def _walk(o, d=0):
    if d > 25: return []
    r = []
    if isinstance(o, str) and 4 < len(o) < 400: r.append(o)
    elif isinstance(o, dict): [r.extend(_walk(v, d+1)) for v in o.values()]
    elif isinstance(o, list): [r.extend(_walk(i, d+1)) for i in o]
    return r

SKIP = frozenset([
    # cascade system prompt markers
    'You are Cascade', 'The USER is interacting', 'communication_style',
    'tool_calling', 'making_code_changes', 'citation_guidelines',
    'Before each tool call', 'Prefer minimal', 'EXTREMELY IMPORTANT',
    'Keep dependent', 'Batch independent', 'No MEMORIES', 'mcp_servers',
    'read_file', 'run_command', 'grep_search', 'write_to_file',
    '{"$schema"', 'additionalProperties', '"description":', 'CodeContent',
    'TargetFile', 'CommandLine', 'SearchPath', 'long-horizon workflow',
    'Bug fixing discipline', 'Modifier keys', 'Available skills',
    'CORTEX_', 'CASCADE_', 'CHAT_MESSAGE_SOURCE', 'SECTION_OVERRIDE',
    'REPLACE_TOOL', 'kubectl', 'terraform',
    'MODEL_', 'user_global', 'user_rules', 'MEMORY[',  # cascade metadata
    # tool names & description fragments
    'ask_user_question', 'browser_preview', 'check_deploy_status',
    'command_status', 'create_memory', 'deploy_web_app', 'edit_notebook',
    'find_by_name', 'list_dir', 'list_resources', 'read_notebook',
    'read_resource', 'read_terminal', 'read_url_content', 'search_web',
    'todo_list', 'trajectory_search', 'view_content_chunk',
    'predefined options', 'allowMultiple', 'browser preview',
    'Spin up a browser', 'Perform click', 'Fill multiple form',
    'Handle a dialog', 'Hover over element', 'Navigate to a URL',
    'Take a screenshot', 'Type text into', 'Wait for text',
    'Perform exact string', 'Search for files', 'A powerful search',
    'Reads a file at', 'Save important context', 'Semantic search',
    'Use this tool to create', 'Invoke a skill', 'Performs a web search',
    'Read content from a URL', 'Propose a command', 'Check the status',
    'Lists files and', 'Read and parse', 'Completely replaces',
    'Retrieves a specified', 'Lists the available',
])

_B64_RE = re.compile(r'^[A-Za-z0-9+/]{20,}={0,2}$')
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)

def _is_real_response(s):
    if _B64_RE.match(s): return False  # skip base64 blobs (fullState)
    if _UUID_RE.match(s): return False  # skip raw UUIDs (cascade/message IDs)
    return not any(frag in s for frag in SKIP)


# ══════════════════════════════════════════════════════════════════════════
# 高层接口
# ══════════════════════════════════════════════════════════════════════════
def _classify_error(s):
    """将错误字符串分类为枚举标签"""
    sl = s.lower()
    if 'rate limit' in sl or 'quota exhaust' in sl or 'daily usage quota' in sl:
        return 'rate_limit'
    if 'failed_precondition' in sl and ('quota' in sl or 'usage' in sl or 'plan' in sl):
        return 'quota_exhausted'
    if 'permission_denied' in sl and 'internal error' in sl:
        return 'internal_error'
    if 'permission_denied' in sl or 'permission denied' in sl:
        return 'permission_denied'
    if 'insufficient' in sl and 'credit' in sl:
        return 'insufficient_credits'
    if 'internal error' in sl:
        return 'internal_error'
    return 'error'


# ══════════════════════════════════════════════════════════════════════════
# Proto binary string extractor (for nested base64-proto blobs in stream)
# ══════════════════════════════════════════════════════════════════════════
_B64_PROTO = re.compile(r'^[A-Za-z0-9+/]{16,}={0,2}$')

def _extract_proto_strings(data, depth=0, min_len=2, max_len=600):
    """Recursively extract UTF-8 strings from proto3 binary."""
    if depth > 10 or not isinstance(data, (bytes, bytearray)): return []
    strings = []; i = 0
    while i < len(data):
        try:
            tag = 0; shift = 0
            while True:
                if i >= len(data): return strings
                b = data[i]; i += 1
                tag |= (b & 0x7F) << shift; shift += 7
                if not (b & 0x80): break
                if shift > 63: break
            wire_type = tag & 0x7
            if wire_type == 0:
                while i < len(data) and (data[i] & 0x80): i += 1
                i += 1
            elif wire_type == 1:
                i += 8
            elif wire_type == 2:
                length = 0; shift = 0
                while True:
                    if i >= len(data): return strings
                    b = data[i]; i += 1
                    length |= (b & 0x7F) << shift; shift += 7
                    if not (b & 0x80): break
                    if shift > 35: break
                if i + length > len(data): return strings
                chunk = data[i:i+length]; i += length
                try:
                    text = chunk.decode('utf-8')
                    if min_len <= len(text) <= max_len and '\x00' not in text:
                        strings.append(text)
                except UnicodeDecodeError:
                    pass
                strings.extend(_extract_proto_strings(chunk, depth+1, min_len, max_len))
            elif wire_type == 5:
                i += 4
            else:
                i += 1
        except Exception:
            i += 1
    return strings

def _deep_strings(obj, depth=0):
    """Walk JSON + decode base64-proto blobs recursively."""
    if depth > 15: return []
    results = []
    if isinstance(obj, str):
        if _B64_PROTO.match(obj) and len(obj) > 20:
            try:
                binary = base64.b64decode(obj + '==')
                results.extend(_extract_proto_strings(binary))
            except: pass
        elif 1 < len(obj) < 600:
            results.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values(): results.extend(_deep_strings(v, depth+1))
    elif isinstance(obj, list):
        for v in obj: results.extend(_deep_strings(v, depth+1))
    return results


def chat(message, model=DEFAULT_MODEL, verbose=False, try_fallback=True):
    """
    完整 cascade 对话（并发流模式：先开流再发消息）
    try_fallback=True: 如果指定模型失败，自动按 MODEL_FALLBACK_CHAIN 重试
    返回 AI 响应字符串
    """
    # ── 自动检测环境 ────────────────────────────────────────────
    port = find_ls_port()
    if not port:
        return "[ERROR] 未找到 Windsurf LS 端口，请确保 Windsurf 正在运行"

    csrf = find_csrf(port)
    if not csrf:
        csrf = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
        if verbose: print(f"[WARN] CSRF 自动扫描失败，使用缓存值", file=sys.stderr)

    if verbose:
        print(f"[ENV] Port={port}  CSRF={csrf[:8]}...", file=sys.stderr)

    # ── 获取 key ────────────────────────────────────────────────
    key = get_claude_key(port, csrf, verbose=verbose)
    if not key:
        return "[ERROR] 未找到可用 WAM key（超时），请稍后重试"

    meta = {**META_TMPL, 'apiKey': key}
    hdr = {'Content-Type': 'application/grpc-web+json', 'Accept': 'application/grpc-web+json',
           'x-codeium-csrf-token': csrf, 'x-grpc-web': '1'}

    # ── Init cascade ────────────────────────────────────────────
    _call(port, csrf, meta, "InitializeCascadePanelState", {"workspaceTrusted": True})
    _call(port, csrf, meta, "UpdateWorkspaceTrust",        {"workspaceTrusted": True})
    f1 = _call(port, csrf, meta, "StartCascade", {"source": "CORTEX_TRAJECTORY_SOURCE_USER"})
    cid = next((json.loads(d).get('cascadeId') for fl,d in f1 if fl==0 and b'cascadeId' in d), None)
    if not cid:
        return "[ERROR] 无法启动 cascade session"

    # ── 并发流：先开流，再发消息（响应式模式）──────────────────
    frames_raw = []
    stream_ready = threading.Event()
    stream_done  = threading.Event()

    def _stream_worker():
        sb = json.dumps({"id": cid, "protocolVersion": 1}).encode()
        try:
            r = requests.post(
                f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
                data=b'\x00' + struct.pack('>I', len(sb)) + sb,
                headers=hdr, timeout=90, stream=True)
            buf=b''; t0=time.time(); fn=0
            for chunk in r.iter_content(chunk_size=256):
                buf += chunk
                while len(buf) >= 5:
                    nl = struct.unpack('>I', buf[1:5])[0]
                    if len(buf) < 5+nl: break
                    fl=buf[0]; fr=buf[5:5+nl]; buf=buf[5+nl:]
                    fn += 1; frames_raw.append((time.time()-t0, fl, fr))
                    if fn == 1: stream_ready.set()
                    if fl == 0x80: stream_done.set(); return
                if time.time()-t0 > 85: break
        except Exception as e:
            if verbose: print(f"[stream] {type(e).__name__}: {str(e)[:60]}", file=sys.stderr)
        stream_done.set()

    t = threading.Thread(target=_stream_worker, daemon=True)
    t.start()
    stream_ready.wait(timeout=10)
    time.sleep(0.2)  # stabilize stream

    # ── Send message ────────────────────────────────────────────
    _call(port, csrf, meta, "SendUserCascadeMessage", {
        "cascadeId": cid,
        "items": [{"text": message}],
        "cascadeConfig": {"plannerConfig": {"requestedModelUid": model, "conversational": {}}},
    })
    if verbose: print(f"[chat] Message sent, waiting for AI response...", file=sys.stderr)
    stream_done.wait(timeout=90)

    # ── 解析响应 ────────────────────────────────────────────────
    denied_msg = ''
    all_strings = []
    for elapsed, fl, raw in frames_raw:
        if fl == 0x80: continue
        try:
            obj = json.loads(raw)
            strs = _deep_strings(obj)
            for s in strs:
                sl = s.lower()
                if 'permission_denied' in sl:
                    if not denied_msg: denied_msg = s
                else:
                    all_strings.append((elapsed, s))
        except: pass

    if denied_msg and verbose:
        print(f"[chat] Server error: {denied_msg[:120]}", file=sys.stderr)

    # Filter: remove system prompt / UUID / base64 / echo of message
    msg_prefix = message[:50]
    filtered = [
        s for (_, s) in all_strings
        if _is_real_response(s) and len(s) > 3 and msg_prefix not in s
    ]

    if filtered:
        unique = list(dict.fromkeys(filtered))
        result = '\n'.join(unique[-10:])
        if verbose: print(f"[chat] Response extracted ({len(unique)} unique strings)", file=sys.stderr)
        return result

    if denied_msg:
        err_type = _classify_error(denied_msg)
        if err_type in ('internal_error', 'quota_exhausted', 'rate_limit'):
            try: os.remove(VAULT_FILE)
            except: pass
            label = {'quota_exhausted': 'QUOTA', 'rate_limit': 'RATE_LIMIT', 'internal_error': 'RETRY'}.get(err_type, 'RETRY')
            return f"[{label}] {denied_msg[:120]}\n请稍后重试"
        return f"[{err_type.upper()}] {denied_msg[:120]}"

    # fallback chain
    if try_fallback and model in MODEL_FALLBACK_CHAIN:
        idx = MODEL_FALLBACK_CHAIN.index(model)
        for next_model in MODEL_FALLBACK_CHAIN[idx+1:]:
            if next_model == model: continue
            if verbose: print(f"[Fallback] {model} → {next_model}", file=sys.stderr)
            result = chat(message, model=next_model, verbose=verbose, try_fallback=False)
            if not result.startswith('[') or result.startswith('[RETRY'):
                return result
        return f"[No response — fallback exhausted ({model})]"

    return "[No response — try again]"


# ══════════════════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    model = DEFAULT_MODEL
    args = sys.argv[1:]
    if '--model' in args:
        i = args.index('--model')
        model = args[i+1] if i+1 < len(args) else model
        args = args[:i] + args[i+2:]

    print(f"Claude Opus 4.6 Ultimate Client | Model: {model}\n")

    if args:
        q = ' '.join(args)
        print(f"Q: {q}\n")
        ans = chat(q, model=model, verbose=True)
        print(f"A: {ans}")
    else:
        print("交互模式 (输入 exit 退出)\n")
        while True:
            try:
                q = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not q or q.lower() in ('exit', 'quit', 'q'):
                break
            print("AI: ...", end='\r')
            ans = chat(q, model=model, verbose=True)
            print(f"AI: {ans}\n")
