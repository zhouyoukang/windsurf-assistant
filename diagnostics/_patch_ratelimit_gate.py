"""
Windsurf Rate Limit Gate Patch — 道法自然·激活死代码门禁
==========================================================
问题根因: workbench.js 中 checkUserMessageRateLimit 的结果被 if(!1) 丢弃,
          导致客户端无视服务端的 rate limit 警告直接发送 → 服务端拒绝 →
          gRPC 流错误 → cascade 状态异常 → 无法发送任何新请求.

修复: 将 if(!1) 改为 if(!response.hasCapacity), 让客户端在发送前
      就检测到 rate limit, 优雅显示服务端消息(含倒计时), 不污染 cascade 会话.

效果:
  - rate limit 时: 显示 "You have reached your message limit..." + 重置倒计时
  - cascade session: 不受影响, 切换模型立即可用
  - 不再出现 "Permission denied" gRPC 流错误
"""
import os, shutil, hashlib
from datetime import datetime

WB = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
BACKUP_DIR = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage')

def md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

def patch():
    if not os.path.exists(WB):
        print(f"ERROR: {WB} not found")
        return False

    # 1. 备份
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = os.path.join(BACKUP_DIR, f'workbench_backup_{ts}.js.md5')
    orig_md5 = md5(WB)
    with open(backup, 'w') as f:
        f.write(f"{orig_md5}  workbench.desktop.main.js\n")
    print(f"[1/4] MD5 backup: {backup}")
    print(f"       Original MD5: {orig_md5}")

    # 2. 读取
    with open(WB, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    print(f"[2/4] Read {len(content)} chars")

    # 3. 检查是否已 patch
    if 'if(!tu.hasCapacity)return' in content:
        print("[!] Already patched. Nothing to do.")
        return True

    # 4. 精确替换 — Gate 1: checkChatCapacity
    old1 = 'U4.modelUid}));if(!1)return np(),py(void 0),ys(Ru.message'
    new1 = 'U4.modelUid}));if(!Ru.hasCapacity)return np(),py(void 0),ys(Ru.message'
    count1 = content.count(old1)
    if count1 != 1:
        print(f"ERROR: Gate 1 pattern found {count1} times (expected 1). Aborting.")
        return False
    content = content.replace(old1, new1, 1)
    print(f"[3/4] Gate 1 patched: if(!1) -> if(!Ru.hasCapacity)  [checkChatCapacity]")

    # 5. 精确替换 — Gate 2: checkUserMessageRateLimit
    old2 = 'U4.modelUid});if(!1)return np(),py(void 0),ys(tu.message'
    new2 = 'U4.modelUid});if(!tu.hasCapacity)return np(),py(void 0),ys(tu.message'
    count2 = content.count(old2)
    if count2 != 1:
        print(f"ERROR: Gate 2 pattern found {count2} times (expected 1). Aborting.")
        return False
    content = content.replace(old2, new2, 1)
    print(f"[3/4] Gate 2 patched: if(!1) -> if(!tu.hasCapacity)  [checkUserMessageRateLimit]")

    # 6. 写入
    with open(WB, 'w', encoding='utf-8', newline='') as f:
        f.write(content)
    new_md5 = md5(WB)
    print(f"[4/4] Written. New MD5: {new_md5}")

    # 7. 验证
    with open(WB, 'r', encoding='utf-8', errors='replace') as f:
        verify = f.read()
    g1_ok = 'if(!Ru.hasCapacity)return np(),py(void 0),ys(Ru.message' in verify
    g2_ok = 'if(!tu.hasCapacity)return np(),py(void 0),ys(tu.message' in verify
    old1_gone = old1 not in verify
    old2_gone = old2 not in verify
    print(f"\n=== VERIFICATION ===")
    print(f"  Gate 1 activated: {'OK' if g1_ok else 'FAIL'}")
    print(f"  Gate 2 activated: {'OK' if g2_ok else 'FAIL'}")
    print(f"  Old Gate 1 gone:  {'OK' if old1_gone else 'FAIL'}")
    print(f"  Old Gate 2 gone:  {'OK' if old2_gone else 'FAIL'}")

    if g1_ok and g2_ok and old1_gone and old2_gone:
        print(f"\n✓ PATCH SUCCESSFUL")
        print(f"  重启 Windsurf 后生效.")
        print(f"  效果: Opus rate limit 时优雅显示倒计时, 不破坏 cascade 会话.")
        print(f"  切换其他模型(Sonnet/SWE)立即可用.")
        return True
    else:
        print(f"\n✗ VERIFICATION FAILED — 请检查文件完整性")
        return False

def unpatch():
    """还原 patch（如需回退）"""
    with open(WB, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    p1 = 'if(!Ru.hasCapacity)return np(),py(void 0),ys(Ru.message'
    p2 = 'if(!tu.hasCapacity)return np(),py(void 0),ys(tu.message'
    o1 = 'if(!1)return np(),py(void 0),ys(Ru.message'
    o2 = 'if(!1)return np(),py(void 0),ys(tu.message'
    content = content.replace(p1, o1, 1).replace(p2, o2, 1)
    with open(WB, 'w', encoding='utf-8', newline='') as f:
        f.write(content)
    print("Unpatched. Restart Windsurf to revert.")

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'unpatch':
        unpatch()
    else:
        patch()
