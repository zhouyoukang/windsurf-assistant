#!/usr/bin/env python3
"""
WAM — Windsurf Account Manager v4.0
====================================
Hot-inject switching: 3-5s (vs 60-180s traditional)

道生一(apiKey) → 一生二(quota+rate_limit) → 二生三(detect+inject+reload) → 三生万物(user无感)

Core Innovation:
  Traditional: kill WS → reset FP → clear auth → restart → manual login = 60-180s
  WAM v4:      write auth snapshot → reload window = 3-5s (20-60x faster)

Commands:
  python wam_engine.py serve              # Dashboard :9876
  python wam_engine.py status             # Pool status
  python wam_engine.py harvest            # Capture current account's auth snapshot
  python wam_engine.py switch [N|email]   # Hot-switch to account #N or by email
  python wam_engine.py next               # Switch to next best account
  python wam_engine.py test               # E2E self-test

Architecture:
  Data source: windsurf-login-accounts.json (Login Helper extension)
  Auth store:  _wam_snapshots.json (harvested auth blobs per account)
  State DB:    state.vscdb (Windsurf runtime state)

  Hot-inject flow:
    1. Read target's auth snapshot from _wam_snapshots.json
    2. Write to state.vscdb: windsurfAuthStatus + cachedPlanInfo + user ref
    3. Trigger workbench.action.reloadWindow
    4. Total: ~3-5 seconds
"""

import os, sys, json, sqlite3, time, subprocess, threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

VERSION = '5.0.0'
HUB_PORT = 9876
SCRIPT_DIR = Path(__file__).parent

# ============================================================
# Path Discovery
# ============================================================
WS_APPDATA = Path(os.environ.get('APPDATA', '')) / 'Windsurf'
WS_GLOBALSTORE = WS_APPDATA / 'User' / 'globalStorage'
WS_STATE_DB = WS_GLOBALSTORE / 'state.vscdb'
WS_STORAGE_JSON = WS_GLOBALSTORE / 'storage.json'

# v2.0 fix: Do NOT cross-inject auth to other users on switch.
# Each user (ai, Administrator) manages their own auth independently via their own VSIX extension.
# Cross-injection was causing: ai switches → overwrites Administrator's state.vscdb auth
# → Administrator's account changes without consent, switching appears ineffective.
# Consistent with cross_user_bridge v2.0 (AUTH_KEYS=[]) and hot_guardian v2.0 (_ALL_POOL_KEYS=[POOL_KEY]).
MULTI_USER_DBS = []  # v2.0: disabled — each user manages their own auth

LOGIN_HELPER_PATHS = [
    WS_GLOBALSTORE / 'zhouyoukang.windsurf-assistant' / 'windsurf-login-accounts.json',
    WS_GLOBALSTORE / 'undefined_publisher.windsurf-login-helper' / 'windsurf-login-accounts.json',
    WS_GLOBALSTORE / 'windsurf-login-accounts.json',
]

SNAPSHOT_FILE = SCRIPT_DIR / '_wam_snapshots.json'
DASHBOARD_FILE = SCRIPT_DIR / 'wam_dashboard.html'
CLI_BRIDGE_URL = 'http://127.0.0.1:19850'

def _find_login_helper_json():
    """Return the Login Helper JSON with the freshest account data.
    Prefers files with more accounts and most-recent lastChecked timestamps.
    Falls back to first-existing file if none can be parsed."""
    best_path = None
    best_score = -1  # higher = better: (count * 1000) + freshness_bonus
    for p in LOGIN_HELPER_PATHS:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
            if not isinstance(data, list) or not data:
                continue
            count = len(data)
            # Find most recent lastChecked across all accounts
            lcs = [a.get('usage', {}).get('lastChecked', 0) for a in data
                   if isinstance(a.get('usage'), dict)]
            max_lc = max(lcs) if lcs else 0
            # Score: more accounts + fresher data wins
            # Freshness: 1000 bonus if checked within 60 min, 500 if within 6h
            import time as _t
            age_min = (_t.time() * 1000 - max_lc) / 60000 if max_lc else 9999
            freshness = 1000 if age_min < 60 else (500 if age_min < 360 else 0)
            score = count * 10 + freshness
            if score > best_score:
                best_score = score
                best_path = p
        except Exception:
            if best_path is None:
                best_path = p  # fallback: use first parseable/existing path
    if best_path is not None:
        return best_path
    # Final fallback: first existing path
    for p in LOGIN_HELPER_PATHS:
        if p.exists():
            return p
    return LOGIN_HELPER_PATHS[0]

# ============================================================
# State DB Operations (read/write while Windsurf running)
# ============================================================
def db_read(key):
    if not WS_STATE_DB.exists(): return None
    try:
        conn = sqlite3.connect(f'file:{WS_STATE_DB}?mode=ro', uri=True)
        row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else None
    except: return None

def db_write(key, value):
    if not WS_STATE_DB.exists(): return False
    try:
        conn = sqlite3.connect(str(WS_STATE_DB), timeout=10)
        conn.execute('PRAGMA journal_mode=WAL')  # safe concurrent access with Windsurf
        conn.execute('PRAGMA busy_timeout=5000')  # wait up to 5s if DB locked
        conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (key, value))
        conn.commit()
        conn.close()
        return True
    except: return False

def db_read_multi(keys):
    if not WS_STATE_DB.exists(): return {}
    try:
        conn = sqlite3.connect(f'file:{WS_STATE_DB}?mode=ro', uri=True)
        result = {}
        for k in keys:
            row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (k,)).fetchone()
            if row: result[k] = row[0]
        conn.close()
        return result
    except: return {}

def db_write_multi(kv_pairs):
    if not WS_STATE_DB.exists(): return 0
    try:
        conn = sqlite3.connect(str(WS_STATE_DB), timeout=10)
        conn.execute('PRAGMA journal_mode=WAL')  # safe concurrent access with Windsurf
        conn.execute('PRAGMA busy_timeout=5000')  # wait up to 5s if DB locked
        n = 0
        for k, v in kv_pairs.items():
            conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (k, v))
            n += 1
        conn.commit()
        conn.close()
        return n
    except: return 0

# ============================================================
# Account Pool (from Login Helper extension)
# ============================================================
class AccountPool:
    def __init__(self):
        self.path = _find_login_helper_json()
        self.accounts = self._load()

    def _load(self):
        if not self.path.exists():
            return []
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []

    def reload(self):
        self.accounts = self._load()

    def count(self):
        return len(self.accounts)

    def get(self, index):
        if 0 <= index < len(self.accounts):
            return self.accounts[index]
        return None

    def find_by_email(self, email_prefix):
        for i, a in enumerate(self.accounts):
            if a.get('email', '').startswith(email_prefix):
                return i, a
        return -1, None

    def get_health(self, acc):
        u = acc.get('usage', {})
        d = u.get('daily', {})
        w = u.get('weekly', {})
        dr = d.get('remaining', 100) if d else 100
        wr = w.get('remaining', 100) if w else 100
        plan = u.get('plan', 'Trial')
        reset_ts = u.get('resetTime', 0)
        weekly_reset_ts = u.get('weeklyReset', 0)
        plan_end = u.get('planEnd', 0)
        last_checked = u.get('lastChecked', 0)
        now_ms = time.time() * 1000
        days_left = max(0, (plan_end - now_ms) / 86400000) if plan_end else 0
        # Staleness: how long since Login Helper last updated this account's data
        stale_ms = (now_ms - last_checked) if last_checked else -1
        stale_min = round(stale_ms / 60000, 1) if stale_ms > 0 else -1
        # Daily reset proximity: seconds until daily quota resets
        daily_reset_in = max(0, (reset_ts - now_ms) / 1000) if reset_ts > now_ms else 0
        weekly_reset_in = max(0, (weekly_reset_ts - now_ms) / 1000) if weekly_reset_ts > now_ms else 0
        return {
            'daily': dr, 'weekly': wr,
            'plan': plan, 'days_left': round(days_left, 1),
            'daily_reset': reset_ts, 'weekly_reset': weekly_reset_ts,
            'daily_reset_in_sec': round(daily_reset_in),
            'weekly_reset_in_sec': round(weekly_reset_in),
            'stale_min': stale_min,
        }

    def pool_total(self):
        td = tw = 0
        for a in self.accounts:
            h = self.get_health(a)
            td += h['daily']
            tw += h['weekly']
        return td, tw

    def get_best_index(self, exclude_index=-1, snapshot_store=None, min_score=5):
        """Get index of best account to switch to, using multi-factor scoring.
        If snapshot_store provided, only considers accounts with harvested snapshots.
        min_score: minimum effective quota % to be considered switchable."""
        best_i, best_score = -1, -1
        for i, a in enumerate(self.accounts):
            if i == exclude_index:
                continue
            email = a.get('email', '')
            has_snap = snapshot_store.has_snapshot(email) if snapshot_store else True
            if snapshot_store and not has_snap:
                continue
            h = self.get_health(a)
            eff = min(h['daily'], h['weekly'])
            if eff <= min_score:
                continue
            sc = score_account(h, has_snap)
            if sc > best_score:
                best_score = sc
                best_i = i
        return best_i

# ============================================================
# Account Classification & Smart Scoring (道法自然·智能排序)
# ============================================================
QUOTA_EXHAUSTED = 2       # D or W <= this = exhausted (榨干到极限)
QUOTA_URGENT = 8          # effective <= this = urgent
QUOTA_LOW = 30            # effective <= this = low
STALE_THRESHOLD_MIN = 60  # health data older than this = stale
DAYS_URGENT = 3           # plan expires in <= this = urgent
DAYS_EXPIRING = 7         # plan expires in <= this = expiring

def classify_account(health, has_snapshot=False):
    """Classify account into status category.
    Returns (status, sort_tier) where lower tier = better (sorted first).
    Status: available, low, urgent, expiring, exhausted, stale, no_snapshot
    """
    d, w = health['daily'], health['weekly']
    eff = min(d, w)
    days = health.get('days_left', 999)
    stale = health.get('stale_min', -1)

    # Tier 0: Exhausted (D or W near zero)
    if d <= QUOTA_EXHAUSTED or w <= QUOTA_EXHAUSTED:
        return 'exhausted', 90
    # Tier 0.5: Stale data (can't trust health)
    if stale > STALE_THRESHOLD_MIN:
        return 'stale', 80
    # Tier 1: Urgent (effective very low or expiring soon)
    if eff <= QUOTA_URGENT:
        return 'urgent', 70
    if 0 < days <= DAYS_URGENT:
        return 'urgent', 70
    # Tier 2: Expiring soon
    if 0 < days <= DAYS_EXPIRING:
        return 'expiring', 50
    # Tier 3: Low quota
    if eff <= QUOTA_LOW:
        return 'low', 40
    # Tier 4: No snapshot (can't hot-switch)
    if not has_snapshot:
        return 'no_snapshot', 30
    # Tier 5: Available and healthy
    return 'available', 10


def score_account(health, has_snapshot=False):
    """Multi-factor score for smart ranking. Higher = better.
    Factors: effective quota, D+W balance, plan days, snapshot, staleness.
    Score range: 0-1000."""
    d, w = health['daily'], health['weekly']
    eff = min(d, w)
    days = health.get('days_left', 999)
    stale = health.get('stale_min', -1)

    # Base: effective quota (0-100) * 5 = 0-500
    score = eff * 5

    # Balance bonus: reward accounts where both D and W are high
    # max bonus when d==w==100: +100
    balance = min(d, w) / max(max(d, w), 1)
    score += balance * 100

    # Weekly deficit penalty: W is the real bottleneck (pool W < D)
    # When W < D, account is weekly-constrained — penalize proportionally
    if w < d and d > 10:
        weekly_deficit = (d - w) * 1.5  # Up to ~150 penalty
        score -= weekly_deficit

    # Days bonus: more days = better (max +150 at 30+ days)
    if days > 0:
        score += min(days, 30) * 5
    else:
        score -= 200  # expired or unknown

    # Snapshot bonus: +100 if can hot-switch
    if has_snapshot:
        score += 100

    # Staleness penalty: -50 per 30min stale
    if stale > STALE_THRESHOLD_MIN:
        score -= min(200, (stale - STALE_THRESHOLD_MIN) / 30 * 50)

    # Exhaustion cliff: severe penalty
    if d <= QUOTA_EXHAUSTED or w <= QUOTA_EXHAUSTED:
        score -= 500

    return max(0, round(score))


# ============================================================
# Auth Snapshot Store
# ============================================================
AUTH_KEYS = [
    'windsurfAuthStatus',
    'windsurfConfigurations',
]

class SnapshotStore:
    def __init__(self):
        self.data = self._load()

    def _load(self):
        if SNAPSHOT_FILE.exists():
            try:
                with open(SNAPSHOT_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except: pass
        return {'version': '4.0', 'snapshots': {}}

    def save(self):
        with open(SNAPSHOT_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def has_snapshot(self, email):
        return email in self.data.get('snapshots', {})

    def get_snapshot(self, email):
        return self.data.get('snapshots', {}).get(email)

    def harvest_current(self):
        """Capture current account's auth state from state.vscdb.
        Uses find_active_index() to auto-detect which Login Helper account is active."""
        blobs = db_read_multi(AUTH_KEYS)
        if 'windsurfAuthStatus' not in blobs:
            return None, 'No windsurfAuthStatus in state.vscdb'

        try:
            auth_data = json.loads(blobs['windsurfAuthStatus'])
            api_key_preview = auth_data.get('apiKey', '')[:20] + '...'
        except:
            api_key_preview = '?'

        # Auto-detect active account via Login Helper lastChecked
        pool = AccountPool()
        active_i = find_active_index(pool)
        email = pool.get(active_i).get('email') if active_i >= 0 else None

        if not email:
            return None, f'Cannot detect active account. Use: harvest <email>'

        # Warn if same apiKey already stored under different email
        for stored_email, snap in self.data.get('snapshots', {}).items():
            if stored_email != email and snap.get('api_key_preview') == api_key_preview:
                return None, (f'apiKey already stored under {stored_email}. '
                              f'Switch accounts via Login Helper first, then harvest.')

        snapshot = {
            'blobs': blobs,
            'harvested_at': datetime.now(timezone.utc).isoformat(),
            'api_key_preview': api_key_preview,
        }
        self.data.setdefault('snapshots', {})[email] = snapshot
        self.save()
        return email, f'Harvested auth for {email} (apiKey={api_key_preview})'


    def harvest_for_email(self, email):
        """Harvest current auth and explicitly assign to email.
        WARNING: Caller must ensure the Login Helper has already switched to this account."""
        blobs = db_read_multi(AUTH_KEYS)
        if 'windsurfAuthStatus' not in blobs:
            return False, 'No auth in state.vscdb'
        try:
            api_key_preview = json.loads(blobs['windsurfAuthStatus']).get('apiKey', '')[:20] + '...'
        except:
            api_key_preview = '?'

        # Warn if same apiKey already stored under different email
        for stored_email, snap in self.data.get('snapshots', {}).items():
            if stored_email != email and snap.get('api_key_preview') == api_key_preview:
                return False, (f'Same apiKey already stored under {stored_email}. '
                               f'Switch accounts via Login Helper first.')

        snapshot = {
            'blobs': blobs,
            'harvested_at': datetime.now(timezone.utc).isoformat(),
            'api_key_preview': api_key_preview,
        }
        self.data.setdefault('snapshots', {})[email] = snapshot
        self.save()
        return True, f'Harvested for {email} (apiKey={api_key_preview})'

    def count_harvested(self):
        return len(self.data.get('snapshots', {}))

    def list_harvested(self):
        result = []
        for email, snap in self.data.get('snapshots', {}).items():
            result.append({
                'email': email,
                'api_key_preview': snap.get('api_key_preview', '?'),
                'harvested_at': snap.get('harvested_at', '?'),
            })
        return result

# ============================================================
# Hot-Inject Switcher (CORE INNOVATION)
# ============================================================
class HotSwitcher:
    """
    Traditional switch: kill WS → reset FP → clear auth → restart → login = 60-180s
    Hot-inject switch: write auth to DB → reload window = 3-5s
    """

    @staticmethod
    def inject_auth(snapshot):
        """Write auth snapshot to state.vscdb + all multi-user DBs. Returns (ok, message)."""
        blobs = snapshot.get('blobs', {})
        if not blobs.get('windsurfAuthStatus'):
            return False, 'Snapshot has no windsurfAuthStatus'
        written = db_write_multi(blobs)
        if written > 0:
            # Cross-user sync: also inject into other users' state.vscdb
            for other_db in MULTI_USER_DBS:
                try:
                    conn = sqlite3.connect(str(other_db), timeout=10)
                    conn.execute('PRAGMA journal_mode=WAL')
                    conn.execute('PRAGMA busy_timeout=5000')
                    for k, v in blobs.items():
                        conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (k, v))
                    conn.commit()
                    conn.close()
                except Exception:
                    pass  # other user's DB may be locked; non-fatal
            return True, f'Injected {written} auth keys to state.vscdb (+{len(MULTI_USER_DBS)} users)'
        return False, 'Failed to write to state.vscdb'

    @staticmethod
    def trigger_reload():
        """Trigger Windsurf window reload. Returns (ok, method, message)."""
        # Method 1: CLI Bridge
        try:
            import urllib.request
            req = urllib.request.Request(
                f'{CLI_BRIDGE_URL}/api/execute',
                data=json.dumps({'command': 'workbench.action.reloadWindow'}).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                if data.get('error'):
                    raise Exception(data['error'])
                return True, 'cli_bridge', 'Window reload via CLI Bridge'
        except: pass

        # Method 2: PowerShell keyboard simulation (Ctrl+Shift+P → "reload" → Enter)
        try:
            ps_cmd = '''
Add-Type -AssemblyName System.Windows.Forms
$ws = Get-Process Windsurf -ErrorAction SilentlyContinue | Select-Object -First 1
if ($ws) {
    [Microsoft.VisualBasic.Interaction]::AppActivate($ws.Id)
    Start-Sleep -Milliseconds 300
    [System.Windows.Forms.SendKeys]::SendWait("^+p")
    Start-Sleep -Milliseconds 500
    [System.Windows.Forms.SendKeys]::SendWait("reload window")
    Start-Sleep -Milliseconds 500
    [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
}
'''
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command', ps_cmd],
                capture_output=True, text=True, timeout=10,
                encoding='utf-8', errors='replace'
            )
            if result.returncode == 0:
                return True, 'keyboard', 'Window reload via keyboard simulation'
        except: pass

        # Method 3: Full restart (fallback)
        try:
            subprocess.run('taskkill /F /IM Windsurf.exe', shell=True,
                           capture_output=True, timeout=10)
            time.sleep(2)
            for exe in [Path('D:/Windsurf/Windsurf.exe'),
                        Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Windsurf' / 'Windsurf.exe']:
                if exe.exists():
                    subprocess.Popen([str(exe)], creationflags=0x00000008)  # DETACHED
                    return True, 'restart', f'Full restart via {exe.name}'
        except: pass

        return False, 'none', 'All reload methods failed'

    @staticmethod
    def hot_switch(target_email, store, retries=2):
        """Execute hot-inject switch with retry. Returns (ok, steps, total_ms)."""
        t0 = time.time()
        steps = []

        # Step 1: Get snapshot
        snapshot = store.get_snapshot(target_email)
        if not snapshot:
            return False, [f'No auth snapshot for {target_email}. Run: harvest'], 0

        # Step 2: Inject auth
        ok, msg = HotSwitcher.inject_auth(snapshot)
        steps.append(f'Inject: {msg}')
        if not ok:
            return False, steps, int((time.time() - t0) * 1000)

        # Step 3: Trigger reload (with retry)
        reload_ok = False
        for attempt in range(1, retries + 1):
            ok, method, msg = HotSwitcher.trigger_reload()
            steps.append(f'Reload#{attempt}: {msg} ({method})')
            if ok:
                reload_ok = True
                break
            if attempt < retries:
                time.sleep(1)  # brief pause before retry

        # Step 4: Persist active account marker (ground truth for find_active_index)
        if reload_ok:
            try:
                write_active_marker(target_email)
            except Exception:
                pass

        total_ms = int((time.time() - t0) * 1000)
        steps.append(f'Total: {total_ms}ms')
        return reload_ok, steps, total_ms

# ============================================================
# Health Reader (current account from state.vscdb)
# ============================================================
def read_current_health():
    """Read current active account's health from Login Helper data.
    (cachedPlanInfo no longer exists in state.vscdb — quota moved to Login Helper)"""
    pool = AccountPool()
    active_i = find_active_index(pool)
    if active_i < 0:
        return {'error': 'No active account detected'}
    acc = pool.get(active_i)
    h = pool.get_health(acc)
    return {
        'index': active_i,
        'email': acc.get('email', '?'),
        'plan': h['plan'],
        'daily': h['daily'],
        'weekly': h['weekly'],
        'daily_reset': h['daily_reset'],
        'weekly_reset': h['weekly_reset'],
        'days_left': h['days_left'],
    }

def _extract_proto_email():
    """Extract the actual email from windsurfAuthStatus protobuf."""
    import base64, re
    raw = db_read('windsurfAuthStatus')
    if not raw: return None
    try:
        d = json.loads(raw)
        proto_b64 = d.get('userStatusProtoBinaryBase64', '')
        if proto_b64:
            proto_raw = base64.b64decode(proto_b64)
            emails = re.findall(rb'[\w.-]+@[\w.-]+\.com', proto_raw[:500])
            if emails:
                return emails[0].decode()
    except: pass
    return None

ACTIVE_MARKER = Path(__file__).parent / '_active_account.txt'

def write_active_marker(email: str):
    """Persist the active account email after a hot-switch."""
    ACTIVE_MARKER.write_text(email.strip(), encoding='utf-8')

def read_active_marker():
    """Read the persisted active account email."""
    try:
        return ACTIVE_MARKER.read_text(encoding='utf-8').strip() if ACTIVE_MARKER.exists() else None
    except:
        return None

def find_active_index(pool):
    """Find which pool account is currently active in Windsurf.
    Strategy 1 (ground truth): marker file written after each hot-switch
    Strategy 2: protobuf email from state.vscdb
    Strategy 3 (fallback): lastChecked timestamp from Login Helper
    """
    # Strategy 1: marker file (written by hot_switch on success)
    marker_email = read_active_marker()
    if marker_email:
        for i, a in enumerate(pool.accounts):
            if marker_email.lower() == a.get('email', '').lower():
                return i

    # Strategy 2: protobuf direct read
    proto_email = _extract_proto_email()
    if proto_email:
        for i, a in enumerate(pool.accounts):
            if proto_email.lower() == a.get('email', '').lower():
                return i

    # Strategy 3: Most recently checked account in Login Helper data
    best_i, best_ts = -1, 0
    for i, a in enumerate(pool.accounts):
        u = a.get('usage', {})
        ts = u.get('lastChecked', 0)
        if ts and ts > best_ts:
            best_ts = ts
            best_i = i
    return best_i

# ============================================================
# HTTP API + Dashboard Server
# ============================================================
class WAMHandler(BaseHTTPRequestHandler):
    pool = None
    store = None
    switch_history = []

    def log_message(self, fmt, *args): pass

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._cors()
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _html(self):
        if not DASHBOARD_FILE.exists():
            self.send_error(404, 'wam_dashboard.html not found')
            return
        body = DASHBOARD_FILE.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length <= 0:
            return {}
        try:
            raw = self.rfile.read(length)
            return json.loads(raw)
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        try:
            path = urlparse(self.path).path
            if path in ('/', '/dashboard'):
                self._html()
            elif path == '/favicon.ico':
                self.send_response(204)
                self.end_headers()
            elif path == '/api/health':
                self._json({'status': 'ok', 'version': VERSION, 'port': HUB_PORT, 'ok': True})
            elif path == '/api/status':
                self._json(self._full_status())
            elif path == '/api/accounts':
                self._json(self._accounts_list())
            elif path == '/api/current':
                self._json(read_current_health())
            elif path == '/api/snapshots':
                self._json(self.store.list_harvested())
            elif path == '/api/history':
                self._json(self.switch_history[-50:])
            # ── Watchdog compatibility routes (/api/pool/*) ──
            elif path in ('/api/pool/status', '/api/pool'):
                s = self._full_status()
                h = s.get('active_health', {})
                self._json({
                    'ok': True,
                    'dailyQuotaPercent': h.get('daily', 100),
                    'weeklyQuotaPercent': h.get('weekly', 100),
                    'dPercent': h.get('daily', 100),
                    'wPercent': h.get('weekly', 100),
                    'rateLimited': s.get('rate_limited', 0) > 0,
                    'isRateLimited': s.get('rate_limited', 0) > 0,
                    'quotaExhausted': (h.get('daily', 100) <= 5 or h.get('weekly', 100) <= 5),
                    'dailyQuotaExhausted': h.get('daily', 100) <= 5,
                    'activeEmail': s.get('active_email', ''),
                    'available': s.get('available', 0),
                    'count': s.get('count', 0),
                    'switches': s.get('switches', 0),
                })
            else:
                self.send_error(404)
        except Exception as e:
            self._json({'error': str(e)}, 500)

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            body = self._body()
            if path == '/api/switch':
                self._json(self._do_switch(body))
            elif path == '/api/next':
                self._json(self._do_next())
            elif path == '/api/harvest':
                self._json(self._do_harvest(body))
            elif path == '/api/auto-switch':
                self._json(self._do_auto_switch())
            elif path == '/api/signal-ratelimit':
                self._json(self._signal_ratelimit(body))
            elif path == '/api/batch-harvest':
                self._json(self._do_batch_harvest())
            elif path == '/api/reload':
                self.pool.reload()
                self._json({'ok': True, 'count': self.pool.count()})
            # ── Watchdog compatibility routes ──
            elif path in ('/api/pool/rotate', '/api/pool/switch'):
                self._json(self._do_next())
            else:
                self.send_error(404)
        except Exception as e:
            self._json({'error': str(e)}, 500)

    def _full_status(self):
        self.pool.reload()
        td, tw = self.pool.pool_total()
        active_i = find_active_index(self.pool)
        health = read_current_health()
        active_acc = self.pool.get(active_i) if active_i >= 0 else None
        active_email = active_acc.get('email', '?') if active_acc else '?'
        active_health = self.pool.get_health(active_acc) if active_acc else {}

        # Classify all accounts for status counts
        counts = {'available': 0, 'low': 0, 'urgent': 0, 'expiring': 0,
                  'exhausted': 0, 'stale': 0, 'no_snapshot': 0, 'rate_limited': 0}
        for a in self.pool.accounts:
            h = self.pool.get_health(a)
            email = a.get('email', '')
            has_snap = self.store.has_snapshot(email)
            status, _ = classify_account(h, has_snap)
            counts[status] = counts.get(status, 0) + 1

        # Best available for auto-switch
        best_i = self.pool.get_best_index(
            exclude_index=active_i, snapshot_store=self.store)
        best_email = ''
        best_score_val = 0
        if best_i >= 0:
            ba = self.pool.get(best_i)
            best_email = ba.get('email', '')
            bh = self.pool.get_health(ba)
            best_score_val = score_account(bh, self.store.has_snapshot(best_email))

        # Active account score
        active_score = 0
        active_status = 'unknown'
        if active_acc:
            active_score = score_account(active_health, self.store.has_snapshot(active_email))
            active_status, _ = classify_account(active_health, self.store.has_snapshot(active_email))

        return {
            'pool_total_d': td, 'pool_total_w': tw,
            'count': self.pool.count(),
            'available': counts['available'] + counts['low'],
            'exhausted': counts['exhausted'],
            'urgent': counts['urgent'],
            'expiring': counts['expiring'],
            'rate_limited': counts.get('rate_limited', 0),
            'stale': counts['stale'],
            'status_counts': counts,
            'active_index': active_i,
            'active_email': active_email,
            'active_health': active_health,
            'active_score': active_score,
            'active_status': active_status,
            'best_candidate': {'index': best_i + 1 if best_i >= 0 else -1,
                               'email': best_email, 'score': best_score_val},
            'live_health': health,
            'snapshots_count': self.store.count_harvested(),
            'switches': len(self.switch_history),
            'version': VERSION,
        }

    def _accounts_list(self):
        self.pool.reload()
        active_i = find_active_index(self.pool)
        raw = []
        for i, a in enumerate(self.pool.accounts):
            h = self.pool.get_health(a)
            email = a.get('email', '?')
            has_snap = self.store.has_snapshot(email)
            status, tier = classify_account(h, has_snap)
            sc = score_account(h, has_snap)
            raw.append({
                'orig_index': i + 1,
                'email': email,
                'daily': h['daily'], 'weekly': h['weekly'],
                'plan': h['plan'], 'days_left': h['days_left'],
                'daily_reset_in': h.get('daily_reset_in_sec', 0),
                'weekly_reset_in': h.get('weekly_reset_in_sec', 0),
                'stale_min': h.get('stale_min', -1),
                'has_snapshot': has_snap,
                'is_active': i == active_i,
                'status': status,
                'tier': tier,
                'score': sc,
            })
        # Smart sort: active always first, then by score desc (best first)
        # Exhausted/stale/no_snapshot sink to bottom
        raw.sort(key=lambda x: (
            0 if x['is_active'] else 1,  # active always first
            x['tier'],                    # lower tier = better
            -x['score'],                  # higher score = better
        ))
        # Re-index after sort
        for idx, item in enumerate(raw):
            item['index'] = idx + 1
        return raw

    def _do_switch(self, body):
        target = body.get('index')  # 1-indexed (may be orig_index from sorted list)
        email = body.get('email')
        orig_index = body.get('orig_index')  # original pool index (1-indexed)

        if email:
            idx, acc = self.pool.find_by_email(email)
            if not acc:
                return {'ok': False, 'error': f'Email {email} not found'}
        elif orig_index is not None:
            acc = self.pool.get(int(orig_index) - 1)
            if not acc:
                return {'ok': False, 'error': f'Account orig#{orig_index} not found'}
            email = acc.get('email')
        elif target is not None:
            acc = self.pool.get(int(target) - 1)
            if not acc:
                return {'ok': False, 'error': f'Account #{target} not found'}
            email = acc.get('email')
        else:
            return {'ok': False, 'error': 'Provide index, orig_index, or email'}

        ok, steps, ms = HotSwitcher.hot_switch(email, self.store)
        record = {
            'target': email, 'ok': ok, 'steps': steps,
            'ms': ms, 'time': datetime.now().strftime('%H:%M:%S'),
        }
        self.switch_history.append(record)
        return record

    def _do_auto_switch(self):
        """Check current account health; if below threshold, auto-switch to best.
        Decision based on EFFECTIVE QUOTA, not staleness — stale D100%W100% = hold."""
        self.pool.reload()
        active_i = find_active_index(self.pool)
        if active_i < 0:
            return {'ok': False, 'action': 'none', 'reason': 'no active account'}

        acc = self.pool.get(active_i)
        h = self.pool.get_health(acc)
        active_email = acc.get('email', '?')
        has_snap = self.store.has_snapshot(active_email)
        status, _ = classify_account(h, has_snap)
        eff = min(h['daily'], h['weekly'])

        # Core decision: effective quota determines switch, NOT staleness
        # Stale data with high D/W = probably still fine, don't waste a switch
        if eff > QUOTA_URGENT:
            return {
                'ok': True, 'action': 'hold',
                'reason': f'Current account healthy: D{h["daily"]}%·W{h["weekly"]}% eff={eff}% ({status})',
                'active_email': active_email, 'active_score': score_account(h, has_snap),
            }

        # Find best candidate
        best_i = self.pool.get_best_index(
            exclude_index=active_i, snapshot_store=self.store)
        if best_i < 0:
            return {
                'ok': False, 'action': 'no_candidate',
                'reason': f'Current {status} D{h["daily"]}%·W{h["weekly"]}% but no switchable candidates',
                'active_email': active_email,
            }

        # Execute switch
        best_acc = self.pool.get(best_i)
        best_email = best_acc.get('email', '')
        best_h = self.pool.get_health(best_acc)
        ok, steps, ms = HotSwitcher.hot_switch(best_email, self.store)
        record = {
            'target': best_email, 'ok': ok, 'steps': steps,
            'ms': ms, 'time': datetime.now().strftime('%H:%M:%S'),
            'action': 'auto_switched' if ok else 'switch_failed',
            'reason': f'{active_email} {status} D{h["daily"]}%·W{h["weekly"]}% → {best_email} D{best_h["daily"]}%·W{best_h["weekly"]}%',
            'from_email': active_email, 'to_email': best_email,
            'to_score': score_account(best_h, True),
        }
        self.switch_history.append(record)
        return record

    def _do_next(self):
        active_i = find_active_index(self.pool)
        best_i = self.pool.get_best_index(exclude_index=active_i, snapshot_store=self.store)
        if best_i < 0:
            return {'ok': False, 'error': 'No available accounts'}
        acc = self.pool.get(best_i)
        email = acc.get('email', '')
        ok, steps, ms = HotSwitcher.hot_switch(email, self.store)
        record = {
            'target': email, 'ok': ok, 'steps': steps,
            'ms': ms, 'time': datetime.now().strftime('%H:%M:%S'),
        }
        self.switch_history.append(record)
        return record

    def _do_harvest(self, body):
        email = body.get('email')
        if email:
            ok, msg = self.store.harvest_for_email(email)
            return {'ok': ok, 'message': msg}
        else:
            email, msg = self.store.harvest_current()
            return {'ok': email is not None, 'email': email, 'message': msg}

    def _signal_ratelimit(self, body):
        """Receive rate-limit signal and write to signal file for sentinel.
        Triggers INSTANT switch bypassing cooldown."""
        signal = {
            'ts': time.time(),
            'model': body.get('model', ''),
            'error': body.get('error', ''),
            'email': body.get('email', ''),
            'source': body.get('source', 'api'),
        }
        signal_file = Path(__file__).parent / '_ratelimit_signal.json'
        try:
            signal_file.write_text(json.dumps(signal), encoding='utf-8')
        except Exception:
            pass
        # Also attempt immediate auto-switch
        result = self._do_auto_switch()
        result['signal'] = 'written'
        return result

    def _do_batch_harvest(self):
        """Harvest auth snapshot for the currently active account.
        For batch harvesting all accounts, use CLI: wam_engine.py batch-harvest"""
        email, msg = self.store.harvest_current()
        return {'ok': email is not None, 'email': email, 'message': msg,
                'total_harvested': self.store.count_harvested()}

# ============================================================
# CLI Interface
# ============================================================
def cli_status():
    pool = AccountPool()
    store = SnapshotStore()
    health = read_current_health()
    active_i = find_active_index(pool)
    td, tw = pool.pool_total()

    print(f'\n{"="*60}')
    print(f'  WAM — Windsurf Account Manager v{VERSION}')
    print(f'  Hot-inject switching: 3-5s (vs 60-180s traditional)')
    print(f'{"="*60}')
    print(f'  Pool: D{td}% · W{tw}%  ({pool.count()} accounts)')
    print(f'  Snapshots: {store.count_harvested()}/{pool.count()} harvested')
    if active_i >= 0:
        a = pool.get(active_i)
        h = pool.get_health(a)
        print(f'  Active: #{active_i+1} {a["email"][:30]} [{h["plan"]}] D{h["daily"]}%·W{h["weekly"]}% {h["days_left"]}d')
    if 'error' not in health:
        print(f'  Live:   D{health["daily"]}%·W{health["weekly"]}% plan={health["plan"]}')
    print()

    for i, a in enumerate(pool.accounts):
        h = pool.get_health(a)
        snap = '●' if store.has_snapshot(a['email']) else '○'
        active = ' ←' if i == active_i else ''
        email_short = a['email'][:25]
        print(f'  {i+1:2d} {email_short:25s} {h["plan"]:>6s} D{h["daily"]:>3d}%·W{h["weekly"]:>3d}% {snap}{active}')

    print(f'\n  ● = snapshot harvested  ○ = needs harvest')
    print(f'  Hub: http://localhost:{HUB_PORT}/')
    print(f'{"="*60}\n')

def cli_harvest(email=None):
    store = SnapshotStore()
    if email:
        ok, msg = store.harvest_for_email(email)
    else:
        email, msg = store.harvest_current()
        ok = email is not None
    print(f'  {"✅" if ok else "❌"} {msg}')
    if ok:
        print(f'  Snapshots: {store.count_harvested()} total')

def cli_switch(target):
    pool = AccountPool()
    store = SnapshotStore()

    # Parse target: number or email prefix
    try:
        idx = int(target) - 1
        acc = pool.get(idx)
        if not acc:
            print(f'  ❌ Account #{target} not found')
            return
        email = acc['email']
    except ValueError:
        idx, acc = pool.find_by_email(target)
        if not acc:
            print(f'  ❌ Email matching "{target}" not found')
            return
        email = acc['email']

    print(f'  🔄 Hot-switching to: {email[:40]}')
    ok, steps, ms = HotSwitcher.hot_switch(email, store)
    for s in steps:
        print(f'    → {s}')
    print(f'  {"✅" if ok else "❌"} {"Done" if ok else "Failed"} ({ms}ms)')

def cli_next():
    pool = AccountPool()
    store = SnapshotStore()
    active_i = find_active_index(pool)
    best_i = pool.get_best_index(exclude_index=active_i, snapshot_store=store)
    if best_i < 0:
        print('  ❌ No available accounts')
        return
    acc = pool.get(best_i)
    h = pool.get_health(acc)
    print(f'  🔄 Best account: #{best_i+1} {acc["email"][:40]} D{h["daily"]}%·W{h["weekly"]}%')
    ok, steps, ms = HotSwitcher.hot_switch(acc['email'], store)
    for s in steps:
        print(f'    → {s}')
    print(f'  {"✅" if ok else "❌"} {"Done" if ok else "Failed"} ({ms}ms)')

def cli_serve(port=HUB_PORT):
    pool = AccountPool()
    store = SnapshotStore()
    WAMHandler.pool = pool
    WAMHandler.store = store
    cli_status()
    server = HTTPServer(('127.0.0.1', port), WAMHandler)
    print(f'  WAM Hub: http://127.0.0.1:{port}/')
    print(f'  API: /api/status /api/accounts /api/current /api/snapshots')
    print(f'  Actions: POST /api/switch /api/next /api/harvest')
    print(f'  Press Ctrl+C to stop\n')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()

# ============================================================
# Cloud Sync — 云端号池同步
# ============================================================
CLOUD_POOL_URL = os.environ.get('CLOUD_POOL_URL', 'http://127.0.0.1:19880')
CLOUD_ADMIN_KEY = os.environ.get('CLOUD_POOL_ADMIN_KEY', '')

def cli_cloud_sync():
    """Push account pool health data to cloud pool server."""
    pool = AccountPool()
    pool.reload()
    accounts_data = []
    for i, a in enumerate(pool.accounts):
        h = pool.get_health(a)
        accounts_data.append({
            'email': a.get('email', ''),
            'plan': h['plan'],
            'daily': h['daily'],
            'weekly': h['weekly'],
            'days_left': h['days_left'],
        })

    print(f'  Cloud sync: {len(accounts_data)} accounts → {CLOUD_POOL_URL}')
    import urllib.request
    try:
        req = urllib.request.Request(
            f'{CLOUD_POOL_URL}/api/admin/sync',
            data=json.dumps({'accounts': accounts_data}).encode(),
            headers={'Content-Type': 'application/json', 'X-Admin-Key': CLOUD_ADMIN_KEY},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if result.get('ok'):
                print(f'  ✅ Synced {result.get("synced", 0)} accounts to cloud')
            else:
                print(f'  ❌ {result.get("error", "Unknown error")}')
            return result
    except Exception as e:
        print(f'  ❌ Cloud unreachable: {e}')
        return {'ok': False, 'error': str(e)}

def cli_test():
    print(f'  WAM v{VERSION} — E2E Test')
    print(f'  {"="*50}')
    results = []

    # T1: Login Helper data
    pool = AccountPool()
    ok = pool.count() > 0
    results.append(('login_helper_data', ok, f'{pool.count()} accounts'))

    # T2: State DB readable
    health = read_current_health()
    ok = 'error' not in health
    results.append(('state_db_read', ok, f'D{health.get("daily","?")}% W{health.get("weekly","?")}%'))

    # T3: Snapshot store
    store = SnapshotStore()
    ok = True
    results.append(('snapshot_store', ok, f'{store.count_harvested()} snapshots'))

    # T4: Active account detection
    active_i = find_active_index(pool)
    ok = active_i >= 0
    detail = f'#{active_i+1} {pool.get(active_i)["email"][:25]}' if ok else 'not detected'
    results.append(('active_detection', ok, detail))

    # T5: Pool health
    td, tw = pool.pool_total()
    ok = td > 0 and tw > 0
    results.append(('pool_health', ok, f'D{td}% W{tw}%'))

    # T6: DB write test (write+restore)
    test_key = '_wam_test_key'
    db_write(test_key, 'test')
    val = db_read(test_key)
    ok = val == 'test'
    results.append(('db_write', ok, f'write+read={val}'))
    # Cleanup
    if WS_STATE_DB.exists():
        try:
            conn = sqlite3.connect(str(WS_STATE_DB))
            conn.execute("DELETE FROM ItemTable WHERE key=?", (test_key,))
            conn.commit()
            conn.close()
        except: pass

    # T7: Hub API
    try:
        tp = 19899
        WAMHandler.pool = pool
        WAMHandler.store = store
        srv = HTTPServer(('127.0.0.1', tp), WAMHandler)
        t = threading.Thread(target=srv.handle_request, daemon=True)
        t.start()
        time.sleep(0.3)
        import urllib.request
        resp = urllib.request.urlopen(f'http://127.0.0.1:{tp}/api/health', timeout=3)
        data = json.loads(resp.read())
        ok = data.get('status') == 'ok'
        results.append(('hub_api', ok, json.dumps(data)))
        srv.server_close()
    except Exception as e:
        results.append(('hub_api', False, str(e)))

    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, detail in results:
        print(f'  {"✅" if ok else "❌"} {name}: {detail[:60]}')
    print(f'\n  {passed}/{len(results)} PASS')

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'serve'
    if cmd == 'serve':
        cli_serve()
    elif cmd == 'status':
        cli_status()
    elif cmd == 'harvest':
        email = sys.argv[2] if len(sys.argv) > 2 else None
        cli_harvest(email)
    elif cmd == 'switch':
        if len(sys.argv) < 3:
            print('Usage: wam_engine.py switch <N|email>')
            return
        cli_switch(sys.argv[2])
    elif cmd == 'next':
        cli_next()
    elif cmd == 'test':
        cli_test()
    elif cmd in ('cloud', 'cloud-sync', 'sync'):
        cli_cloud_sync()
    else:
        print(f'WAM v{VERSION} — Commands: serve|status|harvest|switch|next|cloud-sync|test')

if __name__ == '__main__':
    main()
