#!/usr/bin/env python3
"""Extract and decode ALL Windsurf authentication + model data from state.vscdb"""
import sqlite3, json, base64, os, struct, re, sys
from datetime import datetime, timezone

STATE_DB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')

def decode_varint(data, pos):
    val = 0; shift = 0
    while pos < len(data):
        b = data[pos]; pos += 1
        val |= (b & 0x7F) << shift; shift += 7
        if not (b & 0x80): break
    return val, pos

def parse_pb(data):
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
                result.append((fnum, 'fixed64', struct.unpack('<d', val)[0]))
            elif wtype == 2:
                length, pos = decode_varint(data, pos)
                val = data[pos:pos+length]; pos += length
                result.append((fnum, 'bytes', val))
            elif wtype == 5:
                val = data[pos:pos+4]; pos += 4
                result.append((fnum, 'fixed32', struct.unpack('<f', val)[0]))
            else:
                break
        except:
            break
    return result

def try_str(data):
    try:
        t = data.decode('utf-8')
        if all(32 <= ord(c) < 127 or c in '\n\r\t' for c in t): return t
    except: pass
    return None

def pb_tree(data, depth=0, max_d=5):
    if depth > max_d: return f"<{len(data)}B>"
    fields = {}
    for fnum, wtype, val in parse_pb(data):
        if wtype == 'varint':
            fields.setdefault(fnum, []).append(val)
        elif wtype in ('fixed64', 'fixed32'):
            fields.setdefault(fnum, []).append(round(val, 6))
        elif wtype == 'bytes':
            txt = try_str(val)
            if txt:
                fields.setdefault(fnum, []).append(txt)
            else:
                sub = pb_tree(val, depth+1)
                fields.setdefault(fnum, []).append(sub if isinstance(sub, dict) and sub else f"<{len(val)}B>")
    return fields

conn = sqlite3.connect(f'file:{STATE_DB}?mode=ro', uri=True)
out = {}

# 1. All windsurf keys
print("=" * 70)
print("WINDSURF DEEP AUTH EXTRACTION")
print("=" * 70)
rows = conn.execute("SELECT key, length(value) FROM ItemTable WHERE key LIKE 'windsurf%' ORDER BY key").fetchall()
print(f"\n[1] ALL WINDSURF KEYS ({len(rows)}):")
for k, vlen in rows:
    print(f"  {k:<60} {vlen}B")
out['keys'] = {k: vlen for k, vlen in rows}

# 2. windsurfAuthStatus
row = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
if row:
    auth = json.loads(row[0])
    print(f"\n[2] windsurfAuthStatus TOP-LEVEL ({len(auth)} keys):")
    for k, v in auth.items():
        if isinstance(v, str):
            print(f"  {k}: str[{len(v)}] = {v[:80]}{'...' if len(v)>80 else ''}")
        elif isinstance(v, list):
            print(f"  {k}: list[{len(v)}]")
        elif isinstance(v, (int, float, bool)):
            print(f"  {k}: {v}")
        elif isinstance(v, dict):
            print(f"  {k}: dict{list(v.keys())[:5]}")
        else:
            print(f"  {k}: {type(v).__name__}")

    # API Key analysis
    api_key = auth.get('apiKey', '')
    print(f"\n[3] API KEY:")
    print(f"  Length: {len(api_key)}")
    print(f"  Prefix: {api_key[:40]}...")
    print(f"  Format: {'UUID-like' if '-' in api_key[:40] else 'opaque'}")

    # userStatusProtoBinaryBase64 decode
    us_b64 = auth.get('userStatusProtoBinaryBase64', '')
    if us_b64:
        us_data = base64.b64decode(us_b64)
        print(f"\n[4] userStatus PROTOBUF ({len(us_data)} bytes):")
        raw = parse_pb(us_data)
        field_cat = {}
        for fnum, wtype, val in raw:
            if fnum not in field_cat:
                field_cat[fnum] = {'type': wtype, 'count': 0, 'samples': []}
            field_cat[fnum]['count'] += 1
            if wtype == 'bytes':
                field_cat[fnum]['samples'].append(f"{len(val)}B")
            elif wtype == 'varint':
                field_cat[fnum]['samples'].append(str(val))
            else:
                field_cat[fnum]['samples'].append(str(round(val, 4)))
        for fnum in sorted(field_cat):
            f = field_cat[fnum]
            samp = f['samples'][:5]
            print(f"  F{fnum:<4} {f['type']:<8} x{f['count']:<4} samples={samp}")

        # Decode field 1 (user info)
        for fnum, wtype, val in raw:
            if fnum == 1 and wtype == 'bytes':
                txt = try_str(val)
                if txt:
                    print(f"\n  F1 (user_id/email): {txt}")

        # Decode field 7 (plan status)
        for fnum, wtype, val in raw:
            if fnum == 7 and wtype == 'bytes':
                plan = pb_tree(val)
                print(f"\n[5] PLAN STATUS (F7):")
                print(f"  {json.dumps(plan, indent=4, default=str)[:2000]}")
                out['plan_status'] = plan
                break

        # Decode field 33 (model configs) - first 5
        models = []
        for fnum, wtype, val in raw:
            if fnum == 33 and wtype == 'bytes':
                m_raw = parse_pb(val)
                m = {}
                for mf, mw, mv in m_raw:
                    if mw == 'bytes':
                        t = try_str(mv)
                        if t: m.setdefault(mf, []).append(t)
                        else: m.setdefault(mf, []).append(pb_tree(mv))
                    elif mw == 'varint':
                        m.setdefault(mf, []).append(mv)
                    else:
                        m.setdefault(mf, []).append(round(mv, 4))
                models.append(m)
        print(f"\n[6] MODEL CONFIGS (F33): {len(models)} models")
        for i, m in enumerate(models[:10]):
            strs = [v for vals in m.values() for v in vals if isinstance(v, str)]
            ints = [(k, v) for k, vals in m.items() for v in vals if isinstance(v, int)]
            floats = [(k, v) for k, vals in m.items() for v in vals if isinstance(v, float)]
            name = next((s for s in strs if len(s) > 3 and not s.startswith('MODEL')), '?')
            uid = next((s for s in strs if '/' in s or s.startswith('MODEL')), '?')
            int_str = ' '.join(f"F{k}={v}" for k, v in ints[:6])
            flt_str = ' '.join(f"F{k}={v}" for k, v in floats[:3])
            print(f"  [{i:>3}] {name:<35} uid={uid:<25} {int_str} {flt_str}")
        out['model_count'] = len(models)
        if models:
            out['model_sample'] = models[0]

    # allowedCommandModelConfigs
    cmd_models = auth.get('allowedCommandModelConfigsProtoBinaryBase64', [])
    if cmd_models:
        print(f"\n[7] COMMAND MODEL CONFIGS: {len(cmd_models)}")
        for i, pb64 in enumerate(cmd_models[:5]):
            data = base64.b64decode(pb64)
            tree = pb_tree(data)
            strs = []
            def extract_strs(d):
                if isinstance(d, str): strs.append(d)
                elif isinstance(d, dict):
                    for v in d.values():
                        if isinstance(v, list):
                            for item in v: extract_strs(item)
                elif isinstance(d, list):
                    for item in d: extract_strs(item)
            extract_strs(tree)
            print(f"  [{i}] {', '.join(s for s in strs if len(s) > 2)[:120]}")

# 3. windsurfConfigurations
row = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfConfigurations'").fetchone()
if row:
    try:
        cfg_data = base64.b64decode(row[0])
        cfg = pb_tree(cfg_data)
        print(f"\n[8] windsurfConfigurations ({len(cfg_data)} bytes):")
        cfg_json = json.dumps(cfg, indent=2, default=str)[:3000]
        print(f"  {cfg_json[:2000]}")
        out['windsurf_config'] = cfg
    except:
        print(f"\n[8] windsurfConfigurations: decode failed (raw len={len(row[0])})")

# 4. Secret keys
secret_rows = conn.execute("SELECT key, length(value) FROM ItemTable WHERE key LIKE 'secret://%'").fetchall()
print(f"\n[9] SECRET KEYS ({len(secret_rows)}):")
for k, vlen in secret_rows:
    print(f"  {k[:90]} ({vlen}B)")

# 5. All other auth-related keys
auth_rows = conn.execute("SELECT key, length(value) FROM ItemTable WHERE key LIKE '%auth%' OR key LIKE '%session%' OR key LIKE '%token%' OR key LIKE '%login%'").fetchall()
print(f"\n[10] AUTH-RELATED KEYS ({len(auth_rows)}):")
for k, vlen in auth_rows:
    print(f"  {k[:80]} ({vlen}B)")

conn.close()

# Save output
out_path = os.path.join(os.path.dirname(__file__), '_auth_deep_extract.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(out, f, indent=2, ensure_ascii=False, default=str)
print(f"\nSaved to {out_path}")
