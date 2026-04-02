#!/usr/bin/env python3
"""
workbench.js 持久补丁 — Claude Opus 4.6 commandModels 注入
================================================================
原理: 在两个 commandModels 解析赋值点注入 claude-opus-4-6 fake config
  LOC1: u() 方法 — 初始加载
  LOC2: updateWindsurfAuthStatus() — 登录刷新时
注入后每次 Windsurf 加载/登录刷新均自动追加 opus-4-6 到模型列表
"""
import os, shutil, sys
from datetime import datetime

WB_JS = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
OPUS46_B64 = 'Cg9DbGF1ZGUgT3B1cyA0LjayAQ9jbGF1ZGUtb3B1cy00LTYdAADAQCAAaASQAcCaDKABAMABAw=='

# ── LOC1: u() 初始加载 ──
# D = allowedCommandModelConfigsProtoBinaryBase64 数组
LOC1_OLD = ('allowedCommandModelConfigsProtoBinaryBase64??this.f?.'
            'allowedCommandModelConfigsProtoJsonString;'
            'this.j=this.C(D),this.b.fire(this.f)')

LOC1_NEW = ('allowedCommandModelConfigsProtoBinaryBase64??this.f?.'
            'allowedCommandModelConfigsProtoJsonString;'
            f'const __wD=Array.isArray(D)?[...D,\'{OPUS46_B64}\']:D;'
            'this.j=this.C(__wD),this.b.fire(this.f)')

# ── LOC2: updateWindsurfAuthStatus() 登录刷新 ──
LOC2_OLD = ('allowedCommandModelConfigsProtoBinaryBase64;'
            'this.j=C?this.C(C):[],this.y(),this.b.fire(_),this.z()')

LOC2_NEW = ('allowedCommandModelConfigsProtoBinaryBase64;'
            f'const __wC=Array.isArray(C)?[...C,\'{OPUS46_B64}\']:C?[C,\'{OPUS46_B64}\']:[],\'{OPUS46_B64}\'];'
            'this.j=__wC.length?this.C(__wC):[],this.y(),this.b.fire(_),this.z()')

# 更简洁的LOC2_NEW（避免数组语法错误）
LOC2_NEW = (f'allowedCommandModelConfigsProtoBinaryBase64;'
            f'const __wC=(Array.isArray(C)?[...C]:C?[C]:[]);'
            f'if(!__wC.includes(\'{OPUS46_B64}\'))__wC.push(\'{OPUS46_B64}\');'
            f'this.j=this.C(__wC),this.y(),this.b.fire(_),this.z()')


def check_patch_status(wb):
    """检查补丁状态"""
    already1 = OPUS46_B64 in wb and '__wD' in wb
    already2 = OPUS46_B64 in wb and '__wC' in wb
    loc1_present = LOC1_OLD in wb
    loc2_present = LOC2_OLD in wb
    return already1, already2, loc1_present, loc2_present


def apply_patch():
    print("=" * 65)
    print(f"workbench.js opus-4-6 持久补丁 — {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 65)
    print(f"目标: {WB_JS}")

    if not os.path.exists(WB_JS):
        print(f"❌ 文件不存在: {WB_JS}")
        return False

    with open(WB_JS, 'r', encoding='utf-8', errors='replace') as f:
        wb = f.read()

    orig_size = len(wb)
    print(f"文件大小: {orig_size:,} bytes")

    p1, p2, l1, l2 = check_patch_status(wb)
    print(f"\n状态检查:")
    print(f"  LOC1 (u方法):                 {'✅ 已补丁' if p1 else ('✔ 可注入' if l1 else '❌ 未找到')}")
    print(f"  LOC2 (updateWindsurfAuth):   {'✅ 已补丁' if p2 else ('✔ 可注入' if l2 else '❌ 未找到')}")

    if p1 and p2:
        print("\n✅ 两处补丁均已应用，无需重复操作")
        return True

    # 备份
    bak = WB_JS + f'.bak_opus46_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    existing_baks = [f for f in os.listdir(os.path.dirname(WB_JS)) if 'bak_opus46' in f]
    if not existing_baks:
        shutil.copy2(WB_JS, bak)
        print(f"\n备份: {bak}")
    else:
        print(f"\n备份已存在 ({len(existing_baks)}个)，跳过")

    patches = []

    # LOC1
    if not p1 and l1:
        wb = wb.replace(LOC1_OLD, LOC1_NEW, 1)
        patches.append('LOC1 (u方法 初始加载)')

    # LOC2
    if not p2 and l2:
        wb = wb.replace(LOC2_OLD, LOC2_NEW, 1)
        patches.append('LOC2 (updateWindsurfAuthStatus 登录刷新)')

    if not patches:
        print("\n❌ 无法注入：未找到目标字符串")
        print("  可能workbench.js已被更新或结构变化")
        return False

    # 验证补丁有效
    if OPUS46_B64 not in wb:
        print("\n❌ 补丁验证失败: OPUS46_B64 不在文件中")
        return False

    # 写入
    with open(WB_JS, 'w', encoding='utf-8') as f:
        f.write(wb)

    new_size = len(wb)
    print(f"\n✅ 补丁已应用 ({len(patches)}处):")
    for p in patches:
        print(f"  + {p}")
    print(f"文件大小变化: {orig_size:,} → {new_size:,} (+{new_size-orig_size}B)")
    print("\n→ 重载 Windsurf (Ctrl+Shift+P → Reload Window) 后永久生效")
    print("→ 即使重新登录也会保留 Claude Opus 4.6")
    return True


def revert_patch():
    """回滚补丁"""
    bak_dir = os.path.dirname(WB_JS)
    baks = sorted([f for f in os.listdir(bak_dir) if 'bak_opus46' in f])
    if not baks:
        print("❌ 未找到备份文件")
        return False
    latest = os.path.join(bak_dir, baks[-1])
    shutil.copy2(latest, WB_JS)
    print(f"✅ 已回滚到: {latest}")
    return True


if __name__ == '__main__':
    args = sys.argv[1:]
    if '--revert' in args:
        revert_patch()
    elif '--check' in args:
        with open(WB_JS, 'r', encoding='utf-8', errors='replace') as f:
            wb = f.read()
        p1, p2, l1, l2 = check_patch_status(wb)
        print(f"LOC1: {'已补丁' if p1 else '未补丁'} | LOC2: {'已补丁' if p2 else '未补丁'}")
        print(f"OPUS46_B64 出现次数: {wb.count(OPUS46_B64)}")
    else:
        apply_patch()
