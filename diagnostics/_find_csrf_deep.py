#!/usr/bin/env python3
"""深度溯源 CSRF token — 4路并行"""
import re, os, subprocess

EXT_JS = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
with open(EXT_JS, 'r', encoding='utf-8', errors='replace') as f:
    ext = f.read()

print("="*65)
print("TRACK A: computeServerInputs — CSRF 生成源头")
print("="*65)
# 找 computeServerInputs 函数体
m = re.search(r'function computeServerInputs\(([^)]*)\)\s*\{([^}]{0,800})\}', ext)
if m:
    print(f"Args: {m.group(1)}")
    print(f"Body: {m.group(2)[:400]}")
else:
    # Try arrow function or export style
    for pat in [r'computeServerInputs=', r'computeServerInputs\s*\(']:
        hits = [(m2.start(), ext[m2.start()-20:m2.start()+600]) for m2 in re.finditer(pat, ext)]
        if hits:
            pos, ctx = hits[0]
            print(f"[{pat}] @{pos}:\n{ctx[:500]}")
            break

print("\n" + "="*65)
print("TRACK B: CSRF token 初始赋值")
print("="*65)
# 找 csrfToken 的赋值
for pat in [r'csrfToken\s*=\s*[^;,)]{0,100}', r'this\.csrfToken\s*=', r'_csrfToken\s*=']:
    hits = [(m2.start(), ext[max(0,m2.start()-80):m2.start()+200])
            for m2 in re.finditer(pat, ext)]
    if hits:
        print(f"\n[{pat}] ({len(hits)} hits):")
        for pos, ctx in hits[:4]:
            print(f"  @{pos}: {ctx[:200]}")
            print("  ---")

print("\n" + "="*65)
print("TRACK C: 语言服务器进程命令行参数")
print("="*65)
# 获取 language_server 进程命令行
result = subprocess.run(
    ['wmic', 'process', 'where', 'name="language_server_windows_x64.exe"',
     'get', 'ProcessId,CommandLine'],
    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10
)
print(result.stdout[:1000] if result.stdout else 'NOT FOUND')
# Also try without .exe
result2 = subprocess.run(
    ['wmic', 'process', 'where', 'name like "%language_server%"',
     'get', 'ProcessId,CommandLine'],
    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10
)
print(result2.stdout[:2000] if result2.stdout else 'Not found via LIKE')

print("\n" + "="*65)
print("TRACK D: 语言服务器日志文件")
print("="*65)
log_dirs = [
    os.path.expandvars(r'%APPDATA%\Windsurf\logs'),
    os.path.expandvars(r'%USERPROFILE%\.codeium\windsurf\bin\language_server'),
    r'C:\Users\zhouyoukang\.codeium',
    os.path.expandvars(r'%LOCALAPPDATA%\Windsurf'),
]
import glob
for d in log_dirs:
    if os.path.exists(d):
        log_files = sorted(glob.glob(os.path.join(d, '**', '*.log'), recursive=True),
                           key=lambda x: os.path.getmtime(x), reverse=True)[:3]
        for lf in log_files:
            try:
                with open(lf, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                if 'csrf' in content.lower() or 'csrfToken' in content:
                    csrf_lines = [l for l in content.split('\n') if 'csrf' in l.lower()]
                    print(f"\n  {lf}:")
                    for cl in csrf_lines[:5]:
                        print(f"    {cl[:150]}")
                elif 'port' in content.lower() and len(content) < 50000:
                    print(f"\n  {lf} (first 300B): {content[:300]}")
            except Exception as e:
                pass

print("\n" + "="*65)
print("TRACK E: LanguageServerClient 初始化")
print("="*65)
# Find LanguageServerClient class definition
m2 = re.search(r'class LanguageServerClient\b.{0,2000}', ext)
if m2:
    print(m2.group(0)[:600])
else:
    # Find getInstance
    for m3 in re.finditer(r'getInstance\(\)', ext):
        ctx = ext[max(0,m3.start()-200):m3.start()+200]
        if 'csrf' in ctx.lower():
            print(f"@{m3.start()}: {ctx[:300]}")
            break

print("\n=== DONE ===")
