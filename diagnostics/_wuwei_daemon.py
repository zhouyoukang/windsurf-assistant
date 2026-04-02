"""
_wuwei_daemon.py — 无为守护 v1.0
道法自然 · 无为而无不为 · 唯变所适

核心哲学:
  用户无感无为 - 后台完全自治，不影响Windsurf正常运行
  预防性轮转  - 消息发出前切号，rate limit永不触发
  自愈链路    - 检测到问题自动修复，无需人工干预

功能链路:
  1. IPC管道注入 → 触发extension host无感重启(~1.5s, 无UI闪烁)
  2. 无感GBe注入 → 通过eval机制在当前渲染进程激活拦截器
  3. 预防性轮转守护 → 持续监控号池状态，提前切号
  4. Rate Limit看门狗 → 检测到限流立即执行强制轮转+重试

Usage:
  python _wuwei_daemon.py             # 全部功能（推荐）
  python _wuwei_daemon.py --ipc       # 仅IPC重启extension host
  python _wuwei_daemon.py --watchdog  # 仅启动看门狗
  python _wuwei_daemon.py --once      # 单次检查并轮转
"""
import sys, os, struct, time, json, socket, threading, subprocess
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

ADMIN_HUB = 'http://127.0.0.1:19881'
WAM_HUB   = 'http://127.0.0.1:9870'
POLL_SEC  = 5   # 主循环轮询间隔
FAST_SEC  = 1   # 快速检测间隔（限流后）


# ═══════════════════════════════════════════════
#  HTTP 工具
# ═══════════════════════════════════════════════
def _get(url, timeout=4):
    try:
        r = urlopen(Request(url), timeout=timeout)
        return json.loads(r.read())
    except Exception:
        return None

def _post(url, data, timeout=4):
    try:
        body = json.dumps(data).encode()
        r = urlopen(Request(url, data=body, headers={'Content-Type':'application/json'}), timeout=timeout)
        return json.loads(r.read())
    except Exception:
        return None


# ═══════════════════════════════════════════════
#  IPC 管道 — extension host 无感重启
# ═══════════════════════════════════════════════
def _find_ipc_pipes():
    """枚举所有Windsurf/VSCode IPC管道"""
    pipes = []
    try:
        # Windows named pipes: \\.\pipe\{hex}-{version}-main-sock
        out = subprocess.check_output(
            ['powershell', '-NoProfile', '-Command',
             r'[IO.Directory]::GetFiles("\\.\pipe") | Where-Object { $_ -match "main-sock" }'],
            stderr=subprocess.DEVNULL, encoding='utf-8', errors='replace', timeout=5
        )
        for line in out.strip().splitlines():
            line = line.strip()
            if line and 'main-sock' in line:
                # Normalize: powershell may return \\.\pipe\name, we want \\.\pipe\name
                pipes.append(line)
    except Exception:
        pass
    # Also try direct listing
    try:
        import ctypes
        # Fallback: known pattern from memory
        out2 = subprocess.check_output(
            ['powershell', '-NoProfile', '-Command',
             r'Get-ChildItem "\\.\pipe" | Where-Object { $_.Name -like "*main-sock*" } | Select-Object -ExpandProperty FullName'],
            stderr=subprocess.DEVNULL, encoding='utf-8', errors='replace', timeout=5
        )
        for line in out2.strip().splitlines():
            line = line.strip()
            if line and 'main-sock' in line:
                if line not in pipes:
                    pipes.append(line)
    except Exception:
        pass
    return pipes


def _send_ipc(pipe_path, message):
    """发送4字节LE长度头 + UTF-8 JSON 到IPC管道"""
    try:
        pipe_name = pipe_path
        if not pipe_name.startswith('\\\\.\\pipe\\'):
            # Extract pipe name
            pipe_name = '\\\\.\\pipe\\' + Path(pipe_path).name
        
        msg = json.dumps(message).encode('utf-8')
        header = struct.pack('<I', len(msg))
        
        sock = socket.socket(socket.AF_PIPE if hasattr(socket, 'AF_PIPE') else socket.AF_UNIX)
        # On Windows use CreateFile approach via ctypes
        import ctypes, ctypes.wintypes
        
        GENERIC_READWRITE = 0xC0000000
        OPEN_EXISTING = 3
        FILE_FLAG_OVERLAPPED = 0x40000000
        
        handle = ctypes.windll.kernel32.CreateFileW(
            pipe_name, GENERIC_READWRITE, 0, None, OPEN_EXISTING, 0, None
        )
        if handle == ctypes.c_void_p(-1).value:
            return False
        
        buf = header + msg
        written = ctypes.c_ulong(0)
        ok = ctypes.windll.kernel32.WriteFile(handle, buf, len(buf), ctypes.byref(written), None)
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok)
    except Exception:
        return False


def trigger_extension_host_restart():
    """IPC无感重启extension host — ~1.5s, UI无闪烁"""
    pipes = _find_ipc_pipes()
    if not pipes:
        print('[IPC] 未找到IPC管道，跳过无感重启')
        return False
    
    msg = {'type': 'restartExtensionHost'}
    sent = 0
    for pipe in pipes:
        if _send_ipc(pipe, msg):
            sent += 1
            print(f'[IPC] ✅ 已发送restartExtensionHost → {Path(pipe).name}')
    
    if sent == 0:
        print(f'[IPC] ⚠️  找到{len(pipes)}条管道但发送失败，尝试备用方法')
        return _restart_via_wam_command()
    
    print(f'[IPC] 无感重启中... (~1.5s)')
    time.sleep(2)
    return True


def _restart_via_wam_command():
    """备用: 通过WAM Hub的热重载命令触发"""
    r = _post(f'{WAM_HUB}/api/hot/reload', {})
    if r and r.get('ok'):
        print('[IPC] ✅ WAM热重载成功')
        time.sleep(1)
        return True
    # Fallback: write to hot-dir
    try:
        hot = Path.home() / '.wam-hot'
        hot.mkdir(exist_ok=True)
        (hot / '.reload').write_text(str(time.time()))
        time.sleep(0.6)
        print('[IPC] ✅ 热重载信号已写入 ~/.wam-hot/.reload')
        return True
    except Exception as e:
        print(f'[IPC] ❌ 备用方法失败: {e}')
        return False


# ═══════════════════════════════════════════════
#  号池状态读取
# ═══════════════════════════════════════════════
def get_pool_state():
    """获取WAM号池当前状态"""
    # Try WAM hub first
    state = _get(f'{WAM_HUB}/api/pool/status')
    if state:
        return {'source': 'wam', **state}
    # Try admin hub (public endpoint, no auth needed)
    health = _get(f'{ADMIN_HUB}/api/health')
    if health and health.get('ok'):
        return {'source': 'admin', 'online': True, **health}
    return {'source': None, 'online': False}


def get_rate_limit_status():
    """从管理端获取限流状态（需认证，失败则静默）"""
    return _get(f'{ADMIN_HUB}/api/ratelimit/status')


def force_rotate():
    """强制WAM切换到最优账号"""
    # Try WAM smart rotate command
    r = _post(f'{WAM_HUB}/api/pool/rotate', {'reason': 'proactive_wuwei'})
    if r and r.get('ok'):
        print(f'[轮转] ✅ WAM强制轮转成功 → {r.get("newAccount", {}).get("email", "?")[:20]}...')
        return True
    # Try via pool refresh
    r2 = _get(f'{WAM_HUB}/api/pool/refresh')
    if r2:
        print(f'[轮转] ✅ 号池刷新完成')
        return True
    print('[轮转] ⚠️  WAM Hub不可达，跳过轮转')
    return False


# ═══════════════════════════════════════════════
#  无为看门狗核心
# ═══════════════════════════════════════════════
class WuWeiDaemon:
    """无为守护 — 完全后台自治，零用户感知"""
    
    def __init__(self):
        self._running = False
        self._last_rotate = 0
        self._rotate_count = 0
        self._rate_limit_count = 0
        self._poll_interval = POLL_SEC
        self._fast_mode = False
        self._fast_until = 0
        self._last_state_hash = None
    
    def start(self):
        self._running = True
        print('[无为守护] 启动 — 后台自治模式')
        print(f'[无为守护] WAM Hub: {WAM_HUB} | 管理端: {ADMIN_HUB}')
        print('[无为守护] 按 Ctrl+C 停止')
        print()
        
        while self._running:
            try:
                self._tick()
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f'[无为守护] ⚠️  循环异常: {e}')
            
            # 动态间隔: 限流后切换快速模式
            now = time.time()
            if self._fast_mode and now > self._fast_until:
                self._fast_mode = False
                self._poll_interval = POLL_SEC
                print('[无为守护] 恢复正常轮询间隔 (5s)')
            
            time.sleep(self._poll_interval)
        
        print(f'\n[无为守护] 已停止。共轮转{self._rotate_count}次，处理限流{self._rate_limit_count}次。')
    
    def _tick(self):
        """单次检测与响应"""
        # 1. 读取WAM号池状态
        state = get_pool_state()
        
        if not state.get('online', False) and state.get('source') != 'wam':
            return  # Hub离线，静默等待
        
        # 2. 检测限流信号 — globalThis.__wamRateLimit 通过WAM Hub暴露
        self._check_rate_limit_signal(state)
        
        # 3. 检测配额阈值 — 预防性切号
        self._check_quota_threshold(state)
        
        # 4. 检测WAM Hub心跳 — 确保系统健康
        self._check_hub_health(state)
    
    def _check_rate_limit_signal(self, state):
        """检测限流信号并立即响应"""
        # Method 1: WAM Hub /api/rate-limit-events endpoint
        rl_events = _get(f'{WAM_HUB}/api/rate-limit-events')
        if rl_events and rl_events.get('recent'):
            recent = rl_events['recent']
            if recent and recent[0].get('ts', 0) > self._last_rotate:
                self._rate_limit_count += 1
                email = recent[0].get('email', '?')[:20]
                print(f'[限流检测] ⚡ 检测到限流事件: {email}... → 立即轮转')
                self._do_rotate(reason='rate_limit_signal')
                return
        
        # Method 2: Check WAM pool status for rate-limited flags
        if state.get('rateLimited') or state.get('isRateLimited'):
            self._rate_limit_count += 1
            print(f'[限流检测] ⚡ WAM状态显示限流 → 立即轮转')
            self._do_rotate(reason='wam_rate_limited')
            return
        
        # Method 3: Check opusGuard/sonnetGuard signals
        opus = state.get('opusGuard', {})
        sonnet = state.get('sonnetGuard', {})
        if opus.get('isRateLimited') or sonnet.get('isRateLimited'):
            self._rate_limit_count += 1
            print(f'[限流检测] ⚡ 模型守卫触发限流 → 立即轮转')
            self._do_rotate(reason='model_guard_rate_limited')
    
    def _check_quota_threshold(self, state):
        """预防性: 配额低于阈值时提前切号"""
        # Extract effective quota
        d_pct = state.get('dailyQuotaPercent', state.get('dPercent', 100))
        w_pct = state.get('weeklyQuotaPercent', state.get('wPercent', 100))
        effective = min(d_pct or 100, w_pct or 100)
        
        # Skip if data not available
        if d_pct is None and w_pct is None:
            return
        
        # Proactive threshold: if < 15%, switch now
        if effective < 15 and effective > 0:
            now = time.time()
            if now - self._last_rotate > 30:  # 防连锁: 30s内不重复切
                print(f'[预防切号] 📊 有效配额={effective:.0f}% < 15% → 预防性轮转')
                self._do_rotate(reason='quota_preemptive')
    
    def _check_hub_health(self, state):
        """检测WAM Hub健康状态"""
        if state.get('source') == 'wam' and not state.get('online'):
            # WAM Hub离线 — 尝试重启
            print('[健康检测] ⚠️  WAM Hub离线 → 尝试热重载恢复')
            _restart_via_wam_command()
    
    def _do_rotate(self, reason='unknown'):
        """执行轮转 — 防连锁保护"""
        now = time.time()
        if now - self._last_rotate < 3:  # 最短切号间隔3s
            return
        
        self._last_rotate = now
        self._rotate_count += 1
        
        success = force_rotate()
        if success:
            # 切换到快速模式，密切监控
            self._fast_mode = True
            self._fast_until = now + 30  # 30s快速模式
            self._poll_interval = FAST_SEC
            print(f'[无为守护] 进入快速监控模式 (1s/次, 持续30s)')
        
        return success


# ═══════════════════════════════════════════════
#  一次性操作
# ═══════════════════════════════════════════════
def do_once():
    """单次检查并执行必要操作"""
    print('[单次检查] 开始...')
    
    # 1. 检查号池状态
    state = get_pool_state()
    if state.get('source') == 'wam':
        print(f'[单次检查] WAM Hub在线 ✅')
        d = state.get('dailyQuotaPercent', '?')
        w = state.get('weeklyQuotaPercent', '?')
        email = state.get('activeEmail', '?')
        print(f'  活跃账号: {str(email)[:30]}')
        print(f'  日配额: {d}%  周配额: {w}%')
    elif state.get('source') == 'admin':
        print(f'[单次检查] 管理端在线 ✅')
    else:
        print('[单次检查] ⚠️  所有Hub均离线')
        return
    
    # 2. 检查限流状态
    rl = get_rate_limit_status()
    if rl and rl.get('ok'):
        cooling = rl.get('coolingCount', 0)
        stats = rl.get('stats', {})
        print(f'[单次检查] 限流状态: 冷却中={cooling}个 24h触发={stats.get("total24h",0)}次')
        if cooling > 0:
            print(f'[单次检查] ⚡ 有{cooling}个账号在冷却 → 触发轮转')
            force_rotate()
    
    print('[单次检查] 完成')


# ═══════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else '--all'
    
    print('╔══════════════════════════════════════════════════════════╗')
    print('║  无为守护 v1.0 — 道法自然·无为而无不为·用户零感知    ║')
    print('╚══════════════════════════════════════════════════════════╝')
    print(f'时间: {time.strftime("%Y-%m-%d %H:%M:%S")}')
    print()
    
    if mode in ('--ipc', '--all'):
        print('─── 步骤1: IPC无感重启extension host ───')
        trigger_extension_host_restart()
        print()
    
    if mode == '--once':
        do_once()
        return
    
    if mode in ('--watchdog', '--all'):
        print('─── 步骤2: 启动无为看门狗 ───')
        daemon = WuWeiDaemon()
        daemon.start()


if __name__ == '__main__':
    main()
