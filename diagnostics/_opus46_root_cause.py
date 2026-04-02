#!/usr/bin/env python3
"""
Claude Opus 4.6 不可用 — 根因深度解析
目标: 从底层彻底搞清楚 opus 4.6 在 Windsurf 中不可用的本质原因
"""
import sqlite3, json, os, base64, struct, re
from datetime import datetime

STATE_DB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')
WB_JS = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
EXT_JS = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'

# ── Protobuf helpers ──
def decode_varint(data, pos):
    val=0; shift=0
    while pos < len(data):
        b=data[pos]; pos+=1
        val|=(b&0x7F)<<shift; shift+=7
        if not(b&0x80): break
    return val,pos

def parse_pb_fields(data):
    """返回所有字段的(fnum, wtype, raw_val)列表"""
    result = []
    pos = 0
    while pos < len(data):
        try:
            tag,pos = decode_varint(data, pos)
            fnum=tag>>3; wtype=tag&7
            if fnum==0: break
            if wtype==0:
                val,pos = decode_varint(data, pos)
                result.append((fnum,'varint',val))
            elif wtype==2:
                length,pos = decode_varint(data, pos)
                val = data[pos:pos+length]; pos+=length
                result.append((fnum,'bytes',val))
            elif wtype==1: pos+=8; result.append((fnum,'fixed64',None))
            elif wtype==5:
                val = data[pos:pos+4]; pos+=4
                result.append((fnum,'fixed32',val))
            else: break
        except: break
    return result

def extract_strings(data, min_len=2, max_len=500):
    """从protobuf bytes中提取可读字符串"""
    strings = []
    for fnum,wtype,val in parse_pb_fields(data):
        if wtype=='bytes' and val:
            try:
                t = val.decode('utf-8')
                if min_len <= len(t) <= max_len and all(32<=ord(c)<127 or c in '\n\t' for c in t):
                    strings.append((fnum, t))
            except: pass
    return strings

def int_to_float(v):
    try: return struct.unpack('f', struct.pack('I', v & 0xFFFFFFFF))[0]
    except: return None

# ═══════════════════════════════════════════════════
# PART 1: 当前账户模型状态
# ═══════════════════════════════════════════════════
print("=" * 70)
print("PART 1: 当前账户模型状态 (state.vscdb)")
print("=" * 70)

conn = sqlite3.connect('file:'+STATE_DB+'?mode=ro', uri=True)
cur = conn.cursor()

cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
row = cur.fetchone()
auth = json.loads(row[0])

api_key = auth.get('apiKey','')
print(f"API Key: {api_key[:20]}...")
print(f"Command Models: {len(auth.get('allowedCommandModelConfigsProtoBinaryBase64',[]))}")
print(f"UserStatus size: {len(auth.get('userStatusProtoBinaryBase64',''))} chars (base64)")

# 解码所有command models
print("\n── Command Models (Cascade实际可用) ──")
for pb64 in auth.get('allowedCommandModelConfigsProtoBinaryBase64', []):
    data = base64.b64decode(pb64)
    strs = extract_strings(data)
    name = next((s for fn,s in strs if len(s)>3 and (' ' in s or '-' in s) and not s.startswith('MODEL_')), '?')
    uid  = next((s for fn,s in strs if s.startswith('MODEL_') or ('claude' in s.lower() and '-' in s)), '?')
    print(f"  {name:<45} {uid}")

# 解码 userStatus field 33 — 所有模型
print("\n── All Models in UserStatus (field 33) ──")
pb_b64 = auth.get('userStatusProtoBinaryBase64','')
data_us = base64.b64decode(pb_b64)
fields_us = parse_pb_fields(data_us)
print(f"  UserStatus bytes: {len(data_us)}")

# Count each field
field_counts = {}
for fnum,wtype,val in fields_us:
    field_counts[fnum] = field_counts.get(fnum,0)+1
print(f"  Fields present: {sorted(field_counts.items())}")

# Extract field 33 model entries
opus46_variants = []
model_entries = []
for fnum,wtype,val in fields_us:
    if fnum==33 and wtype=='bytes' and val:
        strs = extract_strings(val)
        name = next((s for fn,s in strs if len(s)>3 and not s.startswith('MODEL_') and not s.startswith('exa.')), '?')
        uid = next((s for fn,s in strs if s.startswith('MODEL_') or ('claude' in s.lower() and '-' in s) or s.startswith('gpt') or s.startswith('gemini') or s.startswith('kimi') or s.startswith('minimax') or s.startswith('glm') or s.startswith('grok')), '?')
        
        # Extract cost (fixed32 float)
        cost = 0.0
        for fn,wt,rv in parse_pb_fields(val):
            if wt=='fixed32' and rv:
                f = int_to_float(struct.unpack('<I', rv)[0])
                if f and 0 < f < 50:
                    cost = round(f, 3)
                    break
        
        model_entries.append((name, uid, cost))
        if 'opus' in name.lower() or 'opus' in uid.lower():
            opus46_variants.append((name, uid, cost))

print(f"\n  Total model entries: {len(model_entries)}")

# Check for opus 4.6 specifically
print("\n── Opus 相关模型 ──")
for name,uid,cost in model_entries:
    if 'opus' in name.lower() or 'opus' in uid.lower():
        print(f"  {name:<50} {uid:<35} {cost}x")

# All premium (cost > 4.0)
print("\n── Premium 模型 (cost > 4.0x) ──")
for name,uid,cost in sorted(model_entries, key=lambda x: -x[2]):
    if cost > 4.0:
        print(f"  {cost:<6} {name:<50} {uid}")

conn.close()

# ═══════════════════════════════════════════════════
# PART 2: workbench.js 模型过滤核心机制
# ═══════════════════════════════════════════════════
print("\n" + "=" * 70)
print("PART 2: workbench.js 模型门禁机制逆向")
print("=" * 70)

print(f"\nWorkbench.js modified: {datetime.fromtimestamp(os.path.getmtime(WB_JS))}")
print(f"Size: {os.path.getsize(WB_JS):,} bytes")

with open(WB_JS,'r',encoding='utf-8',errors='replace') as f:
    wb = f.read()

# 搜索模型选择器的核心过滤逻辑
patterns_to_find = [
    # 模型选择器渲染
    ('cascadeModelSelector', 'model selector'),
    ('setCascadeModel', 'set model'),
    ('selectedModel', 'selected model'),
    ('modelPicker', 'model picker'),
    # 禁用逻辑
    ('model.*notAvailable', 'not available check'),
    # 最重要: allowedCommandModel 使用
    ('allowedCommandModel', 'command model filter'),
]

print("\n── 核心过滤变量 ──")
for pat, desc in patterns_to_find:
    m = re.search(pat, wb, re.I)
    if m:
        pos = m.start()
        print(f"\n[{desc}] @{pos}:")
        print(wb[max(0,pos-100):pos+300][:300])
    else:
        print(f"\n[{desc}] NOT FOUND")

# ── 关键: checkChatCapacity 请求结构 ──
print("\n── CheckChatCapacity RPC ──")
idx = wb.find('CheckChatCapacity')
while idx >= 0:
    ctx = wb[max(0,idx-50):idx+300]
    if 'modelUid' in ctx or 'isCapacityLimited' in ctx or 'kind:' in ctx:
        print(f"@{idx}: {ctx[:250]}")
        print("---")
    idx = wb.find('CheckChatCapacity', idx+1)

# ── 模型不可用时的UI状态 ──
print("\n── 模型状态: disabled/locked/unavailable ──")
for pat in ['isDisabled', 'isUnavailable', 'notAvailable', 'modelDisabled']:
    hits = [m.start() for m in re.finditer(pat, wb)]
    if hits:
        pos = hits[0]
        print(f"\n[{pat}] {len(hits)} hits, first @{pos}:")
        print(wb[max(0,pos-100):pos+300][:300])

# ═══════════════════════════════════════════════════
# PART 3: 当前Windsurf版本与API端点
# ═══════════════════════════════════════════════════
print("\n" + "=" * 70)
print("PART 3: Windsurf 版本与服务端配置")
print("=" * 70)

product_json = r'D:\Windsurf\resources\app\product.json'
if os.path.exists(product_json):
    with open(product_json, 'r', encoding='utf-8') as f:
        product = json.load(f)
    print(f"Version: {product.get('version','?')}")
    print(f"Commit: {product.get('commit','?')[:12]}")
    print(f"Date: {product.get('date','?')}")
    
    # 提取Windsurf特有字段
    for k in ['defaultChatAgent', 'windsurf', 'codeium']:
        if k in product:
            print(f"\n[{k}]:")
            val = product[k]
            if isinstance(val, dict):
                for kk,vv in list(val.items())[:15]:
                    print(f"  {kk}: {str(vv)[:100]}")
else:
    print("product.json NOT FOUND at expected path")

# ═══════════════════════════════════════════════════
# PART 4: 搜索 opus 4.6 在 workbench.js 中的所有引用
# ═══════════════════════════════════════════════════
print("\n" + "=" * 70)
print("PART 4: workbench.js 中的 opus-4-6 引用分析")
print("=" * 70)

opus46_refs = [m.start() for m in re.finditer(r'opus.4.6|claude.opus.4', wb, re.I)]
print(f"\nTotal opus-4-6 references: {len(opus46_refs)}")
for pos in opus46_refs:
    ctx = wb[max(0,pos-80):pos+180]
    # Classify: native or our patch?
    is_patch = '__wam' in ctx or 'wamOpus' in ctx
    source = '[PATCH]' if is_patch else '[NATIVE]'
    print(f"\n{source} @{pos}:")
    print(ctx[:200])

# ═══════════════════════════════════════════════════
# PART 5: UserStatus 顶层字段完整解析
# ═══════════════════════════════════════════════════
print("\n" + "=" * 70)
print("PART 5: UserStatus 关键字段 (Plan/Billing/Model 控制字段)")
print("=" * 70)

conn2 = sqlite3.connect('file:'+STATE_DB+'?mode=ro', uri=True)
cur2 = conn2.cursor()
cur2.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
auth2 = json.loads(cur2.fetchone()[0])
conn2.close()

pb_b64 = auth2.get('userStatusProtoBinaryBase64','')
data_us2 = base64.b64decode(pb_b64)
fields_us2 = parse_pb_fields(data_us2)

print("\nTop-level fields:")
for fnum,wtype,val in fields_us2:
    if wtype != 'bytes':
        print(f"  F{fnum:<3} {wtype:<8} = {val}")
    else:
        # Try to decode as string
        try:
            t = val.decode('utf-8')
            if len(t) < 200 and all(32<=ord(c)<127 for c in t):
                print(f"  F{fnum:<3} bytes    = '{t}'")
            else:
                print(f"  F{fnum:<3} bytes    = <{len(val)} bytes>")
        except:
            print(f"  F{fnum:<3} bytes    = <{len(val)} bytes>")

print("\n=== DONE ===")
