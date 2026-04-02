#!/usr/bin/env python3
"""搜索 Continue 按钮在 workbench.js 中的 DOM 结构"""
import re, os

WB = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'

print("=" * 65)
print("搜索 Continue 按钮相关代码")
print("=" * 65)

with open(WB, 'r', encoding='utf-8', errors='replace') as f:
    wb = f.read()
print(f"workbench.js: {len(wb):,} chars")

patterns = [
    'Continue',
    'continue',
    'continueGeneration',
    'handleContinue',
    'isContinue',
    '"Continue"',
    'Diving',
    'output_limit',
    'outputLimit',
    'maxOutput',
    'truncated',
    'streamTruncated',
]

for p in patterns:
    idx = wb.find(p)
    if idx >= 0:
        ctx = wb[max(0, idx-100):idx+200].replace('\n', ' ')
        print(f'\n[FOUND] "{p}" @{idx}:')
        print(f'  ...{ctx[:250]}...')
    else:
        pass  # skip not found

print("\n" + "=" * 65)
print("搜索 extension.js")
print("=" * 65)

try:
    with open(EXT, 'r', encoding='utf-8', errors='replace') as f:
        ext = f.read()
    print(f"extension.js: {len(ext):,} chars")

    ext_patterns = [
        'Continue',
        'continueGeneration',
        'handleContinue',
        'postMessage',
        'webview',
        'createWebviewPanel',
        'Diving',
    ]
    for p in ext_patterns:
        idx = ext.find(p)
        if idx >= 0:
            ctx = ext[max(0, idx-80):idx+150].replace('\n', ' ')
            print(f'\n[EXT FOUND] "{p}" @{idx}:')
            print(f'  ...{ctx[:200]}...')
except Exception as e:
    print(f"extension.js error: {e}")

# Also check for webview URLs (clues about where chat is rendered)
print("\n" + "=" * 65)
print("Webview URL patterns in workbench.js")
print("=" * 65)
webview_urls = re.findall(r'vscode-webview://[^\s"\'`]+', wb)
print(f"Found {len(webview_urls)} webview URL refs")
for u in webview_urls[:5]:
    print(f"  {u}")

# Check for any CDP / remote debugging refs
print("\n" + "=" * 65)
print("CDP / devtools patterns")
print("=" * 65)
cdp_patterns = ['remote-debugging', 'devtools', 'ChromeDevTools', 'cdpPort']
for p in cdp_patterns:
    c = wb.count(p)
    if c:
        idx = wb.find(p)
        print(f'  "{p}": {c} occurrences, first @{idx}: {repr(wb[idx:idx+100])}')
