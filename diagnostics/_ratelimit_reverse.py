"""
Rate Limit Root Cause Reversal - 道法自然
目标: 找出 Claude Opus 4.6 "message rate limit" 导致无法发送任何新请求的本地根源
"""
import sqlite3, os, json, base64, struct, re

STATE_DB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')
WB_JS = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
EXT_JS = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'

# ===== 1. 查询 state.vscdb 所有 key =====
print("=" * 60)
print("1. STATE.VSCDB KEY SCAN")
print("=" * 60)
conn = sqlite3.connect(f'file:{STATE_DB}?mode=ro', uri=True)
cur = conn.cursor()
cur.execute("SELECT key FROM ItemTable")
all_keys = [r[0] for r in cur.fetchall()]
keywords = ['rate', 'limit', 'cascade', 'capacity', 'block', 'auth', 'plan', 'quota', 'grace', 'token']
for k in all_keys:
    kl = k.lower()
    if any(kw in kl for kw in keywords):
        print(f"  KEY: {k}")
conn.close()

# ===== 2. 搜索 workbench.js 中 rate limit 错误处理和 cascadeState 状态机 =====
print("\n" + "=" * 60)
print("2. WORKBENCH.JS - CASCADESTATE + ERROR HANDLING")
print("=" * 60)

with open(WB_JS, 'r', encoding='utf-8', errors='replace') as f:
    wb = f.read()

# 找 cascadeState trajectory 相关
targets = [
    ("cascadeState.status", 800),
    ("GENERATING", 600),
    ("trajectory.status", 600),
    ("cascade_running", 400),
    ("isCapacityLimited", 400),
    ("GracePeriod.ACTIVE", 400),
    ("gracePeriodStatus", 600),
    ("hasCapacity", 500),
    ("resetsInSeconds", 500),
    ("resets_in_seconds", 500),
    ("messagesRemaining", 500),
    ("rateLimitedUntil", 400),
    ("rateLimitExpiry", 400),
    ("rateLimitCache", 400),
    ("messageRateLimit", 600),
    ("WRITE_CHAT_INSUFFICIENT", 600),
    ("aye(Bi)", 800),  # the function that computes Qb in the cascade component
]

for pat, ctx in targets:
    idx = wb.find(pat)
    if idx >= 0:
        print(f"\n  [{pat}] @ {idx}")
        print(f"  {wb[max(0,idx-200):idx+ctx][:600]}")
    else:
        print(f"\n  [{pat}] NOT FOUND")

# ===== 3. 找 aye 函数（计算 isSendDisabledMessage 的核心） =====
print("\n" + "=" * 60)
print("3. AYE FUNCTION - isSendDisabledMessage CORE")
print("=" * 60)
# search for function aye or const aye
for pat in ['function aye(', 'const aye=', 'aye=Z=>', 'aye=B=>']:
    idx = wb.find(pat)
    if idx >= 0:
        print(f"FOUND: {pat} @ {idx}")
        print(wb[max(0,idx-100):idx+800])
        break

# ===== 4. 找 WRITE_CHAT_INSUFFICIENT_CASCADE_CREDITS 和相关错误代码 =====
print("\n" + "=" * 60)
print("4. ERROR CODES THAT DISABLE SEND BUTTON")
print("=" * 60)
error_codes = ['WRITE_CHAT_INSUFFICIENT_CASCADE_CREDITS', 'WRITE_CHAT_UPGRADE_FOR_CREDITS',
               'WORKFLOWS_NOT_SUPPORTED', 'CASCADE_NOT_SUPPORTED', 'ARENA_MODE_INSUFFICIENT',
               'RATE_LIMITED', 'MESSAGE_RATE', 'USER_MESSAGE_RATE']
for ec in error_codes:
    idx = wb.find(ec)
    if idx >= 0:
        print(f"\n  [{ec}] @ {idx}")
        print(f"  {wb[max(0,idx-100):idx+400]}")
    else:
        print(f"\n  [{ec}] NOT FOUND")

# ===== 5. 搜索 extension.js 中 rate limit 相关的本地缓存逻辑 =====
print("\n" + "=" * 60)
print("5. EXTENSION.JS - LOCAL RATE LIMIT CACHE/STATE")
print("=" * 60)
with open(EXT_JS, 'r', encoding='utf-8', errors='replace') as f:
    ext = f.read()

ext_targets = [
    ("resetsInSeconds", 600),
    ("resets_in_seconds", 600),
    ("messagesRemaining", 600),
    ("rateLimited", 600),
    ("hasCapacity", 600),
    ("messageRateLimit", 600),
    ("RATE_LIMIT", 600),
    ("cascadeRunning", 400),
    ("isRunning", 400),
    ("pendingMessage", 400),
]
for pat, ctx in ext_targets:
    idx = ext.find(pat)
    if idx >= 0:
        print(f"\n  [{pat}] @ {idx}")
        print(f"  {ext[max(0,idx-200):idx+ctx][:600]}")
    else:
        print(f"\n  [{pat}] NOT FOUND")

print("\n=== DONE ===")
