#!/usr/bin/env python3
"""精确定位 MetadataProvider.getMetadata() 代码结构"""
from pathlib import Path
import re, json

EXT = Path(r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js')
src = EXT.read_text(encoding='utf-8', errors='replace')

# 1. 围绕 @4865482 读取完整 MetadataProvider 类
pos = 4865482
window = src[max(0, pos-2000):pos+1500]
print("=== @4865482 上下文 (MetadataProvider.getMetadata) ===")
print(window)
print()

# 2. 围绕 @1078151 读取 (g=i.apiKey 用法)
pos2 = 1078151
window2 = src[max(0, pos2-100):pos2+600]
print("=== @1078151 上下文 (g=i.apiKey 用法) ===")
print(window2)
print()

# 3. 找到 MetadataProvider 完整类范围
meta_defs = [(m.start(), m.group()) for m in re.finditer(
    r'class\s+MetadataProvider[^{]*\{', src)]
print(f"=== MetadataProvider class defs: {len(meta_defs)} ===")
for pos3, code in meta_defs:
    print(f"  @{pos3}: {code[:120]}")
    # Show next 800 chars
    print(src[pos3:pos3+800])
    print("---")

# 4. 找 getMetadata 方法
meta_methods = [(m.start(), m.group()) for m in re.finditer(
    r'getMetadata\s*\(\s*\)\s*\{[^}]{0,500}\}', src)]
print(f"\n=== getMetadata() methods: {len(meta_methods)} ===")
for pos4, code in meta_methods:
    print(f"  @{pos4}: {code[:400]}")
    print("---")

# 5. getInstance pattern
instances = [(m.start(), m.group()) for m in re.finditer(
    r'MetadataProvider\.getInstance\(\)\.getMetadata\(\)', src)]
print(f"\n=== MetadataProvider.getInstance().getMetadata() calls: {len(instances)} ===")
for pos5, code in instances:
    print(f"  @{pos5}: ...{src[max(0,pos5-30):pos5+100]}...")

# 6. 检查 clearAuthentication + apiKey setter (重置时机)
pos6 = 4864478
print(f"\n=== @4864478 clearAuthentication context ===")
print(src[max(0, pos6-200):pos6+500])
