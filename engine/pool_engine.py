#!/usr/bin/env python3
"""
Pool Engine v1.0 — 综合号池机 · 多账号同时实时在线
====================================================
道生一(所有apiKey) → 一生二(实时监控+路由) → 二生三(无限请求) → 三生万物(用户无感)

所有账号同时实时登录，实时检测所有数据，实时路由最优账号。

Architecture:
  MultiAccountPool     — Load ALL accounts + apiKeys from snapshots
  HealthMonitor        — Concurrent real-time health tracking
  ModelRateLimitTracker — Per-account per-model rate limit windows
  SmartRouter          — Model-aware optimal account selection
  ConsumptionTracker   — Per-account velocity + TTE prediction
  HTTP Dashboard       — Real-time monitoring + API (:19877)

Usage:
  python pool_engine.py                # Start engine + dashboard
  python pool_engine.py status         # Full pool status
  python pool_engine.py pick <model>   # Pick best account for model
  python pool_engine.py dashboard      # Open dashboard in browser
"""

import os, sys, json, time, threading, collections, sqlite3, base64, re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

VERSION = '1.0.1'
SCRIPT_DIR = Path(__file__).parent
ENGINE_PORT = 19877

# Hot-patch key file (read by patched extension.js per-request via process.env.APPDATA dynamic path)
POOL_KEY_FILE = Path(os.environ.get('APPDATA', '')) / 'Windsurf' / '_pool_apikey.txt'
# v2.0 fix: Only write to CURRENT user's pool key file.
# Do NOT write to other users — each user's Windsurf reads its own _pool_apikey.txt via
# process.env.APPDATA (dynamic path in hot_patch v2.0). Cross-user writing was the root cause
# of account switching failure for other Windows users.
_ALL_POOL_KEY_FILES = [POOL_KEY_FILE]

# Import WAM components
sys.path.insert(0, str(SCRIPT_DIR))
from wam_engine import (
    AccountPool, SnapshotStore, HotSwitcher,
    find_active_index, read_current_health,
    classify_account, score_account,
    QUOTA_EXHAUSTED, QUOTA_URGENT,
)

# ============================================================
# Per-model rate limit windows (实测值, ms)
# ============================================================
MODEL_RATE_WINDOWS = {
    'claude-opus-4-6':             2400,   # ~40min
    'claude-opus-4.6':             2400,
    'claude-opus-4-5':             2400,
    'claude-opus-4-6-thinking-1m': 1400,   # ~22min
    'claude-opus-4-6-thinking':    1560,   # ~26min
    'claude-sonnet-4-6':            900,   # ~15min
    'claude-sonnet-4-5':            900,
    'claude-sonnet-4':              900,
    'gpt-4.1':                      300,   # ~5min (estimated)
    'gpt-5.4':                      300,
    'default':                     2400,
}

# Model UID → display name mapping (from windsurfConfigurations)
MODEL_DISPLAY = {
    'MODEL_CLAUDE_4_5_OPUS': 'Claude 4.5 Opus',
    'MODEL_CLAUDE_4_SONNET': 'Claude 4 Sonnet',
    'MODEL_CLAUDE_4_5_SONNET': 'Claude 4.5 Sonnet',
    'MODEL_SWE_1_5': 'SWE-1.5',
    'MODEL_CHAT_GPT_4_1_2025_04_14': 'GPT-4.1',
    'MODEL_CHAT_11121': 'Windsurf Fast',
}

# ACU multipliers per model
MODEL_ACU = {
    'Claude 4.5 Opus': 3.0,
    'Claude 4 Sonnet': 1.5,
    'Claude 4.5 Sonnet': 1.5,
    'SWE-1.5': 0,
    'SWE-1.5 Fast': 0.5,
    'GPT-4.1': 1.0,
    'Windsurf Fast': 0.5,
    'Grok-3': 1.0,
}


# ============================================================
# AccountState — Real-time state for a single account
# ============================================================
class AccountState:
    """Complete real-time state for one account."""
    __slots__ = (
        'index', 'email', 'api_key', 'has_snapshot',
        'daily', 'weekly', 'plan', 'days_left',
        'daily_reset_in', 'weekly_reset_in',
        'stale_min', 'last_updated',
        'velocity_d', 'velocity_w',
        'tte_d', 'tte_w',
        'model_rate_limits',
        'request_count', 'total_acu', 'errors',
        'is_active', 'score', 'status',
        '_history',
    )

    def __init__(self, index, email, api_key=None, has_snapshot=False):
        self.index = index
        self.email = email
        self.api_key = api_key
        self.has_snapshot = has_snapshot
        self.daily = 100.0
        self.weekly = 100.0
        self.plan = 'Unknown'
        self.days_left = 0.0
        self.daily_reset_in = 0
        self.weekly_reset_in = 0
        self.stale_min = -1
        self.last_updated = 0.0
        self.velocity_d = 0.0
        self.velocity_w = 0.0
        self.tte_d = float('inf')
        self.tte_w = float('inf')
        self.model_rate_limits = {}  # model_key -> unblock_timestamp
        self.request_count = 0
        self.total_acu = 0.0
        self.errors = 0
        self.is_active = False
        self.score = 0
        self.status = 'unknown'
        self._history = collections.deque(maxlen=120)  # (ts, daily, weekly)

    def update_health(self, daily, weekly, plan, days_left,
                      daily_reset_in=0, weekly_reset_in=0, stale_min=-1):
        """Update health from Login Helper data."""
        self.daily = daily
        self.weekly = weekly
        self.plan = plan
        self.days_left = days_left
        self.daily_reset_in = daily_reset_in
        self.weekly_reset_in = weekly_reset_in
        self.stale_min = stale_min
        self.last_updated = time.time()
        self._history.append((time.time(), daily, weekly))
        self._compute_velocity()
        self._compute_score()

    def _compute_velocity(self):
        """Compute consumption velocity from history."""
        pts = self._history
        if len(pts) < 3:
            self.velocity_d = 0.0
            self.velocity_w = 0.0
            self.tte_d = float('inf')
            self.tte_w = float('inf')
            return
        t0, d0, w0 = pts[0]
        t1, d1, w1 = pts[-1]
        dt_min = max((t1 - t0) / 60.0, 0.1)
        self.velocity_d = (d1 - d0) / dt_min
        self.velocity_w = (w1 - w0) / dt_min
        self.tte_d = -self.daily / self.velocity_d if self.velocity_d < -0.01 else float('inf')
        self.tte_w = -self.weekly / self.velocity_w if self.velocity_w < -0.01 else float('inf')
        self.tte_d = max(0.0, self.tte_d)
        self.tte_w = max(0.0, self.tte_w)

    def _compute_score(self):
        """Multi-factor score. Higher = better."""
        self.status, _ = classify_account(
            {'daily': self.daily, 'weekly': self.weekly,
             'days_left': self.days_left, 'stale_min': self.stale_min},
            self.has_snapshot)
        self.score = score_account(
            {'daily': self.daily, 'weekly': self.weekly,
             'days_left': self.days_left, 'stale_min': self.stale_min},
            self.has_snapshot)

    @property
    def effective(self):
        return min(self.daily, self.weekly)

    @property
    def min_tte(self):
        return min(self.tte_d, self.tte_w)

    def is_model_rate_limited(self, model_key):
        """Check if this account is rate-limited for a specific model."""
        unblock = self.model_rate_limits.get(model_key, 0)
        return time.time() < unblock

    def mark_model_rate_limited(self, model_key, duration_sec=None):
        """Mark this account as rate-limited for a model."""
        if duration_sec is None:
            duration_sec = MODEL_RATE_WINDOWS.get(model_key,
                           MODEL_RATE_WINDOWS['default'])
        self.model_rate_limits[model_key] = time.time() + duration_sec
        self.errors += 1

    def available_for_model(self, model_key):
        """Can this account serve a request for this model right now?"""
        if self.effective <= QUOTA_EXHAUSTED:
            return False
        if not self.has_snapshot:
            return False
        if self.is_model_rate_limited(model_key):
            return False
        return True

    def to_dict(self):
        """Serialize for API/dashboard."""
        now = time.time()
        active_rl = {k: round(v - now) for k, v in self.model_rate_limits.items()
                     if v > now}
        return {
            'index': self.index,
            'email': self.email,
            'has_snapshot': self.has_snapshot,
            'daily': self.daily,
            'weekly': self.weekly,
            'effective': self.effective,
            'plan': self.plan,
            'days_left': self.days_left,
            'daily_reset_in': self.daily_reset_in,
            'weekly_reset_in': self.weekly_reset_in,
            'velocity_d': round(self.velocity_d, 3),
            'velocity_w': round(self.velocity_w, 3),
            'tte_d': round(self.tte_d, 1) if self.tte_d < 9999 else None,
            'tte_w': round(self.tte_w, 1) if self.tte_w < 9999 else None,
            'min_tte': round(self.min_tte, 1) if self.min_tte < 9999 else None,
            'model_rate_limits': active_rl,
            'request_count': self.request_count,
            'total_acu': round(self.total_acu, 2),
            'errors': self.errors,
            'is_active': self.is_active,
            'score': self.score,
            'status': self.status,
            'age_sec': round(now - self.last_updated) if self.last_updated else -1,
        }


# ============================================================
# PoolEngine — 综合号池机核心
# ============================================================
class PoolEngine:
    """Multi-account pool with real-time monitoring and smart routing."""

    def __init__(self):
        self.accounts = {}  # email -> AccountState
        self.lock = threading.Lock()
        self._pool = AccountPool()
        self._store = SnapshotStore()
        self._active_email = ''
        self._switch_history = []
        self._boot_time = time.time()
        self.reload()

    def reload(self):
        """Reload all accounts from Login Helper + WAM snapshots."""
        self._pool.reload()
        with self.lock:
            active_i = find_active_index(self._pool)
            for i, a in enumerate(self._pool.accounts):
                email = a.get('email', '')
                if not email:
                    continue
                h = self._pool.get_health(a)
                has_snap = self._store.has_snapshot(email)

                if email not in self.accounts:
                    # Get apiKey from snapshot
                    snap = self._store.get_snapshot(email)
                    api_key = None
                    if snap and 'blobs' in snap:
                        try:
                            auth_json = json.loads(snap['blobs'].get('windsurfAuthStatus', '{}'))
                            api_key = auth_json.get('apiKey')
                        except:
                            pass
                    self.accounts[email] = AccountState(
                        index=i + 1, email=email,
                        api_key=api_key, has_snapshot=has_snap)

                state = self.accounts[email]
                state.index = i + 1
                state.has_snapshot = has_snap
                state.is_active = (i == active_i)
                if state.is_active:
                    self._active_email = email
                state.update_health(
                    daily=h['daily'], weekly=h['weekly'],
                    plan=h['plan'], days_left=h['days_left'],
                    daily_reset_in=h.get('daily_reset_in_sec', 0),
                    weekly_reset_in=h.get('weekly_reset_in_sec', 0),
                    stale_min=h.get('stale_min', -1))

    # ── Smart Router ──

    def pick_best(self, model_key=None):
        """Pick the best account for a given model.
        Returns AccountState or None."""
        with self.lock:
            candidates = []
            for state in self.accounts.values():
                if not state.api_key:  # skip accounts with no valid API key
                    continue
                if model_key and not state.available_for_model(model_key):
                    continue
                if not model_key and state.effective <= QUOTA_EXHAUSTED:
                    continue
                if not state.has_snapshot:
                    continue
                candidates.append(state)

            if not candidates:
                return None

            # Sort: score desc, but penalize active (spread load)
            candidates.sort(key=lambda s: (
                -s.score + (50 if s.is_active else 0),
            ))
            return candidates[0]

    def pick_best_for_switch(self, exclude_email=None, model_key=None):
        """Pick best account for hot-switching (excludes current)."""
        with self.lock:
            candidates = []
            for state in self.accounts.values():
                if state.email == exclude_email:
                    continue
                if model_key and not state.available_for_model(model_key):
                    continue
                if not model_key and state.effective <= QUOTA_EXHAUSTED:
                    continue
                if not state.has_snapshot:
                    continue
                candidates.append(state)

            if not candidates:
                return None
            candidates.sort(key=lambda s: -s.score)
            return candidates[0]

    def do_switch(self, target_email):
        """Execute hot-switch to target account."""
        ok, steps, ms = HotSwitcher.hot_switch(target_email, self._store)
        record = {
            'target': target_email, 'ok': ok, 'steps': steps,
            'ms': ms, 'time': datetime.now().strftime('%H:%M:%S'),
            'from': self._active_email,
        }
        self._switch_history.append(record)
        if ok:
            with self.lock:
                for s in self.accounts.values():
                    s.is_active = (s.email == target_email)
                self._active_email = target_email
        return record

    def report_rate_limit(self, email, model_key, duration_sec=None):
        """External report: account hit rate limit on model."""
        with self.lock:
            state = self.accounts.get(email)
            if state:
                state.mark_model_rate_limited(model_key, duration_sec)
                return True
        return False

    def report_request(self, email, model_key, acu_cost=0):
        """Track a completed request."""
        with self.lock:
            state = self.accounts.get(email)
            if state:
                state.request_count += 1
                state.total_acu += acu_cost

    # ── Status ──

    def get_pool_status(self):
        """Full pool status for dashboard."""
        with self.lock:
            total = len(self.accounts)
            available = sum(1 for s in self.accounts.values()
                           if s.effective > QUOTA_URGENT and s.has_snapshot)
            exhausted = sum(1 for s in self.accounts.values()
                           if s.effective <= QUOTA_EXHAUSTED)
            urgent = sum(1 for s in self.accounts.values()
                         if QUOTA_EXHAUSTED < s.effective <= QUOTA_URGENT)
            harvested = sum(1 for s in self.accounts.values() if s.has_snapshot)
            has_key = sum(1 for s in self.accounts.values() if s.api_key)

            td = sum(s.daily for s in self.accounts.values())
            tw = sum(s.weekly for s in self.accounts.values())
            total_requests = sum(s.request_count for s in self.accounts.values())
            total_acu = sum(s.total_acu for s in self.accounts.values())
            total_errors = sum(s.errors for s in self.accounts.values())

            # Per-model rate limit summary
            model_rl = {}
            now = time.time()
            for s in self.accounts.values():
                for mk, unblock in s.model_rate_limits.items():
                    if unblock > now:
                        model_rl.setdefault(mk, 0)
                        model_rl[mk] += 1

            # Active account
            active = None
            for s in self.accounts.values():
                if s.is_active:
                    active = s.to_dict()
                    break

            return {
                'ok': True,
                'version': VERSION,
                'uptime_sec': round(time.time() - self._boot_time),
                'pool': {
                    'total': total,
                    'available': available,
                    'exhausted': exhausted,
                    'urgent': urgent,
                    'harvested': harvested,
                    'has_api_key': has_key,
                    'total_daily': round(td),
                    'total_weekly': round(tw),
                },
                'stats': {
                    'total_requests': total_requests,
                    'total_acu': round(total_acu, 2),
                    'total_errors': total_errors,
                    'switches': len(self._switch_history),
                },
                'model_rate_limits': model_rl,
                'active': active,
            }

    def get_all_accounts(self):
        """All accounts sorted by score."""
        with self.lock:
            accs = [s.to_dict() for s in self.accounts.values()]
        accs.sort(key=lambda a: (
            0 if a['is_active'] else 1,
            -a['score'],
        ))
        return accs

    def get_model_availability(self):
        """For each known model, which accounts can serve it."""
        models = {}
        model_keys = list(MODEL_RATE_WINDOWS.keys())
        model_keys.remove('default')
        with self.lock:
            for mk in model_keys:
                avail = []
                blocked = []
                for s in self.accounts.values():
                    if not s.has_snapshot or s.effective <= QUOTA_EXHAUSTED:
                        continue
                    if s.is_model_rate_limited(mk):
                        blocked.append(s.email)
                    else:
                        avail.append(s.email)
                models[mk] = {
                    'available': len(avail),
                    'blocked': len(blocked),
                    'total': len(avail) + len(blocked),
                    'best': avail[0] if avail else None,
                    'window_sec': MODEL_RATE_WINDOWS.get(mk, MODEL_RATE_WINDOWS['default']),
                }
        return models


# ============================================================
# Health Monitor — Background thread polling all accounts
# ============================================================
class HealthMonitor(threading.Thread):
    """Periodically reload all account health from Login Helper."""

    def __init__(self, engine, interval=10):
        super().__init__(daemon=True, name='HealthMonitor')
        self.engine = engine
        self.interval = interval
        self.running = True

    def run(self):
        while self.running:
            try:
                self.engine.reload()
            except Exception as e:
                print(f'[HealthMonitor] Error: {e}')
            time.sleep(self.interval)

    def stop(self):
        self.running = False


# ============================================================
# Auto-Switch Guardian — Watches active account, switches when needed
# ============================================================
class AutoSwitchGuardian(threading.Thread):
    """Background guardian that auto-switches when active account is depleted."""

    def __init__(self, engine, interval=10, threshold=5, tte_min=2.0, cooldown=45):
        super().__init__(daemon=True, name='AutoSwitchGuardian')
        self.engine = engine
        self.interval = interval
        self.threshold = threshold
        self.tte_min = tte_min
        self.cooldown = cooldown
        self.running = True
        self._last_switch = 0

    def run(self):
        while self.running:
            try:
                self._check()
            except Exception as e:
                print(f'[Guardian] Error: {e}')
            time.sleep(self.interval)

    def _check(self):
        eng = self.engine
        with eng.lock:
            active = None
            for s in eng.accounts.values():
                if s.is_active:
                    active = s
                    break
        if not active:
            return

        should_switch = False
        reason = ''

        if active.daily <= 2 or active.weekly <= 2:
            should_switch = True
            reason = f'FLOOR D{active.daily}%·W{active.weekly}%'
        elif active.min_tte < self.tte_min:
            should_switch = True
            which = 'D' if active.tte_d < active.tte_w else 'W'
            reason = f'{which} exhausts in {active.min_tte:.1f}min'
        elif active.effective <= self.threshold:
            should_switch = True
            reason = f'eff={active.effective}% below {self.threshold}%'

        if should_switch:
            now = time.time()
            if now - self._last_switch < self.cooldown:
                return
            best = eng.pick_best_for_switch(exclude_email=active.email)
            if best:
                print(f'[Guardian] {reason} → #{best.index} {best.email[:25]} '
                      f'(score={best.score})')
                result = eng.do_switch(best.email)
                self._last_switch = time.time()
                if result['ok']:
                    print(f'[Guardian] ✅ Switched {result["ms"]}ms')
                else:
                    print(f'[Guardian] ❌ Failed')

    def stop(self):
        self.running = False


# ============================================================
# HTTP API + Dashboard
# ============================================================
_engine = None  # Global reference for handler

class PoolHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._cors()
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

    def _body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length <= 0: return {}
        try: return json.loads(self.rfile.read(length))
        except: return {}

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        qs = parse_qs(urlparse(self.path).query)

        if path in ('/', '/dashboard'):
            return self._html(DASHBOARD_HTML)
        if path == '/api/health':
            return self._json({'ok': True, 'version': VERSION})
        if path == '/api/status':
            return self._json(_engine.get_pool_status())
        if path == '/api/accounts':
            return self._json({'ok': True, 'accounts': _engine.get_all_accounts()})
        if path == '/api/models':
            return self._json({'ok': True, 'models': _engine.get_model_availability()})
        if path == '/api/pick':
            model = qs.get('model', [None])[0]
            best = _engine.pick_best(model_key=model)
            if best:
                return self._json({'ok': True, 'account': best.to_dict(),
                                   'api_key_preview': (best.api_key or '')[:30] + '...'})
            return self._json({'ok': False, 'error': 'no available account'})
        if path == '/api/history':
            return self._json({'ok': True, 'history': _engine._switch_history[-50:]})
        self._json({'ok': False, 'error': 'not found'}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()

        if path == '/api/switch':
            email = body.get('email', '')
            if not email:
                best = _engine.pick_best_for_switch(
                    exclude_email=_engine._active_email,
                    model_key=body.get('model'))
                if not best:
                    return self._json({'ok': False, 'error': 'no candidate'})
                email = best.email
            return self._json(_engine.do_switch(email))

        if path == '/api/rate-limit':
            email = body.get('email', _engine._active_email)
            model = body.get('model', 'default')
            duration = body.get('duration_sec')
            ok = _engine.report_rate_limit(email, model, duration)
            # Also write signal file for dao_engine sentinel
            try:
                sf = SCRIPT_DIR / '_ratelimit_signal.json'
                sf.write_text(json.dumps({
                    'ts': time.time(), 'model': model,
                    'email': email, 'source': 'pool_engine',
                }), encoding='utf-8')
            except: pass
            return self._json({'ok': ok, 'action': 'rate_limit_recorded'})

        if path == '/api/request-done':
            email = body.get('email', _engine._active_email)
            model = body.get('model', '')
            acu = body.get('acu', 0)
            _engine.report_request(email, model, acu)
            return self._json({'ok': True})

        if path == '/api/reload':
            _engine.reload()
            return self._json({'ok': True, 'count': len(_engine.accounts)})

        self._json({'ok': False, 'error': 'not found'}, 404)


# ============================================================
# Dashboard HTML
# ============================================================
DASHBOARD_HTML = '''<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>Pool Engine · 综合号池机</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;padding:16px}
h1{color:#58a6ff;font-size:1.4em;margin-bottom:8px}
.stats{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}
.stat{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 16px;min-width:120px}
.stat .val{font-size:1.8em;font-weight:700;color:#58a6ff}
.stat .lbl{font-size:.75em;color:#8b949e;margin-top:2px}
.stat.warn .val{color:#d29922}
.stat.err .val{color:#f85149}
.stat.ok .val{color:#3fb950}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:.85em}
th{background:#161b22;color:#8b949e;text-align:left;padding:8px 10px;border-bottom:2px solid #30363d;position:sticky;top:0}
td{padding:6px 10px;border-bottom:1px solid #21262d}
tr:hover{background:#161b22}
tr.active{background:#1a2233;border-left:3px solid #58a6ff}
.bar{height:6px;border-radius:3px;background:#21262d;min-width:60px;display:inline-block;vertical-align:middle}
.bar-fill{height:100%;border-radius:3px}
.bg-ok{background:#3fb950}.bg-warn{background:#d29922}.bg-err{background:#f85149}.bg-info{background:#58a6ff}
.pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:.75em;font-weight:600}
.p-available{background:#1a3d25;color:#3fb950}
.p-urgent{background:#3d2a1a;color:#d29922}
.p-exhausted{background:#3d1a1a;color:#f85149}
.p-stale{background:#1a2a3d;color:#58a6ff}
.rl{display:inline-block;background:#3d1a2a;color:#f85149;padding:1px 6px;border-radius:4px;font-size:.7em;margin:1px}
.model-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;margin:12px 0}
.model-card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:10px}
.model-card h3{font-size:.9em;color:#c9d1d9;margin-bottom:4px}
.model-card .avail{font-size:1.4em;font-weight:700;color:#3fb950}
.refresh{color:#8b949e;font-size:.75em;margin:4px 0}
#error{color:#f85149;margin:8px 0}
</style>
</head><body>
<h1>⚡ Pool Engine · 综合号池机 v''' + VERSION + '''</h1>
<div id="error"></div>
<div class="refresh" id="refresh">Loading...</div>

<div class="stats" id="stats"></div>

<h2 style="color:#8b949e;font-size:1em;margin-top:16px">Model Availability</h2>
<div class="model-grid" id="models"></div>

<h2 style="color:#8b949e;font-size:1em;margin-top:16px">All Accounts (real-time)</h2>
<table>
<thead><tr>
<th>#</th><th>Email</th><th>Plan</th><th>Daily</th><th>Weekly</th>
<th>Score</th><th>TTE</th><th>Velocity</th><th>Rate Limits</th><th>Status</th>
</tr></thead>
<tbody id="tbody"></tbody>
</table>

<script>
const API = '';
function bar(pct, w) {
  const c = pct > 60 ? 'bg-ok' : pct > 20 ? 'bg-warn' : 'bg-err';
  return `<div class="bar" style="width:${w||60}px"><div class="bar-fill ${c}" style="width:${Math.max(1,pct)}%"></div></div> ${pct}%`;
}
function pill(status) {
  const m = {available:'p-available',low:'p-available',urgent:'p-urgent',
             exhausted:'p-exhausted',stale:'p-stale',no_snapshot:'p-stale'};
  return `<span class="pill ${m[status]||''}">${status}</span>`;
}
async function refresh() {
  try {
    const [sr, ar, mr] = await Promise.all([
      fetch(API+'/api/status').then(r=>r.json()),
      fetch(API+'/api/accounts').then(r=>r.json()),
      fetch(API+'/api/models').then(r=>r.json()),
    ]);
    document.getElementById('error').textContent = '';
    const p = sr.pool, st = sr.stats;
    document.getElementById('stats').innerHTML = `
      <div class="stat ok"><div class="val">${p.total}</div><div class="lbl">Total Accounts</div></div>
      <div class="stat ok"><div class="val">${p.available}</div><div class="lbl">Available</div></div>
      <div class="stat ${p.exhausted?'err':'ok'}"><div class="val">${p.exhausted}</div><div class="lbl">Exhausted</div></div>
      <div class="stat ${p.urgent?'warn':'ok'}"><div class="val">${p.urgent}</div><div class="lbl">Urgent</div></div>
      <div class="stat"><div class="val">D${p.total_daily}%</div><div class="lbl">Pool Daily</div></div>
      <div class="stat"><div class="val">W${p.total_weekly}%</div><div class="lbl">Pool Weekly</div></div>
      <div class="stat"><div class="val">${p.has_api_key}</div><div class="lbl">With API Key</div></div>
      <div class="stat"><div class="val">${st.switches}</div><div class="lbl">Switches</div></div>
      <div class="stat"><div class="val">${sr.uptime_sec}s</div><div class="lbl">Uptime</div></div>
    `;
    // Models
    const models = mr.models || {};
    document.getElementById('models').innerHTML = Object.entries(models).map(([k,v]) =>
      `<div class="model-card"><h3>${k}</h3>
       <div class="avail">${v.available}</div>
       <div style="font-size:.75em;color:#8b949e">${v.blocked} blocked · ${v.window_sec}s window</div></div>`
    ).join('');
    // Accounts table
    const accs = ar.accounts || [];
    document.getElementById('tbody').innerHTML = accs.map(a => {
      const rl = Object.entries(a.model_rate_limits||{}).map(([m,s])=>
        `<span class="rl">${m} ${s}s</span>`).join(' ');
      const tte = a.min_tte != null ? `${a.min_tte}m` : '∞';
      const vel = (a.velocity_d||a.velocity_w) ?
        `D${a.velocity_d>0?'+':''}${a.velocity_d}/m W${a.velocity_w>0?'+':''}${a.velocity_w}/m` : '-';
      return `<tr class="${a.is_active?'active':''}">
        <td>${a.index}</td>
        <td>${a.email.substring(0,25)}${a.is_active?' ✦':''}</td>
        <td>${a.plan}</td>
        <td>${bar(a.daily)}</td>
        <td>${bar(a.weekly)}</td>
        <td>${a.score}</td>
        <td>${tte}</td>
        <td style="font-size:.75em">${vel}</td>
        <td>${rl||'-'}</td>
        <td>${pill(a.status)}</td>
      </tr>`;
    }).join('');
    document.getElementById('refresh').textContent =
      `Last refresh: ${new Date().toLocaleTimeString()} · Auto-refresh 5s`;
  } catch(e) {
    document.getElementById('error').textContent = 'Error: '+e.message;
  }
}
refresh();
setInterval(refresh, 5000);
</script>
</body></html>'''


# ============================================================
# CLI
# ============================================================
def cli_status():
    eng = PoolEngine()
    s = eng.get_pool_status()
    p = s['pool']
    st = s['stats']
    print('=' * 65)
    print(f'  Pool Engine v{VERSION} · 综合号池机')
    print('=' * 65)
    print(f'  Accounts: {p["total"]} total, {p["available"]} available, '
          f'{p["exhausted"]} exhausted, {p["urgent"]} urgent')
    print(f'  Capacity: D{p["total_daily"]}% / W{p["total_weekly"]}%')
    print(f'  Snapshots: {p["harvested"]} / API Keys: {p["has_api_key"]}')
    if s.get('active'):
        a = s['active']
        print(f'  Active: #{a["index"]} {a["email"][:30]} '
              f'D{a["daily"]}%-W{a["weekly"]}% [{a["plan"]}]')
    print()

    accs = eng.get_all_accounts()
    for a in accs:
        flag = '*' if a['is_active'] else ' '
        snap = 'S' if a['has_snapshot'] else '-'
        key = 'K' if a.get('has_snapshot') else ' '
        tte = f'TTE={a["min_tte"]}m' if a.get('min_tte') else ''
        try:
            print(f'  {a["index"]:>3}{flag} {a["email"][:28]:<28} '
                  f'{a["plan"]:>6} D{a["daily"]:>3.0f}%-W{a["weekly"]:>3.0f}% '
                  f'{snap} sc={a["score"]:<4} {tte}')
        except UnicodeEncodeError:
            pass

    # Model availability
    models = eng.get_model_availability()
    if models:
        print(f'\n  Model Availability:')
        for mk, info in models.items():
            print(f'    {mk:<30} {info["available"]} avail / '
                  f'{info["blocked"]} blocked (window={info["window_sec"]}s)')
    print('=' * 65)


def cli_pick(model=None):
    eng = PoolEngine()
    best = eng.pick_best(model_key=model)
    if best:
        print(f'  Best account for {model or "any"}:')
        print(f'    #{best.index} {best.email[:35]}')
        print(f'    D{best.daily}%·W{best.weekly}% score={best.score} [{best.plan}]')
        if best.api_key:
            print(f'    apiKey: {best.api_key[:30]}...')
    else:
        print(f'  No available account for {model or "any"}')


def cli_serve():
    global _engine
    _engine = PoolEngine()

    # Start health monitor
    monitor = HealthMonitor(_engine, interval=10)
    monitor.start()

    # Start auto-switch guardian
    guardian = AutoSwitchGuardian(_engine, interval=10)
    guardian.start()

    # Start hot-patch key file writer (feeds patched extension.js per-request)
    def _key_writer():
        while True:
            try:
                best = _engine.pick_best()
                if best and best.api_key:
                    for _pkf in _ALL_POOL_KEY_FILES:
                        try:
                            _pkf.parent.mkdir(parents=True, exist_ok=True)
                            _pkf.write_text(best.api_key, encoding='utf-8')
                        except Exception:
                            pass
            except Exception:
                pass
            time.sleep(3)
    threading.Thread(target=_key_writer, daemon=True, name='PoolKeyWriter').start()

    try:
        cli_status()
    except Exception:
        pass

    port = ENGINE_PORT
    server = None
    for attempt in range(5):
        try:
            server = HTTPServer(('127.0.0.1', port), PoolHandler)
            break
        except OSError:
            port += 1
    if not server:
        print(f'  [ERR] Cannot bind to any port {ENGINE_PORT}-{port}')
        return

    print(f'\n  Pool Engine API: http://127.0.0.1:{port}/')
    print(f'  Dashboard:       http://127.0.0.1:{port}/dashboard')
    print(f'  Health Monitor:  every 10s')
    print(f'  Auto-Switch:     TTE<2min / threshold=5%')
    print(f'  Press Ctrl+C to stop\n')

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        monitor.stop()
        guardian.stop()
        server.server_close()
        print('\nPool Engine stopped.')


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'serve'
    if cmd == 'status':
        cli_status()
    elif cmd == 'pick':
        model = sys.argv[2] if len(sys.argv) > 2 else None
        cli_pick(model)
    elif cmd in ('serve', 'start', ''):
        cli_serve()
    elif cmd == 'dashboard':
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{ENGINE_PORT}/dashboard')
    else:
        print(f'Pool Engine v{VERSION}')
        print(f'  serve     Start engine + dashboard (default)')
        print(f'  status    Pool status summary')
        print(f'  pick [M]  Pick best account for model M')
        print(f'  dashboard Open dashboard in browser')


if __name__ == '__main__':
    main()
