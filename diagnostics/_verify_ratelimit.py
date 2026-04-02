"""
Rate Limit 真正验证脚本 — 道法自然·不假设·只验证
搜索 workbench.js + extension.js 中与错误信息的真实匹配
追踪从 gRPC 错误 → 用户 UI 的完整传播路径
"""
import os, re, json

WB_JS = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
EXT_JS = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'

def search_context(content, pattern, ctx_before=300, ctx_after=500, max_hits=5, label=""):
    """搜索并返回所有匹配的上下文"""
    results = []
    idx = 0
    while len(results) < max_hits:
        idx = content.find(pattern, idx)
        if idx < 0:
            break
        start = max(0, idx - ctx_before)
        end = min(len(content), idx + ctx_after)
        results.append((idx, content[start:end]))
        idx += 1
    if not results:
        print(f"  [{label}] '{pattern}' → NOT FOUND")
    for offset, ctx in results:
        print(f"  [{label}] @ offset {offset}")
        print(f"  {ctx}")
        print("  ---")
    return results

print("=" * 70)
print("PHASE 1: 搜索用户截图中的精确错误文本")
print("=" * 70)

with open(WB_JS, 'r', encoding='utf-8', errors='replace') as f:
    wb = f.read()
with open(EXT_JS, 'r', encoding='utf-8', errors='replace') as f:
    ext = f.read()

# 搜索截图中的精确错误文本
error_phrases = [
    "Reached message rate limit",
    "message rate limit for this model",
    "rate limit for this model",
    "Resets in:",
    "Permission denied:",
    "Permission denied: Reached",
]

for phrase in error_phrases:
    print(f"\n--- WB: '{phrase}' ---")
    search_context(wb, phrase, 400, 600, 3, "WB")
    print(f"\n--- EXT: '{phrase}' ---")
    search_context(ext, phrase, 400, 600, 3, "EXT")

print("\n" + "=" * 70)
print("PHASE 2: 验证 if(!1) 死代码的精确上下文")
print("=" * 70)

# 找到 checkUserMessageRateLimit 调用点并提取周围完整逻辑
idx = wb.find("checkUserMessageRateLimit")
while idx >= 0:
    # 检查是否是调用点（不是定义点）
    region = wb[max(0, idx-20):idx+50]
    if "await" in region or ".check" in region:
        print(f"\n  CALL SITE @ {idx}")
        print(wb[max(0, idx-500):idx+800])
        print("  ---")
    idx = wb.find("checkUserMessageRateLimit", idx + 1)

print("\n" + "=" * 70)
print("PHASE 3: 搜索 gRPC 错误传播路径 (ConnectError / PERMISSION_DENIED)")
print("=" * 70)

# 搜索 ConnectError 的处理
for pat in ["PERMISSION_DENIED", "permission_denied", "PermissionDenied"]:
    idx = wb.find(pat)
    if idx >= 0:
        # 只看与 gRPC/connect 相关的
        ctx = wb[max(0, idx-200):idx+300]
        if any(k in ctx.lower() for k in ['grpc', 'connect', 'code', 'status', 'http']):
            print(f"\n  [{pat}] @ {idx} (gRPC related)")
            print(f"  {ctx}")

# 关键: 搜索 trace ID 格式 (trace ID: xxx) — 这能锁定错误生成点
print("\n--- trace ID format ---")
search_context(wb, "trace ID", 300, 300, 3, "WB-trace")
search_context(ext, "trace ID", 300, 300, 3, "EXT-trace")

# 搜索 "trace" 和 "traceId"
for pat in ["traceId", "trace_id", "errorId"]:
    print(f"\n--- {pat} ---")
    hits = search_context(wb, pat, 200, 300, 2, "WB")
    if not hits:
        search_context(ext, pat, 200, 300, 2, "EXT")

print("\n" + "=" * 70)
print("PHASE 4: 搜索错误消息组装逻辑 (error message template)")
print("=" * 70)

# 搜索可能组装 "Permission denied: ... Resets in: ... (trace ID: ...)" 的代码
for pat in [
    "Resets in:",
    "resets in",
    "resetIn",
    "resetsIn",
    "Please try again later",
    "try again later",
]:
    print(f"\n--- '{pat}' ---")
    for label, content in [("WB", wb), ("EXT", ext)]:
        hits = search_context(content, pat, 300, 400, 2, label)

print("\n" + "=" * 70)
print("PHASE 5: 搜索 'rate_limited' 和 'rate limit' 错误代码")
print("=" * 70)

for pat in ["rate_limited", "rateLimited", "RATE_LIMITED", "rate limit", "rateLimit"]:
    for label, content in [("WB", wb), ("EXT", ext)]:
        idx = content.find(pat)
        if idx >= 0:
            ctx = content[max(0, idx-100):idx+200]
            # 过滤掉 ASP.NET 不相关的
            if "aspnet" not in ctx.lower() and "ASPNET" not in ctx:
                print(f"  [{label}] '{pat}' @ {idx}: {ctx[:300]}")

print("\n=== VERIFICATION COMPLETE ===")
