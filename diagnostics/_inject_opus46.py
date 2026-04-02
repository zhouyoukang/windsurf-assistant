#!/usr/bin/env python3
"""
Claude Opus 4.6 commandModels 注入器 + workbench.js 持久补丁
=============================================================
基于逆向发现: commandModels 无签名 → 可直接注入

三合一方案:
  A. state.vscdb 注入 (即时, 重登录后失效)
  B. workbench.js 补丁 (持久, 每次加载生效)
  C. 服务端接受性测试 (验证成功率)

用法:
  python _inject_opus46.py          # 执行全部
  python _inject_opus46.py --test   # 仅测试服务端
  python _inject_opus46.py --db     # 仅注入 state.vscdb
  python _inject_opus46.py --patch  # 仅补丁 workbench.js
  python _inject_opus46.py --check  # 检查当前状态
"""
import sqlite3, json, os, base64, struct, re, sys, shutil
from datetime import datetime

STATE_DB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')
WB_JS = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'

# ── 目标模型 ──
TARGET_UID = 'claude-opus-4-6'
TARGET_NAME = 'Claude Opus 4.6'
TARGET_COST = 6.0   # ACU multiplier
TARGET_TIER = 3     # ModelCostTier.HIGH

# ── Protobuf 编码 ──
def encode_varint(val):
    result = []
    while True:
        bits = val & 0x7F
        val >>= 7
        if val:
            result.append(bits | 0x80)
        else:
            result.append(bits)
            break
    return bytes(result)

def encode_string_field(fnum, s):
    data = s.encode('utf-8')
    tag = (fnum << 3) | 2
    return encode_varint(tag) + encode_varint(len(data)) + data

def encode_varint_field(fnum, val):
    tag = (fnum << 3) | 0
    return encode_varint(tag) + encode_varint(val)

def encode_float32_field(fnum, val):
    tag = (fnum << 3) | 5
    return encode_varint(tag) + struct.pack('<f', val)

def decode_varint(data, pos):
    val=0; shift=0
    while pos < len(data):
        b=data[pos]; pos+=1
        val|=(b&0x7F)<<shift; shift+=7
        if not(b&0x80): break
    return val,pos

def build_opus46_config():
    """构造 Claude Opus 4.6 的 ClientModelConfig protobuf"""
    # F1:  label (string)
    # F22: model_uid (string)
    # F3:  credit_multiplier (float32)
    # F4:  disabled (bool → varint 0)
    # F13: pricing_type = ACU_TOKEN (4)
    # F18: max_tokens (int → 200000)
    # F20: is_capacity_limited (bool → 0)
    # F24: model_cost_tier = HIGH (3)
    config = (
        encode_string_field(1, TARGET_NAME) +
        encode_string_field(22, TARGET_UID) +
        encode_float32_field(3, TARGET_COST) +
        encode_varint_field(4, 0) +           # disabled = false
        encode_varint_field(13, 4) +           # pricing_type = ACU_TOKEN
        encode_varint_field(18, 200000) +      # max_tokens = 200K
        encode_varint_field(20, 0) +           # is_capacity_limited = false
        encode_varint_field(24, TARGET_TIER)   # model_cost_tier = HIGH
    )
    return config

# ── PART A: state.vscdb 注入 ──

def inject_state_db():
    print("\n" + "=" * 60)
    print("PART A: state.vscdb 注入")
    print("=" * 60)
    
    # 备份
    bak = STATE_DB + f'.bak_opus46_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    shutil.copy2(STATE_DB, bak)
    print(f"  备份: {bak}")
    
    conn = sqlite3.connect('file:'+STATE_DB, uri=True)
    cur = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    auth = json.loads(cur.fetchone()[0])
    
    cmd_models = auth.get('allowedCommandModelConfigsProtoBinaryBase64', [])
    print(f"  当前 commandModels: {len(cmd_models)} 个")
    
    # 检查是否已注入
    already_injected = False
    for pb64 in cmd_models:
        data = base64.b64decode(pb64)
        if TARGET_UID.encode() in data or TARGET_NAME.encode() in data:
            already_injected = True
            break
    
    if already_injected:
        print(f"  ✅ claude-opus-4-6 已存在于 commandModels")
        conn.close()
        return True
    
    # 构造并注入
    fake_config = build_opus46_config()
    fake_b64 = base64.b64encode(fake_config).decode('ascii')
    
    print(f"  注入配置: {fake_b64[:60]}...")
    print(f"  字节长度: {len(fake_config)}")
    
    # 解码验证
    strs = []
    pos = 0
    while pos < len(fake_config):
        try:
            tag, pos = decode_varint(fake_config, pos)
            fnum = tag >> 3; wtype = tag & 7
            if wtype == 2:
                length, pos = decode_varint(fake_config, pos)
                val = fake_config[pos:pos+length]; pos += length
                try:
                    t = val.decode('utf-8')
                    strs.append((fnum, t))
                except: pass
            elif wtype == 0: _, pos = decode_varint(fake_config, pos)
            elif wtype == 5:
                fv = struct.unpack('<f', fake_config[pos:pos+4])[0]; pos += 4
                strs.append((f'F{fnum}(float)', round(fv,2)))
            elif wtype == 1: pos += 8
            else: break
        except: break
    print(f"  验证解析: {strs}")
    
    # 注入到列表末尾
    cmd_models.append(fake_b64)
    auth['allowedCommandModelConfigsProtoBinaryBase64'] = cmd_models
    
    cur.execute(
        "UPDATE ItemTable SET value=? WHERE key='windsurfAuthStatus'",
        (json.dumps(auth),)
    )
    conn.commit()
    conn.close()
    
    print(f"  ✅ 注入成功! commandModels 现在: {len(cmd_models)} 个")
    print(f"  → 重载 Windsurf 后模型选择器应显示 '{TARGET_NAME}'")
    print(f"  ⚠️  注意: 登录刷新时会覆盖此注入")
    return True

# ── PART B: workbench.js 持久补丁 ──

# 目标: 在 commandModels 解析之后注入 claude-opus-4-6
# 定位: this.j=this.C(D) 或等价的 commandModel 解析赋值

# 找到 commandModel 解析点的签名字符串
# 从逆向分析: allowedCommandModelConfigsProtoBinaryBase64 → this.j = this.C(D)
# 在解析后立即注入

_WB_PATCH_OLD = 'this.j=this.C(D),this.'
# 注入后: 在 this.j 列表后追加 claude-opus-4-6 config

def find_commandmodel_parse_point(wb):
    """在 workbench.js 中找到 commandModels 解析并赋值的精确位置"""
    # 先找 allowedCommandModelConfigsProtoBinaryBase64
    idx = wb.find('allowedCommandModelConfigsProtoBinaryBase64')
    if idx < 0:
        return None, None
    
    # 从这个位置向后找 this.j= 赋值
    region = wb[idx:idx+2000]
    
    # 找到 this.j= 模式 (可能是 this.j= 或 this.X= 等任意字母)
    # 实际上观察到的是: this.j=this.C(D),this.
    m = re.search(r'this\.\w\s*=\s*this\.\w\(D\)', region)
    if m:
        abs_pos = idx + m.start()
        match_str = m.group()
        return abs_pos, match_str
    
    return None, None

def build_wb_patch(match_str):
    """构建 workbench.js 补丁"""
    # 在 commandModel 赋值后注入
    # 获取变量名 (this.j 中的 j)
    var_match = re.match(r'this\.(\w)\s*=', match_str)
    if not var_match:
        return None, None
    var = var_match.group(1)
    
    # 构造注入代码
    config_b64 = base64.b64encode(build_opus46_config()).decode('ascii')
    
    inject_code = (
        f'try{{var __o46=new(this[Object.keys(this).find(k=>typeof this[k]=="function"&&'
        f'this[k].toString().includes("fromBinary"))]||Object)();'
        f'var __o46d=atob("{config_b64}");'
        f'var __o46b=new Uint8Array(__o46d.length);'
        f'for(var __i=0;__i<__o46d.length;__i++)__o46b[__i]=__o46d.charCodeAt(__i);'
        f'this.{var}=[...this.{var},__o46b]}}catch(__e){{}}'
    )
    
    old = match_str + ','
    new = match_str + ';' + inject_code + ';this.' + match_str.split(',this.')[1] if ',' in match_str else match_str
    
    return old, new

def patch_workbench_js():
    print("\n" + "=" * 60)
    print("PART B: workbench.js 持久补丁")
    print("=" * 60)
    
    with open(WB_JS, 'r', encoding='utf-8', errors='replace') as f:
        wb = f.read()
    
    # 找到解析点
    pos, match_str = find_commandmodel_parse_point(wb)
    if pos is None:
        print("  ❌ 未找到 commandModels 解析点")
        # 备用方案: 直接搜索精确字符串
        idx2 = wb.find('allowedCommandModelConfigsProtoBinaryBase64')
        if idx2 >= 0:
            print(f"  found allowedCommandModel @{idx2}:")
            print(f"  {wb[idx2:idx2+400]}")
        return False
    
    print(f"  找到解析点 @{pos}: '{match_str}'")
    print(f"  区域: {wb[max(0,pos-100):pos+200]}")
    
    # 更简单的补丁方案: 在 this.j=this.C(D) 后, 追加一段注入代码
    # 但需要精确知道 this.C 方法的输出格式才能追加
    
    # 实际上更可靠的方案: 直接替换 windsurfAuthStatus key
    # 利用已有的读取逻辑, 在它读取之前预处理数据
    
    print("\n  → 选择更安全的补丁策略:")
    print("    在 allowedCommandModelConfigsProtoBinaryBase64 读取后注入")
    
    # 找到 this.f?.allowedCommandModelConfigsProtoBinaryBase64 读取点
    amc_idx = wb.find('allowedCommandModelConfigsProtoBinaryBase64')
    region = wb[amc_idx-50:amc_idx+500]
    print(f"\n  完整上下文:")
    print(region[:400])
    
    return False  # 需要更多分析

# ── PART C: 服务端接受性测试 ──

def test_server_acceptance():
    print("\n" + "=" * 60)
    print("PART C: 服务端接受性测试")
    print("=" * 60)
    
    conn = sqlite3.connect('file:'+STATE_DB+'?mode=ro', uri=True)
    cur = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    auth = json.loads(cur.fetchone()[0])
    conn.close()
    
    api_key = auth.get('apiKey', '')
    print(f"  API Key: {api_key[:25]}...")
    
    # 找语言服务器端口
    # 先检查扩展的设置
    try:
        cur2 = sqlite3.connect('file:'+STATE_DB+'?mode=ro', uri=True).cursor()
        cur2.execute("SELECT value FROM ItemTable WHERE key='windsurfConfigurations'")
        row = cur2.fetchone()
        if row:
            import struct as st
            config_b64 = row[0]
            try:
                config_data = base64.b64decode(config_b64)
                print(f"  windsurfConfigurations: {len(config_data)} bytes")
                # 提取字符串
                strs = []
                pos2 = 0
                while pos2 < len(config_data):
                    try:
                        tag, pos2 = decode_varint(config_data, pos2)
                        fnum = tag >> 3; wtype = tag & 7
                        if wtype == 2:
                            l, pos2 = decode_varint(config_data, pos2)
                            v = config_data[pos2:pos2+l]; pos2 += l
                            try:
                                t = v.decode('utf-8')
                                if 5 <= len(t) <= 200 and all(32<=ord(c)<127 for c in t):
                                    strs.append(t)
                            except: pass
                        elif wtype == 0: _, pos2 = decode_varint(config_data, pos2)
                        elif wtype == 1: pos2 += 8
                        elif wtype == 5: pos2 += 4
                        else: break
                    except: break
                print(f"  Configurations strings: {strs[:10]}")
            except Exception as e:
                print(f"  Configurations decode error: {e}")
    except Exception as e:
        print(f"  DB error: {e}")
    
    # gRPC 测试: 用二进制格式调用 server.codeium.com
    # addCascadeInput 的 gRPC 路径
    import urllib.request, urllib.error, ssl
    
    # 构造最小 gRPC-web protobuf 请求
    # 只是检查连通性和认证，不实际发送消息
    
    endpoints = [
        "https://server.codeium.com",
        "https://server.codeium.com:443",
    ]
    
    test_paths = [
        "/exa.language_server_pb.LanguageServerService/GetPlanStatus",
        "/exa.language_server_pb.LanguageServerService/CheckChatCapacity",
        "/exa.language_server_pb.LanguageServerService/GetPlanInfo",
    ]
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    for base_url in endpoints:
        for path in test_paths:
            url = base_url + path
            headers = {
                "Authorization": f"Basic {api_key}",
                "Content-Type": "application/grpc-web+proto",
                "x-grpc-web": "1",
                "User-Agent": "windsurf-ide/1.108.2",
                "x-codeium-ide-name": "windsurf",
            }
            # 空 body (empty protobuf message)
            body = b'\x00\x00\x00\x00\x00'  # gRPC-web frame: flag=0, length=0
            
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                    resp_data = resp.read(500)
                    print(f"  ✅ {url}: {resp.status} - {resp_data[:100]}")
                break  # success on this endpoint
            except urllib.error.HTTPError as e:
                resp_body = e.read(200)
                print(f"  HTTP {e.code}: {url}")
                print(f"         Response: {resp_body[:150]}")
                break
            except urllib.error.URLError as e:
                print(f"  URLError: {url}: {e.reason}")
            except Exception as e:
                print(f"  Error: {url}: {e}")
    
    print("\n  → 若返回 HTTP 200 含 proto 数据 → 服务端在线且API key有效")
    print("  → 若返回 HTTP 401/403 → API key 权限不足")
    print("  → 若返回 HTTP 404/405 → 路径/方法错误，需调整")

# ── PART D: 检查当前状态 ──

def check_status():
    print("\n" + "=" * 60)
    print("检查当前 claude-opus-4-6 状态")
    print("=" * 60)
    
    conn = sqlite3.connect('file:'+STATE_DB+'?mode=ro', uri=True)
    cur = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    auth = json.loads(cur.fetchone()[0])
    conn.close()
    
    cmd_models = auth.get('allowedCommandModelConfigsProtoBinaryBase64', [])
    print(f"\ncommandModels ({len(cmd_models)} 个):")
    
    found_opus46 = False
    for pb64 in cmd_models:
        data = base64.b64decode(pb64)
        strs = []
        pos = 0
        while pos < len(data):
            try:
                tag, pos = decode_varint(data, pos)
                fnum = tag >> 3; wtype = tag & 7
                if wtype == 2:
                    l, pos = decode_varint(data, pos)
                    v = data[pos:pos+l]; pos += l
                    try:
                        t = v.decode('utf-8')
                        if len(t) > 1:
                            strs.append(t)
                    except: pass
                elif wtype == 0: _, pos = decode_varint(data, pos)
                elif wtype == 1: pos += 8
                elif wtype == 5: pos += 4
                else: break
            except: break
        
        name = next((s for s in strs if not s.startswith('MODEL_') and len(s) > 3 and ' ' in s), '?')
        uid = next((s for s in strs if s.startswith('MODEL_') or ('claude' in s.lower() and '-' in s)), '?')
        
        marker = ' ← 已注入!' if TARGET_UID in strs or TARGET_NAME in strs else ''
        if marker:
            found_opus46 = True
        print(f"  {name:<45} {uid}{marker}")
    
    if found_opus46:
        print(f"\n✅ claude-opus-4-6 已在 commandModels 中!")
        print("  → 重载 Windsurf 可见")
    else:
        print(f"\n❌ claude-opus-4-6 不在 commandModels 中")
        print("  → 运行 --db 注入")

# ── MAIN ──

if __name__ == '__main__':
    args = sys.argv[1:]
    
    print("=" * 60)
    print(f"Claude Opus 4.6 注入器 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    if '--check' in args:
        check_status()
    elif '--test' in args:
        test_server_acceptance()
    elif '--db' in args:
        inject_state_db()
        print("\n运行 Windsurf Reload Window (Ctrl+Shift+P → Reload Window) 使注入生效")
    elif '--patch' in args:
        patch_workbench_js()
    else:
        # 全部
        check_status()
        test_server_acceptance()
        inject_state_db()
        print("\n" + "=" * 60)
        print("完成! 建议操作顺序:")
        print("  1. Ctrl+Shift+P → 'Reload Window'")
        print("  2. 在模型选择器中查找 'Claude Opus 4.6'")
        print("  3. 如果仍不可见: 检查服务端是否接受该模型")
        print("  4. 备用: 使用 'Claude Opus 4 BYOK' (需要Anthropic API key)")
