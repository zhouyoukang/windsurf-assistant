#!/usr/bin/env python3
"""找 MetadataProvider.getMetadata() + TextOrScopeItem + StreamCascadeReactiveUpdates proto 定义"""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
txt = open(EXT, 'r', encoding='utf-8', errors='replace').read()

# 1. Find Metadata proto3 field list
print('=== Metadata proto3 fields ===')
for m in re.finditer(r'typeName="exa\.language_server_pb\.Metadata".{0,2000}', txt):
    print(m.group()[:1500])
    print('---')

# 2. Find TextOrScopeItem proto3 fields
print('\n=== TextOrScopeItem proto3 fields ===')
for m in re.finditer(r'typeName="exa\.language_server_pb\.TextOrScopeItem".{0,800}', txt):
    print(m.group()[:800])
    print('---')

# 3. Find StreamCascadeReactiveUpdatesRequest proto3 fields
print('\n=== StreamCascadeReactiveUpdates request proto3 ===')
for m in re.finditer(r'typeName="exa\.language_server_pb\.(StreamCascade|CascadeReactive).{0,800}', txt):
    print(m.group()[:800])
    print('---')

# 4. Find getMetadata function
print('\n=== getMetadata() implementation ===')
for m in re.finditer(r'getMetadata\(\).{0,600}', txt):
    ctx = m.group()
    if 'csrfToken' in ctx or 'apiKey' in ctx or 'ideName' in ctx:
        print(ctx[:600])
        print('---')

# 5. Find MetadataProvider class init
print('\n=== MetadataProvider csrfToken + apiKey ===')
for m in re.finditer(r'.{0,100}(csrfToken|csrf_token).{0,300}', txt):
    ctx = m.group()
    if 'metadata' in ctx.lower() or 'Metadata' in ctx or 'meta' in ctx.lower():
        print(ctx[:400])
        print('---')

# 6. Actual stream call
print('\n=== stream cascade call ===')
for m in re.finditer(r'streamCascadeReactiveUpdates.{0,500}', txt):
    print(m.group()[:500])
    print('---')
