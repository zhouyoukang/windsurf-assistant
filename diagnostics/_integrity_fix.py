#!/usr/bin/env python3
"""修复 Windsurf corrupt installation 警告 — 更新完整性校验"""
import os, json, hashlib, glob, re

WINDSURF_BASE = r'D:\Windsurf'

print("="*65)
print("寻找完整性校验文件")
print("="*65)

# VSCode stores checksums in various places
checksum_paths = []
for pattern in [
    r'D:\Windsurf\resources\app\product.json',
    r'D:\Windsurf\resources\app\package.json',
    r'D:\Windsurf\resources\app\checksums',
    r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js.map',
]:
    if os.path.exists(pattern):
        checksum_paths.append(pattern)
        print(f"  Found: {pattern} ({os.path.getsize(pattern):,} bytes)")

# Find all .json files in resources/app that might have checksums
for f in glob.glob(r'D:\Windsurf\resources\app\*.json'):
    size = os.path.getsize(f)
    print(f"  JSON: {os.path.basename(f)} ({size:,} bytes)")

print("\n" + "="*65)
print("product.json 分析")
print("="*65)
product_path = r'D:\Windsurf\resources\app\product.json'
if os.path.exists(product_path):
    with open(product_path, 'r', encoding='utf-8') as f:
        product = json.load(f)
    print(f"Keys: {list(product.keys())}")
    # Look for integrity-related keys
    for k, v in product.items():
        if any(x in k.lower() for x in ['checksum', 'hash', 'integrity', 'sign', 'verify']):
            print(f"  {k}: {str(v)[:200]}")
    # Print all keys with values that look like hashes
    for k, v in product.items():
        if isinstance(v, str) and re.match(r'^[a-f0-9]{32,}$', v):
            print(f"  [HASH?] {k}: {v}")
        elif isinstance(v, dict):
            for sk, sv in v.items():
                if isinstance(sv, str) and re.match(r'^[a-f0-9]{32,}$', sv):
                    print(f"  [HASH?] {k}.{sk}: {sv}")

print("\n" + "="*65)
print("寻找完整性校验代码")
print("="*65)

# Look in main electron files for integrity check
for main_file in [
    r'D:\Windsurf\resources\app\out\main.js',
    r'D:\Windsurf\resources\app\out\vs\code\electron-main\main.js',
    r'D:\Windsurf\resources\app\out\bootstrap-fork.js',
]:
    if os.path.exists(main_file):
        print(f"\nFound: {main_file}")
        with open(main_file, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        # Search for integrity check
        for pat in ['corrupt', 'checksum', 'integrity', 'reinstall', 'corrupt.*install', 'appears to be corrupt']:
            hits = [m.start() for m in re.finditer(pat, content, re.I)]
            if hits:
                pos = hits[0]
                ctx = content[max(0,pos-100):pos+300]
                print(f"  [{pat}] @{pos}: {ctx[:300]}")
                break

# Check workbench for the actual corrupt message
WB = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
with open(WB, 'r', encoding='utf-8', errors='replace') as f:
    wb = f.read()
for pat in ['corrupt', 'reinstall', 'appears to be corrupt']:
    hits = [(m.start(), wb[max(0,m.start()-100):m.start()+300]) for m in re.finditer(pat, wb, re.I)]
    if hits:
        pos, ctx = hits[0]
        print(f"\nworkbench.js [{pat}] @{pos}:")
        print(ctx[:350])
        break

print("\n" + "="*65)
print("寻找校验文件 (product.json integrityStatements)")
print("="*65)
# VSCode/Electron uses integrityStatements or checksums in product.json
# The key is usually 'checksums' or 'integrityStatements'
if os.path.exists(product_path):
    with open(product_path, 'r', encoding='utf-8') as f:
        product = json.load(f)
    for key in ['checksums', 'integrityStatements', 'files']:
        if key in product:
            val = product[key]
            print(f"  {key}: {type(val).__name__} ({len(val) if isinstance(val, (dict,list)) else 'scalar'})")
            if isinstance(val, dict):
                for k, v in list(val.items())[:10]:
                    print(f"    {k}: {str(v)[:80]}")

# Also check for SHA-256 of workbench.desktop.main.js
wb_hash = hashlib.sha256(open(WB,'rb').read()).hexdigest()
print(f"\nworkbench.desktop.main.js SHA256: {wb_hash}")
# SHA1
wb_sha1 = hashlib.sha1(open(WB,'rb').read()).hexdigest()
print(f"workbench.desktop.main.js SHA1: {wb_sha1}")

# Search product.json for any hash value
if os.path.exists(product_path):
    with open(product_path, 'r', encoding='utf-8') as f:
        product_str = f.read()
    # Search for any existing hash related to workbench
    if 'workbench' in product_str:
        for m in re.finditer(r'workbench[^"]*":\s*"([^"]+)"', product_str):
            print(f"  workbench ref: {m.group(0)[:100]}")

print("\n=== DONE ===")
