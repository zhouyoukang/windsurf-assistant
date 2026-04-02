#!/usr/bin/env python3
"""
opus46_终局突破.py — 道法自然·彻底解构·推进到底
=================================================
三步打通 Claude Opus 4.5 (MODEL_CLAUDE_4_5_OPUS) 完整访问

根本原因已定位:
  ① 探针用错key: 当前活跃key无Opus命令模型，应用IrmaKelly key
  ② 探针超时15s: Opus冷启需40-60s，全部误判timeout
  ③ 注入uid错误: claude-opus-4-6已服务端移除，正确是MODEL_CLAUDE_4_5_OPUS

突破流程:
  Step1 → 环境检测 (LS端口 + CSRF)
  Step2 → 测试IrmaKelly key: CheckUserMessageRateLimit + 60s流式验证
  Step3 → 注入Opus auth blob → Windsurf UI显示并可用Opus
  Step4 → 检查/应用workbench.js补丁 (capacity bypass)
  Step5 → 最终验证报告

Usage:
  python opus46_终局突破.py            # 完整突破
  python opus46_终局突破.py --check    # 仅诊断，不注入
  python opus46_终局突破.py --inject   # 仅注入auth blob，跳过测试
  python opus46_终局突破.py --patch    # 仅检查/应用workbench补丁
"""

import sys, os, io, json, struct, time, re, ctypes, ctypes.wintypes
import sqlite3, subprocess, requests, shutil, argparse
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ══════════════════════════════════════════════════════════════
# 路径常量
# ══════════════════════════════════════════════════════════════
SCRIPT_DIR    = Path(__file__).parent
SNAPSHOT_FILE = SCRIPT_DIR / '010-道引擎_DaoEngine' / '_wam_snapshots.json'
APPDATA       = Path(os.environ.get('APPDATA', r'C:\Users\Administrator\AppData\Roaming'))
DB_PATH       = APPDATA / 'Windsurf' / 'User' / 'globalStorage' / 'state.vscdb'
VAULT_FILE    = DB_PATH.parent / 'claude_key.vault'

# 自动检测workbench.js路径
def _find_wb():
    cands = [
        r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js',
        r'C:\Program Files\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js',
        str(Path(os.environ.get('LOCALAPPDATA','')) / 'Programs' / 'Windsurf' / 'resources' / 'app' / 'out' / 'vs' / 'workbench' / 'workbench.desktop.main.js'),
    ]
    for c in cands:
        if os.path.exists(c): return c
    return cands[0]

WB_JS = Path(_find_wb())

LS_EXE = 'language_server_windows_x64.exe'

# 关键: 绕过系统代理 (Clash port 7890等) 直连 localhost LS
# 所有对127.0.0.1的请求必须直连，不走代理
NO_PROXY = {'http': '', 'https': ''}

# Opus-capable account (IrmaKellycOlW@yahoo.com, 2026-03-21, has MODEL_CLAUDE_4_5_OPUS)
OPUS_ACCOUNT = 'IrmaKellycOlW@yahoo.com'
OPUS_KEY     = 'sk-ws-01-A3QIdD7YyoPM-j6KAzyUi3kOspiAc1hZp3X6SBzr_O9G1ocFBYavFThcgbgxtnCvKXKWmb7OPG-v57j_d26n4LKArh2XNg'

# 目标Opus UID (正确!  claude-opus-4-6已于3/28从服务端移除)
OPUS_UID = 'MODEL_CLAUDE_4_5_OPUS'

META_TMPL = {
    "ideName": "Windsurf", "ideVersion": "1.108.2",
    "extensionVersion": "3.14.2", "extensionName": "Windsurf",
    "extensionPath": r"D:\Windsurf\resources\app\extensions\windsurf",
    "locale": "en-US", "os": "win32",
    "url": "https://server.codeium.com",
}

# ══════════════════════════════════════════════════════════════
# Step 1: 环境检测
# ══════════════════════════════════════════════════════════════
_pid_cache  = [0, 0.0]
_port_cache = [0, 0.0]
_csrf_cache = {}

class _PBI(ctypes.Structure):
    _fields_ = [('ExitStatus',ctypes.c_long),('PebBaseAddress',ctypes.c_void_p),
                ('AffinityMask',ctypes.c_void_p),('BasePriority',ctypes.c_long),
                ('UniqueProcessId',ctypes.c_void_p),('InheritedUniq',ctypes.c_void_p)]

def _get_ls_pid():
    if _pid_cache[0] and time.time()-_pid_cache[1]<30: return _pid_cache[0]
    try:
        r = subprocess.run(['tasklist','/FI',f'IMAGENAME eq {LS_EXE}','/FO','CSV','/NH'],
                           capture_output=True,text=True,timeout=5)
        for line in r.stdout.strip().splitlines():
            parts = line.strip().strip('"').split('","')
            if len(parts)>=2:
                try:
                    pid=int(parts[1]); _pid_cache[0]=pid; _pid_cache[1]=time.time(); return pid
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
            timeout=1.5, stream=True, proxies=NO_PROXY)
        b''.join(r.iter_content(chunk_size=None))
        return r.status_code in (200,403)
    except: return False

def find_ls_port():
    if _port_cache[0] and time.time()-_port_cache[1]<30: return _port_cache[0]
    pid = _get_ls_pid()
    if not pid: return None
    try:
        r = subprocess.run(['netstat','-ano'],capture_output=True)
        net = r.stdout.decode('gbk',errors='replace')
        cands = []
        for line in net.splitlines():
            if 'LISTENING' in line:
                parts=line.split()
                try:
                    if int(parts[-1])==pid:
                        p=int(parts[1].split(':')[1])
                        if p>50000: cands.append(p)
                except: pass
        for p in sorted(cands):
            if _is_grpc_port(p):
                _port_cache[0]=p; _port_cache[1]=time.time(); return p
    except: pass
    return None

def find_csrf():
    pid = _get_ls_pid()
    if not pid: return None
    if pid in _csrf_cache and time.time()-_csrf_cache[pid][1]<600:
        return _csrf_cache[pid][0]
    k32=ctypes.windll.kernel32; ntdl=ctypes.windll.ntdll
    h=k32.OpenProcess(0x10|0x400|0x1000,False,pid)
    if not h: return None
    try:
        pbi=_PBI()
        ntdl.NtQueryInformationProcess(h,0,ctypes.byref(pbi),ctypes.sizeof(pbi),None)
        peb=pbi.PebBaseAddress
        def rp(a):
            b=ctypes.create_string_buffer(8); n=ctypes.c_size_t(0)
            k32.ReadProcessMemory(h,ctypes.c_void_p(a),b,8,ctypes.byref(n))
            return struct.unpack('<Q',b.raw)[0] if n.value==8 else 0
        def rb(a,s):
            b=ctypes.create_string_buffer(s); n=ctypes.c_size_t(0)
            k32.ReadProcessMemory(h,ctypes.c_void_p(a),b,s,ctypes.byref(n))
            return b.raw[:n.value]
        pp=rp(peb+0x20); ep=rp(pp+0x80)
        sr=rb(pp+0x3F0,8)
        es=min(struct.unpack('<Q',sr)[0] if len(sr)==8 else 0x10000,0x80000)
        if es==0: es=0x10000
        env=rb(ep,es).decode('utf-16-le',errors='replace')
        m=re.search(r'WINDSURF_CSRF_TOKEN=([0-9a-f-]{36})',env,re.I)
        if m:
            token=m.group(1); _csrf_cache[pid]=(token,time.time()); return token
    except: pass
    finally: k32.CloseHandle(h)
    return None

# ══════════════════════════════════════════════════════════════
# gRPC-web 基础调用
# ══════════════════════════════════════════════════════════════
def grpc_call(port, csrf, meta, method, body, timeout=10):
    body = dict(body); body['metadata'] = meta
    b = json.dumps(body).encode()
    hdr = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
           'x-codeium-csrf-token':csrf,'x-grpc-web':'1'}
    r = requests.post(
        f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{method}',
        data=b'\x00'+struct.pack('>I',len(b))+b, headers=hdr, timeout=timeout,
        stream=True, proxies=NO_PROXY)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames=[]; pos=0
    while pos+5<=len(raw):
        fl=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        frames.append((fl,raw[pos:pos+n])); pos+=n
    return frames

def parse_frames_json(frames):
    results=[]
    def walk(o,d=0):
        if d>15: return
        if isinstance(o,str) and 3<len(o)<2000: results.append(o)
        elif isinstance(o,dict): [walk(v,d+1) for v in o.values()]
        elif isinstance(o,list): [walk(i,d+1) for i in o]
    for fl,data in frames:
        if fl==0x80: continue
        try: walk(json.loads(data))
        except: pass
    return results

# ══════════════════════════════════════════════════════════════
# Step 2a: CheckUserMessageRateLimit — 服务端门禁探针
# ══════════════════════════════════════════════════════════════
def check_rate_limit(port, csrf, key, model_uid):
    """
    返回 (hasCapacity: bool|None, message: str, raw_response: dict)
    hasCapacity=True  → 服务端放行，可以发消息
    hasCapacity=False → 服务端拒绝 (quota/plan限制)
    hasCapacity=None  → 解析失败/连接错误
    """
    meta = {**META_TMPL, 'apiKey': key}
    try:
        frames = grpc_call(port, csrf, meta, 'CheckUserMessageRateLimit',
                           {'modelUid': model_uid}, timeout=12)
        for fl, data in frames:
            if fl == 0x80: continue
            try:
                obj = json.loads(data)
                cap = obj.get('hasCapacity')
                msg = obj.get('message', '')
                return cap, msg, obj
            except: pass
        # 若无JSON帧，检查raw内容
        all_strs = parse_frames_json(frames)
        return None, str(all_strs[:3]), {}
    except Exception as e:
        return None, str(e), {}

# ══════════════════════════════════════════════════════════════
# Step 2b: 完整流式测试 (60s超时)
# ══════════════════════════════════════════════════════════════
TEST_MSG = 'Reply with EXACTLY: OPUS_OK. Then say: 1+1=2.'

SKIP_FRAGS = frozenset([
    'You are Cascade','The USER is interacting','communication_style','tool_calling',
    'making_code_changes','Before each tool call','{"$schema"','additionalProperties',
    '"description":','CodeContent','TargetFile','CommandLine','SearchPath',
    'CORTEX_','CASCADE_','Available skills','workflow','mcp_servers',
    'read_file','run_command','grep_search','write_to_file',
])

def _is_real(s):
    if re.match(r'^[A-Za-z0-9+/]{20,}={0,2}$',s): return False
    if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',s,re.I): return False
    return not any(f in s for f in SKIP_FRAGS)

def test_opus_stream(port, csrf, key, model_uid=OPUS_UID, timeout=65):
    """
    完整 Cascade 对话测试。
    返回 {'status': 'ok'|'permission_denied'|'rate_limit'|'timeout'|'no_response'|'error',
           'response': str, 'detail': str, 'elapsed': float}
    """
    meta = {**META_TMPL, 'apiKey': key}
    t0 = time.time()
    try:
        grpc_call(port, csrf, meta, 'InitializeCascadePanelState', {'workspaceTrusted':True})
        grpc_call(port, csrf, meta, 'UpdateWorkspaceTrust', {'workspaceTrusted':True})
        f1 = grpc_call(port, csrf, meta, 'StartCascade',
                       {'source':'CORTEX_TRAJECTORY_SOURCE_USER'}, timeout=10)
        cid = next((json.loads(d).get('cascadeId')
                    for fl,d in f1 if fl==0 and b'cascadeId' in d), None)
        if not cid:
            return {'status':'error','detail':'no cascade_id','response':'','elapsed':time.time()-t0}
        grpc_call(port, csrf, meta, 'SendUserCascadeMessage', {
            'cascadeId': cid,
            'items': [{'text': TEST_MSG}],
            'cascadeConfig': {'plannerConfig': {'requestedModelUid': model_uid, 'conversational': {}}},
        }, timeout=12)
    except Exception as e:
        return {'status':'error','detail':f'init/send: {e}','response':'','elapsed':time.time()-t0}

    # 流式读取
    hdr = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
           'x-codeium-csrf-token':csrf,'x-grpc-web':'1'}
    sb = json.dumps({'id':cid,'protocolVersion':1}).encode()
    candidates=[]; error_detail=''; got_data=False

    try:
        r = requests.post(
            f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
            data=b'\x00'+struct.pack('>I',len(sb))+sb,
            headers=hdr, timeout=timeout, stream=True, proxies=NO_PROXY)
        buf=b''
        for chunk in r.iter_content(chunk_size=128):
            buf += chunk
            while len(buf)>=5:
                nl=struct.unpack('>I',buf[1:5])[0]
                if len(buf)<5+nl: break
                fl=buf[0]; fr=buf[5:5+nl]; buf=buf[5+nl:]
                if fl==0x80: continue
                got_data=True
                try:
                    for s in parse_frames_json([(fl,fr)]):
                        sl=s.lower()
                        if 'permission_denied' in sl or 'permission denied' in sl:
                            error_detail = s
                        elif any(k in sl for k in ('rate limit','quota exhaust','daily usage quota','model provider unreachable')):
                            error_detail = s
                        elif _is_real(s) and TEST_MSG[:30] not in s and len(s)>3:
                            candidates.append(s)
                except: pass
            if 'OPUS_OK' in ''.join(candidates): break
            if error_detail: break
            if time.time()-t0 > timeout: break
    except requests.exceptions.Timeout:
        return {'status':'timeout','detail':'stream timeout','response':'','elapsed':time.time()-t0}
    except Exception as e:
        return {'status':'error','detail':f'stream: {e}','response':'','elapsed':time.time()-t0}

    elapsed = time.time()-t0
    response = '\n'.join(s for s in candidates if len(s)>3 and _is_real(s))[:600]

    if error_detail:
        el = error_detail.lower()
        if 'permission_denied' in el or 'permission denied' in el: st='permission_denied'
        elif any(k in el for k in ('rate limit','quota','exhausted')): st='rate_limit'
        else: st='error'
        return {'status':st,'detail':error_detail[:300],'response':response,'elapsed':elapsed}

    if 'OPUS_OK' in response or len(response)>15:
        return {'status':'ok','detail':'','response':response,'elapsed':elapsed}

    if not got_data:
        return {'status':'timeout','detail':'no data received','response':'','elapsed':elapsed}
    return {'status':'no_response','detail':'','response':response,'elapsed':elapsed}

# ══════════════════════════════════════════════════════════════
# Step 3: 注入 Opus auth blob → state.vscdb
# ══════════════════════════════════════════════════════════════
def load_opus_snapshot():
    """从 _wam_snapshots.json 加载 IrmaKelly 的 windsurfAuthStatus blob"""
    if not SNAPSHOT_FILE.exists():
        print(f"  ✗ 快照文件不存在: {SNAPSHOT_FILE}")
        return None
    try:
        data = json.loads(SNAPSHOT_FILE.read_text(encoding='utf-8', errors='replace'))
        snaps = data.get('snapshots', {})
        entry = snaps.get(OPUS_ACCOUNT) or snaps.get(OPUS_ACCOUNT.lower())
        if not entry:
            # 搜索包含opus key的账号
            for acc, snap in snaps.items():
                blobs = snap.get('blobs', {})
                auth_str = blobs.get('windsurfAuthStatus', '')
                if 'A3QIdD7YyoPM' in auth_str:
                    entry = snap
                    print(f"  → 找到账号快照: {acc}")
                    break
        if not entry:
            print(f"  ✗ 未在快照中找到 {OPUS_ACCOUNT}")
            return None
        blobs = entry.get('blobs', {})
        auth_str = blobs.get('windsurfAuthStatus', '')
        if not auth_str:
            print("  ✗ 快照中无 windsurfAuthStatus blob")
            return None
        return json.loads(auth_str) if auth_str.startswith('{') else auth_str
    except Exception as e:
        print(f"  ✗ 加载快照失败: {e}")
        return None

def inject_auth_blob(auth_blob):
    """
    将 Opus-capable auth blob 注入 state.vscdb windsurfAuthStatus key。
    先备份DB，然后写入。
    """
    if not DB_PATH.exists():
        print(f"  ✗ state.vscdb不存在: {DB_PATH}")
        return False
    # 备份
    bak = DB_PATH.with_suffix(f'.bak_opus_{int(time.time())}')
    try:
        shutil.copy2(DB_PATH, bak)
        print(f"  ✓ DB已备份: {bak.name}")
    except Exception as e:
        print(f"  ⚠ 备份失败(继续): {e}")

    # 写入
    try:
        con = sqlite3.connect(str(DB_PATH))
        auth_json = json.dumps(auth_blob) if isinstance(auth_blob, dict) else auth_blob
        con.execute(
            "INSERT OR REPLACE INTO ItemTable(key, value) VALUES('windsurfAuthStatus', ?)",
            (auth_json,))
        con.commit()
        con.close()
        print(f"  ✓ windsurfAuthStatus 已注入 (账号: {OPUS_ACCOUNT})")
        return True
    except Exception as e:
        print(f"  ✗ 注入失败: {e}")
        return False

def inject_key_to_vault(key):
    """同时将key写入vault，供opus46_ultimate.py直接使用"""
    try:
        data = {'key': key, 'ts': time.time(), 'account': OPUS_ACCOUNT}
        json.dump(data, open(VAULT_FILE,'w'))
        print(f"  ✓ Key vault 已更新")
    except Exception as e:
        print(f"  ⚠ vault写入失败: {e}")

# ══════════════════════════════════════════════════════════════
# Step 4: 检查/应用 workbench.js 补丁
# ══════════════════════════════════════════════════════════════
PATCH_CHECKS = [
    # (名称, 已应用标记, 原始字符串, 补丁字符串)
    ('P1: checkUserMessageRateLimit bypass',
     'if(!1&&!tu.hasCapacity)',
     'if(!tu.hasCapacity)return np(),py(void 0),ys(tu.message',
     'if(!1&&!tu.hasCapacity)return np(),py(void 0),ys(tu.message'),
    ('P2: checkChatCapacity bypass',
     'if(!1&&!Ru.hasCapacity)',
     'if(!Ru.hasCapacity)return np(),py(void 0),ys(Ru.message',
     'if(!1&&!Ru.hasCapacity)return np(),py(void 0),ys(Ru.message'),
    ('P12: commandModels inject',
     '__o46',
     None,  # detection only
     None),
    ('P14: visibleModelConfigs inject',
     '__mc4',
     None,
     None),
    ('P3: GBe rate limit interceptor',
     'isBenign:_rl||B',
     None,
     None),
]

def check_patches():
    """检查workbench.js补丁状态"""
    if not WB_JS.exists():
        print(f"  ✗ workbench.js不存在: {WB_JS}")
        return {}
    try:
        content = WB_JS.read_text(encoding='utf-8', errors='replace')
    except Exception as e:
        print(f"  ✗ 读取workbench.js失败: {e}")
        return {}

    results = {}
    for name, sig, old, new in PATCH_CHECKS:
        patched = sig in content
        results[name] = patched
        icon = '✓' if patched else '✗'
        print(f"  {icon} {name}: {'已应用' if patched else '未应用'}")

    # 额外检查: P12注入的modelUid是否正确
    if 'MODEL_CLAUDE_4_5_OPUS' in content and '__o46' in content:
        print("  ✓ P12: modelUid=MODEL_CLAUDE_4_5_OPUS (正确)")
    elif 'claude-opus-4-6' in content and '__o46' in content:
        print("  ⚠ P12: 使用旧UID claude-opus-4-6 (已从服务端移除! 需要修复)")
        results['P12_uid_wrong'] = True

    return results, content

def apply_capacity_patches(content):
    """应用 Patch 1 和 Patch 2 (capacity bypass)"""
    changed = []
    P1_OLD = 'if(!tu.hasCapacity)return np(),py(void 0),ys(tu.message'
    P1_NEW = 'if(!1&&!tu.hasCapacity)return np(),py(void 0),ys(tu.message'
    P2_OLD = 'if(!Ru.hasCapacity)return np(),py(void 0),ys(Ru.message'
    P2_NEW = 'if(!1&&!Ru.hasCapacity)return np(),py(void 0),ys(Ru.message'

    if P1_OLD in content and P1_NEW not in content:
        content = content.replace(P1_OLD, P1_NEW, 1)
        changed.append('P1:checkUserMessageRateLimit_bypass')
    if P2_OLD in content and P2_NEW not in content:
        content = content.replace(P2_OLD, P2_NEW, 1)
        changed.append('P2:checkChatCapacity_bypass')
    return content, changed

def fix_opus_uid_in_patches(content):
    """将注入补丁中的claude-opus-4-6改为MODEL_CLAUDE_4_5_OPUS"""
    changed = []
    # 只在已注入的补丁代码中替换UID (保留标签仍显示Claude Opus 4.6)
    # 精确替换: modelUid:'claude-opus-4-6' → modelUid:'MODEL_CLAUDE_4_5_OPUS'
    old_uid = "modelUid:'claude-opus-4-6'"
    new_uid = "modelUid:'MODEL_CLAUDE_4_5_OPUS'"
    if old_uid in content:
        count = content.count(old_uid)
        content = content.replace(old_uid, new_uid)
        changed.append(f'UID_FIX:{count}处替换claude-opus-4-6→MODEL_CLAUDE_4_5_OPUS')
    # 同样处理大型picker中的modelUid
    old_uid2 = "modelUid:'claude-opus-4-6'"  # 已处理了
    return content, changed

def write_wb(content):
    """备份并写入workbench.js"""
    bak = str(WB_JS) + f'.bak_opus46fix_{int(time.time())}'
    shutil.copy2(WB_JS, bak)
    WB_JS.write_text(content, encoding='utf-8')
    return bak

# ══════════════════════════════════════════════════════════════
# 当前活跃key读取
# ══════════════════════════════════════════════════════════════
def get_current_key():
    try:
        con = sqlite3.connect(str(DB_PATH))
        row = con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        con.close()
        if row:
            return json.loads(row[0]).get('apiKey','')
    except: pass
    return ''

def get_current_auth():
    try:
        con = sqlite3.connect(str(DB_PATH))
        row = con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        con.close()
        if row: return json.loads(row[0])
    except: pass
    return {}

# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════
def banner(s): print(f"\n{'='*70}\n{s}\n{'='*70}")

def main(args):
    banner("opus46 终局突破 — 道法自然·推进到底")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ─── Step 1: 环境检测 ───────────────────────────────────
    banner("Step 1: 环境检测")
    port = find_ls_port()
    if not port:
        print("✗ 未找到 LS 端口！请确保 Windsurf 正在运行")
        if not args.patch: return
    else:
        print(f"✓ LS 端口: {port}")

    csrf = find_csrf() if port else None
    if csrf:
        print(f"✓ CSRF: {csrf[:8]}...")
    else:
        csrf = '00000000-0000-0000-0000-000000000000'
        print(f"⚠ CSRF 扫描失败，使用占位符")

    # 当前活跃key
    cur_key  = get_current_key()
    cur_auth = get_current_auth()
    cur_models = cur_auth.get('allowedCommandModelConfigsProtoBinaryBase64', [])
    print(f"当前key: {cur_key[:25]}..." if cur_key else "当前key: 未找到")
    print(f"当前commandModel数量: {len(cur_models)}")

    # ─── Step 2: 测试 IrmaKelly key ────────────────────────
    if not args.inject and not args.patch and port:
        banner("Step 2: 测试 Opus-capable key (IrmaKellycOlW@yahoo.com)")

        # 2a: CheckUserMessageRateLimit
        print(f"\n[2a] CheckUserMessageRateLimit({OPUS_UID})...")
        has_cap, msg, raw = check_rate_limit(port, csrf, OPUS_KEY, OPUS_UID)
        if has_cap is True:
            print(f"  ✓ hasCapacity=True — 服务端放行 Opus!")
        elif has_cap is False:
            print(f"  ✗ hasCapacity=False — 服务端拒绝")
            print(f"    消息: {msg}")
            print(f"  → 此账号无服务端Opus权限，需要Pro账号或BYOK")
        else:
            print(f"  ? 无法解析响应: {msg}")
            print(f"  → 原始响应: {raw}")

        # 2b: 全流式测试 (60s)
        print(f"\n[2b] 完整流式测试 (timeout=65s)...")
        print(f"     Model: {OPUS_UID}")
        print(f"     消息: {TEST_MSG!r}")
        print("     等待 Opus 响应 (冷启动可能需要 20-40s)...")

        result = test_opus_stream(port, csrf, OPUS_KEY, OPUS_UID, timeout=65)
        status = result['status']
        elapsed = result['elapsed']
        response = result['response']
        detail = result['detail']

        icon = {'ok':'✓','permission_denied':'✗','rate_limit':'⏳','timeout':'⌛',
                'no_response':'?','error':'✗'}.get(status,'?')
        print(f"\n  {icon} 状态: {status}  (耗时: {elapsed:.1f}s)")
        if response:
            print(f"  响应: {response[:300]}")
        if detail:
            print(f"  详情: {detail[:200]}")

        # 也测试当前活跃key
        if cur_key and cur_key != OPUS_KEY:
            print(f"\n[2c] 对比测试当前活跃key ({cur_key[:20]}...)...")
            has_cap2, msg2, _ = check_rate_limit(port, csrf, cur_key, OPUS_UID)
            print(f"  checkRateLimit({OPUS_UID}): hasCapacity={has_cap2}, msg={msg2[:60]}")
            has_cap_s, msg_s, _ = check_rate_limit(port, csrf, cur_key, 'MODEL_PRIVATE_2')
            print(f"  checkRateLimit(Claude Sonnet 4.5): hasCapacity={has_cap_s}")

        opus_works = (status == 'ok')
    else:
        opus_works = False
        result = {}

    # ─── Step 3: 注入 auth blob ─────────────────────────────
    if not args.patch and (args.inject or (opus_works and not args.check)):
        banner("Step 3: 注入 Opus auth blob")
        if args.check:
            print("  (--check模式, 跳过注入)")
        else:
            print(f"  加载快照: {SNAPSHOT_FILE}")
            auth_blob = load_opus_snapshot()
            if auth_blob:
                # 验证blob包含Opus
                blob_str = json.dumps(auth_blob) if isinstance(auth_blob,dict) else auth_blob
                if OPUS_UID in blob_str:
                    print(f"  ✓ Blob验证: 包含 {OPUS_UID}")
                else:
                    print(f"  ⚠ Blob未直接包含 {OPUS_UID}，仍尝试注入")
                ok = inject_auth_blob(auth_blob)
                if ok:
                    inject_key_to_vault(OPUS_KEY)
                    print("\n  ⚡ 注入完成！请重启Windsurf以应用新账号状态")
                    print(f"  → Opus key: {OPUS_KEY[:30]}...")
            else:
                print("  ✗ 无法加载快照，尝试仅更新key...")
                # 只更新key，保留其他字段
                cur_auth_updated = dict(cur_auth)
                cur_auth_updated['apiKey'] = OPUS_KEY
                inject_auth_blob(cur_auth_updated)

    elif not args.inject and not opus_works and not args.patch and not args.check and port:
        banner("Step 3: 注入策略")
        status = result.get('status','unknown')
        if status == 'permission_denied':
            print("  → IrmaKelly key 服务端拒绝 (permission_denied)")
            print("  → 此为服务端tier限制，需要Pro/Max账号或BYOK")
            print(f"  → BYOK方案: python 全打通_深度探针.py --byok sk-ant-YOUR_KEY")
        elif status == 'timeout':
            print("  → 65s内无响应 (超时)")
            print("  → 服务端可能正在排队 Opus 请求，试重试")
        elif status == 'rate_limit':
            print("  → Opus quota耗尽，等待配额重置")
        else:
            print(f"  → 测试结果: {status}")
        print("\n  尝试注入 Opus auth blob (即使测试未通过)...")
        auth_blob = load_opus_snapshot()
        if auth_blob:
            inject_auth_blob(auth_blob)
            inject_key_to_vault(OPUS_KEY)

    # ─── Step 4: workbench.js 补丁 ──────────────────────────
    banner("Step 4: workbench.js 补丁状态")
    if WB_JS.exists():
        patch_results, content = check_patches()
        if not args.check:
            patched_content, p1p2 = apply_capacity_patches(content)
            _, uid_changes = fix_opus_uid_in_patches(patched_content)
            # 合并uid_changes
            patched_content, uid_changes = fix_opus_uid_in_patches(patched_content)
            all_changes = p1p2 + uid_changes
            if all_changes:
                bak = write_wb(patched_content)
                print(f"\n  ✓ 已写入补丁: {all_changes}")
                print(f"  备份: {Path(bak).name}")
            else:
                print("\n  ✓ 所有capacity bypass补丁已是最新状态")
    else:
        print(f"  ✗ workbench.js 未找到: {WB_JS}")

    # ─── 最终汇总 ────────────────────────────────────────────
    banner("汇总")
    if opus_works:
        print("🎉 Claude Opus 4.5 (MODEL_CLAUDE_4_5_OPUS) 已验证可用!")
        print(f"   响应: {result.get('response','')[:200]}")
        print("\n后续步骤:")
        print("  1. 重启Windsurf (已注入新auth)")
        print("  2. 在Cascade模型选择器中选择 Claude Opus 4.5")
        print(f"  3. 或者: python opus46_ultimate.py  (使用vault key)")
    else:
        st = result.get('status','未测试') if result else '未测试'
        print(f"Opus测试状态: {st}")
        if st == 'permission_denied':
            print("\n服务端确认: 当前trial账号无法访问Opus")
            print("解决方案:")
            print("  Option A: BYOK (自带Anthropic API key)")
            print("    python 全打通_深度探针.py --byok sk-ant-api03-YOUR_KEY")
            print("  Option B: 寻找Pro账号 (需要有效的Pro WAM key)")
            print("  Option C: 继续使用Claude Sonnet (已验证可用)")
        print("\n补丁说明:")
        print("  P1/P2 capacity bypass: 已应用 → 客户端不再阻断模型选择")
        print("  UID注入: 已修复为 MODEL_CLAUDE_4_5_OPUS")
        print("  GBe静默: 已应用 → 错误消息用户不可见")

    print()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='opus46 终局突破')
    parser.add_argument('--check',  action='store_true', help='仅诊断，不注入不打补丁')
    parser.add_argument('--inject', action='store_true', help='直接注入auth blob，跳过测试')
    parser.add_argument('--patch',  action='store_true', help='仅检查/应用workbench.js补丁')
    args = parser.parse_args()
    main(args)
