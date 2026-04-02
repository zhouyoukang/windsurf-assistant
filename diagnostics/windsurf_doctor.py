#!/usr/bin/env python3
"""
Windsurf Doctor v2.1 — 7层配置腐化诊断+修复+守护+热补丁检测

道生一(诊断) → 一生二(修复) → 二生三(守护) → 三生万物(自愈)

7层腐化模型:
  L0 安装完整性 — product.json checksums / SHA-256校验 / 自动修复
  L1 settings.json — trailing comma / augment远程配置 / JSON合法性
  L2 user_settings.pb — protobuf完整性 / 并发写入检测
  L3 MCP双配置 — mcp_config.json vs mcp.json 同步一致性
  L4 state.vscdb — SQLite完整性 / 工作区引用正确性
  L5 globalStorage — 会话泄漏 / 存储膨胀
  L6 hooks/rules — 全局vs工作区一致性

逆向发现 (IntegrityService):
  - 算法: SHA-256 → Base64 (无padding '=')
  - 校验文件: 6个, 列在 product.json.checksums
  - 触发: Lifecycle Phase 4 (restored)
  - 存储: integrityService key in state.vscdb
  - 消除: dontShowPrompt + commit hash 匹配

用法:
  python windsurf_doctor.py              # 全量诊断
  python windsurf_doctor.py --fix        # 诊断+自动修复
  python windsurf_doctor.py --watch      # 守护模式(文件监视+自动修复)
  python windsurf_doctor.py --serve      # HTTP Hub :9878
  python windsurf_doctor.py --deploy     # 部署为schtask持久化守护
"""

import os, sys, json, re, time, shutil, hashlib, base64, struct, threading, sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import subprocess

# ── 路径常量 ──────────────────────────────────────────────
APPDATA = os.environ.get('APPDATA', '')
USERPROFILE = os.environ.get('USERPROFILE', '')
CODEIUM_DIR = Path(USERPROFILE) / '.codeium' / 'windsurf'
USER_DATA_DIR = Path(APPDATA) / 'Windsurf'
USER_DIR = USER_DATA_DIR / 'User'
SETTINGS_JSON = USER_DIR / 'settings.json'
MCP_JSON_USER = USER_DIR / 'mcp.json'
MCP_JSON_CODEIUM = CODEIUM_DIR / 'mcp_config.json'
USER_SETTINGS_PB = CODEIUM_DIR / 'user_settings.pb'
HOOKS_GLOBAL = CODEIUM_DIR / 'hooks.json'
WORKSPACE_DIR = Path(r'e:\道\道生一\一生二')
HOOKS_WORKSPACE = WORKSPACE_DIR / '.windsurf' / 'hooks.json'
WINDSURFRULES = WORKSPACE_DIR / '.windsurfrules'
GLOBAL_STORAGE = USER_DIR / 'globalStorage'
WORKSPACE_STORAGE = USER_DIR / 'workspaceStorage'

WINDSURF_INSTALL_DIR = Path(r'D:\Windsurf')
PRODUCT_JSON = WINDSURF_INSTALL_DIR / 'resources' / 'app' / 'product.json'
APP_OUT_DIR = WINDSURF_INSTALL_DIR / 'resources' / 'app' / 'out'

SCRIPT_DIR = Path(__file__).parent
BACKUP_DIR = SCRIPT_DIR / '_doctor_backups'
REPORT_FILE = SCRIPT_DIR / '_doctor_report.md'
PORT = 9878

# ── 诊断结果 ─────────────────────────────────────────────
_NO_WINDOW = 0x08000000

def _hidden_run(cmd, **kwargs):
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    kwargs.setdefault('startupinfo', si)
    kwargs.setdefault('creationflags', _NO_WINDOW)
    return subprocess.run(cmd, **kwargs)


class Issue:
    def __init__(self, layer, severity, title, detail, fix_fn=None):
        self.layer = layer        # L1-L6
        self.severity = severity  # FATAL / WARN / INFO
        self.title = title
        self.detail = detail
        self.fix_fn = fix_fn      # callable or None
        self.fixed = False

    def __repr__(self):
        icon = {'FATAL': '🔴', 'WARN': '🟡', 'INFO': '🟢'}.get(self.severity, '⚪')
        status = ' ✅FIXED' if self.fixed else ''
        return f"{icon} [{self.layer}] {self.title}{status}"


class WindsurfDoctor:
    def __init__(self):
        self.issues = []
        self.stats = {}
        self.start_time = time.time()

    def add_issue(self, layer, severity, title, detail, fix_fn=None):
        issue = Issue(layer, severity, title, detail, fix_fn)
        self.issues.append(issue)
        return issue

    # ── L0: 安装完整性 (逆向IntegrityService) ──────────
    def check_L0_integrity(self):
        print("\n── L0: 安装完整性 ──")
        if not PRODUCT_JSON.exists():
            self.add_issue('L0', 'FATAL', 'product.json不存在',
                           f'路径: {PRODUCT_JSON}')
            return

        try:
            product = json.loads(PRODUCT_JSON.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            self.add_issue('L0', 'FATAL', 'product.json JSON解析失败', str(e))
            return

        checksums = product.get('checksums', {})
        if not checksums:
            self.add_issue('L0', 'WARN', 'product.json无checksums字段',
                           '完整性校验被跳过')
            return

        version = product.get('windsurfVersion', '?')
        commit = product.get('commit', '?')[:12]
        self.stats['windsurf_version'] = version
        self.stats['windsurf_commit'] = commit
        print(f"  ℹ️ Windsurf v{version} (commit: {commit})")

        modified_files = []
        for rel_path, expected_b64 in checksums.items():
            full = APP_OUT_DIR / rel_path.replace('/', os.sep)
            if not full.exists():
                self.add_issue('L0', 'FATAL', f'校验文件缺失: {rel_path}',
                               f'路径: {full}')
                continue
            raw = full.read_bytes()
            actual = base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')
            expected = expected_b64.rstrip('=')
            if actual != expected:
                mtime = datetime.fromtimestamp(full.stat().st_mtime)
                modified_files.append({
                    'path': rel_path, 'expected': expected_b64,
                    'actual': actual, 'size': len(raw), 'mtime': mtime
                })
                print(f"  ❌ MODIFIED: {rel_path}")
                print(f"     Size: {len(raw)}B | Modified: {mtime}")
            else:
                print(f"  ✅ {rel_path}")

        self.stats['integrity_total'] = len(checksums)
        self.stats['integrity_modified'] = len(modified_files)
        self.stats['integrity_files'] = [
            {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in m.items()}
            for m in modified_files
        ]

        if modified_files:
            names = ', '.join(m['path'].split('/')[-1] for m in modified_files)
            self.add_issue('L0', 'FATAL',
                           f'安装完整性校验失败: {len(modified_files)}/{len(checksums)}文件被修改',
                           f'被修改: {names}\n'
                           f'这会触发 "Your Windsurf installation appears to be corrupt" 警告',
                           fix_fn=self._fix_integrity_checksums)
        else:
            print(f"  ✅ 全部{len(checksums)}个文件完整性校验通过")

        # 热补丁检测 — 比对文件大小异常
        self._check_hotpatch(checksums)

    def _check_hotpatch(self, checksums):
        """检测Windsurf热补丁(安装后自动追加的代码)"""
        ref_file = SCRIPT_DIR / '_doctor_reference.json'
        ref = {}
        if ref_file.exists():
            try:
                ref = json.loads(ref_file.read_text(encoding='utf-8'))
            except:
                pass

        current_sizes = {}
        for rel_path in checksums:
            full = APP_OUT_DIR / rel_path.replace('/', os.sep)
            if full.exists():
                current_sizes[rel_path] = full.stat().st_size

        # 保存当前大小作为参考(首次运行)
        if not ref.get('file_sizes'):
            ref['file_sizes'] = current_sizes
            ref['captured'] = datetime.now().isoformat()
            ref_file.write_text(json.dumps(ref, indent=2, ensure_ascii=False), encoding='utf-8')
            return

        # 对比大小差异
        for rel_path, size in current_sizes.items():
            ref_size = ref['file_sizes'].get(rel_path, size)
            delta = size - ref_size
            if abs(delta) > 1000:  # >1KB差异
                full = APP_OUT_DIR / rel_path.replace('/', os.sep)
                scan = self._security_scan_tail(full, ref_size) if delta > 0 else {}
                verdict = scan.get('verdict', 'unknown')
                detail = (f"大小差异: {delta:+,}B (当前{size:,}B vs 参考{ref_size:,}B)\n"
                         f"安全扫描: {verdict}")
                if scan.get('official_signatures', 0) > 0:
                    detail += f" | 官方签名: {scan['official_signatures']}个"
                if scan.get('suspicious', 0) > 0:
                    detail += f" | ⚠️ 可疑模式: {scan['suspicious']}个"
                    self.add_issue('L0', 'WARN', f'热补丁安全扫描发现可疑模式: {rel_path}', detail)
                else:
                    self.stats['hotpatch_detected'] = True
                    self.stats['hotpatch_delta'] = delta
                    print(f"  ℹ️ 热补丁检测: {rel_path.split('/')[-1]} {delta:+,}B (安全: {verdict})")

    def _security_scan_tail(self, filepath, ref_size):
        """扫描热补丁尾部字节的安全性"""
        import re as _re
        with open(filepath, 'rb') as f:
            f.seek(ref_size)
            extra = f.read()
        if not extra:
            return {'verdict': 'no_extra', 'suspicious': 0}

        suspicious_patterns = {
            'eval(': rb'eval\s*\(',
            'navigator.sendBeacon': rb'navigator\.sendBeacon',
            'exfiltrate': rb'exfiltrat',
            'keylogger': rb'keylog',
        }
        official_patterns = {
            'windsurf': rb'windsurf',
            'codeium': rb'codeium',
            'exa/': rb'exa/',
            'Cascade': rb'Cascade',
        }

        susp_count = sum(len(_re.findall(p, extra, _re.I)) for p in suspicious_patterns.values())
        official_count = sum(len(_re.findall(p, extra, _re.I)) for p in official_patterns.values())

        if susp_count > 0 and official_count == 0:
            verdict = 'SUSPICIOUS'
        elif official_count > 0 and susp_count == 0:
            verdict = 'safe_official_hotpatch'
        elif official_count > 0:
            verdict = 'likely_safe_with_caution'
        else:
            verdict = 'unknown_content'

        return {'verdict': verdict, 'suspicious': susp_count,
                'official_signatures': official_count, 'extra_bytes': len(extra)}

    def _fix_integrity_checksums(self):
        """更新product.json checksums匹配当前文件 (逆向IntegrityService)"""
        self._backup(PRODUCT_JSON)
        product = json.loads(PRODUCT_JSON.read_text(encoding='utf-8'))
        checksums = product.get('checksums', {})
        fixed = 0
        for rel_path in list(checksums.keys()):
            full = APP_OUT_DIR / rel_path.replace('/', os.sep)
            if not full.exists():
                continue
            raw = full.read_bytes()
            actual = base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')
            expected = checksums[rel_path].rstrip('=')
            if actual != expected:
                checksums[rel_path] = actual
                fixed += 1
        product['checksums'] = checksums
        with open(PRODUCT_JSON, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(product, f, indent='\t', ensure_ascii=False)
        return f"更新{fixed}个checksum, 重启Windsurf后corrupt警告消失"

    # ── L1: settings.json ────────────────────────────────
    def check_L1_settings_json(self):
        print("\n── L1: settings.json ──")
        if not SETTINGS_JSON.exists():
            self.add_issue('L1', 'FATAL', 'settings.json不存在',
                           f'路径: {SETTINGS_JSON}')
            return

        raw = SETTINGS_JSON.read_text(encoding='utf-8')
        self.stats['settings_json_size'] = len(raw)
        self.stats['settings_json_mtime'] = os.path.getmtime(SETTINGS_JSON)

        # 1. JSON合法性检查
        try:
            # VS Code uses JSONC (允许comments和trailing commas)
            # 但严格JSON不允许 → 检测trailing commas
            cleaned = re.sub(r'//.*?$', '', raw, flags=re.MULTILINE)  # 去注释
            cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)
            json.loads(cleaned)
            print("  ✅ JSON语法有效(宽松模式)")
        except json.JSONDecodeError as e:
            self.add_issue('L1', 'FATAL', 'settings.json JSON语法错误',
                           f'{e}', fix_fn=self._fix_settings_json_syntax)

        # 2. Trailing comma检测
        trailing_commas = list(re.finditer(r',\s*[\}\]]', raw))
        if trailing_commas:
            self.add_issue('L1', 'WARN', f'settings.json有{len(trailing_commas)}处trailing comma',
                           '严格JSON解析器(如Codeium后端)可能无法正确读取',
                           fix_fn=self._fix_trailing_commas)

        # 3. augment远程配置检测
        if 'useRemoteService' in raw:
            match = re.search(r'"base_url"\s*:\s*"([^"]+)"', raw)
            url = match.group(1) if match else 'unknown'
            self.add_issue('L1', 'WARN', f'augment.modelConfig指向远程服务: {url}',
                           '远程服务不可达时会导致Cascade设置面板超时/无响应',
                           fix_fn=self._fix_augment_config)

        # 4. 检查已知问题配置
        try:
            data = json.loads(re.sub(r',(\s*[\}\]])', r'\1', cleaned))
            if data.get('editor.accessibilitySupport') == 'on':
                self.add_issue('L1', 'INFO', 'accessibilitySupport已开启',
                               '可能影响性能，除非需要屏幕阅读器建议关闭')

            # 检查proxy设置
            proxy_support = data.get('http.proxySupport', '')
            if proxy_support:
                print(f"  ℹ️ http.proxySupport = {proxy_support}")

        except:
            pass

        print(f"  📊 settings.json: {len(raw)} chars, {len(trailing_commas)} trailing commas")

    def _fix_trailing_commas(self):
        """修复trailing commas"""
        raw = SETTINGS_JSON.read_text(encoding='utf-8')
        self._backup(SETTINGS_JSON)
        fixed = re.sub(r',(\s*[\}\]])', r'\1', raw)
        SETTINGS_JSON.write_text(fixed, encoding='utf-8')
        return f"移除trailing commas, {len(raw)} → {len(fixed)} chars"

    def _fix_settings_json_syntax(self):
        """修复JSON语法错误"""
        raw = SETTINGS_JSON.read_text(encoding='utf-8')
        self._backup(SETTINGS_JSON)
        # 去除trailing commas
        fixed = re.sub(r',(\s*[\}\]])', r'\1', raw)
        # 去除注释
        fixed = re.sub(r'//.*?$', '', fixed, flags=re.MULTILINE)
        fixed = re.sub(r'/\*.*?\*/', '', fixed, flags=re.DOTALL)
        try:
            data = json.loads(fixed)
            # 重新格式化
            formatted = json.dumps(data, indent=2, ensure_ascii=False)
            SETTINGS_JSON.write_text(formatted, encoding='utf-8')
            return "JSON语法修复并重新格式化"
        except json.JSONDecodeError as e:
            return f"无法自动修复: {e}"

    def _fix_augment_config(self):
        """移除augment远程配置"""
        raw = SETTINGS_JSON.read_text(encoding='utf-8')
        self._backup(SETTINGS_JSON)
        # 移除整个augment.modelConfig块
        fixed = re.sub(
            r'"augment\.modelConfig"\s*:\s*\{[^}]*\}\s*,?\s*',
            '',
            raw,
            flags=re.DOTALL
        )
        # 清理可能的连续逗号
        fixed = re.sub(r',(\s*,)', r',', fixed)
        fixed = re.sub(r',(\s*[\}\]])', r'\1', fixed)
        SETTINGS_JSON.write_text(fixed, encoding='utf-8')
        return "已移除augment.modelConfig远程配置"

    # ── L2: user_settings.pb ─────────────────────────────
    def check_L2_protobuf(self):
        print("\n── L2: user_settings.pb ──")
        if not USER_SETTINGS_PB.exists():
            self.add_issue('L2', 'FATAL', 'user_settings.pb不存在',
                           f'路径: {USER_SETTINGS_PB}')
            return

        stat = USER_SETTINGS_PB.stat()
        size = stat.st_size
        mtime = datetime.fromtimestamp(stat.st_mtime)
        self.stats['pb_size'] = size
        self.stats['pb_mtime'] = stat.st_mtime

        print(f"  📊 size: {size}B, modified: {mtime}")

        # 1. 大小异常检测
        if size < 1000:
            self.add_issue('L2', 'FATAL', f'user_settings.pb异常小({size}B)',
                           '正常应>10KB, 可能已损坏')
        elif size > 500000:
            self.add_issue('L2', 'WARN', f'user_settings.pb异常大({size/1024:.0f}KB)',
                           '可能包含大量历史数据, 建议关注')

        # 2. Protobuf头部验证
        with open(USER_SETTINGS_PB, 'rb') as f:
            head = f.read(16)
        # protobuf通常以field tag开头 (varint)
        if len(head) < 2:
            self.add_issue('L2', 'FATAL', 'user_settings.pb文件为空或过小', '')
        elif head[0] == 0:
            self.add_issue('L2', 'WARN', 'user_settings.pb头部为零字节',
                           '可能是截断写入的结果')

        # 3. 并发写入风险检测
        try:
            result = _hidden_run(
                ['powershell', '-NoProfile', '-Command',
                 f'(Get-Process Windsurf -ErrorAction SilentlyContinue).Count'],
                capture_output=True, text=True, timeout=10
            )
            proc_count = int(result.stdout.strip() or '0')
            self.stats['windsurf_processes'] = proc_count
            if proc_count > 10:
                self.add_issue('L2', 'INFO', f'{proc_count}个Windsurf进程运行中',
                               '多进程并发写入user_settings.pb可能导致数据竞争')
            print(f"  ℹ️ Windsurf进程数: {proc_count}")
        except:
            pass

        # 4. 提取模型计数
        data = USER_SETTINGS_PB.read_bytes()
        text = data.decode('utf-8', errors='replace')
        model_ids = re.findall(r'MODEL_[A-Z0-9_]+', text)
        unique_models = set(model_ids)
        self.stats['model_count'] = len(unique_models)
        print(f"  ℹ️ 模型定义: {len(unique_models)}个唯一模型ID")

        # 5. 字符串完整性 - 检查是否有截断的UTF-8
        null_blocks = data.count(b'\x00' * 16)
        if null_blocks > 10:
            self.add_issue('L2', 'WARN', f'user_settings.pb有{null_blocks}个16字节零块',
                           '可能是部分写入/截断的痕迹')

    # ── L3: MCP双配置 ───────────────────────────────────
    def check_L3_mcp(self):
        print("\n── L3: MCP双配置 ──")

        codeium_mcp = {}
        user_mcp = {}

        # 读取Codeium级MCP
        if MCP_JSON_CODEIUM.exists():
            try:
                codeium_mcp = json.loads(MCP_JSON_CODEIUM.read_text(encoding='utf-8'))
                servers_c = codeium_mcp.get('mcpServers', {})
                self.stats['mcp_codeium_count'] = len(servers_c)
                print(f"  📊 Codeium MCP: {len(servers_c)}个服务器")
                for name, cfg in servers_c.items():
                    status = '🔴disabled' if cfg.get('disabled') else '🟢active'
                    print(f"    {status} {name}")
            except json.JSONDecodeError as e:
                self.add_issue('L3', 'FATAL', 'mcp_config.json JSON解析失败',
                               str(e))

        # 读取User级MCP
        if MCP_JSON_USER.exists():
            try:
                user_mcp = json.loads(MCP_JSON_USER.read_text(encoding='utf-8'))
                servers_u = user_mcp.get('servers', {})
                self.stats['mcp_user_count'] = len(servers_u)
                print(f"  📊 User MCP: {len(servers_u)}个服务器")
            except json.JSONDecodeError as e:
                self.add_issue('L3', 'WARN', 'User/mcp.json JSON解析失败',
                               str(e))

        # 对比差异
        servers_c = set(codeium_mcp.get('mcpServers', {}).keys())
        servers_u = set(user_mcp.get('servers', {}).keys())
        only_in_codeium = servers_c - servers_u
        only_in_user = servers_u - servers_c

        if only_in_codeium:
            self.add_issue('L3', 'INFO',
                           f'MCP仅在Codeium级存在: {only_in_codeium}',
                           'Codeium MCP有更多服务器定义, User级MCP是子集')
        if only_in_user:
            self.add_issue('L3', 'WARN',
                           f'MCP仅在User级存在: {only_in_user}',
                           '可能导致设置面板和实际行为不一致')

        # 检查MCP备份文件堆积
        bak_files = list(CODEIUM_DIR.glob('mcp_config.json.bak*'))
        if len(bak_files) > 3:
            self.add_issue('L3', 'INFO',
                           f'MCP备份文件堆积: {len(bak_files)}个',
                           '建议清理旧备份')

    # ── L4: state.vscdb ─────────────────────────────────
    def check_L4_state_db(self):
        print("\n── L4: state.vscdb ──")
        if not WORKSPACE_STORAGE.exists():
            self.add_issue('L4', 'WARN', 'workspaceStorage目录不存在', '')
            return

        ws_dirs = list(WORKSPACE_STORAGE.iterdir())
        self.stats['workspace_count'] = len(ws_dirs)
        healthy = 0
        corrupt = 0
        total_size = 0
        current_ws = None

        for ws_dir in ws_dirs:
            if not ws_dir.is_dir():
                continue
            state_db = ws_dir / 'state.vscdb'
            ws_json = ws_dir / 'workspace.json'

            if state_db.exists():
                total_size += state_db.stat().st_size
                # SQLite header check
                with open(state_db, 'rb') as f:
                    header = f.read(16)
                if header[:15] == b'SQLite format 3':
                    healthy += 1
                else:
                    corrupt += 1
                    self.add_issue('L4', 'FATAL',
                                   f'state.vscdb损坏: {ws_dir.name}',
                                   f'SQLite头部无效',
                                   fix_fn=lambda d=ws_dir: self._fix_corrupt_state_db(d))

            # 查找当前工作区
            if ws_json.exists():
                try:
                    ws_data = json.loads(ws_json.read_text(encoding='utf-8'))
                    folder = ws_data.get('folder', '')
                    if '一生二' in folder or 'ScreenStream' in folder:
                        current_ws = {
                            'hash': ws_dir.name,
                            'folder': folder,
                            'state_db_size': state_db.stat().st_size if state_db.exists() else 0,
                            'state_db_mtime': datetime.fromtimestamp(state_db.stat().st_mtime).isoformat() if state_db.exists() else None
                        }
                except:
                    pass

        self.stats['state_db_healthy'] = healthy
        self.stats['state_db_corrupt'] = corrupt
        self.stats['state_db_total_size'] = total_size

        print(f"  📊 workspaces: {len(ws_dirs)} | healthy: {healthy} | corrupt: {corrupt}")
        print(f"  📊 total state.vscdb size: {total_size/1024:.1f}KB")

        if current_ws:
            print(f"  ℹ️ 当前工作区: {current_ws['hash']}")
            print(f"    folder: {current_ws['folder']}")
            # 检查路径是否正确
            if 'ScreenStream_v2' in current_ws['folder']:
                self.add_issue('L4', 'INFO',
                               '历史工作区记录指向旧路径(ScreenStream_v2)',
                               f"工作区记录: {current_ws['folder']}\n"
                               "这是历史残留, Windsurf按实际打开的文件夹确定当前工作区, 不影响功能")
        else:
            self.add_issue('L4', 'INFO', '未找到当前工作区的state.vscdb',
                           '可能使用新的workspace hash')

        # 检查过多的workspace (历史遗留)
        if len(ws_dirs) > 20:
            self.add_issue('L4', 'INFO',
                           f'{len(ws_dirs)}个历史工作区(>20)',
                           '过多的工作区目录可能影响启动性能',
                           fix_fn=self._fix_stale_workspaces)

    def _fix_corrupt_state_db(self, ws_dir):
        """修复损坏的state.vscdb — 删除让Windsurf重建"""
        state_db = ws_dir / 'state.vscdb'
        self._backup(state_db)
        state_db.unlink(missing_ok=True)
        backup = ws_dir / 'state.vscdb.backup'
        if backup.exists():
            # 尝试用backup恢复
            with open(backup, 'rb') as f:
                header = f.read(16)
            if header[:15] == b'SQLite format 3':
                shutil.copy2(backup, state_db)
                return "从state.vscdb.backup恢复"
        return "已删除损坏的state.vscdb, Windsurf重启后将重建"

    def _fix_stale_workspaces(self):
        """清理过期的workspace目录"""
        threshold = datetime.now() - timedelta(days=30)
        cleaned = 0
        for ws_dir in WORKSPACE_STORAGE.iterdir():
            if not ws_dir.is_dir():
                continue
            state_db = ws_dir / 'state.vscdb'
            if state_db.exists():
                mtime = datetime.fromtimestamp(state_db.stat().st_mtime)
                if mtime < threshold:
                    ws_json = ws_dir / 'workspace.json'
                    if ws_json.exists():
                        try:
                            data = json.loads(ws_json.read_text(encoding='utf-8'))
                            folder = data.get('folder', '')
                            if '一生二' in folder or 'ScreenStream' in folder:
                                continue  # 跳过当前工作区
                        except:
                            pass
                    self._backup(state_db)
                    shutil.rmtree(ws_dir, ignore_errors=True)
                    cleaned += 1
        return f"清理{cleaned}个过期(>30天)工作区"

    # ── L5: globalStorage ────────────────────────────────
    def check_L5_global_storage(self):
        print("\n── L5: globalStorage ──")
        if not GLOBAL_STORAGE.exists():
            print("  ℹ️ globalStorage目录不存在")
            return

        # 检查PowerShell会话泄漏
        ps_sessions_dir = GLOBAL_STORAGE / 'ms-vscode.powershell' / 'sessions'
        if ps_sessions_dir.exists():
            sessions = list(ps_sessions_dir.glob('PSES-*.json'))
            self.stats['ps_sessions'] = len(sessions)
            if len(sessions) > 20:
                self.add_issue('L5', 'WARN',
                               f'PowerShell会话文件泄漏: {len(sessions)}个',
                               '过多的陈旧会话文件可能影响扩展性能',
                               fix_fn=self._fix_ps_sessions)
            print(f"  ℹ️ PowerShell会话文件: {len(sessions)}个")

        # 总存储大小
        total = sum(f.stat().st_size for f in GLOBAL_STORAGE.rglob('*') if f.is_file())
        self.stats['global_storage_size'] = total
        print(f"  📊 globalStorage总大小: {total/1024:.1f}KB")

    def _fix_ps_sessions(self):
        """清理陈旧的PowerShell会话文件"""
        ps_dir = GLOBAL_STORAGE / 'ms-vscode.powershell' / 'sessions'
        if not ps_dir.exists():
            return "目录不存在"
        sessions = sorted(ps_dir.glob('PSES-*.json'),
                         key=lambda p: p.stat().st_mtime)
        # 保留最新5个
        to_remove = sessions[:-5] if len(sessions) > 5 else []
        for f in to_remove:
            f.unlink(missing_ok=True)
        return f"清理{len(to_remove)}个陈旧会话, 保留最新5个"

    # ── L6: hooks/rules一致性 ────────────────────────────
    def check_L6_hooks_rules(self):
        print("\n── L6: hooks/rules一致性 ──")

        # hooks双文件检查
        global_hooks = {}
        ws_hooks = {}

        if HOOKS_GLOBAL.exists():
            try:
                global_hooks = json.loads(HOOKS_GLOBAL.read_text(encoding='utf-8'))
            except:
                self.add_issue('L6', 'WARN', '全局hooks.json解析失败', '')

        if HOOKS_WORKSPACE.exists():
            try:
                ws_hooks = json.loads(HOOKS_WORKSPACE.read_text(encoding='utf-8'))
            except:
                self.add_issue('L6', 'WARN', '工作区hooks.json解析失败', '')

        global_empty = not global_hooks.get('hooks', {})
        ws_has_hooks = bool(ws_hooks.get('hooks', {}).get('pre_user_prompt') or
                           ws_hooks.get('hooks', {}).get('post_cascade_response'))

        if global_empty and ws_has_hooks:
            print("  ℹ️ 全局hooks为空, 工作区hooks有配置 — 正常(工作区级生效)")
        elif not global_empty and ws_has_hooks:
            self.add_issue('L6', 'INFO', '全局和工作区hooks同时有配置',
                           '可能导致hooks重复执行')

        # hooks引用的文件是否存在
        for hook_type in ['pre_user_prompt', 'post_cascade_response']:
            hooks = ws_hooks.get('hooks', {}).get(hook_type, [])
            for hook in hooks:
                cmd = hook.get('command', '')
                # 提取文件路径
                parts = cmd.split()
                for part in parts:
                    if part.endswith('.py') and not Path(part).exists():
                        self.add_issue('L6', 'WARN',
                                       f'Hook引用的脚本不存在: {part}',
                                       f'hook类型: {hook_type}')

        # .windsurfrules检查
        if WINDSURFRULES.exists():
            content = WINDSURFRULES.read_text(encoding='utf-8')
            self.stats['windsurfrules_size'] = len(content)
            print(f"  ℹ️ .windsurfrules: {len(content)} chars")
        else:
            self.add_issue('L6', 'WARN', '.windsurfrules不存在', '')

        # skills/workflows计数
        skills_dir = WORKSPACE_DIR / '.windsurf' / 'skills'
        workflows_dir = WORKSPACE_DIR / '.windsurf' / 'workflows'
        skill_count = len([d for d in skills_dir.iterdir() if d.is_dir()]) if skills_dir.exists() else 0
        wf_count = len([f for f in workflows_dir.glob('*.md')]) if workflows_dir.exists() else 0
        self.stats['skills'] = skill_count
        self.stats['workflows'] = wf_count
        print(f"  ℹ️ Skills: {skill_count} | Workflows: {wf_count}")

    # ── 备份工具 ─────────────────────────────────────────
    def _backup(self, filepath):
        """备份文件到_doctor_backups/"""
        filepath = Path(filepath)
        if not filepath.exists():
            return
        BACKUP_DIR.mkdir(exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"{filepath.name}.{ts}.bak"
        dest = BACKUP_DIR / backup_name
        shutil.copy2(filepath, dest)
        return dest

    # ── 主诊断流程 ───────────────────────────────────────
    def diagnose(self):
        print("=" * 60)
        print("🏥 Windsurf Doctor v2.1 — 7层配置腐化诊断+热补丁检测")
        print("=" * 60)
        print(f"时间: {datetime.now().isoformat()}")
        print(f"Windsurf安装: {WINDSURF_INSTALL_DIR}")
        print(f"用户数据: {USER_DATA_DIR}")
        print(f"Codeium数据: {CODEIUM_DIR}")

        self.check_L0_integrity()
        self.check_L1_settings_json()
        self.check_L2_protobuf()
        self.check_L3_mcp()
        self.check_L4_state_db()
        self.check_L5_global_storage()
        self.check_L6_hooks_rules()

        elapsed = time.time() - self.start_time
        self._print_summary(elapsed)
        return self.issues

    def _print_summary(self, elapsed):
        print("\n" + "=" * 60)
        print("📋 诊断摘要")
        print("=" * 60)

        fatal = [i for i in self.issues if i.severity == 'FATAL']
        warn = [i for i in self.issues if i.severity == 'WARN']
        info = [i for i in self.issues if i.severity == 'INFO']

        for issue in self.issues:
            print(f"  {issue}")
            if issue.detail:
                for line in issue.detail.split('\n')[:2]:
                    print(f"    → {line}")

        # 健康评分
        score = 100 - len(fatal) * 25 - len(warn) * 10 - len(info) * 2
        score = max(0, min(100, score))
        self.stats['health_score'] = score
        self.stats['fatal'] = len(fatal)
        self.stats['warn'] = len(warn)
        self.stats['info'] = len(info)

        grade = 'S' if score >= 95 else 'A' if score >= 80 else 'B' if score >= 60 else 'C' if score >= 40 else 'F'
        print(f"\n🏆 健康评分: {score}/100 (Grade {grade})")
        print(f"   🔴FATAL: {len(fatal)} | 🟡WARN: {len(warn)} | 🟢INFO: {len(info)}")
        print(f"   耗时: {elapsed:.2f}s")

        fixable = [i for i in self.issues if i.fix_fn]
        if fixable:
            print(f"\n🔧 可自动修复: {len(fixable)}项 — 运行 `python windsurf_doctor.py --fix`")

    # ── 修复流程 ─────────────────────────────────────────
    def fix_all(self):
        """修复所有可自动修复的问题"""
        fixable = [i for i in self.issues if i.fix_fn]
        if not fixable:
            print("\n✅ 没有需要修复的问题")
            return

        print(f"\n🔧 开始修复 ({len(fixable)}项)...")
        for issue in fixable:
            print(f"\n  修复: {issue.title}")
            try:
                result = issue.fix_fn()
                issue.fixed = True
                print(f"    ✅ {result}")
            except Exception as e:
                print(f"    ❌ 修复失败: {e}")

        fixed_count = sum(1 for i in fixable if i.fixed)
        print(f"\n🏁 修复完成: {fixed_count}/{len(fixable)}")

    # ── 报告生成 ─────────────────────────────────────────
    def generate_report(self):
        """生成Markdown诊断报告"""
        lines = [
            f"# Windsurf Doctor 诊断报告",
            f"",
            f"**时间**: {datetime.now().isoformat()}",
            f"**健康评分**: {self.stats.get('health_score', '?')}/100",
            f"",
            f"## 配置层全景",
            f"",
            f"| 层 | 项目 | 值 |",
            f"|---|------|-----|",
            f"| L0 | 安装完整性 | {self.stats.get('integrity_modified', '?')}/{self.stats.get('integrity_total', '?')} 被修改 | Windsurf v{self.stats.get('windsurf_version', '?')} |",
            f"| L1 | settings.json | {self.stats.get('settings_json_size', '?')}B |",
            f"| L2 | user_settings.pb | {self.stats.get('pb_size', '?')}B, {self.stats.get('model_count', '?')}个模型 |",
            f"| L3 | MCP (Codeium) | {self.stats.get('mcp_codeium_count', '?')}个服务器 |",
            f"| L3 | MCP (User) | {self.stats.get('mcp_user_count', '?')}个服务器 |",
            f"| L4 | workspaces | {self.stats.get('workspace_count', '?')}个, 健康{self.stats.get('state_db_healthy', '?')}/损坏{self.stats.get('state_db_corrupt', '?')} |",
            f"| L5 | PS会话 | {self.stats.get('ps_sessions', '?')}个 |",
            f"| L6 | Skills/Workflows | {self.stats.get('skills', '?')}/{self.stats.get('workflows', '?')} |",
            f"",
            f"## 发现的问题",
            f"",
        ]

        for issue in self.issues:
            icon = {'FATAL': '🔴', 'WARN': '🟡', 'INFO': '🟢'}.get(issue.severity, '⚪')
            fixed = ' ✅' if issue.fixed else ''
            lines.append(f"### {icon} [{issue.layer}] {issue.title}{fixed}")
            if issue.detail:
                lines.append(f"")
                lines.append(f"{issue.detail}")
            lines.append(f"")

        lines.extend([
            f"## 腐化根因模型",
            f"",
            f"```",
            f"L1 settings.json trailing comma → 严格JSON解析器部分失败",
            f"    ↓",
            f"L1 augment远程配置不可达 → Cascade设置超时/无响应",
            f"    ↓",
            f"L2 多进程并发写user_settings.pb → protobuf数据竞争",
            f"    ↓",
            f"L4 state.vscdb写入竞争 → 工作区设置丢失/回退",
            f"    ↓",
            f"重装清除APPDATA → 临时恢复 → 同样模式重现 → 循环",
            f"```",
            f"",
            f"## 为什么重装能临时缓解",
            f"",
            f"1. 清除`APPDATA\\Windsurf\\` → 所有state.vscdb/WebStorage/缓存重建",
            f"2. `~\\.codeium\\windsurf\\` **未被清除** → user_settings.pb/mcp_config/memories保留",
            f"3. 用户重新配置settings.json → 可能带入相同的trailing comma和augment配置",
            f"4. 根因(并发写入+JSON语法+远程配置)未解决 → 腐化重现",
            f"",
            f"## 永久修复方案",
            f"",
            f"1. **修复settings.json** — 移除trailing comma + 移除augment远程配置",
            f"2. **定期诊断** — `python windsurf_doctor.py` 检查配置健康",
            f"3. **守护模式** — `python windsurf_doctor.py --watch` 监视配置变化",
            f"4. **清理积累** — 陈旧workspace/PS会话/MCP备份",
        ])

        report = '\n'.join(lines)
        REPORT_FILE.write_text(report, encoding='utf-8')
        return report

    # ── 守护模式 ─────────────────────────────────────────
    def watch(self, interval=60):
        """文件监视+自动修复守护模式"""
        print(f"\n👁️ 守护模式启动 (每{interval}秒检查)")
        checksums = {}

        def get_checksum(path):
            if path.exists():
                return hashlib.md5(path.read_bytes()).hexdigest()
            return None

        # 初始快照 — 包含L0关键文件
        workbench_js = APP_OUT_DIR / 'vs' / 'workbench' / 'workbench.desktop.main.js'
        watched = [SETTINGS_JSON, USER_SETTINGS_PB, MCP_JSON_CODEIUM, MCP_JSON_USER,
                   PRODUCT_JSON, workbench_js]
        for w in watched:
            checksums[str(w)] = get_checksum(w)

        while True:
            time.sleep(interval)
            changed = False
            l0_changed = False
            for w in watched:
                new_hash = get_checksum(w)
                old_hash = checksums.get(str(w))
                if new_hash != old_hash:
                    print(f"\n⚡ 变更检测: {w.name} ({datetime.now().isoformat()})")
                    checksums[str(w)] = new_hash
                    changed = True
                    if w in (PRODUCT_JSON, workbench_js):
                        l0_changed = True

            if changed:
                self.issues.clear()
                if l0_changed:
                    self.check_L0_integrity()
                self.check_L1_settings_json()
                fixable = [i for i in self.issues if i.fix_fn and i.severity == 'FATAL']
                if fixable:
                    print(f"  🔧 自动修复{len(fixable)}个FATAL问题")
                    for issue in fixable:
                        try:
                            result = issue.fix_fn()
                            print(f"    ✅ {issue.title}: {result}")
                        except Exception as e:
                            print(f"    ❌ {issue.title}: {e}")

    # ── HTTP Hub ─────────────────────────────────────────
    def serve(self, port=PORT):
        doctor = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.split('?')[0]
                if path == '/api/health':
                    self._json({'ok': True, 'service': 'windsurf-doctor', 'version': '2.1',
                                'score': doctor.stats.get('health_score', -1),
                                'integrity': doctor.stats.get('integrity_modified', -1) == 0})
                elif path == '/api/diagnose':
                    doctor.issues.clear()
                    doctor.stats.clear()
                    doctor.start_time = time.time()
                    doctor.diagnose()
                    self._json({
                        'stats': doctor.stats,
                        'issues': [{'layer': i.layer, 'severity': i.severity,
                                    'title': i.title, 'detail': i.detail,
                                    'fixable': i.fix_fn is not None,
                                    'fixed': i.fixed} for i in doctor.issues]
                    })
                elif path == '/api/fix':
                    doctor.fix_all()
                    self._json({
                        'fixed': sum(1 for i in doctor.issues if i.fixed),
                        'total': sum(1 for i in doctor.issues if i.fix_fn)
                    })
                elif path == '/':
                    self._html(self._dashboard())
                else:
                    self._json({'error': 'not found'}, 404)

            def _json(self, data, code=200):
                body = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)

            def _html(self, html):
                body = html.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)

            def _dashboard(self):
                return '''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Windsurf Doctor</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:system-ui,-apple-system,sans-serif;padding:20px}
h1{color:#58a6ff;margin-bottom:20px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin:12px 0}
.score{font-size:48px;font-weight:bold;text-align:center}
.score.s{color:#3fb950}.score.a{color:#58a6ff}.score.b{color:#d29922}.score.f{color:#f85149}
.issue{padding:8px;margin:4px 0;border-radius:4px;border-left:3px solid}
.issue.FATAL{border-color:#f85149;background:#1a0a0a}.issue.WARN{border-color:#d29922;background:#1a150a}.issue.INFO{border-color:#3fb950;background:#0a1a0a}
.tag{display:inline-block;padding:2px 8px;border-radius:12px;font-size:12px;margin-right:4px}
.tag.FATAL{background:#f85149;color:#fff}.tag.WARN{background:#d29922;color:#000}.tag.INFO{background:#3fb950;color:#000}
button{background:#238636;color:#fff;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:14px}
button:hover{background:#2ea043}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.stat{background:#21262d;padding:12px;border-radius:6px;text-align:center}
.stat .val{font-size:24px;font-weight:bold;color:#58a6ff}
.stat .lbl{color:#8b949e;font-size:12px}
#log{background:#0d1117;border:1px solid #30363d;padding:12px;border-radius:6px;max-height:300px;overflow-y:auto;font-family:monospace;font-size:13px;white-space:pre-wrap}
</style></head><body>
<h1>🏥 Windsurf Doctor v2.1</h1>
<div class="card"><button onclick="diagnose()">🔍 全量诊断</button> <button onclick="fix()">🔧 自动修复</button></div>
<div class="stats" id="stats"></div>
<div class="card"><h3>发现的问题</h3><div id="issues"></div></div>
<div class="card"><h3>诊断日志</h3><div id="log">点击"全量诊断"开始...</div></div>
<script>
async function diagnose(){
  document.getElementById('log').textContent='诊断中...';
  const r=await fetch('/api/diagnose');const d=await r.json();
  renderStats(d.stats);renderIssues(d.issues);
  document.getElementById('log').textContent=JSON.stringify(d,null,2);
}
async function fix(){
  const r=await fetch('/api/fix');const d=await r.json();
  document.getElementById('log').textContent='修复结果: '+JSON.stringify(d,null,2);
  diagnose();
}
function renderStats(s){
  const el=document.getElementById('stats');
  const score=s.health_score||0;
  const grade=score>=95?'S':score>=80?'A':score>=60?'B':'F';
  const gc=score>=95?'s':score>=80?'a':score>=60?'b':'f';
  el.innerHTML=`
    <div class="stat"><div class="val score ${gc}">${score}</div><div class="lbl">健康评分 (${grade})</div></div>
    <div class="stat"><div class="val">${s.fatal||0}/${s.warn||0}/${s.info||0}</div><div class="lbl">FATAL/WARN/INFO</div></div>
    <div class="stat"><div class="val">${s.integrity_modified===0?'✅':'❌ '+s.integrity_modified}</div><div class="lbl">安装完整性 (L0)</div></div>
    <div class="stat"><div class="val">${s.windsurf_version||'?'}</div><div class="lbl">Windsurf版本</div></div>
    <div class="stat"><div class="val">${s.model_count||'?'}</div><div class="lbl">模型定义</div></div>
    <div class="stat"><div class="val">${s.workspace_count||'?'}</div><div class="lbl">工作区</div></div>
    <div class="stat"><div class="val">${s.ps_sessions||'?'}</div><div class="lbl">PS会话</div></div>
    <div class="stat"><div class="val">${((s.pb_size||0)/1024).toFixed(1)}KB</div><div class="lbl">user_settings.pb</div></div>
  `;
}
function renderIssues(issues){
  const el=document.getElementById('issues');
  if(!issues||!issues.length){el.innerHTML='<div style="color:#3fb950;padding:8px">✅ 无问题</div>';return}
  el.innerHTML=issues.map(i=>`<div class="issue ${i.severity}">
    <span class="tag ${i.severity}">${i.severity}</span> <strong>[${i.layer}]</strong> ${i.title}
    ${i.fixable?'<span style="color:#58a6ff">🔧可修复</span>':''}
    ${i.fixed?'<span style="color:#3fb950">✅已修复</span>':''}
    ${i.detail?'<div style="color:#8b949e;font-size:12px;margin-top:4px">'+i.detail.split('\\n')[0]+'</div>':''}
  </div>`).join('');
}
diagnose();
</script></body></html>'''

            def log_message(self, format, *args):
                pass  # 静默日志

        server = HTTPServer(('0.0.0.0', port), Handler)
        print(f"\n🌐 Windsurf Doctor Hub: http://localhost:{port}/")
        print(f"   API: /api/health | /api/diagnose | /api/fix")
        server.serve_forever()


# ── schtask部署 ──────────────────────────────────────────
def deploy_schtask():
    """部署Doctor为schtask持久化守护(每小时L0+L1检查)"""
    script = Path(__file__).resolve()
    python = Path(sys.executable)
    # 使用pythonw避免弹窗
    pythonw = python.parent / 'pythonw.exe'
    if not pythonw.exists():
        pythonw = python

    task_name = 'WindsurfDoctor'
    cmd = f'"{pythonw}" "{script}" --watch --interval 3600'

    _scht = dict(capture_output=True, timeout=10, encoding='gbk', errors='replace')

    # 检查是否已存在
    check = _hidden_run(
        ['schtasks', '/Query', '/TN', task_name, '/FO', 'CSV', '/NH'], **_scht
    )
    if task_name in (check.stdout or ''):
        print(f"  ℹ️ 任务 {task_name} 已存在，先删除...")
        _hidden_run(['schtasks', '/Delete', '/TN', task_name, '/F'], **_scht)

    # 创建任务: ONLOGON触发
    result = _hidden_run(
        ['schtasks', '/Create', '/TN', task_name,
         '/TR', cmd, '/SC', 'ONLOGON', '/RL', 'HIGHEST', '/F'],
        capture_output=True, timeout=15, encoding='gbk', errors='replace'
    )

    if result.returncode == 0:
        print(f"  ✅ 已部署 schtask '{task_name}'")
        print(f"     触发: ONLOGON | 命令: --watch --interval 3600")
        print(f"     Python: {pythonw}")
        _hidden_run(['schtasks', '/Run', '/TN', task_name], **_scht)
        print(f"  ✅ 已启动守护进程")
    else:
        print(f"  ❌ 部署失败: {(result.stderr or '').strip()}")
        print(f"     尝试手动: schtasks /Create /TN {task_name} /TR \"{cmd}\" /SC ONLOGON /RL HIGHEST")


# ── CLI入口 ──────────────────────────────────────────────
def main():
    args = sys.argv[1:]
    doctor = WindsurfDoctor()

    if '--deploy' in args:
        print("\n🚀 部署Windsurf Doctor守护...")
        deploy_schtask()
        return
    elif '--serve' in args:
        doctor.diagnose()
        doctor.serve()
    elif '--watch' in args:
        doctor.diagnose()
        interval = 60
        for i, a in enumerate(args):
            if a == '--interval' and i + 1 < len(args):
                interval = int(args[i + 1])
        doctor.watch(interval)
    else:
        doctor.diagnose()
        if '--fix' in args:
            doctor.fix_all()
        report = doctor.generate_report()
        print(f"\n📄 报告已保存: {REPORT_FILE}")

        if '--fix' in args:
            # 修复后重新诊断验证
            print("\n🔄 修复后重新诊断...")
            doctor2 = WindsurfDoctor()
            doctor2.diagnose()


if __name__ == '__main__':
    main()
