#!/usr/bin/env python3
"""读取 MetadataProvider 精确上下文，确定手术缝合点"""
from pathlib import Path
import re

EXT = Path(r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js')
src = EXT.read_text(encoding='utf-8', errors='replace')

# --- 关键位置 @4865482 ---
POS = 4865482
region = src[max(0, POS-1000):POS+1500]
print("=== @4865482 REGION ===")
print(region)
print()

# --- 寻找唯一的 apiKey:this.apiKey,sessionId 模式 ---
pat = r'apiKey:this\.apiKey,sessionId:this\.sessionId'
matches = [(m.start(), m.group()) for m in re.finditer(pat, src)]
print(f"\n=== Pattern 'apiKey:this.apiKey,sessionId:this.sessionId': {len(matches)} hits ===")
for pos, txt in matches:
    ctx = src[max(0, pos-200):pos+500]
    print(f"  @{pos}: {ctx[:600]}")
    print("---")

# --- 寻找 updateApiKey 精确文本 ---
ua_matches = [(m.start(), m.group()) for m in re.finditer(r'updateApiKey\([A-Z]\)\{this\.apiKey=[A-Z]', src)]
print(f"\n=== updateApiKey pattern: {len(ua_matches)} hits ===")
for pos, txt in ua_matches:
    print(f"  @{pos}: ...{src[max(0,pos-50):pos+200]}...")

# --- 验证 getMetadata 的返回对象 ---
print("\n=== Full getMetadata return object (next 1500 chars from @4865400) ===")
print(src[4865400:4866900])
