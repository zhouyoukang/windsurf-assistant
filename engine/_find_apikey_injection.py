#!/usr/bin/env python3
"""Find ALL apiKey injection points in extension.js for surgical patching."""
import re, json
from pathlib import Path

EXT = Path(r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js')
with open(EXT, 'r', encoding='utf-8', errors='replace') as f:
    src = f.read()

print(f'Total size: {len(src):,} chars')

# Pattern 1: apiKey:g (variable assignment in object literal)
hits1 = [(m.start(), m.group()) for m in re.finditer(r'apiKey:[a-z_$]{1,4}[,}]', src)]
print(f'\nPattern1 "apiKey:VAR": {len(hits1)} hits')
for i, (pos, ctx) in enumerate(hits1[:15]):
    surround = src[max(0, pos-60):pos+100].replace('\n', ' ')
    print(f'  [{i:>2}] @{pos:>9}: ...{surround}...')

# Pattern 2: .apiKey = / .apiKey= (property assignment)
hits2 = [(m.start(), m.group()) for m in re.finditer(r'\.apiKey\s*=\s*[a-z_$]', src)]
print(f'\nPattern2 ".apiKey=VAR": {len(hits2)} hits')
for i, (pos, ctx) in enumerate(hits2[:10]):
    surround = src[max(0, pos-50):pos+80].replace('\n', ' ')
    print(f'  [{i:>2}] @{pos:>9}: ...{surround}...')

# Pattern 3: metadata construction with apiKey
hits3 = [(m.start(), m.group()) for m in re.finditer(r'apiKey.{0,5}sessionId', src)]
print(f'\nPattern3 "apiKey...sessionId" (metadata): {len(hits3)} hits')
for i, (pos, ctx) in enumerate(hits3[:10]):
    surround = src[max(0, pos-80):pos+200].replace('\n', ' ')
    print(f'  [{i:>2}] @{pos:>9}: ...{surround[:250]}...')

# Pattern 4: Authorization Bearer injection in interceptors
hits4 = [(m.start(), m.group()) for m in re.finditer(r'Authorization.{0,30}Bearer', src)]
print(f'\nPattern4 "Authorization Bearer": {len(hits4)} hits')
for i, (pos, ctx) in enumerate(hits4[:10]):
    surround = src[max(0, pos-40):pos+120].replace('\n', ' ')
    print(f'  [{i:>2}] @{pos:>9}: ...{surround}...')

# Pattern 5: setHeader or header.set with api key
hits5 = [(m.start(), m.group()) for m in re.finditer(r'header\.set.{0,60}api', src, re.IGNORECASE)]
print(f'\nPattern5 "header.set...api": {len(hits5)} hits')
for i, (pos, ctx) in enumerate(hits5[:10]):
    surround = src[max(0, pos-30):pos+150].replace('\n', ' ')
    print(f'  [{i:>2}] @{pos:>9}: ...{surround}...')

# Pattern 6: interceptor function bodies that set headers
hits6 = [(m.start(), m.group()) for m in re.finditer(r'appendMetadataToHeaders.{0,300}', src)]
print(f'\nPattern6 "appendMetadataToHeaders": {len(hits6)} hits')
for i, (pos, ctx) in enumerate(hits6[:5]):
    print(f'  [{i:>2}] @{pos:>9}: {ctx[:200]}')

# Pattern 7: find the actual gRPC auth interceptor
hits7 = [(m.start(), m.group()) for m in re.finditer(
    r'function\s*\w*\s*\([^)]*\)\s*\{[^}]*apiKey[^}]*\}', src)]
print(f'\nPattern7 "function...apiKey...": {len(hits7)} hits')
for i, (pos, ctx) in enumerate(hits7[:5]):
    print(f'  [{i:>2}] @{pos:>9}: {ctx[:200]}')

# Pattern 8: the Connect-RPC interceptor structure
# interceptors take (next) and return a function that takes (req)
hits8 = [(m.start(), m.group()) for m in re.finditer(
    r'return[^;]*function[^;]*req[^;]*\{[^}]{0,200}apiKey', src)]
print(f'\nPattern8 "return function(req)...apiKey": {len(hits8)} hits')
for i, (pos, ctx) in enumerate(hits8[:5]):
    surround = src[max(0, pos-50):pos+250].replace('\n', ' ')
    print(f'  [{i:>2}] @{pos:>9}: {surround[:300]}')

# Pattern 9: find where auth metadata is appended to headers
hits9 = [(m.start(), m.group()) for m in re.finditer(
    r'(?:headers|header).*?api.{0,200}', src, re.IGNORECASE)]
print(f'\nPattern9 "headers...api": {len(hits9)} hits (first 5)')
for i, (pos, ctx) in enumerate(hits9[:5]):
    print(f'  [{i:>2}] @{pos:>9}: {ctx[:180]}')

print('\n=== DONE ===')
