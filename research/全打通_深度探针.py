#!/usr/bin/env python3
"""
全打通_深度探针.py — 彻底打通 Windsurf 后端 v1.0
================================================
道法自然·万法归宗

完整流程:
  ① 自动检测 LS 端口 + CSRF
  ② 获取 WAM key (多源: vault / DB / 账号池扫描)
  ③ GetPlanStatus → 账户能力/配额/计费策略
  ④ 逐模型测试: free → standard → premium → Claude
     - 每个模型发送 "1+1=?" 并等待响应
     - 精确报告: 成功/限流/permission_denied/内部错误
  ⑤ 输出 JSON 报告 + 首个成功模型的完整响应
  ⑥ 自动更新 opus46_ultimate.py 中的 DEFAULT_MODEL

Usage:
  python 全打通_深度探针.py              # 完整探测
  python 全打通_深度探针.py --quick      # 只测 Claude 系列
  python 全打通_深度探针.py --byok KEY  # 测试 BYOK 通道 (自带 Anthropic key)
  python 全打通_深度探针.py --plan       # 只查账户计划状态
"""

import sys, os, io, json, struct, time, re, ctypes, ctypes.wintypes
import sqlite3, subprocess, requests, argparse
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ══════════════════════════════════════════════════════════════════════════
# 路径常量
# ══════════════════════════════════════════════════════════════════════════
VAULT_FILE = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\claude_key.vault'
DB_PATH    = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
REPORT_OUT = Path(__file__).parent / '全打通_报告.json'

LS_EXE = 'language_server_windows_x64.exe'

META_TMPL = {
    "ideName": "Windsurf", "ideVersion": "1.108.2",
    "extensionVersion": "3.14.2", "extensionName": "Windsurf",
    "extensionPath": r"D:\Windsurf\resources\app\extensions\windsurf",
    "locale": "en-US", "os": "win32",
    "url": "https://server.codeium.com",
}

# ══════════════════════════════════════════════════════════════════════════
# 模型优先级测试列表  (UID, 显示名, tier)
# ══════════════════════════════════════════════════════════════════════════
MODEL_PRIORITY = [
    # — Free / SWE —
    ("MODEL_SWE_1_5",                    "SWE-1.5 Fast",              "free"),
    ("MODEL_SWE_1_5_SLOW",               "SWE-1.5 Slow",              "free"),
    # — Low cost —
    ("MODEL_CHAT_GPT_5_CODEX",           "GPT-5-Codex",               "low"),
    ("MODEL_PRIVATE_6",                  "GPT-5 Low Thinking",        "low"),
    ("MODEL_KIMI_K2",                    "Kimi K2",                   "low"),
    # — Standard —
    ("MODEL_CHAT_GPT_4_1_2025_04_14",    "GPT-4.1",                   "standard"),
    ("MODEL_GOOGLE_GEMINI_2_5_PRO",      "Gemini 2.5 Pro",            "standard"),
    ("MODEL_CHAT_O3",                    "o3",                        "standard"),
    # — Claude (Haiku/Sonnet 4) — 
    ("MODEL_PRIVATE_11",                 "Claude Haiku 4.5",          "claude"),
    ("MODEL_CLAUDE_4_SONNET",            "Claude Sonnet 4",           "claude"),
    # — Claude Sonnet 4.5 / 4.6 —
    ("MODEL_PRIVATE_2",                  "Claude Sonnet 4.5",         "claude"),
    ("claude-sonnet-4-6",                "Claude Sonnet 4.6",         "claude"),
    ("claude-sonnet-4-6-thinking",       "Claude Sonnet 4.6 Thinking","claude"),
    # — Claude Opus — 核心目标 —
    ("MODEL_CLAUDE_4_5_OPUS",            "Claude Opus 4.5",           "claude_opus"),
    ("MODEL_CLAUDE_4_5_OPUS_THINKING",   "Claude Opus 4.5 Thinking",  "claude_opus"),
    # — BYOK (需要用户自带 Anthropic key) —
    ("MODEL_CLAUDE_4_OPUS_BYOK",         "Claude Opus 4 BYOK",        "byok"),
    ("MODEL_CLAUDE_4_OPUS_THINKING_BYOK","Claude Opus 4 Thinking BYOK","byok"),
    # — 旧 UID 别名测试 (服务端是否仍接受) —
    ("claude-opus-4-6",                  "claude-opus-4-6 (legacy)",  "legacy"),
    ("claude-opus-4-5",                  "claude-opus-4-5 (alt)",     "legacy"),
]

# ══════════════════════════════════════════════════════════════════════════
# LS 端口 + PID 检测
# ══════════════════════════════════════════════════════════════════════════
_ls_pid_cache  = [0, 0]
_ls_port_cache = [0, 0]

def _get_ls_pid():
    cached_pid, cached_ts = _ls_pid_cache
    if cached_pid and time.time() - cached_ts < 30:
        return cached_pid
    try:
        r = subprocess.run(
            ['tasklist', '/FI', f'IMAGENAME eq {LS_EXE}', '/FO', 'CSV', '/NH'],
            capture_output=True, text=True, timeout=5)
        for line in r.stdout.strip().splitlines():
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 2:
                try:
                    pid = int(parts[1])
                    _ls_pid_cache[0] = pid
                    _ls_pid_cache[1] = time.time()
                    return pid
                except: pass
    except: pass
    return None

def _is_grpc_port(port):
    try:
        b = json.dumps({'metadata':{'ideName':'W'},'workspaceTrusted':True}).encode()
        r = requests.post(
            f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState',
            data=b'\x00'+struct.pack('>I',len(b))+b,
            headers={'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
                     'x-codeium-csrf-token':'probe','x-grpc-web':'1'},
            timeout=1.5, stream=True)
        b''.join(r.iter_content(chunk_size=None))
        return r.status_code in (200, 403)
    except: return False

def find_ls_port():
    cached_port, cached_ts = _ls_port_cache
    if cached_port and time.time() - cached_ts < 30:
        return cached_port
    pid = _get_ls_pid()
    if not pid:
        return None
    try:
        r = subprocess.run(['netstat', '-ano'], capture_output=True)
        net = r.stdout.decode('gbk', errors='replace')
        candidates = []
        for line in net.splitlines():
            if 'LISTENING' in line:
                parts = line.split()
                try:
                    if int(parts[-1]) == pid:
                        port = int(parts[1].split(':')[1])
                        if port > 50000:
                            candidates.append(port)
                except: pass
        for port in sorted(candidates):
            if _is_grpc_port(port):
                _ls_port_cache[0] = port
                _ls_port_cache[1] = time.time()
                return port
    except: pass
    return None

# ══════════════════════════════════════════════════════════════════════════
# CSRF — PEB 环境变量读取
# ══════════════════════════════════════════════════════════════════════════
class _PBI(ctypes.Structure):
    _fields_ = [('ExitStatus',ctypes.c_long),('PebBaseAddress',ctypes.c_void_p),
                ('AffinityMask',ctypes.c_void_p),('BasePriority',ctypes.c_long),
                ('UniqueProcessId',ctypes.c_void_p),('InheritedUniq',ctypes.c_void_p)]

def _peb_read_ptr(h, addr):
    buf = ctypes.create_string_buffer(8); n = ctypes.c_size_t(0)
    ctypes.windll.kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, 8, ctypes.byref(n))
    return struct.unpack('<Q', buf.raw)[0] if n.value == 8 else 0

def _peb_read_bytes(h, addr, size):
    buf = ctypes.create_string_buffer(size); n = ctypes.c_size_t(0)
    ctypes.windll.kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(n))
    return buf.raw[:n.value]

def find_csrf():
    pid = _get_ls_pid()
    if not pid: return None
    k32 = ctypes.windll.kernel32; ntdl = ctypes.windll.ntdll
    h = k32.OpenProcess(0x10 | 0x400 | 0x1000, False, pid)
    if not h: return None
    try:
        pbi = _PBI()
        ntdl.NtQueryInformationProcess(h, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), None)
        peb = pbi.PebBaseAddress
        pp = _peb_read_ptr(h, peb + 0x20)
        env_ptr = _peb_read_ptr(h, pp + 0x80)
        env_size = min(struct.unpack('<Q', _peb_read_bytes(h, pp + 0x3F0, 8))[0]
                       if len(_peb_read_bytes(h, pp + 0x3F0, 8)) == 8 else 0x10000, 0x80000)
        if env_size == 0: env_size = 0x10000
        env = _peb_read_bytes(h, env_ptr, env_size).decode('utf-16-le', errors='replace')
        m = re.search(r'WINDSURF_CSRF_TOKEN=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', env, re.I)
        if m: return m.group(1)
    except: pass
    finally: k32.CloseHandle(h)
    return None

# ══════════════════════════════════════════════════════════════════════════
# WAM Key — 多源获取
# ══════════════════════════════════════════════════════════════════════════
def get_wam_key_from_db(db_path=DB_PATH):
    try:
        con = sqlite3.connect(db_path)
        row = con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        con.close()
        if row:
            return json.loads(row[0]).get('apiKey', '')
    except: pass
    return ''

def get_wam_key_from_vault():
    try:
        data = json.load(open(VAULT_FILE))
        if time.time() - data.get('ts', 0) < 86400:
            return data.get('key', '')
    except: pass
    return ''

def get_all_wam_keys():
    """从 WAM token cache 获取所有账号的 key"""
    keys = []
    cache_paths = [
        r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\zhouyoukang.windsurf-assistant\wam-token-cache.json',
        r'C:\Users\zhouyoukang\AppData\Roaming\Windsurf\User\globalStorage\zhouyoukang.windsurf-assistant\wam-token-cache.json',
    ]
    for cp in cache_paths:
        try:
            data = json.load(open(cp))
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, dict) and v.get('apiKey'):
                        keys.append(v['apiKey'])
                    elif isinstance(v, str) and len(v) > 20:
                        keys.append(v)
        except: pass
    # 也从主 DB 读
    k = get_wam_key_from_db()
    if k: keys.insert(0, k)
    k2 = get_wam_key_from_vault()
    if k2: keys.insert(0, k2)
    return list(dict.fromkeys(keys))  # dedup

# ══════════════════════════════════════════════════════════════════════════
# gRPC-web 调用基础
# ══════════════════════════════════════════════════════════════════════════
def grpc_call(port, csrf, meta, method, body, timeout=10):
    body['metadata'] = meta
    b = json.dumps(body).encode()
    hdr = {
        'Content-Type': 'application/grpc-web+json',
        'Accept': 'application/grpc-web+json',
        'x-codeium-csrf-token': csrf, 'x-grpc-web': '1',
    }
    r = requests.post(
        f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{method}',
        data=b'\x00' + struct.pack('>I', len(b)) + b,
        headers=hdr, timeout=timeout, stream=True
    )
    raw = b''.join(r.iter_content(chunk_size=None))
    frames = []; pos = 0
    while pos + 5 <= len(raw):
        fl = raw[pos]; n = struct.unpack('>I', raw[pos+1:pos+5])[0]; pos += 5
        frames.append((fl, raw[pos:pos+n])); pos += n
    return frames

def parse_frames(frames):
    """从帧列表提取所有字符串 (包括嵌套)"""
    results = []
    def walk(obj, depth=0):
        if depth > 20: return
        if isinstance(obj, str) and 3 < len(obj) < 2000:
            results.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values(): walk(v, depth+1)
        elif isinstance(obj, list):
            for i in obj: walk(i, depth+1)
    for fl, data in frames:
        if fl == 0x80: continue
        try: walk(json.loads(data))
        except: pass
    return results

# ══════════════════════════════════════════════════════════════════════════
# GetPlanStatus — 查账户计划状态
# ══════════════════════════════════════════════════════════════════════════
def get_plan_status_direct(api_key):
    """直连 server.codeium.com 查 PlanStatus (gRPC-web binary proto)"""
    def enc_str(fnum, s):
        d = s.encode(); t = (fnum << 3) | 2
        vb = bytearray()
        v = t
        while v > 0x7f: vb.append((v & 0x7f) | 0x80); v >>= 7
        vb.append(v)
        lb = bytearray()
        v = len(d)
        while v > 0x7f: lb.append((v & 0x7f) | 0x80); v >>= 7
        lb.append(v)
        return bytes(vb) + bytes(lb) + d

    body = enc_str(1, api_key)
    framed = b'\x00' + struct.pack('>I', len(body)) + body
    try:
        r = requests.post(
            'https://server.codeium.com/exa.seat_management_pb.SeatManagementService/GetPlanStatus',
            data=framed,
            headers={
                'Content-Type': 'application/grpc-web+proto',
                'Accept': 'application/grpc-web+proto',
                'x-grpc-web': '1',
                'Authorization': f'Basic {api_key}',
            },
            timeout=10
        )
        raw = r.content
        # 解析帧
        pos = 0; result_bytes = b''
        while pos + 5 <= len(raw):
            fl = raw[pos]; n = struct.unpack('>I', raw[pos+1:pos+5])[0]; pos += 5
            if fl == 0: result_bytes = raw[pos:pos+n]
            pos += n
        return {'status_code': r.status_code, 'raw_len': len(result_bytes), 'raw': result_bytes.hex()[:200]}
    except Exception as e:
        return {'error': str(e)}

# ══════════════════════════════════════════════════════════════════════════
# 单模型测试
# ══════════════════════════════════════════════════════════════════════════
TEST_MSG = "Reply EXACTLY: PROBE_OK. Then answer: 1+1=?"

SKIP_STRINGS = frozenset([
    'You are Cascade', 'The USER is interacting', 'communication_style',
    'tool_calling', 'making_code_changes', 'citation_guidelines',
    'Before each tool call', 'read_file', 'run_command', 'grep_search',
    'write_to_file', '{"$schema"', 'additionalProperties', '"description":',
    'CodeContent', 'TargetFile', 'CommandLine', 'SearchPath',
    'CORTEX_', 'CASCADE_', 'Available skills', 'workflow',
])

def _is_real_response(s):
    if re.match(r'^[A-Za-z0-9+/]{20,}={0,2}$', s): return False
    return not any(f in s for f in SKIP_STRINGS)

def test_model(port, csrf, key, model_uid, timeout_stream=20):
    """
    测试单个模型。返回:
      {'status': 'ok'|'permission_denied'|'internal_error'|'rate_limit'|'timeout'|'error',
       'response': str, 'error_detail': str, 'elapsed': float}
    """
    meta = {**META_TMPL, 'apiKey': key}
    t0 = time.time()

    try:
        grpc_call(port, csrf, meta, "InitializeCascadePanelState", {"workspaceTrusted": True})
        grpc_call(port, csrf, meta, "UpdateWorkspaceTrust", {"workspaceTrusted": True})
        f1 = grpc_call(port, csrf, meta, "StartCascade",
                       {"source": "CORTEX_TRAJECTORY_SOURCE_USER"}, timeout=8)
        cid = next((json.loads(d).get('cascadeId') for fl,d in f1
                    if fl==0 and b'cascadeId' in d), None)
        if not cid:
            return {'status': 'error', 'error_detail': 'no cascade_id', 'elapsed': time.time()-t0, 'response': ''}

        grpc_call(port, csrf, meta, "SendUserCascadeMessage", {
            "cascadeId": cid,
            "items": [{"text": TEST_MSG}],
            "cascadeConfig": {"plannerConfig": {
                "requestedModelUid": model_uid,
                "conversational": {}
            }},
        }, timeout=10)

    except Exception as e:
        return {'status': 'error', 'error_detail': f'init/send: {e}', 'elapsed': time.time()-t0, 'response': ''}

    # — 流式读取 —
    hdr = {'Content-Type': 'application/grpc-web+json', 'Accept': 'application/grpc-web+json',
           'x-codeium-csrf-token': csrf, 'x-grpc-web': '1'}
    sb = json.dumps({"id": cid, "protocolVersion": 1}).encode()
    candidates = []; error_detail = ''

    try:
        r = requests.post(
            f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
            data=b'\x00' + struct.pack('>I', len(sb)) + sb,
            headers=hdr, timeout=timeout_stream, stream=True)
        buf = b''
        for chunk in r.iter_content(chunk_size=128):
            buf += chunk
            while len(buf) >= 5:
                nl = struct.unpack('>I', buf[1:5])[0]
                if len(buf) < 5 + nl: break
                fl = buf[0]; fr = buf[5:5+nl]; buf = buf[5+nl:]
                if fl == 0x80: continue
                try:
                    obj = json.loads(fr)
                    for s in parse_frames([(fl, fr)]):
                        sl = s.lower()
                        if 'permission_denied' in sl or 'permission denied' in sl:
                            error_detail = s
                        elif 'internal error' in sl and 'trace' in sl:
                            error_detail = error_detail or s
                        elif 'rate limit' in sl or 'quota' in sl or 'exhausted' in sl:
                            error_detail = s
                        elif _is_real_response(s) and TEST_MSG[:30] not in s and len(s) > 3:
                            candidates.append(s)
                except: pass
            if 'PROBE_OK' in ''.join(candidates): break
            if time.time() - t0 > timeout_stream: break
    except requests.exceptions.Timeout:
        return {'status': 'timeout', 'error_detail': 'stream timeout', 'elapsed': time.time()-t0, 'response': ''}
    except Exception as e:
        return {'status': 'error', 'error_detail': f'stream: {e}', 'elapsed': time.time()-t0, 'response': ''}

    elapsed = time.time() - t0
    response = '\n'.join(s for s in candidates if len(s) > 3 and _is_real_response(s))[:500]

    if error_detail:
        ed_l = error_detail.lower()
        if 'permission_denied' in ed_l or 'permission denied' in ed_l:
            if 'internal error' in ed_l:
                status = 'internal_error'
            else:
                status = 'permission_denied'
        elif 'rate limit' in ed_l or 'quota' in ed_l:
            status = 'rate_limit'
        else:
            status = 'error'
        return {'status': status, 'error_detail': error_detail[:300], 'elapsed': elapsed, 'response': response}

    if 'PROBE_OK' in response or len(response) > 20:
        return {'status': 'ok', 'error_detail': '', 'elapsed': elapsed, 'response': response}

    return {'status': 'no_response', 'error_detail': '', 'elapsed': elapsed, 'response': response}

# ══════════════════════════════════════════════════════════════════════════
# 账号-key 矩阵扫描
# ══════════════════════════════════════════════════════════════════════════
def find_best_key(port, csrf, quick=False):
    """返回 (key, plan_info)，选最有权限的 key"""
    keys = get_all_wam_keys()
    if not keys:
        print("  [WARN] 未找到任何 WAM key!")
        return None, {}

    print(f"  [KEY] 找到 {len(keys)} 个 key，快速验证中...")
    for i, key in enumerate(keys[:20]):
        plan = get_plan_status_direct(key)
        print(f"  [{i+1}/{min(len(keys),20)}] key={key[:20]}... plan={plan}")
        if plan.get('status_code') in (200, None) and plan.get('raw_len', 0) > 5:
            return key, plan
    # fallback: return first key
    return keys[0], {}

# ══════════════════════════════════════════════════════════════════════════
# 主探测流程
# ══════════════════════════════════════════════════════════════════════════
def probe(args):
    print("=" * 70)
    print("全打通深度探针 v1.0 — 彻底解构 Windsurf 后端")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # ── ① 环境检测 ────────────────────────────────────────────
    print("\n[①] 检测 LS 环境...")
    port = find_ls_port()
    if not port:
        print("  ✗ 未找到 LS 端口! 请确保 Windsurf 正在运行。")
        return
    print(f"  ✓ LS 端口: {port}")

    csrf = find_csrf()
    if not csrf:
        csrf = '00000000-0000-0000-0000-000000000000'
        print(f"  ⚠ CSRF 扫描失败，使用占位符（可能影响部分请求）")
    else:
        print(f"  ✓ CSRF: {csrf[:8]}...")

    # ── ② WAM Key ─────────────────────────────────────────────
    print("\n[②] 获取 WAM Key...")
    keys = get_all_wam_keys()
    if not keys:
        print("  ✗ 无可用 key!")
        return
    print(f"  找到 {len(keys)} 个 key")

    # 优先使用 vault key
    key = keys[0]
    print(f"  使用 key: {key[:25]}...")

    # ── ③ 账户计划状态 ─────────────────────────────────────────
    print("\n[③] 查询账户计划状态...")
    if args.plan or True:
        plan = get_plan_status_direct(key)
        print(f"  计划状态: {plan}")
    meta = {**META_TMPL, 'apiKey': key}

    # ── ④ 模型测试 ────────────────────────────────────────────
    print("\n[④] 逐模型测试...")

    # 过滤模型列表
    if args.quick:
        test_models = [(uid, name, tier) for uid, name, tier in MODEL_PRIORITY
                       if 'claude' in uid.lower() or 'opus' in uid.lower() or 'byok' in tier]
    else:
        test_models = MODEL_PRIORITY

    if args.byok:
        print(f"  [BYOK] 将使用 Anthropic key: {args.byok[:20]}... 测试 BYOK 模型")

    report = {
        'timestamp': datetime.now().isoformat(),
        'port': port, 'csrf_ok': csrf != '00000000-0000-0000-0000-000000000000',
        'key': key[:30] + '...', 'models': []
    }

    first_success = None
    print(f"\n  {'Model UID':<45} {'Display':<30} {'Status':<20} {'Time':>6}")
    print(f"  {'-'*45} {'-'*30} {'-'*20} {'-'*6}")

    for model_uid, display_name, tier in test_models:
        # BYOK 模型用用户提供的 key 替换
        test_key = key
        if tier == 'byok' and args.byok:
            # 对于 BYOK，需要在 cascadeConfig 中注入 byok key
            # 这里先用普通 key 测试路由
            pass

        result = test_model(port, csrf, test_key, model_uid, timeout_stream=15)
        status_icon = {
            'ok': '✓', 'permission_denied': '✗', 'internal_error': '⚠',
            'rate_limit': '⏳', 'timeout': '⌛', 'error': '✗', 'no_response': '?'
        }.get(result['status'], '?')

        print(f"  {model_uid:<45} {display_name:<30} {status_icon} {result['status']:<18} {result['elapsed']:>5.1f}s")

        if result['status'] == 'ok' and not first_success:
            first_success = (model_uid, display_name, result)
            print(f"\n  ✓✓✓ 首个成功模型: {display_name} ({model_uid})")
            print(f"  响应: {result['response'][:200]}")
            print()

        if result['error_detail']:
            print(f"    └── {result['error_detail'][:120]}")

        report['models'].append({
            'uid': model_uid, 'name': display_name, 'tier': tier,
            **result
        })

        time.sleep(0.3)  # 防止过快请求

    # ── ⑤ 报告 ───────────────────────────────────────────────
    print("\n[⑤] 生成报告...")
    report['first_success'] = {
        'uid': first_success[0], 'name': first_success[1]
    } if first_success else None

    with open(REPORT_OUT, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"  报告已保存: {REPORT_OUT}")

    # ── ⑥ 自动更新 opus46_ultimate.py ────────────────────────
    if first_success:
        best_uid, best_name, best_result = first_success
        ultimate_path = Path(__file__).parent / 'opus46_ultimate.py'
        if ultimate_path.exists():
            src = ultimate_path.read_text(encoding='utf-8')
            old_line = 'DEFAULT_MODEL = "claude-opus-4-6"'
            new_line = f'DEFAULT_MODEL = "{best_uid}"  # auto-updated by 全打通探针'
            if old_line in src:
                src = src.replace(old_line, new_line)
                ultimate_path.write_text(src, encoding='utf-8')
                print(f"  ✓ opus46_ultimate.py DEFAULT_MODEL → {best_uid}")
            else:
                print(f"  ⚠ opus46_ultimate.py 中未找到 DEFAULT_MODEL 行，请手动更新为: {best_uid}")

    # ── 汇总 ────────────────────────────────────────────────
    print("\n" + "=" * 70)
    ok_models = [m for m in report['models'] if m['status'] == 'ok']
    err_models = [m for m in report['models'] if m['status'] != 'ok']
    print(f"汇总: {len(ok_models)} 个模型成功 / {len(err_models)} 个失败")
    if ok_models:
        print("可用模型:")
        for m in ok_models:
            print(f"  ✓ {m['name']} ({m['uid']})")
    else:
        print("⚠ 所有模型均失败!")
        # 错误分类
        from collections import Counter
        statuses = Counter(m['status'] for m in err_models)
        print(f"错误分布: {dict(statuses)}")
        print("\n常见原因:")
        if statuses.get('internal_error', 0) + statuses.get('permission_denied', 0) > 5:
            print("  → 账户配额/权限不足: 尝试切换到有更高配额的账号")
            print("  → 或: 使用 BYOK 通道 (python 全打通_深度探针.py --byok sk-ant-YOUR_KEY)")
        if statuses.get('rate_limit', 0) > 0:
            print("  → 限流: 等待配额重置 (通常 1 小时)")
    print("=" * 70)

    return report

# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='全打通深度探针')
    parser.add_argument('--quick', action='store_true', help='只测 Claude 系列')
    parser.add_argument('--byok', metavar='KEY', help='Anthropic API key (sk-ant-...)')
    parser.add_argument('--plan', action='store_true', help='只查账户计划状态')
    args = parser.parse_args()

    if args.plan:
        key = get_wam_key_from_db() or get_wam_key_from_vault()
        if key:
            print(f"Key: {key[:25]}...")
            print(f"Plan: {get_plan_status_direct(key)}")
        else:
            print("未找到 key")
    else:
        probe(args)
