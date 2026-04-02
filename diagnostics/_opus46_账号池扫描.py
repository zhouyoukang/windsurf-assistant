#!/usr/bin/env python3
"""
_opus46_账号池扫描.py — 完全解构所有账号底层opus-4-6可用性
=============================================================
道法自然·知己知彼·百战不殆

功能:
  1. 扫描全部116个账号的commandModels配置
  2. 检测每个账号的BillingStrategy和quota状态
  3. 测试服务端是否实际接受claude-opus-4-6请求
  4. 生成最优账号优先级列表

用法:
  python _opus46_账号池扫描.py           # 完整扫描(含服务端测试)
  python _opus46_账号池扫描.py --local   # 仅本地状态分析，不测试服务端
  python _opus46_账号池扫描.py --best    # 直接输出最优账号
"""
import json, sqlite3, base64, struct, os, sys, time
import urllib.request, urllib.error, ssl
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
ENGINE_DIR = SCRIPT_DIR.parent / '010-道引擎_DaoEngine'
SNAPSHOT_FILE = ENGINE_DIR / '_wam_snapshots.json'
STATE_DB = Path(os.environ.get('APPDATA','')) / 'Windsurf' / 'User' / 'globalStorage' / 'state.vscdb'
RESULT_FILE = SCRIPT_DIR / '_opus46_账号可用性.json'

# ── Protobuf helpers ──
def decode_varint(data, pos):
    val=0; shift=0
    while pos < len(data):
        b=data[pos]; pos+=1
        val|=(b&0x7F)<<shift; shift+=7
        if not(b&0x80): break
    return val, pos

def extract_strings_from_pb(data, min_len=2):
    """从protobuf bytes中提取可读字符串"""
    strings = []
    pos = 0
    while pos < len(data):
        try:
            tag, pos = decode_varint(data, pos)
            fnum = tag >> 3; wtype = tag & 7
            if wtype == 2:
                length, pos = decode_varint(data, pos)
                val = data[pos:pos+length]; pos += length
                try:
                    t = val.decode('utf-8')
                    if min_len <= len(t) <= 300 and all(32<=ord(c)<127 for c in t):
                        strings.append((fnum, t))
                except: pass
            elif wtype == 0: _, pos = decode_varint(data, pos)
            elif wtype == 1: pos += 8
            elif wtype == 5: pos += 4
            else: break
        except: break
    return strings

def decode_command_models(pb64_list):
    """解码commandModels列表，返回模型名和UID列表"""
    models = []
    for pb64 in pb64_list:
        try:
            data = base64.b64decode(pb64)
            strs = extract_strings_from_pb(data)
            uid  = next((s for fn,s in strs if 
                         ('claude' in s.lower() and '-' in s) or 
                         s.startswith('MODEL_') or s.startswith('gpt') or 
                         s.startswith('gemini') or s.startswith('swe') or
                         s.startswith('kimi') or s.startswith('minimax')), '?')
            name = next((s for fn,s in strs if 
                         len(s) > 3 and ' ' in s and not s.startswith('MODEL_') and 
                         'http' not in s), uid)
            models.append({'uid': uid, 'name': name})
        except Exception as e:
            models.append({'uid': '?', 'name': f'err:{e}'})
    return models

def analyze_account(email, snap):
    """分析单个账号的opus-4-6可用性"""
    result = {
        'email': email,
        'harvested_at': snap.get('harvested_at', '?'),
        'has_opus46_in_command_models': False,
        'has_opus45': False,
        'command_model_count': 0,
        'command_model_uids': [],
        'billing_strategy': 'unknown',
        'quota_daily': 100,
        'quota_weekly': 100,
        'api_key_prefix': '',
        'usable': True,
    }
    
    blobs = snap.get('blobs', {})
    auth_str = blobs.get('windsurfAuthStatus', '')
    if not auth_str:
        result['usable'] = False
        result['error'] = 'no_auth_blob'
        return result
    
    try:
        auth = json.loads(auth_str)
    except:
        result['usable'] = False
        result['error'] = 'invalid_json'
        return result
    
    api_key = auth.get('apiKey', '')
    result['api_key_prefix'] = api_key[:30] if api_key else ''
    
    if not api_key:
        result['usable'] = False
        result['error'] = 'no_api_key'
        return result
    
    # 解码commandModels
    cmd_models = auth.get('allowedCommandModelConfigsProtoBinaryBase64', [])
    result['command_model_count'] = len(cmd_models)
    models = decode_command_models(cmd_models)
    uids = [m['uid'] for m in models]
    result['command_model_uids'] = uids
    
    result['has_opus46_in_command_models'] = any(
        'opus-4-6' in u.lower() or 'opus_4_6' in u.lower() or 'OPUS_4_6' in u
        for u in uids
    )
    result['has_opus45'] = any(
        'opus-4-5' in u.lower() or 'CLAUDE_4_5_OPUS' in u
        for u in uids
    )
    
    # 解析cachedPlanInfo (quota状态)
    cached_plan = blobs.get('cachedPlanInfo', '')
    if cached_plan:
        try:
            plan = json.loads(cached_plan)
            quota = plan.get('quotaUsage', {})
            result['quota_daily'] = quota.get('dailyRemainingPercent', 100)
            result['quota_weekly'] = quota.get('weeklyRemainingPercent', 100)
            result['billing_strategy'] = plan.get('billingStrategy', 'unknown')
        except: pass
    
    return result

def test_server_opus46(api_key, timeout=8):
    """测试服务端是否接受claude-opus-4-6 (通过CheckChatCapacity gRPC)"""
    def encode_varint(v):
        r = []
        while v > 0x7F:
            r.append((v & 0x7F) | 0x80); v >>= 7
        r.append(v)
        return bytes(r)

    def encode_bytes_field(fnum, data):
        """Encode a length-delimited field (wire type 2) with raw bytes payload"""
        tag = encode_varint((fnum << 3) | 2)
        return tag + encode_varint(len(data)) + data

    def encode_str_field(fnum, s):
        """Encode a string field"""
        return encode_bytes_field(fnum, s.encode('utf-8'))

    try:
        # Build protobuf request body
        # CheckChatCapacityRequest { 1: GetCompletionMetadata, 3: model_uid }
        # GetCompletionMetadata { 1: api_key }
        meta_inner = encode_str_field(1, api_key)   # api_key in GetCompletionMetadata
        meta_field = encode_bytes_field(1, meta_inner)  # wrap as message field 1
        model_field = encode_str_field(3, 'claude-opus-4-6')
        proto_body = meta_field + model_field
        
        # gRPC-web frame: flag byte(0=data) + length(4 bytes big-endian)
        frame = b'\x00' + len(proto_body).to_bytes(4, 'big') + proto_body
        
        url = 'https://server.codeium.com/exa.language_server_pb.LanguageServerService/CheckChatCapacity'
        headers = {
            'Authorization': f'Basic {api_key}',
            'Content-Type': 'application/grpc-web+proto',
            'x-grpc-web': '1',
            'User-Agent': 'windsurf-ide/1.108.2',
            'x-codeium-ide-name': 'windsurf',
        }
        req = urllib.request.Request(url, data=frame, headers=headers, method='POST')
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            resp_data = resp.read(512)
            status = resp.status
            # Parse gRPC-web response
            if len(resp_data) >= 5 and resp_data[0] == 0:
                proto_len = int.from_bytes(resp_data[1:5], 'big')
                proto_resp = resp_data[5:5+proto_len]
                # Look for has_capacity (field 1, varint)
                if len(proto_resp) >= 2 and proto_resp[0] == 0x08:  # field 1, wire type 0
                    has_capacity = bool(proto_resp[1])
                    return {'ok': True, 'has_capacity': has_capacity, 'status': status}
            return {'ok': True, 'has_capacity': None, 'status': status, 'raw': resp_data[:50].hex()}
    
    except urllib.error.HTTPError as e:
        return {'ok': False, 'status': e.code, 'error': str(e.reason)}
    except Exception as e:
        return {'ok': False, 'error': str(e)[:100]}

def scan_all_accounts(test_server=True, max_server_tests=5):
    """扫描所有账号"""
    print('=' * 65)
    print(f'Claude Opus 4.6 账号池全量扫描 — {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print('=' * 65)
    
    if not SNAPSHOT_FILE.exists():
        print(f'❌ 快照文件不存在: {SNAPSHOT_FILE}')
        return None
    
    data = json.loads(SNAPSHOT_FILE.read_text('utf-8'))
    snapshots = data.get('snapshots', {})
    print(f'总账号数: {len(snapshots)}')
    
    results = []
    has_opus46_native = []
    has_opus45_only = []
    quota_high = []    # daily+weekly > 50%
    
    for email, snap in snapshots.items():
        r = analyze_account(email, snap)
        results.append(r)
        
        if r['has_opus46_in_command_models']:
            has_opus46_native.append(r)
        elif r['has_opus45']:
            has_opus45_only.append(r)
        
        if r['quota_daily'] > 50 and r['quota_weekly'] > 50 and r['usable']:
            quota_high.append(r)
    
    print(f'\n账号可用性分析:')
    print(f'  ✅ 原生含opus-4-6的账号: {len(has_opus46_native)}')
    print(f'  ⚡ 仅含opus-4-5(可通过补丁升级): {len(has_opus45_only)}')
    print(f'  💎 配额>50%的健康账号: {len(quota_high)}')
    
    # 优先级排序
    def score(r):
        s = 0
        if r['has_opus46_in_command_models']: s += 100
        if r['has_opus45']: s += 50
        if r['usable']: s += 30
        s += (r['quota_daily'] + r['quota_weekly']) / 2 * 0.2
        if '2026-03-22' in r['harvested_at']: s += 20
        elif '2026-03-21' in r['harvested_at']: s += 10
        return s
    
    results.sort(key=score, reverse=True)
    
    print(f'\nTop 10 最优账号 (按综合评分):')
    for i, r in enumerate(results[:10]):
        opus46 = '🌟opus46' if r['has_opus46_in_command_models'] else ('⚡opus45' if r['has_opus45'] else '🔵base')
        quota = f"D:{r['quota_daily']}%/W:{r['quota_weekly']}%"
        print(f'  #{i+1:2d} {r["email"][:45]:<45} {opus46} {quota} {r["harvested_at"][:10]}')
    
    # 服务端测试 (取前N个最优账号测试opus-4-6接受性)
    if test_server and results:
        print(f'\n服务端接受性测试 (前{max_server_tests}个账号)...')
        print('目标: 确认claude-opus-4-6在服务端是否仍可用')
        server_results = []
        
        test_accounts = results[:max_server_tests]
        for i, r in enumerate(test_accounts):
            if not r['api_key_prefix'] or not r['usable']:
                continue
            # 从完整auth提取api_key
            try:
                snap = snapshots[r['email']]
                auth = json.loads(snap['blobs']['windsurfAuthStatus'])
                api_key = auth.get('apiKey', '')
                if not api_key:
                    continue
            except:
                continue
            
            print(f'  [{i+1}/{max_server_tests}] {r["email"][:40]}... ', end='', flush=True)
            t0 = time.time()
            srv = test_server_opus46(api_key)
            elapsed = time.time() - t0
            
            if srv.get('ok'):
                cap = srv.get('has_capacity')
                if cap is True:
                    print(f'✅ has_capacity=True ({elapsed:.1f}s)')
                    server_results.append({'email': r['email'], 'result': 'accepted'})
                elif cap is False:
                    print(f'⚠️  has_capacity=False ({elapsed:.1f}s)')
                    server_results.append({'email': r['email'], 'result': 'denied'})
                else:
                    print(f'📊 HTTP {srv.get("status")} ({elapsed:.1f}s) raw={srv.get("raw","")}')
                    server_results.append({'email': r['email'], 'result': f'http{srv.get("status")}'})
            else:
                print(f'❌ {srv.get("error","err")[:50]} ({elapsed:.1f}s)')
                server_results.append({'email': r['email'], 'result': 'error', 'error': srv.get('error','')})
        
        accepted = [s for s in server_results if s['result'] == 'accepted']
        print(f'\n服务端测试结果: {len(accepted)}/{len(server_results)} 接受 opus-4-6')
        
        if accepted:
            print('✅ 服务端确认接受 claude-opus-4-6！')
            print('   这些账号可以直接使用Opus 4.6 (服务端无需特殊权限)')
        else:
            print('⚠️  测试账号均被服务端拒绝/无法确认')
            print('   但补丁仍然有效：GBe静默 + 账号池轮换可继续工作')
    
    # 保存结果
    output = {
        'scan_time': datetime.now().isoformat(),
        'total': len(results),
        'has_opus46_native': len(has_opus46_native),
        'has_opus45': len(has_opus45_only),
        'quota_high': len(quota_high),
        'top_accounts': results[:20],
    }
    RESULT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n📄 结果已保存: {RESULT_FILE}')
    
    return results

def print_best_account():
    """输出最优账号信息"""
    if RESULT_FILE.exists():
        data = json.loads(RESULT_FILE.read_text('utf-8'))
        top = data.get('top_accounts', [{}])[0]
        print(f'最优账号: {top.get("email","?")}')
        print(f'配额: D:{top.get("quota_daily","?")}%  W:{top.get("quota_weekly","?")}%')
        print(f'opus-4-6 native: {top.get("has_opus46_in_command_models","?")}')
        return top
    else:
        results = scan_all_accounts(test_server=False)
        if results:
            print(f'最优账号: {results[0]["email"]}')
            return results[0]
    return None

if __name__ == '__main__':
    args = sys.argv[1:]
    
    if '--best' in args:
        print_best_account()
    elif '--local' in args:
        scan_all_accounts(test_server=False)
    else:
        max_tests = 3
        for i, a in enumerate(args):
            if a == '--tests' and i+1 < len(args):
                max_tests = int(args[i+1])
        scan_all_accounts(test_server=True, max_server_tests=max_tests)
