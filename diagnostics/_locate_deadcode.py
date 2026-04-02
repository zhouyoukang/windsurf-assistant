"""精确定位 workbench.js 中两处 if(!1) 死代码的替换模式"""
import os

WB = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
with open(WB, 'r', encoding='utf-8', errors='replace') as f:
    wb = f.read()

print(f"File size: {len(wb)} chars")

# === 1. 定位 checkChatCapacity 的 if(!1) ===
pat1 = 'U4.modelUid}));if(!1)return np(),py(void 0),ys(Ru.message'
idx1 = wb.find(pat1)
print(f"\n1. checkChatCapacity if(!1): {'FOUND at ' + str(idx1) if idx1>=0 else 'NOT FOUND'}")
if idx1 >= 0:
    print(f"   Context: {wb[idx1:idx1+120]}")
    print(f"   Unique: {wb.count(pat1)}")

# === 2. 定位 checkUserMessageRateLimit 的 if(!1) ===
pat2 = 'U4.modelUid});if(!1)return np(),py(void 0),ys(tu.message'
idx2 = wb.find(pat2)
print(f"\n2. checkUserMessageRateLimit if(!1): {'FOUND at ' + str(idx2) if idx2>=0 else 'NOT FOUND'}")
if idx2 >= 0:
    print(f"   Context: {wb[idx2:idx2+120]}")
    print(f"   Unique: {wb.count(pat2)}")

# === 3. 构造精确替换对 ===
# Gate 1: checkChatCapacity — 变量 Ru 是 CheckChatCapacityResponse
old1 = 'U4.modelUid}));if(!1)return np(),py(void 0),ys(Ru.message'
new1 = 'U4.modelUid}));if(!Ru.hasCapacity)return np(),py(void 0),ys(Ru.message'
# Gate 2: checkUserMessageRateLimit — 变量 tu 是 CheckUserMessageRateLimitResponse
old2 = 'U4.modelUid});if(!1)return np(),py(void 0),ys(tu.message'
new2 = 'U4.modelUid});if(!tu.hasCapacity)return np(),py(void 0),ys(tu.message'

print(f"\n=== REPLACEMENT PLAN ===")
print(f"Gate 1: '{old1[:50]}...' -> '{new1[:50]}...'")
print(f"  old len={len(old1)}, new len={len(new1)}, diff={len(new1)-len(old1)}")
print(f"  occurrences: {wb.count(old1)}")
print(f"Gate 2: '{old2[:50]}...' -> '{new2[:50]}...'")
print(f"  old len={len(old2)}, new len={len(new2)}, diff={len(new2)-len(old2)}")
print(f"  occurrences: {wb.count(old2)}")

# === 4. 验证替换后语法正确性 ===
test1 = wb.replace(old1, new1, 1)
test2 = test1.replace(old2, new2, 1)
# 检查替换后上下文
idx_new = test2.find('if(!Ru.hasCapacity)return')
if idx_new >= 0:
    print(f"\nGate 1 after patch: {test2[idx_new:idx_new+80]}")
idx_new2 = test2.find('if(!tu.hasCapacity)return')
if idx_new2 >= 0:
    print(f"Gate 2 after patch: {test2[idx_new2:idx_new2+80]}")

# === 5. 计算 if(!1)return 总出现次数 ===
total = wb.count('if(!1)return')
print(f"\nTotal 'if(!1)return' in file: {total}")
print(f"We only patch 2 of them (the rate limit gates)")
