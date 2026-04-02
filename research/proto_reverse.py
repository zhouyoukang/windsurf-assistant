#!/usr/bin/env python3
"""逆向 extension.js: 找 StreamCascadeReactiveUpdates + SendUserCascadeMessage 的准确格式"""
import sys, io, re, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
print(f'Reading {EXT}...')
txt = open(EXT, 'r', encoding='utf-8', errors='replace').read()
print(f'Size: {len(txt):,} chars\n')

# 1. Find StreamCascadeReactiveUpdates context
print('=== StreamCascadeReactiveUpdates usages ===')
for m in re.finditer(r'.{0,400}StreamCascadeReactiveUpdates.{0,400}', txt):
    ctx = m.group()
    print(ctx[:600])
    print('---')

# 2. Find protocolVersion usage
print('\n=== protocolVersion usages ===')
for m in re.finditer(r'.{0,200}protocolVersion.{0,200}', txt):
    ctx = m.group()
    if 'Cascade' in ctx or 'cascade' in ctx or 'stream' in ctx.lower():
        print(ctx[:400])
        print('---')

# 3. Find SendUserCascadeMessage context
print('\n=== SendUserCascadeMessage usages ===')
for m in re.finditer(r'.{0,300}SendUserCascadeMessage.{0,300}', txt):
    ctx = m.group()
    # filter for calls with config
    if 'cascadeConfig' in ctx or 'plannerConfig' in ctx or 'items' in ctx:
        print(ctx[:500])
        print('---')

# 4. Find workspace/context init
print('\n=== workspaceId / rootDirectory in cascade ===')
for m in re.finditer(r'.{0,200}(workspaceId|rootDir|workspaceRoot|initCascade).{0,200}', txt):
    ctx = m.group()
    if 'cascade' in ctx.lower() or 'Cascade' in ctx:
        print(ctx[:400])
        print('---')

# 5. Find the actual request builder for cascade
print('\n=== cascade request builders ===')
for m in re.finditer(r'(cascadeId|CascadeId).{0,500}', txt):
    ctx = m.group()
    if 'items' in ctx and ('metadata' in ctx or 'apiKey' in ctx):
        print(ctx[:600])
        print('---')
