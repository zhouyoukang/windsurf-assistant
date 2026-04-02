"""Decode protobuf command models + full model list from windsurfAuthStatus"""
import sqlite3, json, os, base64, struct, re, sys

DB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')

def decode_varint(data, pos):
    val = 0; shift = 0
    while pos < len(data):
        b = data[pos]; pos += 1
        val |= (b & 0x7F) << shift; shift += 7
        if not (b & 0x80): break
    return val, pos

def parse_pb(data, depth=0):
    """Recursive protobuf parser returning field→value dict"""
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
                # Try as string
                try:
                    txt = val.decode('utf-8')
                    if txt.isprintable() and len(txt) < 500:
                        fields.setdefault(fnum, []).append(txt)
                    else:
                        # Try recursive parse
                        if depth < 3:
                            sub = parse_pb(val, depth+1)
                            if sub and len(sub) > 0:
                                fields.setdefault(fnum, []).append(sub)
                            else:
                                fields.setdefault(fnum, []).append(f"<{len(val)}B>")
                        else:
                            fields.setdefault(fnum, []).append(f"<{len(val)}B>")
                except:
                    if depth < 3:
                        sub = parse_pb(val, depth+1)
                        if sub and len(sub) > 0:
                            fields.setdefault(fnum, []).append(sub)
                        else:
                            fields.setdefault(fnum, []).append(f"<{len(val)}B>")
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

conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
cur = conn.cursor()
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
auth = json.loads(cur.fetchone()[0])

# === 1. Decode 8 Command Models ===
print("=" * 70)
print("COMMAND MODELS (allowedCommandModelConfigsProtoBinaryBase64)")
print("=" * 70)
cmd_protos = auth.get('allowedCommandModelConfigsProtoBinaryBase64', [])
print(f"Count: {len(cmd_protos)}")

cmd_models = []
for i, pb64 in enumerate(cmd_protos):
    data = base64.b64decode(pb64)
    fields = parse_pb(data)
    
    # Extract known fields from ChatModelMetadata protobuf
    # Field mapping (from reverse engineering):
    # 1=modelUid(enum int), 2=displayName, 3=description, 
    # 4=creditMultiplier(float?), 5=modelType, 6=provider, ...
    model = {}
    for fnum, vals in fields.items():
        for v in vals:
            if isinstance(v, str):
                if len(v) > 5 and not v.startswith('<'):
                    model.setdefault('strings', []).append((fnum, v))
            elif isinstance(v, int):
                model.setdefault('ints', []).append((fnum, v))
            elif isinstance(v, dict):
                model.setdefault('subs', []).append((fnum, v))
    
    # Display
    name = ""
    enum_val = None
    cost = None
    for fnum, v in model.get('strings', []):
        if not name and len(v) > 3 and len(v) < 60:
            name = v
    for fnum, v in model.get('ints', []):
        if fnum <= 3 and v > 100:
            enum_val = v
        if fnum <= 3 and v == 0:
            cost = 0
    
    print(f"\n  Model #{i+1}:")
    print(f"    Raw fields: {fields}")
    for fnum, v in model.get('strings', []):
        print(f"    F{fnum} str: {v[:100]}")
    for fnum, v in model.get('ints', []):
        print(f"    F{fnum} int: {v}")
    
    cmd_models.append({'index': i, 'fields': {str(k): [str(x)[:200] for x in v] for k,v in fields.items()}, 'name_guess': name})

# === 2. Decode userStatus Field 33 (all models) ===
print("\n" + "=" * 70)
print("FULL MODEL LIST (userStatus protobuf field 33)")
print("=" * 70)

pb_b64 = auth.get('userStatusProtoBinaryBase64', '')
data = base64.b64decode(pb_b64)
top = parse_pb(data, depth=0)

# Field 33 contains the model configs (33143 bytes)
field33_raw = None
pos = 0
tag_data = data
# Re-parse to get raw field 33 bytes
while pos < len(tag_data):
    try:
        tag, new_pos = decode_varint(tag_data, pos)
        fnum = tag >> 3; wtype = tag & 7
        if fnum == 0: break
        if wtype == 2:
            length, new_pos = decode_varint(tag_data, new_pos)
            val = tag_data[new_pos:new_pos+length]
            if fnum == 33:
                field33_raw = val
                print(f"Field 33 raw: {len(val)} bytes")
            new_pos += length
            pos = new_pos
        elif wtype == 0:
            _, pos = decode_varint(tag_data, new_pos)
        elif wtype == 1:
            pos = new_pos + 8
        elif wtype == 5:
            pos = new_pos + 4
        else:
            break
    except:
        break

if field33_raw:
    # Parse field 33 as a repeated message of model configs
    f33 = parse_pb(field33_raw, depth=0)
    print(f"Field 33 sub-fields: {list(f33.keys())}")
    
    # Each repeated field in f33 should be a model config
    # Find the field that has the most entries (likely the model list)
    max_field = max(f33.keys(), key=lambda k: len(f33[k]))
    models_raw = f33[max_field]
    print(f"Largest sub-field: {max_field} with {len(models_raw)} entries")
    
    # Parse each model
    all_models = []
    for j, m in enumerate(models_raw):
        if isinstance(m, dict):
            # Extract model info
            info = {'_idx': j}
            for fk, fv in m.items():
                for v in fv:
                    if isinstance(v, str) and len(v) > 2 and len(v) < 100:
                        info.setdefault('_strings', []).append((fk, v))
                    elif isinstance(v, int):
                        info.setdefault('_ints', []).append((fk, v))
            all_models.append(info)
    
    print(f"\nParsed {len(all_models)} model entries")
    
    # Show first 20 with details
    print(f"\n{'#':<4} {'Name':<45} {'Ints'}")
    print("-" * 90)
    for m in all_models[:80]:
        strings = m.get('_strings', [])
        ints = m.get('_ints', [])
        name = next((v for fk, v in strings if 'MODEL' not in v and len(v) > 3), 
                     next((v for fk, v in strings), '?'))
        int_str = ', '.join(f"F{fk}={v}" for fk, v in ints)
        str_str = ' | '.join(f"F{fk}={v[:40]}" for fk, v in strings[:3])
        print(f"  {m['_idx']:<3} {str_str:<60} {int_str}")

conn.close()

# Save
out = {'commandModels': cmd_models, 'totalModels': len(all_models) if field33_raw else 0}
with open('_decoded_models.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, indent=2, ensure_ascii=False, default=str)
print(f"\nSaved to _decoded_models.json")
