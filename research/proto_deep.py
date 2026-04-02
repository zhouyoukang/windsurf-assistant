#!/usr/bin/env python3
"""深度逆向: StreamReactiveUpdatesRequest + Metadata 完整字段"""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
txt = open(EXT, 'r', encoding='utf-8', errors='replace').read()

# 1. StreamReactiveUpdatesRequest proto3
print('=== StreamReactiveUpdatesRequest ===')
for m in re.finditer(r'StreamReactiveUpdatesRequest["\']?\s*[;,{].{0,1500}', txt):
    ctx = m.group()
    if 'typeName' in ctx or 'fields' in ctx or 'proto3' in ctx:
        print(ctx[:1200])
        print('---')
        break

# Also try from typeName
for m in re.finditer(r'typeName="exa\.language_server_pb\.StreamReactiveUpdatesRequest".{0,1000}', txt):
    print(m.group()[:1000])
    print('---')

# 2. Metadata proto3 fields (full)
print('\n=== Metadata proto3 full fields ===')
for m in re.finditer(r'typeName="exa\.language_server_pb\.Metadata".{0,3000}', txt):
    print(m.group()[:3000])
    print('---')

# 3. How streamCascadeReactiveUpdates is actually called
print('\n=== streamCascadeReactiveUpdates actual calls ===')
for m in re.finditer(r'.{0,200}streamCascadeReactiveUpdates\(.{0,400}', txt):
    print(m.group()[:600])
    print('---')

# 4. Find initializeConversation or similar workspace init
print('\n=== initCascade / initializeConversation ===')
for m in re.finditer(r'.{0,100}(initCascade|InitializeCascade|initializeConversation|getCascadeId).{0,300}', txt):
    ctx = m.group()
    if any(x in ctx for x in ['cascadeId', 'workspace', 'workspaceId']):
        print(ctx[:400])
        print('---')

# 5. workspaceId in cascade init
print('\n=== getCascadeIdForCurrentWorkspace ===')
for m in re.finditer(r'.{0,100}getCascadeIdForCurrentWorkspace.{0,400}', txt):
    print(m.group()[:500])
    print('---')
