#!/usr/bin/env python3
"""
Hot Guardian v1.0 — 全热化总守护进程
======================================
道法自然: 万物生于一。一个守护进程，管理一切热运行时。

职责:
  1. 端口强制   — 启动前清除 :19877/:19876 占用进程
  2. 进程守护   — pool_engine(:19877) + pool_proxy(:19876) 崩溃自动重启
  3. 补丁守护   — extension.js 被覆盖时自动重新注入
  4. Key 降级   — pool_engine 崩溃期间用最后已知 key 保持文件有效
  5. 状态 API   — :19875/status 随时查看全系统健康
  6. 热测试     — /test 端点触发 E2E 快照

Usage:
  python hot_guardian.py          # 前台运行 (Ctrl+C 优雅退出)
  python hot_guardian.py daemon   # 后台 Windows 窗口
  python hot_guardian.py status   # 查询运行状态
  python hot_guardian.py stop     # 停止所有托管进程
"""

import os, sys, json, time, signal, hashlib, threading, subprocess, traceback
import urllib.request, urllib.error
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

SCRIPT_DIR  = Path(__file__).parent
APPDATA     = Path(os.environ.get('APPDATA', ''))
POOL_KEY    = APPDATA / 'Windsurf' / '_pool_apikey.txt'
# v2.0 fix: Only write to CURRENT user's pool key — do NOT overwrite other users' files.
# Each user manages their own _pool_apikey.txt independently.
# Writing ai's key to Administrator's file was the root cause of cross-user switching failure:
# Administrator's hot_patch read Administrator's file (overwritten by ai's guardian every 3s)
# → all Administrator gRPC requests used ai's key → account switching had zero effect.
_ALL_POOL_KEYS = [POOL_KEY]
EXT_JS      = Path(r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js')
PATCH_MARKER = '/* POOL_HOT_PATCH_V1 */'

ENGINE_PORT  = 19877
PROXY_PORT   = 19876
GUARDIAN_PORT = 19875

RESTART_DELAY  = 5    # seconds before restarting crashed process
WATCH_INTERVAL = 10   # seconds between health checks
KEY_WRITE_INTERVAL = 3

PYTHON = sys.executable
LOG_FILE = SCRIPT_DIR / '_guardian.log'

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
_log_lock = threading.Lock()

def log(msg, level='INFO'):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] [{level}] {msg}'
    with _log_lock:
        print(line, flush=True)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


# ─────────────────────────────────────────────
# Port utilities
# ─────────────────────────────────────────────
def kill_port(port: int):
    """Kill any process listening on the given port (Windows)."""
    try:
        result = subprocess.run(
            ['netstat', '-ano'],
            capture_output=True, text=True, timeout=5
        )
        pids = set()
        for line in result.stdout.splitlines():
            if f':{port} ' in line and 'LISTENING' in line:
                parts = line.split()
                if parts:
                    try:
                        pids.add(int(parts[-1]))
                    except ValueError:
                        pass
        for pid in pids:
            if pid > 4:  # never kill System (PID 4)
                subprocess.run(['taskkill', '/PID', str(pid), '/F'],
                               capture_output=True, timeout=5)
                log(f'Killed PID {pid} on :{port}', 'PORT')
        if pids:
            time.sleep(1)
    except Exception as e:
        log(f'kill_port({port}) error: {e}', 'WARN')


def port_alive(port: int, path: str = '/api/health', expect_key: str = 'ok') -> bool:
    """Return True if port responds with expected JSON key."""
    try:
        r = urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=2)
        d = json.loads(r.read())
        return d.get(expect_key) is not None
    except Exception:
        return False


def engine_port_alive() -> bool:
    """Check pool_engine health (validates version field)."""
    try:
        r = urllib.request.urlopen(f'http://127.0.0.1:{ENGINE_PORT}/api/health', timeout=2)
        d = json.loads(r.read())
        return bool(d.get('ok') and d.get('version'))
    except Exception:
        return False


def proxy_port_alive() -> bool:
    """Check pool_proxy health."""
    return port_alive(PROXY_PORT, '/pool/health', 'ok')


# ─────────────────────────────────────────────
# Process manager
# ─────────────────────────────────────────────
class ManagedProcess:
    """Wrap a subprocess with auto-restart logic."""

    def __init__(self, name: str, cmd: list, alive_fn, cwd=None):
        self.name     = name
        self.cmd      = cmd
        self.alive_fn = alive_fn
        self.cwd      = cwd or str(SCRIPT_DIR)
        self.proc     = None
        self.starts   = 0
        self.last_start = 0.0
        self.running  = False
        self._lock    = threading.Lock()

    def start(self):
        with self._lock:
            self._start_inner()

    def _start_inner(self):
        self.starts += 1
        self.last_start = time.time()
        log(f'Starting [{self.name}] (attempt #{self.starts}): {" ".join(self.cmd)}', 'PROC')
        try:
            self.proc = subprocess.Popen(
                self.cmd,
                cwd=self.cwd,
                stdout=open(SCRIPT_DIR / f'_{self.name}.stdout.log', 'a', encoding='utf-8', errors='replace'),
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            )
            self.running = True
            log(f'[{self.name}] started PID={self.proc.pid}', 'PROC')
        except Exception as e:
            log(f'[{self.name}] start FAILED: {e}', 'ERROR')
            self.running = False

    def check_and_restart(self) -> bool:
        """Return True if process was restarted."""
        with self._lock:
            alive = self.alive_fn()
            if not alive:
                elapsed = time.time() - self.last_start
                if elapsed < RESTART_DELAY:
                    return False
                log(f'[{self.name}] DOWN — restarting in {RESTART_DELAY}s', 'WATCH')
                time.sleep(RESTART_DELAY)
                self._start_inner()
                return True
        return False

    def stop(self):
        with self._lock:
            self.running = False
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.terminate()
                    self.proc.wait(timeout=5)
                except Exception:
                    self.proc.kill()
                log(f'[{self.name}] stopped', 'PROC')

    def status(self) -> dict:
        return {
            'name': self.name,
            'alive': self.alive_fn(),
            'pid': self.proc.pid if self.proc else None,
            'starts': self.starts,
            'last_start': self.last_start,
        }


# ─────────────────────────────────────────────
# Patch watcher
# ─────────────────────────────────────────────
class PatchWatcher:
    """Watch extension.js and re-apply patch if overwritten."""

    def __init__(self):
        self._last_hash = None
        self._patch_count = 0

    def _hash(self) -> str:
        if not EXT_JS.exists():
            return ''
        try:
            h = hashlib.md5()
            with open(EXT_JS, 'rb') as f:
                for chunk in iter(lambda: f.read(65536), b''):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ''

    def is_patched(self) -> bool:
        if not EXT_JS.exists():
            return False
        try:
            src = EXT_JS.read_text(encoding='utf-8', errors='replace')
            return PATCH_MARKER in src
        except Exception:
            return False

    def check_and_repatch(self) -> bool:
        """Return True if repatch was needed and done."""
        current_hash = self._hash()
        if current_hash == self._last_hash:
            return False
        self._last_hash = current_hash
        if not self.is_patched():
            log('extension.js changed and UNPATCHED — applying patch...', 'PATCH')
            try:
                result = subprocess.run(
                    [PYTHON, str(SCRIPT_DIR / 'hot_patch.py'), 'apply'],
                    capture_output=True, text=True, timeout=30, cwd=str(SCRIPT_DIR)
                )
                if result.returncode == 0:
                    self._patch_count += 1
                    log(f'Patch re-applied (#{self._patch_count}). Windsurf needs one restart.', 'PATCH')
                else:
                    log(f'Patch FAILED: {result.stderr[:200]}', 'ERROR')
                return True
            except Exception as e:
                log(f'Patch exception: {e}', 'ERROR')
        return False

    def status(self) -> dict:
        return {
            'patched': self.is_patched(),
            'ext_js_exists': EXT_JS.exists(),
            'repatch_count': self._patch_count,
        }


# ─────────────────────────────────────────────
# Key file keeper (fallback when engine is down)
# ─────────────────────────────────────────────
class KeyKeeper:
    """Keep _pool_apikey.txt fresh. Falls back to last known key if engine is down."""

    def __init__(self):
        self._last_key = ''
        self._write_count = 0
        self._last_write = 0.0

    def refresh(self):
        try:
            r = urllib.request.urlopen(f'http://127.0.0.1:{ENGINE_PORT}/api/pick', timeout=2)
            d = json.loads(r.read())
            key = d.get('api_key') or d.get('api_key_preview', '')
            if key and key.startswith('sk-ws') and len(key) > 20:
                self._last_key = key
        except Exception:
            pass  # use last known

        if self._last_key:
            for _pkf in _ALL_POOL_KEYS:
                try:
                    _pkf.parent.mkdir(parents=True, exist_ok=True)
                    _pkf.write_text(self._last_key, encoding='utf-8')
                except Exception:
                    pass
            self._write_count += 1
            self._last_write = time.time()

    def status(self) -> dict:
        key = ''
        try:
            key = POOL_KEY.read_text(encoding='utf-8', errors='replace').strip()
        except Exception:
            pass
        return {
            'key_file': str(POOL_KEY),
            'key_valid': key.startswith('sk-ws') and len(key) > 20,
            'key_preview': key[:25] + '...' if key else '',
            'write_count': self._write_count,
        }


# ─────────────────────────────────────────────
# Guardian status HTTP API (:19875)
# ─────────────────────────────────────────────
_guardian_ref = None

class GuardianHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'application/json')

    def _json(self, data, code=200):
        body = json.dumps(data, indent=2).encode()
        self.send_response(code)
        self._cors()
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ('/', '/status'):
            if _guardian_ref:
                self._json(_guardian_ref.full_status())
            else:
                self._json({'ok': False, 'error': 'no guardian'})
        elif self.path == '/test':
            # Quick inline test: verify key file + engine
            results = {}
            results['key_valid'] = (
                POOL_KEY.exists() and
                POOL_KEY.read_text(encoding='utf-8', errors='replace').strip().startswith('sk-ws')
            )
            results['engine_alive'] = engine_port_alive()
            results['proxy_alive'] = proxy_port_alive()
            patched = False
            try:
                src = EXT_JS.read_text(encoding='utf-8', errors='replace')
                patched = PATCH_MARKER in src
            except Exception:
                pass
            results['ext_patched'] = patched
            results['ok'] = all(results.values())
            self._json(results)
        elif self.path == '/stop':
            if _guardian_ref:
                threading.Thread(target=_guardian_ref.stop, daemon=True).start()
            self._json({'ok': True, 'msg': 'stopping'})
        else:
            self.send_response(404)
            self.end_headers()


# ─────────────────────────────────────────────
# Guardian main
# ─────────────────────────────────────────────
class HotGuardian:
    def __init__(self):
        self._running = False
        self._start_time = time.time()
        self._patch_watcher = PatchWatcher()
        self._key_keeper = KeyKeeper()
        self._procs: list[ManagedProcess] = []
        self._api_thread = None

    def _setup_processes(self):
        self._procs = [
            ManagedProcess(
                'pool_engine',
                [PYTHON, str(SCRIPT_DIR / 'pool_engine.py'), 'serve'],
                engine_port_alive,
            ),
            ManagedProcess(
                'pool_proxy',
                [PYTHON, str(SCRIPT_DIR / 'pool_proxy.py')],
                proxy_port_alive,
            ),
        ]

    def _start_api(self):
        def _serve():
            try:
                srv = HTTPServer(('127.0.0.1', GUARDIAN_PORT), GuardianHandler)
                log(f'Guardian API: http://127.0.0.1:{GUARDIAN_PORT}/status', 'API')
                srv.serve_forever()
            except Exception as e:
                log(f'Guardian API error: {e}', 'WARN')
        t = threading.Thread(target=_serve, daemon=True, name='GuardianAPI')
        t.start()
        self._api_thread = t

    def _key_loop(self):
        while self._running:
            self._key_keeper.refresh()
            time.sleep(KEY_WRITE_INTERVAL)

    def _watch_loop(self):
        while self._running:
            # 1. Health-check + restart managed processes
            for p in self._procs:
                p.check_and_restart()
            # 2. Patch watcher
            self._patch_watcher.check_and_repatch()
            time.sleep(WATCH_INTERVAL)

    def start(self):
        global _guardian_ref
        _guardian_ref = self

        log('=' * 60, 'INIT')
        log('HOT GUARDIAN v1.0 — 全热化总守护进程', 'INIT')
        log('=' * 60, 'INIT')

        # 1. Kill port occupants
        log(f'Clearing ports :{ENGINE_PORT} :{PROXY_PORT}...', 'PORT')
        kill_port(ENGINE_PORT)
        kill_port(PROXY_PORT)

        # 2. Apply patch if missing
        if not self._patch_watcher.is_patched():
            log('extension.js not patched — applying now...', 'PATCH')
            subprocess.run([PYTHON, str(SCRIPT_DIR / 'hot_patch.py'), 'apply'],
                           cwd=str(SCRIPT_DIR), timeout=30)

        # 3. Setup + start managed processes
        self._setup_processes()
        self._running = True
        for p in self._procs:
            p.start()

        time.sleep(3)  # let services initialize

        # 4. Start guardian API
        self._start_api()

        # 5. Start key writer thread
        threading.Thread(target=self._key_loop, daemon=True, name='KeyLoop').start()

        # 6. Start watch loop thread
        threading.Thread(target=self._watch_loop, daemon=True, name='WatchLoop').start()

        # 7. Print status
        time.sleep(2)
        self._print_status()

        log('Guardian running. Press Ctrl+C to stop.', 'INIT')

        # 8. Main thread: heartbeat + graceful signal
        try:
            while self._running:
                time.sleep(30)
                self._heartbeat()
        except KeyboardInterrupt:
            log('Ctrl+C — shutting down...', 'INIT')
            self.stop()

    def _heartbeat(self):
        e = '✅' if engine_port_alive() else '❌'
        pr = '✅' if proxy_port_alive() else '❌'
        pa = '✅' if self._patch_watcher.is_patched() else '❌'
        ks = self._key_keeper.status()
        kk = '✅' if ks['key_valid'] else '❌'
        log(f'engine={e} proxy={pr} patch={pa} key={kk}', 'BEAT')

    def _print_status(self):
        log(f'Engine  : http://127.0.0.1:{ENGINE_PORT}/', 'STATUS')
        log(f'Proxy   : http://127.0.0.1:{PROXY_PORT}/', 'STATUS')
        log(f'Guardian: http://127.0.0.1:{GUARDIAN_PORT}/status', 'STATUS')
        log(f'KeyFile : {POOL_KEY}', 'STATUS')
        self._heartbeat()

    def stop(self):
        self._running = False
        for p in self._procs:
            p.stop()
        log('Guardian stopped.', 'INIT')

    def full_status(self) -> dict:
        uptime = round(time.time() - self._start_time)
        return {
            'ok': True,
            'version': '1.0.0',
            'uptime_s': uptime,
            'engine': engine_port_alive(),
            'proxy': proxy_port_alive(),
            'patch': self._patch_watcher.status(),
            'key': self._key_keeper.status(),
            'processes': [p.status() for p in self._procs],
            'guardian_api': f'http://127.0.0.1:{GUARDIAN_PORT}',
        }


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
def cli_status():
    """Query running guardian status."""
    try:
        r = urllib.request.urlopen(f'http://127.0.0.1:{GUARDIAN_PORT}/status', timeout=3)
        s = json.loads(r.read())
        print(json.dumps(s, indent=2, ensure_ascii=False))
    except Exception:
        print(f'Guardian not running on :{GUARDIAN_PORT}')
        sys.exit(1)


def cli_test():
    """Quick hot-test via guardian API."""
    try:
        r = urllib.request.urlopen(f'http://127.0.0.1:{GUARDIAN_PORT}/test', timeout=3)
        s = json.loads(r.read())
        ok = s.pop('ok')
        for k, v in s.items():
            icon = '✅' if v else '❌'
            print(f'  {icon} {k}')
        print(f'\n  {"✅ ALL OK" if ok else "❌ ISSUES FOUND"}')
    except Exception:
        print('Guardian not running. Start with: python hot_guardian.py')
        sys.exit(1)


def cli_stop():
    """Stop all guardian-managed processes."""
    try:
        r = urllib.request.urlopen(f'http://127.0.0.1:{GUARDIAN_PORT}/stop', timeout=3)
        print(json.loads(r.read()))
    except Exception:
        print('Guardian not reachable.')
        sys.exit(1)


def cli_daemon():
    """Launch guardian as a new visible PowerShell window."""
    script = str(Path(__file__).absolute())
    cmd = ['powershell', '-NoExit', '-Command',
           f'cd "{SCRIPT_DIR}"; python "{script}"']
    subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
    print(f'Guardian launched in new window.')
    print(f'  Status: python hot_guardian.py status')
    print(f'  API:    http://127.0.0.1:{GUARDIAN_PORT}/status')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'run'
    if cmd == 'status':
        cli_status()
    elif cmd == 'test':
        cli_test()
    elif cmd == 'stop':
        cli_stop()
    elif cmd == 'daemon':
        cli_daemon()
    else:
        HotGuardian().start()
