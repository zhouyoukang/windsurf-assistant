#!/usr/bin/env python3
import re, os

WB = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
with open(WB,'r',encoding='utf-8',errors='replace') as f:
    wb = f.read()

# 找到 allowedCommandModelConfigs 上下文精确字符串
idx = wb.find('allowedCommandModelConfigsProtoBinaryBase64')
region = wb[max(0,idx-100):idx+800]
print("=== allowedCommandModel region ===")
print(repr(region))
print()
print("=== PLAIN ===")
print(region)
