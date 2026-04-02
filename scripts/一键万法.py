#!/usr/bin/env python3
"""
一键万法.py — 道生一·一生二·二生三·三生万物
============================================
调用万法之资，全面打通 Windsurf 后端

执行顺序:
  ① 状态扫描    — 当前补丁 + Windsurf 版本 + LS 端口
  ② 全补丁应用  — P1-P5 + ws_repatch + P15 AutoContinue
  ③ 密钥守护    — 后台启动 key_daemon (维护 Claude key vault)
  ④ 深度探针    — 逐模型测试，找到最佳可用模型
  ⑤ 热重载      — IPC reloadWindow (2s 内无感生效)
  ⑥ 汇总报告    — 打印可用模型 + DEFAULT_MODEL 建议

Usage:
  python 一键万法.py           # 完整流程
  python 一键万法.py --status  # 仅查状态
  python 一键万法.py --patch   # 仅打补丁 + 热重载
  python 一键万法.py --probe   # 仅探测模型
  python 一键万法.py --daemon  # 仅启动密钥守护
  python 一键万法.py --quick   # 快速模式 (只测 Claude 系列)
"""

import sys, os, io, json, time, subprocess, argparse
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SCRIPT_DIR  = Path(__file__).parent
DIAG_DIR    = SCRIPT_DIR / '040-诊断工具_Diagnostics'
PROBE_SCRIPT = SCRIPT_DIR / '全打通_深度探针.py'
ULTIMATE     = SCRIPT_DIR / 'opus46_ultimate.py'
REPATCH      = SCRIPT_DIR / 'ws_repatch.py'
PATCH_BYPASS = SCRIPT_DIR / 'patch_continue_bypass.py'
AC_FIX       = DIAG_DIR   / '_auto_continue_fix.py'
KEY_DAEMON   = SCRIPT_DIR / 'key_daemon.py'

PYTHON = sys.executable

def hr(char='═', n=70):
    print(char * n)

def section(title):
    hr()
    print(f"  {title}")
    hr('─')

def run_script(script: Path, extra_args=(), timeout=120, capture=False):
    """运行子脚本，返回 (returncode, stdout+stderr)"""
    cmd = [PYTHON, str(script)] + list(extra_args)
    if capture:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=timeout)
        return r.returncode, (r.stdout + r.stderr)
    else:
        r = subprocess.run(cmd, timeout=timeout)
        return r.returncode, ''

# ══════════════════════════════════════════════════════════════
# ① 状态扫描
# ══════════════════════════════════════════════════════════════
def do_status():
    section("① 状态扫描")

    # Windsurf 版本
    for wf_root in [
        Path(r'D:\Windsurf\resources\app'),
        Path(os.environ.get('LOCALAPPDATA','')) / 'Programs' / 'Windsurf' / 'resources' / 'app',
    ]:
        pkg = wf_root / 'package.json'
        if pkg.exists():
            try:
                v = json.loads(pkg.read_text(encoding='utf-8')).get('version', '?')
                print(f"  Windsurf 版本: {v}  ({wf_root})")
            except: pass
            break

    # LS 进程
    try:
        r = subprocess.run(['tasklist','/FI','IMAGENAME eq language_server_windows_x64.exe','/FO','CSV','/NH'],
                           capture_output=True, text=True, timeout=5)
        pids = [line.split('","')[1] for line in r.stdout.strip().splitlines()
                if '","' in line]
        if pids:
            print(f"  LS 进程 PID: {', '.join(pids)}")
        else:
            print("  ⚠ 未找到 LS 进程! 请启动 Windsurf")
    except: pass

    # 补丁状态
    if PATCH_BYPASS.exists():
        rc, out = run_script(PATCH_BYPASS, ['--verify'], capture=True)
        lines = [l for l in out.splitlines() if any(x in l for x in
                 ['P1','P2','P3','P4','P5','APPLIED','NOT_APPLIED','UNKNOWN','PARTIAL','FILE_MISSING'])]
        for l in lines[:10]:
            print(f"  {l.strip()}")
    else:
        print("  ⚠ patch_continue_bypass.py 不存在")

    # ws_repatch 状态
    if REPATCH.exists():
        rc, out = run_script(REPATCH, ['--check'], capture=True)
        lines = [l for l in out.splitlines() if any(x in l for x in
                 ['APPLIED','NOT_APPLIED','P3','P5','P12','P13','P14'])]
        for l in lines[:8]:
            print(f"  {l.strip()}")

    print()


# ══════════════════════════════════════════════════════════════
# ② 全补丁应用
# ══════════════════════════════════════════════════════════════
def do_patch():
    section("② 全补丁应用")

    applied_any = False

    # A. patch_continue_bypass.py — P1-P5
    if PATCH_BYPASS.exists():
        print("[A] 应用 P1-P5 (maxGen=9999 + AutoContinue ENABLED)...")
        rc, _ = run_script(PATCH_BYPASS)
        if rc == 0:
            print("  ✓ P1-P5 完成")
            applied_any = True
        else:
            print(f"  ⚠ 退出码 {rc}")
    else:
        print(f"  ✗ {PATCH_BYPASS.name} 不存在")

    # B. ws_repatch.py — P3-P14 (rate limit bypass + model injection)
    if REPATCH.exists():
        print("\n[B] 应用 ws_repatch (P3/P5/P12/P13/P14: 限流静默 + 模型注入)...")
        rc, _ = run_script(REPATCH)
        if rc == 0:
            print("  ✓ ws_repatch 完成")
            applied_any = True
        else:
            print(f"  ⚠ 退出码 {rc}")
    else:
        print(f"  ✗ {REPATCH.name} 不存在")

    # C. _auto_continue_fix.py — P15 (AutoContinue UI 全局修复)
    if AC_FIX.exists():
        print("\n[C] 应用 P15 AutoContinue 全局修复 + 热重载...")
        rc, _ = run_script(AC_FIX)
        if rc == 0:
            print("  ✓ P15 完成，Windsurf 热重载中...")
            applied_any = True
        else:
            print(f"  ⚠ 退出码 {rc}")
    else:
        print(f"  ✗ {AC_FIX.name} 不存在")

    if applied_any:
        print("\n  所有补丁应用完成")
    else:
        print("\n  ⚠ 无补丁被应用")
    print()
    return applied_any


# ══════════════════════════════════════════════════════════════
# ③ 密钥守护
# ══════════════════════════════════════════════════════════════
def do_daemon():
    section("③ 密钥守护 (key_daemon)")

    if not KEY_DAEMON.exists():
        print(f"  ✗ {KEY_DAEMON.name} 不存在，跳过")
        return

    # 检查 daemon 是否已在运行
    try:
        r = subprocess.run(['tasklist','/FI','IMAGENAME eq python.exe','/FO','CSV'],
                           capture_output=True, text=True, timeout=5)
        if 'key_daemon' in r.stdout:
            print("  ✓ key_daemon 已在运行")
            return
    except: pass

    # 后台启动
    try:
        subprocess.Popen(
            [PYTHON, str(KEY_DAEMON)],
            stdout=open(SCRIPT_DIR / 'daemon.log', 'a', encoding='utf-8'),
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        print(f"  ✓ key_daemon 后台启动 (日志: daemon.log)")
    except Exception as e:
        print(f"  ⚠ 启动失败: {e}")
    print()


# ══════════════════════════════════════════════════════════════
# ④ 深度探针
# ══════════════════════════════════════════════════════════════
def do_probe(quick=False):
    section("④ 深度探针 (逐模型测试)")

    if not PROBE_SCRIPT.exists():
        print(f"  ✗ {PROBE_SCRIPT.name} 不存在")
        return None

    extra = ['--quick'] if quick else []
    print(f"  运行探针{'(快速模式)' if quick else '(完整模式)'}...")
    rc, _ = run_script(PROBE_SCRIPT, extra, timeout=300)

    # 读取探针报告
    report_path = SCRIPT_DIR / '全打通_报告.json'
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding='utf-8'))
            ok_models = [m for m in report.get('models', []) if m.get('status') == 'ok']
            if ok_models:
                print(f"\n  ✓ 可用模型 ({len(ok_models)}个):")
                for m in ok_models:
                    print(f"    [{m['tier']}] {m['name']} → {m['uid']}")
                return ok_models[0]['uid']
            else:
                print("  ⚠ 无模型成功响应")
                # 错误统计
                from collections import Counter
                statuses = Counter(m.get('status','?') for m in report.get('models', []))
                print(f"  错误分布: {dict(statuses)}")
        except Exception as e:
            print(f"  解析报告失败: {e}")
    print()
    return None


# ══════════════════════════════════════════════════════════════
# ⑤ 最终报告
# ══════════════════════════════════════════════════════════════
def do_summary(best_uid):
    hr()
    print("  最终报告")
    hr('─')

    if best_uid:
        print(f"  ✓ 最佳可用模型: {best_uid}")
        print(f"  → opus46_ultimate.py DEFAULT_MODEL = \"{best_uid}\"")
        print()
        print(f"  立即测试:")
        print(f"    python opus46_ultimate.py \"你好，介绍一下你自己\"")
    else:
        print("  ⚠ 未找到可用模型")
        print()
        print("  可能原因:")
        print("  1. 账号配额耗尽 — 等待日/周重置或注册新账号")
        print("  2. WAM key 无 Claude 权限 — 切换到有 Pro 计划的账号")
        print("  3. Windsurf 未启动 — 先启动 Windsurf IDE")
        print()
        print("  备选方案 (无限额度):")
        print("  A. BYOK: 配置自己的 Anthropic API key → 使用 MODEL_CLAUDE_4_OPUS_BYOK")
        print("  B. 免费模型: SWE-1.5 / GPT-5-Codex 无需 Claude 权限")
        print("  C. 注册新账号: 使用账号池中的 fresh Trial 账号")

    hr()
    print(f"  完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    hr()


# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description='一键万法 — Windsurf 全打通')
    parser.add_argument('--status',  action='store_true', help='仅查状态')
    parser.add_argument('--patch',   action='store_true', help='仅打补丁')
    parser.add_argument('--probe',   action='store_true', help='仅探测模型')
    parser.add_argument('--daemon',  action='store_true', help='仅启动密钥守护')
    parser.add_argument('--quick',   action='store_true', help='快速模式 (只测 Claude 系列)')
    args = parser.parse_args()

    hr('═')
    print("  一键万法 — 道生一·一生二·二生三·三生万物")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    hr('═')
    print()

    if args.status:
        do_status()
        return

    if args.patch:
        do_patch()
        return

    if args.probe:
        best = do_probe(args.quick)
        do_summary(best)
        return

    if args.daemon:
        do_daemon()
        return

    # 完整流程
    do_status()
    do_patch()
    do_daemon()
    best_uid = do_probe(args.quick)
    do_summary(best_uid)


if __name__ == '__main__':
    main()
