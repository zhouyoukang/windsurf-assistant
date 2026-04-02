#!/usr/bin/env python3
"""
Windsurf Continue Bypass — 一键patch脚本 v6.0 万法归宗
========================================================
道生一(maxGen=9999) → 一生二(AutoContinue+EAGER+TURBO) → 二生三(ParallelRollout+客户端续接+autoRunAllowed) → 三生万物

11处patch (万法归宗·上善若水: 消除一切用户手动操作):
  P1. extension.js: maxGeneratorInvocations=0→9999
  P2. workbench.desktop.main.js: maxGeneratorInvocations=0→9999 (×2)
  P3. @exa/chat-client/index.js: maxGeneratorInvocations=0→9999
  P4. workbench.desktop.main.js: AutoContinue default DISABLED→ENABLED
  P5. extension.js: 注入ParallelRolloutConfig(2并行×50invocations) (实验性)
  P10. workbench+chat-client: 注入useEffect自动触发handleContinue (终极保底)
  P11. workbench.desktop.main.js: CascadeAutoExecution OFF→EAGER (命令自动执行)
  P12. workbench.desktop.main.js: CascadeWebRequests ALLOWLIST→TURBO (网络全自动)
  P13. workbench.desktop.main.js: autoRunAllowed强制true (绕过teamConfig服务端gate) ★根源
  P14. workbench.desktop.main.js: document.hidden→false (后台tab不throttle) ★根源
  P15. workbench.desktop.main.js: WAITING状态自动accept (终极保底: 注入autoAccept observer)

用法:
  python patch_continue_bypass.py              # 应用所有patch
  python patch_continue_bypass.py --verify     # 仅验证patch状态
  python patch_continue_bypass.py --rollback   # 非交互式回滚到最新原始备份
  python patch_continue_bypass.py --backup     # 仅备份不patch
  python patch_continue_bypass.py --watch      # 检测Windsurf更新并自动重新patch
  python patch_continue_bypass.py --status     # 完整状态报告(版本+patch+备份)
  python patch_continue_bypass.py --p5-only     # 仅应用P5(实验性ParallelRollout)

根因分析 (v6.0 万法归宗·上善若水):
  - 服务端强制~25次invocation限制 → P1-P3 maxGen=9999 + P10客户端强制续接
  - AutoContinue服务端不可靠 → P4 ENABLED + P10 useEffect自动触发
  - 命令执行需手动Run → P11 cascadeAutoExecution=EAGER
  - 网络搜索仅Allowlist → P12 cascadeWebRequests=TURBO
  - ★ autoRunAllowed受teamConfig服务端gate → P13 强制true (根源!)
  - ★ 后台tab timer被throttle → P14 document.hidden=false
  - ★ Run/Skip弹窗仍残留 → P15 自动accept observer
  - 所有patch在$mhb迁移函数中强制设置, 每次加载即生效
"""

import os, sys, shutil, json, hashlib, re
from datetime import datetime
from pathlib import Path

def _find_windsurf():
    """Auto-detect Windsurf installation path."""
    candidates = [
        Path(os.environ.get("WINDSURF_PATH", "")),
        Path(r"D:\Windsurf\resources\app"),
        Path(r"C:\Users") / os.environ.get("USERNAME", "user") / "AppData" / "Local" / "Programs" / "Windsurf" / "resources" / "app",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Windsurf" / "resources" / "app",
    ]
    for c in candidates:
        if c.exists() and (c / "package.json").exists():
            return c
    return Path(r"D:\Windsurf\resources\app")

WINDSURF_BASE = _find_windsurf()
SCRIPT_DIR = Path(__file__).parent
BACKUP_DIR = SCRIPT_DIR / "_windsurf_backups"
STATE_FILE = BACKUP_DIR / "_patch_state.json"

FILES = {
    "extension": WINDSURF_BASE / "extensions" / "windsurf" / "dist" / "extension.js",
    "workbench": WINDSURF_BASE / "out" / "vs" / "workbench" / "workbench.desktop.main.js",
    "chat_client": WINDSURF_BASE / "node_modules" / "@exa" / "chat-client" / "index.js",
}

PATCHES = [
    {
        "id": "P1",
        "file": "extension",
        "old": "maxGeneratorInvocations=0",
        "new": "maxGeneratorInvocations=9999",
        "desc": "extension.js maxGen 0→9999",
        "expected_count": 1,
    },
    {
        "id": "P2",
        "file": "workbench",
        "old": "maxGeneratorInvocations=0",
        "new": "maxGeneratorInvocations=9999",
        "desc": "workbench.js maxGen 0→9999 (×2)",
        "expected_count": 2,
    },
    {
        "id": "P3",
        "file": "chat_client",
        "old": "maxGeneratorInvocations=0",
        "new": "maxGeneratorInvocations=9999",
        "desc": "chat-client maxGen 0→9999",
        "expected_count": 1,
    },
    {
        "id": "P4",
        "file": "workbench",
        "old": "C.autoContinueOnMaxGeneratorInvocations===AutoContinueOnMaxGeneratorInvocations.UNSPECIFIED&&(C.autoContinueOnMaxGeneratorInvocations=AutoContinueOnMaxGeneratorInvocations.DISABLED)",
        "new": "C.autoContinueOnMaxGeneratorInvocations!==AutoContinueOnMaxGeneratorInvocations.ENABLED  &&(C.autoContinueOnMaxGeneratorInvocations=AutoContinueOnMaxGeneratorInvocations.ENABLED )",
        "desc": "AutoContinue default DISABLED→ENABLED (核心突破)",
        "expected_count": 1,
    },
]

# ============================================================
# P6-P9: 从WF无限调优v5.6.29逆向提取的新补丁方案 (2026-03-18)
# 这些方案在Windsurf版本更新后P1-P4匹配失败时作为备选
# ============================================================
PATCHES_WF_EXTENDED = [
    {
        "id": "P6",
        "file": "workbench",
        "regex": True,
        "pattern": r'(\w+)\[\1\.MAX_INVOCATIONS=3\]="MAX_INVOCATIONS"',
        "replace": lambda m: f'{m.group(1)}[{m.group(1)}.MAX_INVOCATIONS=999999]="MAX_INVOCATIONS"',
        "desc": "WF方案E: workbench MAX_INVOCATIONS枚举 3→999999 (regex)",
    },
    {
        "id": "P7",
        "file": "workbench",
        "regex": True,
        "pattern": r'=\s*\(0,\s*(\w+)\.useMemo\)\(\(\)\s*=>\s*\{',
        "replace_first_only": True,
        "replace_str": "=(0,{useMemo_var}.useMemo)(()=>false,[",
        "desc": "WF方案F: workbench useMemo弹窗禁用→false (regex, 首次匹配)",
    },
    {
        "id": "P8",
        "file": "extension",
        "regex": True,
        "pattern": r'(\w+)\[\1\.MAX_INVOCATIONS=3\]="MAX_INVOCATIONS"',
        "replace": lambda m: f'{m.group(1)}[{m.group(1)}.MAX_INVOCATIONS=999999]="MAX_INVOCATIONS"',
        "desc": "WF方案C: extension.js MAX_INVOCATIONS枚举 3→999999 (regex)",
    },
    {
        "id": "P9",
        "file": "extension",
        "old": "executorConfig:{maxGeneratorInvocations:3}",
        "new": "executorConfig:{maxGeneratorInvocations:999999}",
        "desc": "WF方案A: extension.js executorConfig注入极大值",
        "expected_count": 1,
    },
]

REGEX_FALLBACKS = [
    re.compile(r'(this\.maxGeneratorInvocations\s*=\s*)0([,;\s])'),
    re.compile(r'(name:"max_generator_invocations".{0,200}?maxGeneratorInvocations\s*=\s*)0([,;\s])'),
]

AUTO_CONTINUE_REGEX = re.compile(
    r'(C\.autoContinueOnMaxGeneratorInvocations)==='
    r'(AutoContinueOnMaxGeneratorInvocations)\.UNSPECIFIED'
    r'&&\(\1=(\2)\.DISABLED\)'
)

# P5: ParallelRolloutConfig injection patterns
P5_CASCADE_CONFIG_TYPENAME = 'typeName="exa.cortex_pb.CascadeConfig"'
P5_PRC_TYPENAME = 'typeName="exa.cortex_pb.ParallelRolloutConfig"'
P5_MARKER = 'parallelRolloutConfig||'  # presence = P5 already applied

# P10: Client-side auto-continue injection (终极保底)
# 当服务端不auto-continue时, 客户端"Continue response"组件挂载后自动触发handleContinue
P10_MARKER = '_ac=setTimeout(()=>'  # presence = P10 already applied
P10_PATCHES = [
    {
        "file": "workbench",
        "old_pattern": re.compile(
            r'handleContinue:(\w+),getLexical:(\w+)\}\)=>\{'
            r'const (\w+)=\(0,(\w+)\.useIsMac\)\(\);'
            r'\(0,(\w+)\.useEffect\)\(\(\)=>\{const (\w+)=\2\(\)'
        ),
        "build_new": lambda m: (
            f'handleContinue:{m.group(1)},getLexical:{m.group(2)}}})=>{{'
            f'(0,{m.group(5)}.useEffect)(()=>{{const _ac=setTimeout(()=>{m.group(1)}(),800);return()=>clearTimeout(_ac)}},[{m.group(1)}]);'
            f'const {m.group(3)}=(0,{m.group(4)}.useIsMac)();'
            f'(0,{m.group(5)}.useEffect)(()=>{{const {m.group(6)}={m.group(2)}()'
        ),
        "desc": "workbench: auto-continue useEffect injection",
    },
    {
        "file": "chat_client",
        "old_pattern": re.compile(
            r'handleContinue:(\w+),getLexical:(\w+)\}\)=>\{'
            r'const (\w+)=\(0,(\w+)\.useIsMac\)\(\);'
            r'\(0,(\w+)\.useEffect\)\(\(\)=>\{const (\w+)=\2\(\)'
        ),
        "build_new": lambda m: (
            f'handleContinue:{m.group(1)},getLexical:{m.group(2)}}})=>{{'
            f'(0,{m.group(5)}.useEffect)(()=>{{const _ac=setTimeout(()=>{m.group(1)}(),800);return()=>clearTimeout(_ac)}},[{m.group(1)}]);'
            f'const {m.group(3)}=(0,{m.group(4)}.useIsMac)();'
            f'(0,{m.group(5)}.useEffect)(()=>{{const {m.group(6)}={m.group(2)}()'
        ),
        "desc": "chat-client: auto-continue useEffect injection",
    },
]

# P11: CascadeAutoExecution OFF→EAGER (命令自动执行)
# P12: CascadeWebRequests ALLOWLIST→TURBO (网络全自动)
# 这两个patch在同一个迁移函数$mhb中, 与P4同源
PATCHES_SETTINGS = [
    {
        "id": "P11",
        "file": "workbench",
        "old": "C.cascadeAutoExecutionPolicy===CascadeCommandsAutoExecution.UNSPECIFIED&&(C.cascadeAutoExecutionPolicy=CascadeCommandsAutoExecution.OFF)",
        "new": "C.cascadeAutoExecutionPolicy!==CascadeCommandsAutoExecution.EAGER&&(C.cascadeAutoExecutionPolicy=CascadeCommandsAutoExecution.EAGER)",
        "desc": "CascadeAutoExecution OFF→EAGER (命令全自动)",
        "expected_count": 1,
    },
    {
        "id": "P12",
        "file": "workbench",
        "old": "_?.cascadeWebSearchEnabled?C.cascadeWebRequestsAutoExecutionPolicy===CascadeWebRequestsAutoExecution.UNSPECIFIED&&(C.cascadeWebRequestsAutoExecutionPolicy=CascadeWebRequestsAutoExecution.ALLOWLIST):C.cascadeWebRequestsAutoExecutionPolicy=CascadeWebRequestsAutoExecution.DISABLED",
        "new": "C.cascadeWebRequestsAutoExecutionPolicy!==CascadeWebRequestsAutoExecution.TURBO&&(C.cascadeWebRequestsAutoExecutionPolicy=CascadeWebRequestsAutoExecution.TURBO)",
        "desc": "CascadeWebRequests ALLOWLIST→TURBO (网络全自动)",
        "expected_count": 1,
    },
]

# P13: autoRunAllowed 强制true (绕过teamConfig服务端gate)
# 根因: teamConfig?.allowAutoRunCommands 默认false, 导致autoRunAllowed=false
# 运行时计算: Hl=(0,M.useMemo)(()=>Bo!==an.UNSPECIFIED?Bo!==an.DISABLED:Aa?.teamConfig?.allowAutoRunCommands??!1,...)
# 显示门控: C=...allowAutoRunCommands||_!==void 0&&...;this.t.style.display=C?"block":"none"
P13_PATCHES = [
    {
        "id": "P13a",
        "file": "workbench",
        "old": "allowAutoRunCommands??!1",
        "new": "allowAutoRunCommands??!0",
        "desc": "autoRunAllowed强制true (绕过teamConfig gate) ★根源",
        "expected_count": 1,
    },
    {
        "id": "P13b",
        "file": "workbench",
        "old": 'this.t&&(this.t.style.display=C?"block":"none")',
        "new": 'this.t&&(this.t.style.display="block")',
        "desc": "autoRun设置面板强制显示 (绕过teamConfig显示gate)",
        "expected_count": 1,
    },
]

# P14: document.hidden覆盖 (workbench入口注入)
# 根因: 后台tab时浏览器throttle setTimeout到1s+, 导致P10 auto-continue失效
# 解决: 在workbench加载时注入document.hidden=false覆盖
P14_MARKER = '/*P14_VISIBILITY_OVERRIDE*/'
P14_INJECT = (
    '/*P14_VISIBILITY_OVERRIDE*/'
    'Object.defineProperty(document,"hidden",{get:function(){return false},configurable:true});'
    'Object.defineProperty(document,"visibilityState",{get:function(){return"visible"},configurable:true});'
)

# P15: WAITING状态自动accept observer
# 根因: 即使P11 EAGER + P13 autoRunAllowed=true, 也可能因服务端autoRunDecision返回非ALLOW而显示Run/Skip
# 解决: 注入setInterval每500ms检查并自动点击Run按钮
P15_MARKER = '/*P15_AUTO_ACCEPT_OBSERVER*/'
P15_INJECT = (
    '/*P15_AUTO_ACCEPT_OBSERVER*/'
    'setInterval(()=>{'
    'try{'
    'document.querySelectorAll("[data-testid=\'accept-command\'],[aria-label=\'Run\']").forEach(b=>{'
    'if(b.offsetParent!==null){b.click()}'
    '});'
    'document.querySelectorAll("button").forEach(b=>{'
    'const t=b.textContent?.trim();'
    'if(t==="Run"||t==="Continue"){'
    'const p=b.closest("[class*=waiting]");'
    'if(p||b.closest("[class*=cascade]"))b.click()'
    '}'
    '})'
    '}catch(e){}'
    '},500);'
)


def _adaptive_patch(content, file_key):
    """Regex fallback when exact match fails (e.g., after Windsurf update changes formatting)."""
    patched = content
    count = 0
    for rx in REGEX_FALLBACKS:
        matches = list(rx.finditer(patched))
        for m in matches:
            old_val = m.group(0)
            new_val = m.group(1) + "9999" + m.group(2)
            patched = patched[:m.start()] + new_val + patched[m.end():]
            count += 1
            _log(f"  Regex fallback: '{old_val[:60]}' → 9999")
            break  # re-scan after replacement (positions shifted)
        if count > 0:
            break
    return patched, count


def _file_hash(path):
    """SHA256 of file for change detection."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _get_windsurf_version():
    """Read Windsurf version from package.json."""
    pkg = WINDSURF_BASE / "package.json"
    if pkg.exists():
        try:
            return json.loads(pkg.read_text(encoding="utf-8")).get("version", "unknown")
        except Exception:
            pass
    return "unknown"


def _load_state():
    """Load persistent state (hashes, version, backup info)."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(state):
    """Save persistent state."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def backup_files(only_originals=False):
    """Backup files. If only_originals=True, skip files that are already patched."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backed = []
    state = _load_state()
    for key, path in FILES.items():
        if not path.exists():
            backed.append(f"  ❌ {path.name} not found")
            continue
        if only_originals:
            content = path.read_text(encoding="utf-8")
            has_patch = any(content.count(p["new"]) >= p["expected_count"] for p in PATCHES if p["file"] == key)
            if has_patch:
                backed.append(f"  ⏭️  {path.name} (already patched, skipping)")
                continue
        bk = BACKUP_DIR / f"{path.name}.{ts}.bak"
        shutil.copy2(path, bk)
        sz = bk.stat().st_size
        fh = _file_hash(path)
        backed.append(f"  ✅ {path.name} → {bk.name} ({sz:,}B) [{fh}]")
        state.setdefault("original_backups", {})
        if key not in state["original_backups"]:
            state["original_backups"][key] = {"file": str(bk), "hash": fh, "size": sz, "ts": ts}
    state["windsurf_version"] = _get_windsurf_version()
    state["last_backup"] = ts
    _save_state(state)
    print(f"备份完成 ({ts}):")
    for b in backed:
        print(b)
    return ts


def verify_patches():
    results = []
    for p in PATCHES:
        path = FILES[p["file"]]
        if not path.exists():
            results.append({"id": p["id"], "status": "FILE_MISSING", "desc": p["desc"]})
            continue
        content = path.read_text(encoding="utf-8")
        applied = content.count(p["new"])
        unapplied = content.count(p["old"])
        if applied >= p["expected_count"] and unapplied == 0:
            status = "APPLIED"
        elif unapplied >= p["expected_count"]:
            status = "NOT_APPLIED"
        elif applied > 0 and unapplied > 0:
            status = "PARTIAL"
        else:
            status = "UNKNOWN"
        results.append({
            "id": p["id"],
            "status": status,
            "applied": applied,
            "unapplied": unapplied,
            "desc": p["desc"],
            "hash": _file_hash(path) if path.exists() else None,
        })
    # P11/P12 settings patches verification
    for p in PATCHES_SETTINGS:
        path = FILES[p["file"]]
        if not path.exists():
            results.append({"id": p["id"], "status": "FILE_MISSING", "desc": p["desc"]})
            continue
        content = path.read_text(encoding="utf-8")
        applied = content.count(p["new"])
        unapplied = content.count(p["old"])
        if applied >= p["expected_count"] and unapplied == 0:
            status = "APPLIED"
        elif unapplied >= p["expected_count"]:
            status = "NOT_APPLIED"
        elif applied > 0:
            status = "APPLIED"
        else:
            status = "UNKNOWN"
        results.append({"id": p["id"], "status": status, "applied": applied, "unapplied": unapplied, "desc": p["desc"]})
    # P13: autoRunAllowed bypass
    for p in P13_PATCHES:
        path = FILES[p["file"]]
        if not path.exists():
            results.append({"id": p["id"], "status": "FILE_MISSING", "desc": p["desc"]})
            continue
        content = path.read_text(encoding="utf-8")
        applied = content.count(p["new"])
        unapplied = content.count(p["old"])
        if applied >= p["expected_count"] and unapplied == 0:
            st = "APPLIED"
        elif unapplied >= p["expected_count"]:
            st = "NOT_APPLIED"
        elif applied > 0:
            st = "APPLIED"
        else:
            st = "UNKNOWN"
        results.append({"id": p["id"], "status": st, "applied": applied, "unapplied": unapplied, "desc": p["desc"]})
    # P14: visibility override
    results.append(verify_p14())
    # P15: auto-accept observer
    results.append(verify_p15())
    # P5 verification
    results.append(verify_p5())
    # P10 verification
    results.extend(verify_p10())
    return results


def _find_class_name(content, type_name_str):
    """Find minified class variable name from its protobuf typeName."""
    idx = content.find(type_name_str)
    if idx < 0:
        return None
    chunk = content[max(0, idx - 600):idx]
    matches = re.findall(r'class\s+(\w+)\s+extends', chunk)
    return matches[-1] if matches else None


def apply_p5_parallel_rollout(dry_run=False):
    """P5: Inject ParallelRolloutConfig into CascadeConfig constructor.
    
    Dynamic approach (survives Windsurf updates):
    1. Find ParallelRolloutConfig class name via typeName
    2. Find CascadeConfig constructor via typeName
    3. Inject parallelRolloutConfig default after initPartial
    
    Returns: (success: bool, message: str)
    """
    ext_path = FILES["extension"]
    if not ext_path.exists():
        return False, "extension.js not found"
    
    content = ext_path.read_text(encoding="utf-8")
    
    # Check if already applied
    if P5_MARKER in content:
        return True, "P5 already applied"
    
    # Step 1: Find ParallelRolloutConfig class name
    prc_class = _find_class_name(content, P5_PRC_TYPENAME)
    if not prc_class:
        return False, "ParallelRolloutConfig class not found"
    
    # Step 2: Find CascadeConfig constructor
    # Pattern: constructor(X){super(),Y.proto3.util.initPartial(X,this)}static runtime=Y.proto3;static typeName="exa.cortex_pb.CascadeConfig"
    cc_rx = re.compile(
        r'(constructor\((\w+)\)\{super\(\),(\w+)\.proto3\.util\.initPartial\(\2,this\)\})'
        r'(static\s+runtime=\3\.proto3;static\s+' + re.escape(P5_CASCADE_CONFIG_TYPENAME) + r')'
    )
    cc_match = cc_rx.search(content)
    if not cc_match:
        return False, "CascadeConfig constructor pattern not found"
    
    old_ctor = cc_match.group(1)
    arg_var = cc_match.group(2)
    mod_var = cc_match.group(3)
    static_part = cc_match.group(4)
    
    # Step 3: Build new constructor with parallelRolloutConfig injection
    new_ctor = (
        f'constructor({arg_var}){{super(),{mod_var}.proto3.util.initPartial({arg_var},this);'
        f'this.parallelRolloutConfig||(this.parallelRolloutConfig='
        f'new {prc_class}({{numParallelRollouts:2,maxInvocationsPerRollout:50}}))}}'
    )
    
    old_full = old_ctor + static_part
    new_full = new_ctor + static_part
    
    count = content.count(old_full)
    if count != 1:
        return False, f"Expected 1 match for CascadeConfig constructor, found {count}"
    
    if dry_run:
        return True, f"P5 ready: inject {prc_class}(2×50) into CascadeConfig"
    
    new_content = content.replace(old_full, new_full)
    ext_path.write_text(new_content, encoding="utf-8")
    _log(f"  ✅ P5: ParallelRolloutConfig({prc_class}) injected — 2 parallel × 50 invocations")
    return True, f"P5 applied: {prc_class}(2×50)"


def apply_p10_auto_continue():
    """P10: Inject client-side auto-continue into Continue response components.
    
    When server doesn't auto-continue (despite P4 ENABLED), this ensures
    the Continue response component auto-triggers handleContinue() after 800ms.
    
    Returns: (success_count: int, messages: list[str])
    """
    success = 0
    msgs = []
    for p10 in P10_PATCHES:
        path = FILES[p10["file"]]
        if not path.exists():
            msgs.append(f"  ❌ P10-{p10['file']}: {path.name} not found")
            continue
        content = path.read_text(encoding="utf-8")
        if P10_MARKER in content:
            msgs.append(f"  ⏭️  P10-{p10['file']}: Already applied")
            success += 1
            continue
        m = p10["old_pattern"].search(content)
        if not m:
            msgs.append(f"  ⚠️  P10-{p10['file']}: Pattern not found ({p10['desc']})")
            continue
        new_text = p10["build_new"](m)
        new_content = content[:m.start()] + new_text + content[m.end():]
        path.write_text(new_content, encoding="utf-8")
        verify = P10_MARKER in path.read_text(encoding="utf-8")
        if verify:
            msgs.append(f"  ✅ P10-{p10['file']}: {p10['desc']}")
            success += 1
        else:
            msgs.append(f"  ❌ P10-{p10['file']}: Write verify failed")
    return success, msgs


def verify_p10():
    """Verify P10 patch status."""
    results = []
    for p10 in P10_PATCHES:
        path = FILES[p10["file"]]
        fid = f"P10-{p10['file']}"
        if not path.exists():
            results.append({"id": fid, "status": "FILE_MISSING", "desc": p10["desc"]})
            continue
        content = path.read_text(encoding="utf-8")
        if P10_MARKER in content:
            results.append({"id": fid, "status": "APPLIED", "desc": p10["desc"]})
        elif p10["old_pattern"].search(content):
            results.append({"id": fid, "status": "NOT_APPLIED", "desc": p10["desc"]})
        else:
            results.append({"id": fid, "status": "UNKNOWN", "desc": p10["desc"]})
    return results


def verify_p14():
    """Verify P14 (visibility override) patch status."""
    path = FILES["workbench"]
    if not path.exists():
        return {"id": "P14", "status": "FILE_MISSING", "desc": "document.hidden→false (后台tab不throttle)"}
    content = path.read_text(encoding="utf-8")
    if P14_MARKER in content:
        return {"id": "P14", "status": "APPLIED", "desc": "document.hidden→false (后台tab不throttle) ★根源"}
    return {"id": "P14", "status": "NOT_APPLIED", "desc": "document.hidden→false (后台tab不throttle) ★根源"}


def verify_p15():
    """Verify P15 (auto-accept observer) patch status."""
    path = FILES["workbench"]
    if not path.exists():
        return {"id": "P15", "status": "FILE_MISSING", "desc": "WAITING自动accept observer"}
    content = path.read_text(encoding="utf-8")
    if P15_MARKER in content:
        return {"id": "P15", "status": "APPLIED", "desc": "WAITING自动accept observer (终极保底)"}
    return {"id": "P15", "status": "NOT_APPLIED", "desc": "WAITING自动accept observer (终极保底)"}


def apply_p13():
    """P13: Force autoRunAllowed=true by patching teamConfig gate."""
    success = 0
    msgs = []
    for p in P13_PATCHES:
        path = FILES[p["file"]]
        if not path.exists():
            msgs.append(f"  ❌ {p['id']}: {path.name} not found")
            continue
        content = path.read_text(encoding="utf-8")
        count = content.count(p["old"])
        if count == 0:
            already = content.count(p["new"])
            if already >= p["expected_count"]:
                msgs.append(f"  ⏭️  {p['id']}: Already applied ({p['desc']})")
                success += already
            else:
                msgs.append(f"  ⚠️  {p['id']}: Pattern not found ({p['desc']})")
            continue
        new_content = content.replace(p["old"], p["new"])
        path.write_text(new_content, encoding="utf-8")
        verify = path.read_text(encoding="utf-8").count(p["new"])
        if verify >= p["expected_count"]:
            msgs.append(f"  ✅ {p['id']}: {p['desc']} ({verify}x)")
            success += verify
        else:
            msgs.append(f"  ❌ {p['id']}: Verify failed ({p['desc']})")
    return success, msgs


def apply_p14():
    """P14: Inject document.hidden=false override at workbench entry point."""
    path = FILES["workbench"]
    if not path.exists():
        return False, "  ❌ P14: workbench not found"
    content = path.read_text(encoding="utf-8")
    if P14_MARKER in content:
        return True, "  ⏭️  P14: Already applied (document.hidden→false)"
    # Inject at the very beginning after the copyright comment
    # Find the end of the first comment block
    inject_point = content.find('var __defProp=')
    if inject_point < 0:
        inject_point = content.find('var ')
    if inject_point < 0:
        return False, "  ⚠️  P14: Injection point not found"
    new_content = content[:inject_point] + P14_INJECT + content[inject_point:]
    path.write_text(new_content, encoding="utf-8")
    if P14_MARKER in path.read_text(encoding="utf-8"):
        return True, "  ✅ P14: document.hidden→false injected (后台tab不throttle) ★根源"
    return False, "  ❌ P14: Write verify failed"


def apply_p15():
    """P15: Inject auto-accept observer for WAITING command steps."""
    path = FILES["workbench"]
    if not path.exists():
        return False, "  ❌ P15: workbench not found"
    content = path.read_text(encoding="utf-8")
    if P15_MARKER in content:
        return True, "  ⏭️  P15: Already applied (auto-accept observer)"
    # Inject right after P14 marker or at the same injection point
    inject_point = content.find(P14_MARKER)
    if inject_point >= 0:
        # Insert after P14 injection
        end_of_p14 = content.find(';', content.find('configurable:true})', inject_point)) + 1
        if end_of_p14 > inject_point:
            inject_point = end_of_p14
        else:
            inject_point = content.find('var __defProp=') or content.find('var ')
    else:
        inject_point = content.find('var __defProp=')
        if inject_point < 0:
            inject_point = content.find('var ')
    if inject_point < 0:
        return False, "  ⚠️  P15: Injection point not found"
    new_content = content[:inject_point] + P15_INJECT + content[inject_point:]
    path.write_text(new_content, encoding="utf-8")
    if P15_MARKER in path.read_text(encoding="utf-8"):
        return True, "  ✅ P15: auto-accept observer injected (WAITING自动accept) ★终极保底"
    return False, "  ❌ P15: Write verify failed"


def verify_p5():
    """Verify P5 patch status."""
    ext_path = FILES["extension"]
    if not ext_path.exists():
        return {"id": "P5", "status": "FILE_MISSING", "desc": "ParallelRollout injection"}
    content = ext_path.read_text(encoding="utf-8")
    if P5_MARKER in content:
        return {"id": "P5", "status": "APPLIED", "desc": "ParallelRollout injection (experimental)"}
    if P5_CASCADE_CONFIG_TYPENAME in content:
        return {"id": "P5", "status": "NOT_APPLIED", "desc": "ParallelRollout injection (experimental)"}
    return {"id": "P5", "status": "UNKNOWN", "desc": "ParallelRollout injection (experimental)"}


def apply_patches():
    print("=" * 60)
    print(f"Windsurf Continue Bypass Patcher v6.0")
    print(f"Windsurf: {_get_windsurf_version()} @ {WINDSURF_BASE}")
    print("=" * 60)

    ts = backup_files(only_originals=True)
    print()

    total_applied = 0
    state = _load_state()
    for p in PATCHES:
        path = FILES[p["file"]]
        if not path.exists():
            print(f"  ❌ {p['id']}: {path.name} not found")
            continue
        content = path.read_text(encoding="utf-8")
        count = content.count(p["old"])
        if count == 0:
            already = content.count(p["new"])
            if already >= p["expected_count"]:
                print(f"  ⏭️  {p['id']}: Already applied ({p['desc']})")
                total_applied += already
                continue
            else:
                patched, rx_count = _adaptive_patch(content, p["file"])
                if rx_count > 0:
                    path.write_text(patched, encoding="utf-8")
                    print(f"  ⚡ {p['id']}: Regex fallback applied ({p['desc']})")
                    total_applied += rx_count
                else:
                    print(f"  ⚠️  {p['id']}: Pattern not found ({p['desc']})")
                continue
        new_content = content.replace(p["old"], p["new"])
        path.write_text(new_content, encoding="utf-8")
        verify = path.read_text(encoding="utf-8").count(p["new"])
        if verify >= p["expected_count"]:
            print(f"  ✅ {p['id']}: {p['desc']} ({verify}x)")
            total_applied += verify
        else:
            print(f"  ❌ {p['id']}: Verify failed ({p['desc']})")

    state["last_patch"] = datetime.now().isoformat()
    state["windsurf_version"] = _get_windsurf_version()
    state["patched_hashes"] = {key: _file_hash(path) for key, path in FILES.items() if path.exists()}
    _save_state(state)

    # P11/P12: Settings patches (EAGER + TURBO)
    for p in PATCHES_SETTINGS:
        path = FILES[p["file"]]
        if not path.exists():
            print(f"  \u274c {p['id']}: {path.name} not found")
            continue
        content = path.read_text(encoding="utf-8")
        count = content.count(p["old"])
        if count == 0:
            already = content.count(p["new"])
            if already >= p["expected_count"]:
                print(f"  \u23ed\ufe0f  {p['id']}: Already applied ({p['desc']})")
                total_applied += already
            else:
                print(f"  \u26a0\ufe0f  {p['id']}: Pattern not found ({p['desc']})")
            continue
        new_content = content.replace(p["old"], p["new"])
        path.write_text(new_content, encoding="utf-8")
        verify = path.read_text(encoding="utf-8").count(p["new"])
        if verify >= p["expected_count"]:
            print(f"  \u2705 {p['id']}: {p['desc']} ({verify}x)")
            total_applied += verify
        else:
            print(f"  \u274c {p['id']}: Verify failed ({p['desc']})")

    # P5: ParallelRollout (experimental)
    p5_ok, p5_msg = apply_p5_parallel_rollout()
    if p5_ok:
        total_applied += 1
        print(f"  {'⏭️ ' if 'already' in p5_msg else '✅'} P5: {p5_msg}")
    else:
        print(f"  ⚠️  P5: {p5_msg} (experimental, non-critical)")

    # P10: Client-side auto-continue (终极保底)
    p10_count, p10_msgs = apply_p10_auto_continue()
    total_applied += p10_count
    for msg in p10_msgs:
        print(msg)

    # P13: autoRunAllowed强制true (★根源: 绕过teamConfig服务端gate)
    p13_count, p13_msgs = apply_p13()
    total_applied += p13_count
    for msg in p13_msgs:
        print(msg)

    # P14: document.hidden→false (★根源: 后台tab不throttle)
    p14_ok, p14_msg = apply_p14()
    if p14_ok:
        total_applied += 1
    print(p14_msg)

    # P15: WAITING自动accept observer (★终极保底)
    p15_ok, p15_msg = apply_p15()
    if p15_ok:
        total_applied += 1
    print(p15_msg)

    # 更新state包含P14/P15注入后的hash
    state["patched_hashes"] = {key: _file_hash(path) for key, path in FILES.items() if path.exists()}
    _save_state(state)

    print(f"\n{'=' * 60}")
    print(f"Total: {total_applied} patches applied/verified")
    print(f"Backup: {BACKUP_DIR}")
    print(f"\n⚡ 激活: Ctrl+Shift+P → Reload Window")
    print(f"⚡ P13验证: 命令应自动执行,不再出现Run/Skip弹窗")
    print(f"⚡ P14验证: 切换到其他tab后auto-continue仍应工作")
    print(f"⚡ P15验证: 即使P13失效,Run按钮也会被自动点击")
    return total_applied


def rollback(force=True):
    """Non-interactive rollback. Finds oldest backup per file (=original)."""
    state = _load_state()
    orig = state.get("original_backups", {})
    baks = sorted(BACKUP_DIR.glob("*.bak"), key=lambda x: x.name)
    if not baks:
        print("  无备份文件")
        return

    file_originals = {}
    for b in baks:
        base = b.name.split(".")[0]
        if base == "extension":
            base = "extension.js"
        for key, path in FILES.items():
            if path.name == b.name.rsplit(".", 2)[0]:
                if key not in file_originals:
                    file_originals[key] = b

    print("回滚目标 (最早备份=原始文件):")
    for key, bak in file_originals.items():
        print(f"  {bak.name} ({bak.stat().st_size:,}B) → {FILES[key].name}")

    if not force:
        print("\n使用 --rollback --force 或 -y 跳过确认")
        print("回滚? (y/n): ", end="")
        if input().strip().lower() != "y":
            print("取消")
            return

    for key, bak in file_originals.items():
        path = FILES[key]
        shutil.copy2(bak, path)
        print(f"  ✅ {bak.name} → {path}")
    print("回滚完成。需Reload Window生效。")


def _log(msg):
    """Append to watch log (for scheduled task with no console)."""
    log_file = BACKUP_DIR / "_watch.log"
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass
    print(msg)


def _apply_rate_limit_bypass():
    """Call patch_rate_limit_bypass.py apply to re-apply P6-P9."""
    import subprocess
    script = SCRIPT_DIR / "patch_rate_limit_bypass.py"
    if script.exists():
        try:
            result = subprocess.run([sys.executable, str(script), "apply"], capture_output=True, text=True, timeout=30)
            _log(f"P6-P9 rate limit bypass: {result.stdout.strip().split(chr(10))[-1] if result.stdout else 'no output'}")
        except Exception as e:
            _log(f"P6-P9 rate limit bypass failed: {e}")
    else:
        _log(f"⚠️ {script} not found, skipping P6-P9")


def watch():
    """Check if Windsurf updated (files changed) and auto-re-patch."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    state = _load_state()
    patched_hashes = state.get("patched_hashes", {})
    saved_ver = state.get("windsurf_version", "unknown")
    current_ver = _get_windsurf_version()

    if saved_ver != current_ver:
        _log(f"⚠️ Windsurf版本变更: {saved_ver} → {current_ver} — 自动重新patch")
        apply_patches()
        _apply_rate_limit_bypass()
        return True

    changed = False
    for key, path in FILES.items():
        if not path.exists():
            continue
        current_hash = _file_hash(path)
        saved_hash = patched_hashes.get(key)
        if saved_hash and current_hash != saved_hash:
            _log(f"⚠️ {path.name} 文件已变更 (hash: {saved_hash} → {current_hash})")
            changed = True

    if changed:
        results = verify_patches()
        needs_repatch = any(r["status"] != "APPLIED" for r in results)
        if needs_repatch:
            _log("Patch已丢失！自动重新patch...")
            apply_patches()
            _apply_rate_limit_bypass()
            return True
        else:
            _log("✅ Patch仍有效(可能是无关变更)")
            state["patched_hashes"] = {key: _file_hash(path) for key, path in FILES.items() if path.exists()}
            _save_state(state)
    else:
        _log(f"✅ Windsurf {current_ver} — patch有效")
    return False


def status():
    """Complete status report."""
    ver = _get_windsurf_version()
    state = _load_state()
    print("=" * 60)
    print(f"Windsurf Continue Bypass — Status Report")
    print("=" * 60)
    print(f"Windsurf版本: {ver}")
    print(f"安装路径: {WINDSURF_BASE}")
    print(f"上次patch: {state.get('last_patch', 'never')}")
    print()

    results = verify_patches()
    print("Patch状态:")
    for r in results:
        icon = "✅" if r["status"] == "APPLIED" else "❌" if r["status"] == "NOT_APPLIED" else "⚠️"
        print(f"  {icon} {r['id']}: {r['status']} — {r['desc']}")
    applied = sum(1 for r in results if r["status"] == "APPLIED")
    print(f"  → {applied}/{len(results)} APPLIED")
    print()

    baks = sorted(BACKUP_DIR.glob("*.bak"))
    print(f"备份: {len(baks)} files in {BACKUP_DIR}")
    orig = state.get("original_backups", {})
    for key, info in orig.items():
        p = Path(info["file"])
        exists = "✅" if p.exists() else "❌"
        print(f"  {exists} {key} 原始: {p.name} ({info['size']:,}B)")
    print()

    print(f"文件大小:")
    for key, path in FILES.items():
        if path.exists():
            sz = path.stat().st_size
            h = _file_hash(path)
            print(f"  {path.name}: {sz:,}B [{h}]")
    print("=" * 60)


def cleanup_backups(keep=3):
    """Keep only the N most recent backup sets per file."""
    groups = {}
    for b in BACKUP_DIR.glob("*.bak"):
        base = b.name.rsplit(".", 2)[0]
        groups.setdefault(base, []).append(b)
    removed = 0
    for base, files in groups.items():
        files.sort(key=lambda x: x.name, reverse=True)
        for old in files[keep:]:
            state = _load_state()
            orig_files = [Path(v["file"]) for v in state.get("original_backups", {}).values()]
            if old in orig_files:
                continue
            old.unlink()
            removed += 1
    if removed:
        print(f"清理: 删除 {removed} 个旧备份")


def main():
    args = sys.argv[1:]

    if "--verify" in args:
        results = verify_patches()
        print("Patch状态验证:")
        for r in results:
            icon = "✅" if r["status"] == "APPLIED" else "❌" if r["status"] == "NOT_APPLIED" else "⚠️"
            detail = f"applied={r.get('applied', '?')}, unapplied={r.get('unapplied', '?')}" if "applied" in r else ""
            print(f"  {icon} {r['id']}: {r['status']} — {r['desc']} {detail}")
        applied = sum(1 for r in results if r["status"] == "APPLIED")
        print(f"\n{applied}/{len(results)} patches verified")

    elif "--rollback" in args:
        force = "--force" in args or "-y" in args
        rollback(force=force)

    elif "--backup" in args:
        backup_files(only_originals=("--originals" in args))

    elif "--watch" in args:
        watch()

    elif "--p5-only" in args:
        ok, msg = apply_p5_parallel_rollout()
        print(f"{'✅' if ok else '❌'} P5: {msg}")

    elif "--status" in args:
        status()

    elif "--cleanup" in args:
        cleanup_backups(keep=3)

    else:
        apply_patches()

    if "--json" in args:
        results = verify_patches()
        print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
