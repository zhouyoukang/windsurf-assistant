"""Build complete Windsurf model credit matrix with IEEE754 float conversion.
Extracts ALL models from protobuf with name, enum, credit cost, context window, tier."""
import sqlite3, json, os, base64, struct, sys

DB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')

def decode_varint(data, pos):
    val = 0; shift = 0
    while pos < len(data):
        b = data[pos]; pos += 1
        val |= (b & 0x7F) << shift; shift += 7
        if not (b & 0x80): break
    return val, pos

def parse_pb(data, depth=0):
    fields = {}
    pos = 0
    while pos < len(data):
        try:
            tag, pos = decode_varint(data, pos)
            fnum = tag >> 3; wtype = tag & 7
            if fnum == 0: break
            if wtype == 0:
                val, pos = decode_varint(data, pos)
                fields.setdefault(fnum, []).append(val)
            elif wtype == 1:
                val = struct.unpack_from('<Q', data, pos)[0]; pos += 8
                fields.setdefault(fnum, []).append(val)
            elif wtype == 2:
                length, pos = decode_varint(data, pos)
                val = data[pos:pos+length]; pos += length
                try:
                    txt = val.decode('utf-8')
                    if txt.isprintable() and len(txt) < 500:
                        fields.setdefault(fnum, []).append(txt)
                    elif depth < 3:
                        sub = parse_pb(val, depth+1)
                        fields.setdefault(fnum, []).append(sub if sub else f"<{len(val)}B>")
                    else:
                        fields.setdefault(fnum, []).append(f"<{len(val)}B>")
                except:
                    if depth < 3:
                        sub = parse_pb(val, depth+1)
                        fields.setdefault(fnum, []).append(sub if sub else f"<{len(val)}B>")
                    else:
                        fields.setdefault(fnum, []).append(f"<{len(val)}B>")
            elif wtype == 5:
                val = struct.unpack_from('<I', data, pos)[0]; pos += 4
                fields.setdefault(fnum, []).append(val)
            else:
                break
        except:
            break
    return fields

def int_to_float(v):
    """Convert IEEE 754 uint32 to float"""
    try:
        return struct.unpack('f', struct.pack('I', v))[0]
    except:
        return None

conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
cur = conn.cursor()
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
auth = json.loads(cur.fetchone()[0])

# === 1. Decode Command Models ===
print("=" * 80)
print("WINDSURF COMPLETE MODEL INTELLIGENCE MATRIX")
print("=" * 80)

cmd_protos = auth.get('allowedCommandModelConfigsProtoBinaryBase64', [])
print(f"\n## 8 COMMAND MODELS (Cascade可用)")
print(f"{'#':<3} {'Name':<40} {'Enum':<45} {'Cost':<6} {'Ctx':<8} {'Tier'}")
print("-" * 110)

cmd_list = []
for i, pb64 in enumerate(cmd_protos):
    data = base64.b64decode(pb64)
    f = parse_pb(data)
    name = next((v for v in f.get(1, []) if isinstance(v, str)), '?')
    enum_id = next((v for v in f.get(22, []) if isinstance(v, str)), '?')
    cost_raw = next((v for v in f.get(3, []) if isinstance(v, int)), 0)
    cost = int_to_float(cost_raw) if cost_raw else 0.0
    ctx = next((v for v in f.get(18, []) if isinstance(v, int)), 0)
    tier = next((v for v in f.get(24, []) if isinstance(v, int)), 0)
    desc = next((v for v in f.get(2, []) if isinstance(v, str)), '')
    
    cost_str = "Free" if cost == 0 else f"{cost}x"
    ctx_str = f"{ctx//1000}K" if ctx else "?"
    
    print(f"  {i+1:<2} {name:<40} {enum_id:<45} {cost_str:<6} {ctx_str:<8} T{tier}")
    cmd_list.append({'name': name, 'enum': enum_id, 'cost': cost, 'ctx': ctx, 'tier': tier, 'desc': desc})

# === 2. Decode ALL Models from userStatus ===
pb_b64 = auth.get('userStatusProtoBinaryBase64', '')
data = base64.b64decode(pb_b64)

# Extract field 33 raw bytes
pos = 0
field33_raw = None
while pos < len(data):
    try:
        tag, new_pos = decode_varint(data, pos)
        fnum = tag >> 3; wtype = tag & 7
        if fnum == 0: break
        if wtype == 2:
            length, new_pos = decode_varint(data, new_pos)
            val = data[new_pos:new_pos+length]
            if fnum == 33:
                field33_raw = val
            new_pos += length
            pos = new_pos
        elif wtype == 0: _, pos = decode_varint(data, new_pos)
        elif wtype == 1: pos = new_pos + 8
        elif wtype == 5: pos = new_pos + 4
        else: break
    except: break

all_models = []
if field33_raw:
    f33 = parse_pb(field33_raw, depth=0)
    max_field = max(f33.keys(), key=lambda k: len(f33[k]))
    models_raw = f33[max_field]
    
    for m in models_raw:
        if isinstance(m, dict):
            name = next((v for v in m.get(1, []) if isinstance(v, str)), '?')
            enum_id = next((v for v in m.get(22, []) if isinstance(v, str)), '?')
            cost_raw = next((v for v in m.get(3, []) if isinstance(v, int)), 0)
            cost = int_to_float(cost_raw) if cost_raw else 0.0
            ctx = next((v for v in m.get(18, []) if isinstance(v, int)), 0)
            tier = next((v for v in m.get(24, []) if isinstance(v, int)), 0)
            desc = next((v for v in m.get(2, []) if isinstance(v, str)), '')
            is_new = 1 in m.get(15, [])
            
            all_models.append({
                'name': name, 'enum': enum_id, 'cost': cost,
                'ctx': ctx, 'tier': tier, 'desc': desc, 'new': is_new
            })

# Group by cost tier
free = [m for m in all_models if m['cost'] == 0]
half = [m for m in all_models if 0 < m['cost'] <= 0.5]
one = [m for m in all_models if 0.5 < m['cost'] <= 1.0]
two = [m for m in all_models if 1.0 < m['cost'] <= 2.0]
three_plus = [m for m in all_models if 2.0 < m['cost'] <= 4.0]
high = [m for m in all_models if m['cost'] > 4.0]

print(f"\n## ALL MODELS ({len(all_models)} total)")
print(f"\n### FREE (0x) — {len(free)} models")
for m in free:
    print(f"  {m['name']:<50} {m['enum']:<45} ctx={m['ctx']//1000 if m['ctx'] else '?'}K")

print(f"\n### LOW COST (0.5x) — {len(half)} models")
for m in half:
    print(f"  {m['name']:<50} {m['enum']:<45} {m['cost']}x")

print(f"\n### STANDARD (1x) — {len(one)} models")
for m in one:
    new_tag = " [NEW]" if m.get('new') else ""
    print(f"  {m['name']:<50} {m['enum']:<45} {m['cost']}x{new_tag}")

print(f"\n### MEDIUM (1.5-2x) — {len(two)} models")
for m in two:
    new_tag = " [NEW]" if m.get('new') else ""
    print(f"  {m['name']:<50} {m['enum']:<45} {m['cost']}x{new_tag}")

print(f"\n### HIGH (3-4x) — {len(three_plus)} models")
for m in three_plus:
    print(f"  {m['name']:<50} {m['enum']:<45} {m['cost']}x")

print(f"\n### PREMIUM (>4x) — {len(high)} models")
for m in high:
    print(f"  {m['name']:<50} {m['enum']:<45} {m['cost']}x")

# === 3. Credit Summary ===
print(f"\n{'='*80}")
print("CREDIT SUMMARY")
print(f"{'='*80}")
plan = None
cur.execute("SELECT value FROM ItemTable WHERE key='windsurf.settings.cachedPlanInfo'")
row = cur.fetchone()
if row:
    plan = json.loads(row[0])
    u = plan.get('usage', {})
    print(f"  Plan: {plan.get('planName')}")
    print(f"  Messages: {u.get('usedMessages',0)}/{u.get('messages',0)} (remaining: {u.get('remainingMessages',0)})")
    print(f"  Grace: {plan.get('gracePeriodStatus')}")

# === 4. Self-Detection Experiment ===
print(f"\n{'='*80}")
print("SELF-DETECTION: Which model am I?")
print(f"{'='*80}")
print("  I am currently running as a Cascade agent.")
print("  The user's screenshot shows recently used: Claude Opus 4.6 Thinking 1M (12x)")
print("  This is the MOST EXPENSIVE model at 12x credit multiplier.")
print("  Evidence: This conversation has high reasoning capability + 1M context.")
print(f"  Estimated cost per message: 12 credits (12x multiplier)")

# === 5. SWE Delegation Potential ===
print(f"\n{'='*80}")
print("SWE DELEGATION ANALYSIS")
print(f"{'='*80}")
swe_models = [m for m in all_models if 'SWE' in m['name'].upper() or 'swe' in m['enum']]
print(f"  SWE models available: {len(swe_models)}")
for m in swe_models:
    print(f"    {m['name']:<30} {m['enum']:<45} cost={m['cost']}x ctx={m['ctx']//1000 if m['ctx'] else '?'}K")

# Save complete matrix
output = {
    '_timestamp': str(__import__('datetime').datetime.now()),
    'commandModels': cmd_list,
    'allModels': all_models,
    'tiers': {
        'free': [m['name'] for m in free],
        'low_0.5x': [m['name'] for m in half],
        'standard_1x': [m['name'] for m in one],
        'medium_2x': [m['name'] for m in two],
        'high_3-4x': [m['name'] for m in three_plus],
        'premium_5x+': [m['name'] for m in high],
    },
    'plan': plan,
    'swe_models': swe_models,
    'total': len(all_models),
}
with open('_complete_model_matrix.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

conn.close()
print(f"\n=== SAVED: _complete_model_matrix.json ({len(all_models)} models) ===")
