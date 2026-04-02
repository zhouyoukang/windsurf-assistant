#!/usr/bin/env python3
"""
道引擎 — 五行合一·万法归宗
==============================
金(Patch) · 木(Pool) · 水(Rotation) · 火(Guardian) · 土(Monitor)

水利万物而不争，处众人之所恶，故几于道。
上善若水任方圆，道法自然通万象。
五行结合破万难，直达道之根源也。

用法:
  python dao_engine.py             # 太极: 全五行启动(patch+status+sentinel)
  python dao_engine.py status      # 五行状态总览
  python dao_engine.py sentinel    # 配额哨兵 (长驻自动切号)
  python dao_engine.py patrol      # 单次巡逻 (供计划任务调用)
  python dao_engine.py switch      # 立即切到最佳账号
  python dao_engine.py guard       # 安装/更新守护(计划任务→patrol)
"""

import os, sys, json, time, subprocess, logging, collections
from pathlib import Path
from datetime import datetime, timezone

VERSION = '1.0.0'
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from wam_engine import (
    AccountPool, SnapshotStore, HotSwitcher,
    find_active_index, read_current_health,
    classify_account, score_account,
    VERSION as WAM_VERSION,
)

# ============================================================
# 道 · Configuration (随境而变)
# ============================================================
SENTINEL_INTERVAL = 10      # 哨兵轮询间隔(秒) — 高频感知·实时响应
QUOTA_THRESHOLD = 5         # 有效配额阈值(%) — 榨干到极限·每滴不废
DAILY_THRESHOLD = 3         # 日配额单独阈值(%) — 日额度绝对下限
SWITCH_COOLDOWN = 45        # 切号冷却(秒) — 快速响应·防振荡兼顾
DAILY_RESET_GRACE = 120     # 日重置宽限(秒) — 2分钟内重置则等待
MAX_SWITCH_RETRIES = 3      # 切号失败最大重试次数
STALE_DATA_WARN = 30        # 健康数据超过此分钟数视为过期
TTE_SWITCH_MIN = 2.0        # 预测耗尽提前量(分钟) — 预测剩余<2分钟则切
TTE_WARN_MIN = 5.0          # 预测耗尽预警(分钟)
ANTI_OSCILLATION_SEC = 600  # 反振荡窗口(秒) — 10分钟内不回切同一账号
RATELIMIT_SIGNAL_FILE = SCRIPT_DIR / '_ratelimit_signal.json'
LOG_FILE = SCRIPT_DIR / '_dao_engine.log'
GUARD_TASK_NAME = "DaoEngineGuardian"
GUARD_PYTHONW = Path(sys.executable).parent / "pythonw.exe"

# ============================================================
# 观 · Logging (知微知著)
# ============================================================
logger = logging.getLogger('dao')
logger.setLevel(logging.DEBUG)

_fh = logging.FileHandler(LOG_FILE, encoding='utf-8', delay=True)
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%m-%d %H:%M:%S'))
logger.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setLevel(logging.INFO)
_ch.setFormatter(logging.Formatter('  [%(asctime)s] %(message)s', datefmt='%H:%M:%S'))
logger.addHandler(_ch)


# ============================================================
# 玄 · VelocityTracker (预测·感知·先机)
# ============================================================
class VelocityTracker:
    """Track quota consumption velocity for predictive switching.
    Stores recent data points per account, computes time-to-exhaustion (TTE).
    道法自然·上善若水: 感知流速，预判枯竭，先机而动。"""

    def __init__(self, window_size=60):
        self.history = {}  # email -> deque of (ts, daily%, weekly%)
        self.window_size = window_size
        self._switched_from = {}  # email -> ts (anti-oscillation)

    def record(self, email, daily, weekly):
        if email not in self.history:
            self.history[email] = collections.deque(maxlen=self.window_size)
        self.history[email].append((time.time(), daily, weekly))

    def get_velocity(self, email):
        """Return (d_per_min, w_per_min). Negative = consuming."""
        pts = self.history.get(email)
        if not pts or len(pts) < 3:
            return 0.0, 0.0
        # Smoothed: use oldest vs newest over available window
        t0, d0, w0 = pts[0]
        t1, d1, w1 = pts[-1]
        dt_min = max((t1 - t0) / 60.0, 0.1)
        return (d1 - d0) / dt_min, (w1 - w0) / dt_min

    def predict_tte(self, email, daily, weekly):
        """Time-to-exhaustion in minutes. (d_tte, w_tte).
        Returns inf if not consuming or insufficient data."""
        d_rate, w_rate = self.get_velocity(email)
        d_tte = -daily / d_rate if d_rate < -0.01 else float('inf')
        w_tte = -weekly / w_rate if w_rate < -0.01 else float('inf')
        return max(0.0, d_tte), max(0.0, w_tte)

    def mark_switched_from(self, email):
        self._switched_from[email] = time.time()

    def is_recently_used(self, email):
        ts = self._switched_from.get(email, 0)
        return time.time() - ts < ANTI_OSCILLATION_SEC


def _check_ratelimit_signal():
    """Check for external rate-limit signal (written by watchdog/VSIX).
    Returns (triggered, info_dict) and clears the signal."""
    if not RATELIMIT_SIGNAL_FILE.exists():
        return False, {}
    try:
        data = json.loads(RATELIMIT_SIGNAL_FILE.read_text(encoding='utf-8'))
        age = time.time() - data.get('ts', 0)
        if age > 120:  # Signal older than 2 min = stale
            RATELIMIT_SIGNAL_FILE.unlink(missing_ok=True)
            return False, {}
        RATELIMIT_SIGNAL_FILE.unlink(missing_ok=True)
        return True, data
    except Exception:
        return False, {}


# ============================================================
# 金 · Patch (斩·改·持久化)
# ============================================================
def check_patches():
    """Verify patch status. Returns (applied, total)."""
    script = SCRIPT_DIR / "patch_continue_bypass.py"
    if not script.exists():
        return 0, 0
    try:
        r = subprocess.run(
            [sys.executable, str(script), "--verify"],
            capture_output=True, text=True, timeout=30, cwd=str(SCRIPT_DIR),
        )
        applied = sum(1 for l in r.stdout.split('\n') if '✅' in l)
        total = sum(1 for l in r.stdout.split('\n')
                    if l.strip().startswith(('✅', '❌', '⚠')))
        return applied, total
    except Exception:
        return 0, 0


def apply_patches():
    """Apply all patches via patch_continue_bypass.py. Returns ok."""
    script = SCRIPT_DIR / "patch_continue_bypass.py"
    if not script.exists():
        return False
    try:
        r = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=60, cwd=str(SCRIPT_DIR),
        )
        return r.returncode == 0
    except Exception:
        return False


# ============================================================
# 木 · Pool (生·长·号池)
# ============================================================
def pool_snapshot():
    """Return a dict summarising the entire pool state."""
    pool = AccountPool()
    pool.reload()
    store = SnapshotStore()
    active_i = find_active_index(pool)
    td, tw = pool.pool_total()

    available = switchable = 0
    buckets = {'full': 0, 'high': 0, 'mid': 0, 'low': 0, 'empty': 0}

    for a in pool.accounts:
        email = a.get('email', '')
        h = pool.get_health(a)
        eff = min(h['daily'], h['weekly'])
        if eff > QUOTA_THRESHOLD:
            available += 1
            if store.has_snapshot(email):
                switchable += 1
        if eff >= 90:
            buckets['full'] += 1
        elif eff >= 50:
            buckets['high'] += 1
        elif eff >= 20:
            buckets['mid'] += 1
        elif eff > 0:
            buckets['low'] += 1
        else:
            buckets['empty'] += 1

    active_info = {}
    if active_i >= 0:
        acc = pool.get(active_i)
        h = pool.get_health(acc)
        active_info = {
            'index': active_i + 1,
            'email': acc.get('email', '?'),
            'daily': h['daily'], 'weekly': h['weekly'],
            'plan': h['plan'], 'days_left': h['days_left'],
            'effective': min(h['daily'], h['weekly']),
        }

    return {
        'total': pool.count(), 'available': available,
        'switchable': switchable, 'harvested': store.count_harvested(),
        'pool_daily': td, 'pool_weekly': tw,
        'active': active_info, 'buckets': buckets,
    }


# ============================================================
# 水 · Rotation (流·转·自动切号)
# ============================================================
def find_best_switchable(pool, store, exclude_i=-1, velocity_tracker=None):
    """Find best account using multi-factor scoring + anti-oscillation.
    Requires snapshot AND quota > threshold.
    Returns (index, score) or (-1, -1)."""
    best_i, best_score = -1, -1
    for i, a in enumerate(pool.accounts):
        if i == exclude_i:
            continue
        email = a.get('email', '')
        if not store.has_snapshot(email):
            continue
        h = pool.get_health(a)
        eff = min(h['daily'], h['weekly'])
        if eff <= QUOTA_THRESHOLD:
            continue
        sc = score_account(h, has_snapshot=True)
        # Anti-oscillation: recently-switched-from accounts get penalized
        if velocity_tracker and velocity_tracker.is_recently_used(email):
            sc = max(0, sc - 200)
        if sc > best_score:
            best_score = sc
            best_i = i
    return best_i, best_score


def _should_switch(h, tte_d=float('inf'), tte_w=float('inf')):
    """Determine if current account needs switching.
    Hybrid: predictive TTE + absolute threshold + reset-awareness.
    Returns (should_switch: bool, reason: str)."""
    d, w = h['daily'], h['weekly']
    eff = min(d, w)
    min_tte = min(tte_d, tte_w)

    # Layer 0: Absolute floor — 已耗尽
    if d <= 2 or w <= 2:
        return True, f'FLOOR D{d}%·W{w}%'

    # Layer 1: Predictive — TTE过短，先机而动
    if min_tte < TTE_SWITCH_MIN:
        which = 'D' if tte_d < tte_w else 'W'
        return True, f'{which} exhausts in {min_tte:.1f}min (predicted)'

    # Layer 2: D exhausted but daily reset imminent — wait
    daily_reset_in = h.get('daily_reset_in_sec', 0)
    if d <= DAILY_THRESHOLD and w >= QUOTA_THRESHOLD and 0 < daily_reset_in <= DAILY_RESET_GRACE:
        return False, f'D{d}% resets in {daily_reset_in}s — waiting'

    # Layer 3: D exhausted, no imminent reset
    if d <= DAILY_THRESHOLD:
        return True, f'D{d}% exhausted (reset {daily_reset_in}s away)'

    # Layer 4: W exhausted
    if w <= QUOTA_THRESHOLD:
        return True, f'W{w}% exhausted'

    # Layer 5: Both above threshold — hold
    tte_info = f' TTE:D={tte_d:.0f}m·W={tte_w:.0f}m' if min_tte < 999 else ''
    return False, f'eff={eff}% ok{tte_info}'


def do_switch_best():
    """Switch to best available account immediately.
    Returns (ok, message)."""
    pool = AccountPool()
    pool.reload()
    store = SnapshotStore()
    active_i = find_active_index(pool)

    best_i, best_score = find_best_switchable(pool, store, exclude_i=active_i)
    if best_i < 0:
        return False, 'No switchable accounts (need snapshot + quota)'

    acc = pool.get(best_i)
    email = acc.get('email', '')
    logger.info(f'🔄 → #{best_i+1} {email[:30]} (score={best_score}%)')

    ok, steps, ms = HotSwitcher.hot_switch(email, store)
    if ok:
        logger.info(f'✅ Switched in {ms}ms')
        return True, f'#{best_i+1} {email[:30]} ({ms}ms)'
    else:
        logger.error(f'❌ Switch failed: {steps}')
        return False, f'Failed: {"; ".join(steps)}'


# ============================================================
# 火 · Guardian (护·守·自愈)
# ============================================================
def patrol():
    """Single patrol cycle: check patches + check quota + switch if needed.
    Designed for scheduled-task (guardian) invocation."""
    import os as _os
    _pid = _os.getpid()
    try:
        import psutil as _ps
        _ppid = _ps.Process(_pid).ppid()
        _pname = _ps.Process(_ppid).name()
    except Exception:
        _ppid = _os.getppid() if hasattr(_os, 'getppid') else 0
        _pname = '?'
    _appdata = _os.environ.get('APPDATA', '?')
    _parts = _appdata.replace('/', chr(92)).split(chr(92))
    _user = _parts[2] if len(_parts) > 2 else _appdata
    _argv = sys.argv[-1] if sys.argv else '?'
    # Log which login helper file will be used
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from wam_engine import _find_login_helper_json as _flhj
        _lhf = str(_flhj())
    except Exception as _e:
        _lhf = f'ERR:{_e}'
    logger.info(f'🔍 巡逻 [PID={_pid} user={_user} lhf={_lhf.split(chr(92))[-1]}@{_lhf.split(chr(92))[-3] if _lhf.count(chr(92)) >= 3 else "?"}]')

    # 金: patch integrity
    applied, total = check_patches()
    if total > 0 and applied < total:
        logger.info(f'金: {applied}/{total} — re-patching…')
        if apply_patches():
            applied, total = check_patches()
    if total > 0:
        logger.info(f'金: {applied}/{total}')

    # 水: quota check
    pool = AccountPool()
    pool.reload()
    store = SnapshotStore()

    # Strategy 0: absolute-path marker lookup (works even when V: drive inaccessible)
    active_i = -1
    _known_marker_paths = [
        SCRIPT_DIR / '_active_account.txt',
        Path(r'E:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\_active_account.txt'),
        Path(r'D:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\_active_account.txt'),
    ]
    for _mp in _known_marker_paths:
        try:
            _marker_email = _mp.read_text(encoding='utf-8').strip()
            if _marker_email:
                for _idx, _acc in enumerate(pool.accounts):
                    if _acc.get('email', '').lower() == _marker_email.lower():
                        active_i = _idx
                        break
                if active_i >= 0:
                    break
        except Exception:
            pass

    # Fallback: use wam_engine's find_active_index (strategies 1-3)
    if active_i < 0:
        active_i = find_active_index(pool)

    # Fallback: if default APPDATA context fails, reload pool from all known user paths
    if active_i < 0:
        from pathlib import Path as _P
        import json as _json
        _known_gs = [
            _P(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage'),
            _P(r'C:\Users\ai\AppData\Roaming\Windsurf\User\globalStorage'),
        ]
        for _gs in _known_gs:
            for _fname in ('windsurf-login-accounts.json',
                           r'zhouyoukang.windsurf-assistant\windsurf-login-accounts.json'):
                _lhf = _gs / _fname
                if not _lhf.exists():
                    continue
                try:
                    _data = _json.loads(_lhf.read_text(encoding='utf-8'))
                    if not isinstance(_data, list) or not _data:
                        continue
                    from wam_engine import AccountPool as _AP, find_active_index as _fai
                    _fb_pool = _AP.__new__(_AP)
                    _fb_pool.accounts = _data
                    _fb_pool.path = _lhf
                    _fb_i = _fai(_fb_pool)
                    if _fb_i >= 0:
                        pool = _fb_pool
                        active_i = _fb_i
                        logger.debug(f'Fallback: {_lhf.parent.name}/{_lhf.name} → #{_fb_i+1}')
                        break
                except Exception:
                    pass
            if active_i >= 0:
                break

    if active_i < 0:
        logger.warning('No active account')
        return

    acc = pool.get(active_i)
    h = pool.get_health(acc)
    eff = min(h['daily'], h['weekly'])
    stale = h.get('stale_min', -1)
    stale_tag = f' stale={stale}m' if stale > STALE_DATA_WARN else ''
    logger.info(f'水: #{active_i+1} {acc.get("email","?")[:25]} '
                f'D{h["daily"]}%·W{h["weekly"]}% eff={eff}%{stale_tag}')

    should, reason = _should_switch(h)
    if should:
        best_i, best_score = find_best_switchable(pool, store, exclude_i=active_i)
        if best_i >= 0:
            best_acc = pool.get(best_i)
            best_email = best_acc.get('email', '')
            logger.info(f'🔄 {reason} → #{best_i+1} {best_email[:25]} (score={best_score}%)')
            ok, steps, ms = HotSwitcher.hot_switch(best_email, store, retries=MAX_SWITCH_RETRIES)
            if ok:
                logger.info(f'✅ Auto-switched {ms}ms')
            else:
                logger.error(f'❌ Auto-switch failed: {steps}')
        else:
            logger.warning(f'⚠️ {reason} but no switchable accounts')
    else:
        logger.debug(f'Hold: {reason}')

    logger.info('🔍 巡逻完成')


def install_guardian():
    """Install/update Windows Scheduled Task that calls `dao_engine.py patrol`."""
    pythonw = GUARD_PYTHONW if GUARD_PYTHONW.exists() else Path(sys.executable)
    dao_script = SCRIPT_DIR / "dao_engine.py"
    logger.info(f'守护进程 → {pythonw}')

    task_xml = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Dao Engine Guardian — 五行合一·自动巡逻</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled></LogonTrigger>
    <TimeTrigger>
      <Repetition>
        <Interval>PT5M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>2026-01-01T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal><RunLevel>HighestAvailable</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT2M</ExecutionTimeLimit>
    <Hidden>true</Hidden>
  </Settings>
  <Actions>
    <Exec>
      <Command>{pythonw}</Command>
      <Arguments>"{dao_script}" patrol</Arguments>
      <WorkingDirectory>{SCRIPT_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>'''

    task_file = SCRIPT_DIR / "_dao_guardian_task.xml"
    task_file.write_text(task_xml, encoding='utf-16')
    r = subprocess.run(
        ["schtasks", "/Create", "/TN", GUARD_TASK_NAME, "/XML", str(task_file), "/F"],
        capture_output=True, encoding='gbk', errors='replace',
    )
    task_file.unlink(missing_ok=True)

    if r.returncode == 0:
        logger.info(f'✅ Guardian installed: {GUARD_TASK_NAME} (每5分钟+开机)')
        return True
    else:
        logger.warning(f'⚠️ schtasks: {r.stderr.strip()}')
        return False


# ============================================================
# 土 · Sentinel (恒·久·长驻哨兵)
# ============================================================
def sentinel():
    """Predictive sentinel daemon — 先机而动·无感轮转:
    - VelocityTracker: 消耗速率追踪 → 预测耗尽时间(TTE)
    - TTE < 2min: 提前切号，用户永远不触碰限流墙
    - Rate-limit signal: 外部信号即时响应，跳过冷却
    - Anti-oscillation: 10分钟内不回切同一账号
    道法自然·上善若水: 感知流速，预判枯竭，先机而动。"""
    logger.info(f'哨兵启动 interval={SENTINEL_INTERVAL}s threshold={QUOTA_THRESHOLD}% '
                f'TTE<{TTE_SWITCH_MIN}min→切 cooldown={SWITCH_COOLDOWN}s')
    last_switch_ts = 0
    last_active_email = ''
    vt = VelocityTracker()
    tick = 0

    while True:
        try:
            # ── Layer 0: Check rate-limit signal (instant, bypass cooldown) ──
            rl_triggered, rl_info = _check_ratelimit_signal()
            if rl_triggered:
                logger.warning(f'⚡ Rate limit signal: {rl_info.get("model", "?")} '
                              f'{rl_info.get("error", "")[:60]}')
                pool = AccountPool()
                pool.reload()
                store = SnapshotStore()
                active_i = find_active_index(pool)
                if active_i >= 0:
                    cur_email = pool.get(active_i).get('email', '')
                    vt.mark_switched_from(cur_email)
                    best_i, best_score = find_best_switchable(
                        pool, store, exclude_i=active_i, velocity_tracker=vt)
                    if best_i >= 0:
                        best_email = pool.get(best_i).get('email', '')
                        logger.info(f'⚡ INSTANT → #{best_i+1} {best_email[:20]} '
                                   f'(score={best_score})')
                        ok, steps, ms = HotSwitcher.hot_switch(
                            best_email, store, retries=MAX_SWITCH_RETRIES)
                        last_switch_ts = time.time()
                        if ok:
                            logger.info(f'✅ Instant-switched {ms}ms')
                            last_active_email = best_email
                        else:
                            logger.error(f'❌ Instant-switch failed: {steps}')
                    else:
                        logger.warning('⚡ Rate limit signal but no switchable accounts')

            # ── Layer 1: Normal predictive patrol ──
            pool = AccountPool()
            pool.reload()
            store = SnapshotStore()
            active_i = find_active_index(pool)

            if active_i < 0:
                time.sleep(SENTINEL_INTERVAL)
                continue

            acc = pool.get(active_i)
            email = acc.get('email', '?')
            h = pool.get_health(acc)

            # Record velocity data point
            vt.record(email, h['daily'], h['weekly'])
            tte_d, tte_w = vt.predict_tte(email, h['daily'], h['weekly'])
            d_rate, w_rate = vt.get_velocity(email)

            # Log on account change
            if email != last_active_email:
                logger.info(f'👁 Active: #{active_i+1} {email[:30]} '
                            f'D{h["daily"]}%·W{h["weekly"]}% [{h["plan"]}]')
                last_active_email = email
                tick = 0

            # Periodic telemetry (every ~60s)
            tick += 1
            if tick % 6 == 0:
                min_tte = min(tte_d, tte_w)
                tte_tag = f' TTE:D={tte_d:.0f}m·W={tte_w:.0f}m' if min_tte < 999 else ''
                rate_tag = (f' vel:D{d_rate:+.2f}/m·W{w_rate:+.2f}/m'
                           if abs(d_rate) > 0.01 or abs(w_rate) > 0.01 else '')
                logger.debug(f'📊 #{active_i+1} D{h["daily"]}%·W{h["weekly"]}%'
                            f'{tte_tag}{rate_tag}')

            # Decision: should we switch?
            should, reason = _should_switch(h, tte_d, tte_w)
            if should:
                now = time.time()
                if now - last_switch_ts < SWITCH_COOLDOWN:
                    cd = int(SWITCH_COOLDOWN - (now - last_switch_ts))
                    logger.debug(f'Cooldown {cd}s ({reason})')
                    time.sleep(SENTINEL_INTERVAL)
                    continue

                vt.mark_switched_from(email)
                best_i, best_score = find_best_switchable(
                    pool, store, exclude_i=active_i, velocity_tracker=vt)

                if best_i < 0:
                    logger.warning(f'⚠️ {reason}, no switchable accounts')
                    time.sleep(SENTINEL_INTERVAL * 3)
                    continue

                best_acc = pool.get(best_i)
                best_email = best_acc.get('email', '')
                best_h = pool.get_health(best_acc)
                logger.info(f'🔄 {reason} → #{best_i+1} '
                            f'{best_email[:20]} D{best_h["daily"]}%·W{best_h["weekly"]}% '
                            f'(score={best_score})')

                ok, steps, ms = HotSwitcher.hot_switch(
                    best_email, store, retries=MAX_SWITCH_RETRIES)
                last_switch_ts = time.time()
                tick = 0
                if ok:
                    logger.info(f'✅ Switched {ms}ms')
                    last_active_email = best_email
                else:
                    logger.error(f'❌ Failed: {steps}')

        except KeyboardInterrupt:
            logger.info('哨兵停止')
            break
        except Exception as e:
            logger.error(f'Sentinel err: {e}')

        time.sleep(SENTINEL_INTERVAL)


# ============================================================
# 五行状态
# ============================================================
def full_status():
    """Five-element status report with predictive engine info."""
    print('=' * 60)
    print('道引擎 · 五行状态 · v' + VERSION + ' (预测引擎)')
    print(f'  poll={SENTINEL_INTERVAL}s threshold={QUOTA_THRESHOLD}% '
          f'TTE<{TTE_SWITCH_MIN}min→切 cooldown={SWITCH_COOLDOWN}s')
    print('=' * 60)

    # 金
    applied, total = check_patches()
    ok = applied == total and total > 0
    print(f'\n{"[OK]" if ok else "[!!]"} Jin Patch: {applied}/{total}')

    # 木
    ps = pool_snapshot()
    bk = ps['buckets']
    print(f'{"[OK]" if ps["switchable"]>0 else "[!!]"} Mu Pool: '
          f'{ps["total"]} total, {ps["available"]} avail, '
          f'{ps["switchable"]} switchable, {ps["harvested"]} snaps')
    print(f'     buckets: full={bk["full"]} high={bk["high"]} '
          f'mid={bk["mid"]} low={bk["low"]} empty={bk["empty"]}')
    print(f'     capacity: D{ps["pool_daily"]}% W{ps["pool_weekly"]}%')

    # 水
    a = ps.get('active', {})
    if a:
        eff = a.get('effective', 0)
        icon = '[OK]' if eff > QUOTA_THRESHOLD else '[low]' if eff > 0 else '[!!]'
        print(f'{icon} Shui Active: #{a["index"]} {a["email"][:30]} '
              f'[{a["plan"]}] D{a["daily"]}%-W{a["weekly"]}% '
              f'{a["days_left"]}d left')
    else:
        print('[!!] Shui Active: none detected')

    # 玄 (predictive engine status)
    signal_pending = RATELIMIT_SIGNAL_FILE.exists()
    print(f'{"[SIG]" if signal_pending else "[-]"} Xuan Predict: '
          f'TTE<{TTE_SWITCH_MIN}min anti-osc={ANTI_OSCILLATION_SEC}s '
          f'signal={"PENDING" if signal_pending else "clear"}')

    # 火
    try:
        r = subprocess.run(
            ['schtasks', '/Query', '/TN', GUARD_TASK_NAME, '/FO', 'LIST'],
            capture_output=True, encoding='gbk', errors='replace', timeout=10,
        )
        if r.returncode == 0:
            info_lines = [l.strip() for l in (r.stdout or '').split('\n')
                          if any(k in l for k in ('下次运行', 'Next Run', '状态', 'Status'))]
            print(f'[OK] Huo Guardian: {"; ".join(info_lines[:2]) or "installed"}')
        else:
            print('[!!] Huo Guardian: not installed (run: dao_engine.py guard)')
    except Exception:
        print('[?] Huo Guardian: check failed')

    # 土
    if LOG_FILE.exists():
        try:
            lines = LOG_FILE.read_text(encoding='utf-8').strip().split('\n')
            switches = sum(1 for l in lines if 'Switch' in l or 'switch' in l)
            last = lines[-1][:70] if lines else '-'
            try:
                print(f'[OK] Tu Log: {len(lines)} entries, {switches} switches')
                print(f'     Last: {last}')
            except UnicodeEncodeError:
                print(f'[OK] Tu Log: {len(lines)} entries, {switches} switches')
        except Exception:
            print('[OK] Tu Log: exists')
    else:
        print('[-] Tu Log: not started')

    print(f'\n{"="*60}')


# ============================================================
# 太极 · 全五行启动
# ============================================================
def taiji():
    """Full five-element startup: patch → status → sentinel daemon."""
    print('=' * 60)
    print('道引擎 · 五行合一 · 万法归宗')
    print('水利万物而不争 上善若水任方圆')
    print('=' * 60)

    # 金
    applied, total = check_patches()
    if total > 0 and applied < total:
        logger.info(f'金: {applied}/{total} — patching…')
        apply_patches()
        applied, total = check_patches()
    logger.info(f'金: Patch {applied}/{total}')

    # 木
    ps = pool_snapshot()
    logger.info(f'木: {ps["total"]} accounts, {ps["switchable"]} switchable')

    # 水
    a = ps.get('active', {})
    if a:
        logger.info(f'水: #{a["index"]} {a["email"][:30]} '
                    f'D{a["daily"]}%·W{a["weekly"]}% [{a["plan"]}]')

    # 火
    install_guardian()

    # 土: sentinel
    logger.info(f'土: 哨兵启动 (Ctrl+C stop)')
    print()
    sentinel()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'status':
        full_status()
    elif cmd == 'sentinel':
        sentinel()
    elif cmd == 'patrol':
        patrol()
    elif cmd == 'switch':
        ok, msg = do_switch_best()
        print(f'  {"✅" if ok else "❌"} {msg}')
    elif cmd == 'guard':
        install_guardian()
    elif cmd == 'signal':
        signal_ratelimit()
    elif cmd == 'daemon':
        daemon()
    elif cmd in ('', 'taiji'):
        taiji()
    else:
        print(f'道引擎 v{VERSION}')
        print(f'  [taiji]   太极: patch+status+guardian+sentinel')
        print(f'  status    五行状态')
        print(f'  sentinel  配额哨兵(长驻)')
        print(f'  daemon    后台运行哨兵(无控制台)')
        print(f'  patrol    单次巡逻(计划任务用)')
        print(f'  switch    立即切到最佳账号')
        print(f'  signal    发送限额信号(立即切换)')
        print(f'  guard     安装/更新守护任务')


if __name__ == '__main__':
    main()
