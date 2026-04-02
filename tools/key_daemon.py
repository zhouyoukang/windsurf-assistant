"""
key_daemon.py — 后台持续监控 WAM key，找到 Claude 权限 key 即缓存

用法（后台运行）:
  start /B pythonw key_daemon.py
  # 或直接:
  python key_daemon.py

当找到 Claude-capable key 时：
  1. 写入 claude_key.vault
  2. 打印成功消息
  3. 保持运行（24h 后重新搜索）
"""

import sys, os, io, json, struct, time, re, sqlite3, requests, subprocess, ctypes

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

VAULT   = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\claude_key.vault'
DB_PATH = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
LS_EXE  = 'language_server_windows_x64.exe'

# ── 基础工具 ──────────────────────────────────────────────────────────────
def _wam_key():
    try:
        con = sqlite3.connect(DB_PATH)
        v = con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        con.close()
        return json.loads(v[0]).get('apiKey', '') if v else ''
    except: return ''

def _vault_valid():
    try:
        d = json.load(open(VAULT))
        return time.time() - d.get('ts', 0) < 86400 and bool(d.get('key'))
    except: return False

def _vault_save(key):
    json.dump({'key': key, 'ts': time.time()}, open(VAULT, 'w'))

# ── LS 端口 + CSRF ─────────────────────────────────────────────────────────
def _ls_pid():
    try:
        r = subprocess.run(['tasklist','/FI',f'IMAGENAME eq {LS_EXE}','/FO','CSV','/NH'],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.strip().splitlines():
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 2:
                try: return int(parts[1])
                except: pass
    except: pass
    return None

def _ls_port(pid):
    try:
        r = subprocess.run(['netstat','-ano'], capture_output=True)
        net = r.stdout.decode('gbk', errors='replace')
        for line in net.splitlines():
            if 'LISTENING' in line:
                p = line.split()
                try:
                    if int(p[-1]) == pid:
                        port = int(p[1].split(':')[1])
                        if port > 50000:
                            return port
                except: pass
    except: pass
    return None

class _PBI(ctypes.Structure):
    _fields_ = [('ExitStatus',ctypes.c_long),('PebBaseAddress',ctypes.c_void_p),
                ('AffinityMask',ctypes.c_void_p),('BasePriority',ctypes.c_long),
                ('UniqueProcessId',ctypes.c_void_p),('InheritedUniq',ctypes.c_void_p)]

def _peb_csrf(pid):
    k32 = ctypes.windll.kernel32; ntdl = ctypes.windll.ntdll
    h = k32.OpenProcess(0x10|0x400|0x1000, False, pid)
    if not h: return None
    try:
        pbi = _PBI()
        ntdl.NtQueryInformationProcess(h, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), None)
        peb = pbi.PebBaseAddress
        def rp(a):
            b = ctypes.create_string_buffer(8); n = ctypes.c_size_t(0)
            k32.ReadProcessMemory(h, ctypes.c_void_p(a), b, 8, ctypes.byref(n))
            return struct.unpack('<Q', b.raw)[0] if n.value==8 else 0
        def rb(a, s):
            b = ctypes.create_string_buffer(s); n = ctypes.c_size_t(0)
            k32.ReadProcessMemory(h, ctypes.c_void_p(a), b, s, ctypes.byref(n))
            return b.raw[:n.value]
        pp = rp(peb + 0x20); ep = rp(pp + 0x80)
        sr = rb(pp + 0x3F0, 8)
        es = min(struct.unpack('<Q', sr)[0] if len(sr)==8 else 0x10000, 0x80000)
        if es == 0: es = 0x10000
        env = rb(ep, es).decode('utf-16-le', errors='replace')
        m = re.search(r'WINDSURF_CSRF_TOKEN=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', env, re.I)
        return m.group(1) if m else None
    except: return None
    finally: k32.CloseHandle(h)

def _grpc_port(pid):
    """Find the gRPC cascade port among LS ports (skip 404)"""
    try:
        r = subprocess.run(['netstat','-ano'], capture_output=True)
        net = r.stdout.decode('gbk', errors='replace')
        for line in net.splitlines():
            if 'LISTENING' in line:
                p = line.split()
                try:
                    if int(p[-1]) == pid:
                        port = int(p[1].split(':')[1])
                        if port <= 50000: continue
                        # Quick gRPC probe
                        b = b'{"metadata":{"ideName":"W"},"workspaceTrusted":true}'
                        resp = requests.post(
                            f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState',
                            data=b'\x00'+struct.pack('>I',len(b))+b,
                            headers={'Content-Type':'application/grpc-web+json','x-codeium-csrf-token':'probe','x-grpc-web':'1'},
                            timeout=1.5, stream=True)
                        list(resp.iter_content(chunk_size=None))
                        if resp.status_code in (200, 403):
                            return port
                except: pass
    except: pass
    return None

def _get_env():
    """Get current LS pid, port, csrf"""
    pid = _ls_pid()
    if not pid: return None, None, None
    port = _grpc_port(pid)
    csrf = _peb_csrf(pid) if port else None
    return pid, port, csrf

# ── Key 测试 ──────────────────────────────────────────────────────────────
META = {"ideName":"Windsurf","ideVersion":"1.108.2","extensionVersion":"3.14.2",
        "locale":"en-US","os":"win32","url":"https://server.codeium.com",
        "impersonateTier":"TEAMS_TIER_PRO"}

def _test(key, port, csrf):
    """Returns True=Claude OK, False=denied, None=infra error"""
    meta = {**META, 'apiKey': key}
    hdr  = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
            'x-codeium-csrf-token': csrf, 'x-grpc-web': '1'}
    def call(method, body, timeout=15):
        b = json.dumps(body).encode()
        r = requests.post(
            f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{method}',
            data=b'\x00'+struct.pack('>I',len(b))+b, headers=hdr, timeout=timeout, stream=True)
        raw = b''.join(r.iter_content(chunk_size=None))
        frames=[]; pos=0
        while pos+5<=len(raw):
            fl=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
            frames.append((fl,raw[pos:pos+n])); pos+=n
        return frames
    try:
        call('InitializeCascadePanelState', {'metadata':meta,'workspaceTrusted':True})
        call('UpdateWorkspaceTrust',        {'metadata':meta,'workspaceTrusted':True})
        f1 = call('StartCascade', {'metadata':meta,'source':'CORTEX_TRAJECTORY_SOURCE_USER'})
        cid = next((json.loads(d).get('cascadeId') for fl,d in f1 if fl==0 and b'cascadeId' in d), None)
        if not cid:
            return None
    except Exception as e:
        print(f'[KeyDaemon] _test startup err: {e}', flush=True)
        return None
    try:
        # Try current model UIDs in order
        sent = False
        for model_uid in ['MODEL_CLAUDE_4_5_OPUS', 'claude-sonnet-4-6', 'MODEL_SWE_1_5']:
            try:
                call('SendUserCascadeMessage', {
                    'metadata':meta, 'cascadeId':cid,
                    'items':[{'text':'hi'}],
                    'cascadeConfig':{'plannerConfig':{'requestedModelUid':model_uid,'conversational':{}}}
                }, timeout=12)
                sent = True
                break
            except Exception:
                continue
        if not sent:
            return None
        sb = json.dumps({'id':cid,'protocolVersion':1}).encode()
        r3 = requests.post(
            f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
            data=b'\x00'+struct.pack('>I',len(sb))+sb, headers=hdr, timeout=10, stream=True)
        buf=b''; t0=time.time(); denied=False; got=False
        for chunk in r3.iter_content(chunk_size=128):
            buf+=chunk
            while len(buf)>=5:
                nl=struct.unpack('>I',buf[1:5])[0]
                if len(buf)<5+nl: break
                fr=buf[5:5+nl]; buf=buf[5+nl:]
                if fr: got=True
                try:
                    if 'permission_denied' in json.dumps(json.loads(fr)).lower(): denied=True
                except: pass
            if denied or time.time()-t0>6: break
        if not got: return None
        return not denied
    except Exception as e:
        print(f'[KeyDaemon] _test stream err: {e}', flush=True)
        return None

# ── 主循环 ────────────────────────────────────────────────────────────────
def run():
    print(f"[KeyDaemon] 启动  vault={VAULT}", flush=True)
    print(f"[KeyDaemon] WAM 池约 97 个账号，找到 Claude key 即缓存", flush=True)

    seen = set()
    none_count = {}   # key -> consecutive None count
    port_csrf_cache = [None, None, 0.0]

    while True:
        # Check vault
        if _vault_valid():
            import json as _j
            cached_key = _j.load(open(VAULT)).get('key','')
            print(f"[KeyDaemon] vault 有效: {cached_key[:25]}... 等待 1h 后重验", flush=True)
            time.sleep(3600)
            continue

        # Get current WAM key
        key = _wam_key()
        if not key or key in seen:
            time.sleep(2)
            continue

        # Refresh port/csrf every 60s
        now = time.time()
        if now - port_csrf_cache[2] > 60:
            pid = _ls_pid()
            if pid:
                port = _grpc_port(pid)
                csrf = _peb_csrf(pid) if port else None
                if port and csrf:
                    port_csrf_cache[:] = [port, csrf, now]
                    print(f"[KeyDaemon] LS port={port} CSRF={csrf[:8]}...", flush=True)
                    none_count.clear()  # reset on successful infra refresh

        port, csrf = port_csrf_cache[0], port_csrf_cache[1]
        if not port or not csrf:
            time.sleep(5)
            continue

        print(f"[KeyDaemon] 测试 {key[:25]}... (none:{none_count.get(key,0)})", flush=True)
        result = _test(key, port, csrf)
        if result is True:
            _vault_save(key)
            print(f"\n[KeyDaemon] *** 找到 Claude key！已写入 vault ***", flush=True)
            print(f"[KeyDaemon] Key: {key[:40]}...", flush=True)
            print(f"[KeyDaemon] 现在可以运行: python opus46_ultimate.py '你的问题'", flush=True)
            time.sleep(82800)  # 23h
            seen.clear(); none_count.clear()
        elif result is None:
            none_count[key] = none_count.get(key, 0) + 1
            if none_count[key] >= 3:
                # Give up on this key after 3 consecutive infra errors
                seen.add(key)
                print(f"[KeyDaemon] key {key[:25]}... infra失败3次，跳过", flush=True)
                none_count.pop(key, None)
            else:
                port_csrf_cache[2] = 0  # force infra refresh
                time.sleep(3)
        else:
            seen.add(key)
            none_count.pop(key, None)
            print(f"[KeyDaemon] denied, 累计已测: {len(seen)}", flush=True)
            time.sleep(15)  # 避免 LS 过载

if __name__ == '__main__':
    run()
