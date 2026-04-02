"""
Windsurf Deep Reverse Engineering v9.0
道法自然 — 从表象推本质，从现象推本源

完全解构当前Windsurf Quota/ACU机制:
1. 提取所有protobuf定义 (workbench.js + extension.js)
2. 解码当前用户状态 (state.vscdb)
3. 解构模型矩阵与ACU定价
4. 映射完整计费流程
5. 定位本地可控路径
"""

import sqlite3, json, os, base64, struct, re, sys
from datetime import datetime, timezone

# === Paths ===
WORKBENCH_JS = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
EXTENSION_JS = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
STATE_DB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')
PRODUCT_JSON = r'D:\Windsurf\resources\app\product.json'
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# === Protobuf Decoder ===
def decode_varint(data, pos):
    val = 0; shift = 0
    while pos < len(data):
        b = data[pos]; pos += 1
        val |= (b & 0x7F) << shift; shift += 7
        if not (b & 0x80): break
    return val, pos

def parse_pb_raw(data):
    """Parse protobuf into list of (field_num, wire_type, raw_value)"""
    result = []
    pos = 0
    while pos < len(data):
        try:
            tag, pos = decode_varint(data, pos)
            fnum = tag >> 3; wtype = tag & 7
            if fnum == 0: break
            if wtype == 0:
                val, pos = decode_varint(data, pos)
                result.append((fnum, 'varint', val))
            elif wtype == 1:
                val = data[pos:pos+8]; pos += 8
                result.append((fnum, 'fixed64', val))
            elif wtype == 2:
                length, pos = decode_varint(data, pos)
                val = data[pos:pos+length]; pos += length
                result.append((fnum, 'bytes', val))
            elif wtype == 5:
                val = data[pos:pos+4]; pos += 4
                result.append((fnum, 'fixed32', val))
            else:
                break
        except:
            break
    return result

def try_decode_string(data):
    try:
        txt = data.decode('utf-8')
        if all(32 <= ord(c) < 127 or c in '\n\r\t' for c in txt):
            return txt
    except:
        pass
    return None

def decode_pb_recursive(data, depth=0, max_depth=4):
    """Recursive protobuf decoder returning structured data"""
    if depth > max_depth:
        return f"<{len(data)}B>"
    
    fields = {}
    for fnum, wtype, val in parse_pb_raw(data):
        if wtype == 'varint':
            fields.setdefault(fnum, []).append(val)
        elif wtype == 'fixed64':
            # Could be double, int64, or uint64
            d = struct.unpack('<d', val)[0]
            i = struct.unpack('<q', val)[0]
            fields.setdefault(fnum, []).append({'double': d, 'int64': i})
        elif wtype == 'fixed32':
            f_val = struct.unpack('<f', val)[0]
            i_val = struct.unpack('<I', val)[0]
            fields.setdefault(fnum, []).append({'float': f_val, 'uint32': i_val})
        elif wtype == 'bytes':
            txt = try_decode_string(val)
            if txt is not None:
                fields.setdefault(fnum, []).append(txt)
            else:
                sub = decode_pb_recursive(val, depth+1)
                if isinstance(sub, dict) and len(sub) > 0:
                    fields.setdefault(fnum, []).append(sub)
                else:
                    fields.setdefault(fnum, []).append(f"<{len(val)}B>")
    return fields

# ========================================
# PART 1: Extract Proto Definitions from JS
# ========================================

def extract_proto_defs(js_path, type_names):
    """Extract protobuf field definitions from minified JS"""
    with open(js_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    
    results = {}
    for type_name in type_names:
        idx = content.find(type_name)
        if idx < 0:
            results[type_name] = None
            continue
        
        # Find the nearest preceding newFieldList
        search_back = min(5000, idx)
        search_region = content[max(0, idx - search_back):idx + 2000]
        
        # Find ALL newFieldList blocks and pick the closest one before typeName
        type_pos_in_region = search_back
        all_field_lists = []
        fl_idx = 0
        while True:
            fl_idx = search_region.find('newFieldList(', fl_idx)
            if fl_idx < 0:
                break
            # Find matching end
            bracket_count = 0
            end_idx = fl_idx
            started = False
            for ci in range(fl_idx, min(fl_idx + 5000, len(search_region))):
                c = search_region[ci]
                if c == '[':
                    bracket_count += 1
                    started = True
                elif c == ']':
                    bracket_count -= 1
                    if started and bracket_count == 0:
                        all_field_lists.append((fl_idx, search_region[fl_idx:ci+1]))
                        break
            fl_idx += 1
        
        # Pick the one closest to (and before) the typeName
        best = None
        for fl_pos, fl_content in all_field_lists:
            if fl_pos < type_pos_in_region:
                best = fl_content
        
        if best:
            # Parse field definitions
            pattern = r'no:(\d+),name:"([^"]+)",kind:"([^"]+)"'
            fields = re.findall(pattern, best)
            
            # Also capture optional flag
            opt_pattern = r'no:(\d+),name:"([^"]+)",kind:"([^"]+)"[^}]*opt:!0'
            opt_fields = set(m[0] for m in re.findall(opt_pattern, best))
            
            parsed = []
            for f in fields:
                parsed.append({
                    'no': int(f[0]),
                    'name': f[1],
                    'kind': f[2],
                    'optional': f[0] in opt_fields
                })
            results[type_name] = parsed
        else:
            results[type_name] = None
    
    return results

# ========================================
# PART 2: Extract Enums from JS
# ========================================

def extract_enums(js_path, enum_names):
    """Extract enum definitions from minified JS"""
    with open(js_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    
    results = {}
    for enum_name in enum_names:
        # Pattern: L[L.NAME=0]="NAME"
        # Search for the enum's setEnumType call
        idx = content.find(f'setEnumType({enum_name}')
        if idx < 0:
            # Try alternate pattern
            idx = content.find(f'"{enum_name}"')
        
        if idx < 0:
            results[enum_name] = None
            continue
        
        # Extract the definition block
        region = content[max(0, idx-500):idx+1000]
        
        # Pattern: L[L.VALUE=N]="VALUE"
        values = re.findall(r'(\w+)\[(\w+)\.(\w+)=(\d+)\]="(\w+)"', region)
        if values:
            results[enum_name] = [(v[2], int(v[3])) for v in values]
        else:
            # Try setEnumType format: {no:N,name:"NAME"}
            values = re.findall(r'no:(\d+),name:"([^"]+)"', region)
            results[enum_name] = [(v[1], int(v[0])) for v in values]
    
    return results

# ========================================
# PART 3: Decode Current State
# ========================================

def decode_state_db():
    """Extract and decode all relevant data from state.vscdb"""
    conn = sqlite3.connect(f'file:{STATE_DB}?mode=ro', uri=True)
    cur = conn.cursor()
    
    result = {}
    
    # 1. Auth status
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    row = cur.fetchone()
    if row:
        auth = json.loads(row[0])
        result['apiKey'] = auth.get('apiKey', '')[:20] + '...'
        result['commandModelCount'] = len(auth.get('allowedCommandModelConfigsProtoBinaryBase64', []))
        result['userStatusSize'] = len(auth.get('userStatusProtoBinaryBase64', ''))
        
        # Decode command models
        cmd_models = []
        for pb64 in auth.get('allowedCommandModelConfigsProtoBinaryBase64', []):
            data = base64.b64decode(pb64)
            fields = decode_pb_recursive(data)
            cmd_models.append(fields)
        result['commandModels'] = cmd_models
        
        # Decode top-level userStatus
        pb_b64 = auth.get('userStatusProtoBinaryBase64', '')
        if pb_b64:
            data = base64.b64decode(pb_b64)
            result['userStatusBytes'] = len(data)
            
            # Get top-level field catalog
            raw_fields = parse_pb_raw(data)
            catalog = {}
            for fnum, wtype, val in raw_fields:
                if fnum not in catalog:
                    catalog[fnum] = {'type': wtype, 'count': 0, 'sizes': []}
                catalog[fnum]['count'] += 1
                if wtype == 'bytes':
                    catalog[fnum]['sizes'].append(len(val))
                elif wtype == 'varint':
                    catalog[fnum]['sizes'].append(val)
            result['userStatusFieldCatalog'] = catalog
            
            # Decode PlanStatus (field 7 in userStatus)
            for fnum, wtype, val in raw_fields:
                if fnum == 7 and wtype == 'bytes':
                    plan_status = decode_pb_recursive(val, depth=0)
                    result['planStatus_raw'] = plan_status
            
            # Decode field 33 (model configs)
            model_configs = []
            for fnum, wtype, val in raw_fields:
                if fnum == 33 and wtype == 'bytes':
                    model_data = decode_pb_recursive(val, depth=0)
                    model_configs.append(model_data)
            result['modelConfigCount'] = len(model_configs)
            if model_configs:
                result['modelConfigSample'] = model_configs[:5]
    
    # 2. Cached plan info
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurf.settings.cachedPlanInfo'")
    row = cur.fetchone()
    if row:
        result['cachedPlanInfo'] = json.loads(row[0])
    
    # 3. Windsurf configurations (protobuf)
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfConfigurations'")
    row = cur.fetchone()
    if row:
        try:
            config_data = base64.b64decode(row[0])
            result['windsurfConfigSize'] = len(config_data)
            config_fields = decode_pb_recursive(config_data, depth=0)
            result['windsurfConfig'] = config_fields
        except:
            result['windsurfConfig'] = 'decode_failed'
    
    # 4. Account count
    cur.execute("SELECT key FROM ItemTable WHERE key LIKE 'windsurf_auth-%'")
    accounts = [r[0] for r in cur.fetchall()]
    result['accountCount'] = len(accounts)
    result['accounts'] = [a.replace('windsurf_auth-', '').replace('-usages', '') for a in accounts]
    
    conn.close()
    return result

# ========================================
# PART 4: Extract Quota Enforcement Flow
# ========================================

def extract_quota_flow(ext_js_path):
    """Extract quota enforcement logic from extension.js"""
    with open(ext_js_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    
    flows = {}
    
    # 1. Find billingStrategy translation
    targets = [
        ('billing_strategy_translation', 'billingStrategy===', 500),
        ('quota_construction', 'dailyRemainingPercent', 500),
        ('rate_limit_check', 'checkUserMessageRateLimit', 800),
        ('chat_capacity_check', 'checkChatCapacity', 800),
        ('plan_status_fetch', 'GetPlanStatus', 500),
        ('quota_remaining_event', 'onDidChangeQuota', 500),
        ('send_cascade_input', 'sendCascadeInput', 500),
        ('add_cascade_input', 'addCascadeInput', 500),
        ('cortex_error', 'INSUFFICIENT', 500),
    ]
    
    for name, pattern, ctx in targets:
        idx = content.find(pattern)
        if idx >= 0:
            start = max(0, idx - 200)
            end = min(len(content), idx + ctx)
            flows[name] = content[start:end].replace('\n', ' ')[:700]
        else:
            flows[name] = 'NOT_FOUND'
    
    return flows

# ========================================
# PART 5: Extract Model Pricing from userStatus
# ========================================

def extract_model_matrix(auth_data):
    """Extract complete model matrix with ACU pricing from userStatus protobuf"""
    pb_b64 = auth_data.get('userStatusProtoBinaryBase64', '')
    if not pb_b64:
        return []
    
    data = base64.b64decode(pb_b64)
    raw_fields = parse_pb_raw(data)
    
    models = []
    for fnum, wtype, val in raw_fields:
        if fnum == 33 and wtype == 'bytes':
            # Each field 33 is a model config
            model_raw = parse_pb_raw(val)
            model = {'_raw_fields': {}}
            
            for mf, mw, mv in model_raw:
                if mw == 'varint':
                    model['_raw_fields'].setdefault(mf, []).append(mv)
                elif mw == 'bytes':
                    txt = try_decode_string(mv)
                    if txt:
                        model['_raw_fields'].setdefault(mf, []).append(txt)
                    else:
                        sub = decode_pb_recursive(mv, depth=0)
                        model['_raw_fields'].setdefault(mf, []).append(sub)
                elif mw == 'fixed32':
                    f_val = struct.unpack('<f', mv)[0]
                    i_val = struct.unpack('<I', mv)[0]
                    model['_raw_fields'].setdefault(mf, []).append({'float': round(f_val, 6), 'uint32': i_val})
                elif mw == 'fixed64':
                    d_val = struct.unpack('<d', mv)[0]
                    model['_raw_fields'].setdefault(mf, []).append({'double': round(d_val, 6)})
            
            # Extract known fields
            strings = []
            ints = []
            floats = []
            for field_no, values in model['_raw_fields'].items():
                for v in values:
                    if isinstance(v, str):
                        strings.append((field_no, v))
                    elif isinstance(v, int):
                        ints.append((field_no, v))
                    elif isinstance(v, dict):
                        if 'float' in v:
                            floats.append((field_no, v['float']))
                        elif 'double' in v:
                            floats.append((field_no, v['double']))
            
            model['strings'] = strings
            model['ints'] = ints
            model['floats'] = floats
            
            # Guess name: longest string that isn't an enum
            name_candidates = [(fn, s) for fn, s in strings if len(s) > 2 and not s.startswith('MODEL_')]
            uid_candidates = [(fn, s) for fn, s in strings if s.startswith('MODEL_') or '/' in s]
            
            model['name'] = name_candidates[0][1] if name_candidates else '?'
            model['uid'] = uid_candidates[0][1] if uid_candidates else '?'
            
            models.append(model)
    
    return models

# ========================================
# MAIN EXECUTION
# ========================================

if __name__ == '__main__':
    print("=" * 70)
    print("Windsurf Deep Reverse v9.0 — 道法自然")
    print(f"Time: {datetime.now().isoformat()}")
    print("=" * 70)
    
    output = {
        '_meta': {
            'timestamp': datetime.now().isoformat(),
            'windsurf_install': r'D:\Windsurf',
            'workbench_js': WORKBENCH_JS,
            'extension_js': EXTENSION_JS,
        }
    }
    
    # --- PART 1: Proto Definitions ---
    print("\n[1/5] Extracting protobuf definitions from workbench.js...")
    proto_types = [
        'exa.codeium_common_pb.PlanInfo',
        'exa.codeium_common_pb.PlanStatus',
        'exa.cortex_pb.CortexStepMetadata',
        'exa.cortex_pb.ChatModelMetadata',
        'exa.cortex_pb.ExecutorMetadata',
        'exa.codeium_common_pb.ModelUsageStats',
        'exa.cortex_pb.CascadeExecutorConfig',
        'exa.language_server_pb.CheckUserMessageRateLimitResponse',
        'exa.language_server_pb.CheckUserMessageRateLimitRequest',
        'exa.language_server_pb.CheckChatCapacityResponse',
        'exa.language_server_pb.CheckChatCapacityRequest',
    ]
    proto_defs = extract_proto_defs(WORKBENCH_JS, proto_types)
    output['protobuf_definitions'] = {}
    for name, fields in proto_defs.items():
        short_name = name.split('.')[-1]
        if fields:
            print(f"  {short_name}: {len(fields)} fields")
            for f in fields:
                opt = " [optional]" if f['optional'] else ""
                print(f"    F{f['no']:<3} {f['name']:<45} {f['kind']}{opt}")
            output['protobuf_definitions'][short_name] = fields
        else:
            print(f"  {short_name}: NOT FOUND")
    
    # --- PART 1b: Enums ---
    print("\n  Extracting enums...")
    enum_names = ['BillingStrategy', 'ModelPricingType', 'ModelCostTier', 
                  'ExecutorTerminationReason', 'GracePeriodStatus']
    enums = extract_enums(WORKBENCH_JS, enum_names)
    output['enums'] = {}
    for name, values in enums.items():
        if values:
            print(f"  {name}: {values}")
            output['enums'][name] = values
    
    # --- PART 2: Current State ---
    print("\n[2/5] Extracting current state from state.vscdb...")
    state = decode_state_db()
    print(f"  API Key: {state.get('apiKey', 'N/A')}")
    print(f"  Command Models: {state.get('commandModelCount', 0)}")
    print(f"  Model Configs: {state.get('modelConfigCount', 0)}")
    print(f"  Accounts: {state.get('accountCount', 0)}")
    print(f"  Cached Plan: {json.dumps(state.get('cachedPlanInfo', {}), indent=4)}")
    
    # userStatus field catalog
    catalog = state.get('userStatusFieldCatalog', {})
    if catalog:
        print(f"\n  userStatus field catalog ({state.get('userStatusBytes', 0)} bytes):")
        for fnum in sorted(catalog.keys()):
            f = catalog[fnum]
            size_info = f['sizes'][:3] if f['count'] <= 3 else f['sizes'][:2] + ['...']
            print(f"    F{fnum:<4} {f['type']:<8} count={f['count']:<5} samples={size_info}")
    
    output['state'] = {
        'cachedPlanInfo': state.get('cachedPlanInfo'),
        'accounts': state.get('accounts'),
        'commandModelCount': state.get('commandModelCount'),
        'modelConfigCount': state.get('modelConfigCount'),
        'userStatusFieldCatalog': {str(k): v for k, v in catalog.items()} if catalog else None,
    }
    
    # --- PART 3: Model Matrix ---
    print("\n[3/5] Extracting model matrix with ACU pricing...")
    conn = sqlite3.connect(f'file:{STATE_DB}?mode=ro', uri=True)
    cur = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    auth = json.loads(cur.fetchone()[0])
    conn.close()
    
    models = extract_model_matrix(auth)
    print(f"  Total models in userStatus: {len(models)}")
    
    # Print model summary
    model_summary = []
    for i, m in enumerate(models):
        name = m['name']
        uid = m['uid']
        ints_str = ', '.join(f"F{fn}={v}" for fn, v in m['ints'][:5])
        floats_str = ', '.join(f"F{fn}={v}" for fn, v in m['floats'][:3])
        print(f"  [{i:>3}] {name:<40} uid={uid:<30} ints=[{ints_str}] floats=[{floats_str}]")
        model_summary.append({
            'index': i,
            'name': name,
            'uid': uid,
            'int_fields': m['ints'][:8],
            'float_fields': m['floats'][:5],
            'string_fields': m['strings'][:5],
        })
    
    output['model_matrix'] = model_summary
    
    # --- PART 4: Quota Enforcement Flow ---
    print("\n[4/5] Extracting quota enforcement flow from extension.js...")
    flows = extract_quota_flow(EXTENSION_JS)
    for name, code in flows.items():
        if code != 'NOT_FOUND':
            print(f"  {name}: {code[:150]}...")
        else:
            print(f"  {name}: NOT FOUND")
    output['quota_flows'] = flows
    
    # --- PART 5: Key Code Offsets ---
    print("\n[5/5] Mapping key code offsets...")
    with open(WORKBENCH_JS, 'r', encoding='utf-8', errors='replace') as f:
        wb_content = f.read()
    
    key_patterns = [
        'quota_cost_basis_points', 'overage_cost_cents',
        'billing_strategy', 'BillingStrategy',
        'dailyQuotaRemainingPercent', 'weeklyQuotaRemainingPercent',
        'overageBalanceMicros', 'dailyQuotaResetAtUnix',
        'formatMicrosAsUsd', 'checkChatCapacity',
        'checkUserMessageRateLimit', 'isCapacityLimited',
        'sendCascadeInput', 'addCascadeInput',
        'MAX_INVOCATIONS', 'WRITE_CHAT_INSUFFICIENT',
        'acuCost', 'creditCost', 'cumulativeTokensAtStep',
        'monthlyPromptCredits', 'monthlyAcuLimit',
        '$Had', '$Gad', 'quotaRemaining',
        'onDidChangeQuotaRemaining',
    ]
    
    offsets = {}
    for pat in key_patterns:
        idx = wb_content.find(pat)
        if idx >= 0:
            offsets[pat] = idx
            print(f"  {pat:<40} @ offset {idx}")
        else:
            print(f"  {pat:<40} NOT FOUND")
    output['key_offsets'] = offsets
    
    # Save complete output
    out_path = os.path.join(OUTPUT_DIR, '_deep_reverse_v9_results.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n=== Results saved to {out_path} ===")
    print(f"Total size: {os.path.getsize(out_path)} bytes")
