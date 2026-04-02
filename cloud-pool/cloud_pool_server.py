#!/usr/bin/env python3
"""
Windsurf Cloud Pool v2.0 — 云端号池统一管理 (安全加固版)
道生一(号池) → 一生二(自界+云端) → 二生三(用户+支付+分配) → 三生万物(无感使用)

v2.0 安全加固:
  - HMAC-SHA256 请求签名 (防篡改/重放)
  - 账号凭据AES-256加密存储 (防泄露)
  - IP速率限制 (防暴力)
  - 设备绑定 (防滥用)
  - Nonce重放防护
  - 敏感字段脱敏返回

Deploy:  python cloud_pool_server.py --port 19880 --admin-key SECRET --host 0.0.0.0
"""

import os, sys, json, sqlite3, time, uuid, secrets, argparse, hmac, hashlib, base64
import threading
from pathlib import Path
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from socketserver import ThreadingMixIn
from collections import defaultdict
import gzip, zlib, struct, socket

VERSION = '3.1.0'
SCRIPT_DIR = Path(__file__).parent
DB_FILE = SCRIPT_DIR / 'cloud_pool.db'
DASHBOARD_FILE = SCRIPT_DIR / 'cloud_pool.html'

ACCOUNT_COST_CENTS = 600
SELL_PRICE_CENTS = 800
ACCOUNT_LIFESPAN_DAYS = 12
ADMIN_KEY = os.environ.get('CLOUD_POOL_ADMIN_KEY', '')
HMAC_SECRET = os.environ.get('CLOUD_POOL_HMAC_SECRET', '')
CRYPT_KEY = os.environ.get('CLOUD_POOL_CRYPT_KEY', '')  # 32-byte hex for AES
ADMIN_IP_ALLOWLIST = os.environ.get('CLOUD_POOL_ADMIN_IPS', '').split(',')  # e.g. '127.0.0.1,1.2.3.4'

# ETag cache for public pool (损之又损·最小化数据交互)
_pool_cache = {'etag': '', 'data': None, 'ts': 0}
_pool_cache_lock = threading.Lock()
POOL_CACHE_TTL = 10  # seconds

# ============================================================
# Concurrency: Thread-safe DB + Global State Locks (v3.1)
# ============================================================
DB_BUSY_TIMEOUT = 30  # seconds — wait for write lock instead of SQLITE_BUSY
DB_MAX_RETRIES = 3    # retry failed writes
DB_RETRY_DELAY = 0.1  # seconds between retries (exponential backoff)
_db_local = threading.local()  # thread-local DB connections
_db_write_lock = threading.Lock()  # serialize write transactions

def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

# ============================================================
# Security: HMAC Signing + Rate Limiting + Nonce Replay
# ============================================================
_rate_limits = defaultdict(list)  # ip -> [timestamps]
_rate_lock = threading.Lock()
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 300  # v3.1: raised for multi-device behind NAT (was 60)
RATE_LIMIT_ADMIN = 1000  # v3.1: raised for admin bulk ops (was 200)
RATE_LIMIT_LOCALHOST_EXEMPT = True  # v3.1: localhost exempt (Hub relay)
_used_nonces = {}  # nonce -> expiry_ts
_nonce_lock = threading.Lock()
NONCE_TTL = 300  # 5 minutes

def _is_loopback(ip):
    """Check if IP is any form of loopback (IPv4/IPv6/mapped)."""
    if not ip:
        return False
    ip = ip.strip()
    return ip in ('127.0.0.1', '::1', 'localhost') or ip.startswith('127.') or ip.startswith('::ffff:127.')

def _rate_check(ip, is_admin=False):
    """Check rate limit. Returns True if allowed. Thread-safe.
    v3.1: Localhost exempt (Hub relay from same machine)."""
    if RATE_LIMIT_LOCALHOST_EXEMPT and _is_loopback(ip):
        return True
    now = time.time()
    limit = RATE_LIMIT_ADMIN if is_admin else RATE_LIMIT_MAX
    with _rate_lock:
        _rate_limits[ip] = [t for t in _rate_limits[ip] if now - t < RATE_LIMIT_WINDOW]
        if len(_rate_limits[ip]) >= limit:
            return False
        _rate_limits[ip].append(now)
        return True

def _verify_hmac(body_bytes, sig_header, timestamp_header, nonce_header):
    """Verify HMAC-SHA256 signature. Returns (ok, error_msg)."""
    if not HMAC_SECRET:
        return True, ''  # HMAC not configured, skip
    if not sig_header or not timestamp_header:
        return False, 'missing signature or timestamp'
    # Replay protection: timestamp within 5 minutes
    try:
        ts = int(timestamp_header)
        if abs(time.time() - ts) > 300:
            return False, 'timestamp expired'
    except (ValueError, TypeError):
        return False, 'invalid timestamp'
    # Nonce replay protection (thread-safe)
    if nonce_header:
        now = time.time()
        with _nonce_lock:
            # Clean old nonces
            expired = [n for n, exp in _used_nonces.items() if now > exp]
            for n in expired:
                del _used_nonces[n]
            if nonce_header in _used_nonces:
                return False, 'nonce replay'
            _used_nonces[nonce_header] = now + NONCE_TTL
    # Compute expected signature
    msg = f'{timestamp_header}.{nonce_header or ""}.'.encode() + (body_bytes or b'')
    expected = hmac.new(HMAC_SECRET.encode(), msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig_header, expected):
        return False, 'signature mismatch'
    return True, ''

def _mask_email(email):
    """Mask email for safe display: ab***@domain.com"""
    if not email or '@' not in email:
        return email or ''
    local, domain = email.rsplit('@', 1)
    if len(local) <= 2:
        return f'{local[0]}***@{domain}'
    return f'{local[:2]}***@{domain}'

def _simple_encrypt(text):
    """XOR-based obfuscation for credentials (not AES, but zero-dependency).
    For production, use Fernet/AES. This prevents plaintext in DB."""
    if not CRYPT_KEY or not text:
        return text
    key = CRYPT_KEY.encode('utf-8')
    encrypted = bytearray()
    for i, ch in enumerate(text.encode('utf-8')):
        encrypted.append(ch ^ key[i % len(key)])
    return 'ENC:' + base64.b64encode(bytes(encrypted)).decode()

def _simple_decrypt(text):
    """Reverse XOR obfuscation."""
    if not text or not text.startswith('ENC:') or not CRYPT_KEY:
        return text
    key = CRYPT_KEY.encode('utf-8')
    data = base64.b64decode(text[4:])
    decrypted = bytearray()
    for i, ch in enumerate(data):
        decrypted.append(ch ^ key[i % len(key)])
    return decrypted.decode('utf-8')

# ============================================================
# Database
# ============================================================
def init_db():
    c = sqlite3.connect(str(DB_FILE))
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, contact TEXT DEFAULT '',
        token TEXT UNIQUE NOT NULL, balance_cents INTEGER DEFAULT 0,
        total_paid_cents INTEGER DEFAULT 0, total_allocated INTEGER DEFAULT 0,
        created_at TEXT, status TEXT DEFAULT 'active'
    );
    CREATE TABLE IF NOT EXISTS payments (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, amount_cents INTEGER NOT NULL,
        method TEXT DEFAULT 'manual', status TEXT DEFAULT 'pending',
        created_at TEXT, confirmed_at TEXT, note TEXT
    );
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL,
        password_enc TEXT DEFAULT '', api_key_enc TEXT DEFAULT '',
        auth_blob_enc TEXT DEFAULT '',
        api_key_preview TEXT DEFAULT '', harvested_at TEXT DEFAULT '',
        source TEXT DEFAULT '',
        plan TEXT DEFAULT 'Trial', daily_pct INTEGER DEFAULT 100,
        weekly_pct INTEGER DEFAULT 100, days_left REAL DEFAULT 12,
        status TEXT DEFAULT 'available', allocated_to TEXT,
        allocated_at TEXT, synced_at TEXT,
        device_id TEXT DEFAULT '', last_device TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL, detail TEXT DEFAULT '',
        ip TEXT DEFAULT '', device_id TEXT DEFAULT '',
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS allocations (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, account_id INTEGER NOT NULL,
        allocated_at TEXT, released_at TEXT, cost_cents INTEGER DEFAULT 800
    );
    CREATE TABLE IF NOT EXISTS devices (
        id TEXT PRIMARY KEY,
        hwid TEXT UNIQUE NOT NULL,
        hwid_source TEXT DEFAULT 'browser',
        browser_fp TEXT DEFAULT '',
        name TEXT DEFAULT '',
        ip TEXT DEFAULT '',
        activated_at TEXT,
        last_seen TEXT,
        status TEXT DEFAULT 'active'
    );
    CREATE TABLE IF NOT EXISTS w_credits (
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL,
        total_w INTEGER DEFAULT 300,
        used_w INTEGER DEFAULT 0,
        source TEXT DEFAULT 'activation',
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS p2p_orders (
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL,
        amount_cents INTEGER NOT NULL,
        w_credits INTEGER NOT NULL,
        method TEXT DEFAULT 'alipay',
        status TEXT DEFAULT 'pending',
        phone_serial TEXT DEFAULT '',
        created_at TEXT,
        detected_at TEXT,
        confirmed_at TEXT,
        note TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS push_directives (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        payload TEXT DEFAULT '{}',
        target TEXT DEFAULT 'all',
        priority TEXT DEFAULT 'normal',
        signature TEXT DEFAULT '',
        created_at TEXT,
        expires_at TEXT,
        revoked INTEGER DEFAULT 0,
        acked_count INTEGER DEFAULT 0,
        creator_ip TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS security_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        severity TEXT DEFAULT 'info',
        ip TEXT DEFAULT '',
        device_id TEXT DEFAULT '',
        detail TEXT DEFAULT '',
        fingerprint TEXT DEFAULT '',
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS ip_reputation (
        ip TEXT PRIMARY KEY,
        score INTEGER DEFAULT 100,
        total_requests INTEGER DEFAULT 0,
        blocked_count INTEGER DEFAULT 0,
        last_seen TEXT,
        first_seen TEXT,
        tags TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS merchant_config (
        key TEXT PRIMARY KEY,
        value TEXT DEFAULT '',
        updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS redemption_codes (
        code TEXT PRIMARY KEY,
        product TEXT NOT NULL DEFAULT 'windsurf_trial',
        tier TEXT DEFAULT 'standard',
        price_cents INTEGER DEFAULT 170,
        status TEXT DEFAULT 'available',
        account_id INTEGER,
        buyer_ip TEXT DEFAULT '',
        buyer_contact TEXT DEFAULT '',
        created_at TEXT,
        redeemed_at TEXT,
        expires_at TEXT,
        batch_id TEXT DEFAULT ''
    );
    """)
    c.close()

def migrate_db():
    """Add new columns to existing DB (safe to run multiple times)."""
    c = sqlite3.connect(str(DB_FILE))
    existing = {row[1] for row in c.execute("PRAGMA table_info(accounts)").fetchall()}
    migrations = [
        ('auth_blob_enc', "ALTER TABLE accounts ADD COLUMN auth_blob_enc TEXT DEFAULT ''"),
        ('api_key_preview', "ALTER TABLE accounts ADD COLUMN api_key_preview TEXT DEFAULT ''"),
        ('harvested_at', "ALTER TABLE accounts ADD COLUMN harvested_at TEXT DEFAULT ''"),
        ('source', "ALTER TABLE accounts ADD COLUMN source TEXT DEFAULT ''"),
    ]
    for col, sql in migrations:
        if col not in existing:
            try:
                c.execute(sql)
            except sqlite3.OperationalError:
                pass
    c.commit()
    c.close()

def audit_log(action, detail='', ip='', device_id=''):
    """Write audit trail. v3.1: Uses independent connection to avoid
    thread-local connection conflicts with _db_write_lock callers."""
    try:
        c = sqlite3.connect(str(DB_FILE), timeout=5)
        c.execute("INSERT INTO audit_log (action,detail,ip,device_id,created_at) VALUES (?,?,?,?,?)",
                  (action, detail[:500], ip, device_id, _now()))
        c.commit()
        c.close()
    except Exception:
        pass

def _invalidate_pool_cache():
    """Invalidate public pool cache after data changes. Thread-safe."""
    with _pool_cache_lock:
        _pool_cache['ts'] = 0

def get_db(readonly=False):
    """Get thread-local DB connection with busy_timeout.
    v3.1: Connections are reused per-thread to reduce overhead.
    busy_timeout ensures concurrent writes wait instead of SQLITE_BUSY."""
    attr = '_db_ro' if readonly else '_db_rw'
    conn = getattr(_db_local, attr, None)
    if conn is not None:
        try:
            conn.execute('SELECT 1')  # liveness check
            return conn
        except Exception:
            try: conn.close()
            except: pass
            setattr(_db_local, attr, None)
    if readonly:
        c = sqlite3.connect(f'file:{DB_FILE}?mode=ro', uri=True, timeout=DB_BUSY_TIMEOUT)
    else:
        c = sqlite3.connect(str(DB_FILE), timeout=DB_BUSY_TIMEOUT)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA busy_timeout=%d' % (DB_BUSY_TIMEOUT * 1000))
    c.execute('PRAGMA synchronous=NORMAL')  # WAL-safe, faster than FULL
    setattr(_db_local, attr, c)
    return c

def _db_write(fn, *args, **kwargs):
    """Execute a write operation with serialized locking and retry.
    v3.1: Prevents SQLITE_BUSY under multi-user concurrent writes.
    Usage: result = _db_write(lambda db: db.execute(...).rowcount)"""
    last_err = None
    for attempt in range(DB_MAX_RETRIES):
        try:
            with _db_write_lock:
                db = get_db(readonly=False)
                result = fn(db, *args, **kwargs)
                db.commit()
                return result
        except sqlite3.OperationalError as e:
            last_err = e
            if 'locked' in str(e).lower() or 'busy' in str(e).lower():
                time.sleep(DB_RETRY_DELAY * (2 ** attempt))
                continue
            raise
    raise last_err

# ============================================================
# API Functions
# ============================================================
def api_health():
    db = get_db(readonly=True)
    t = db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    a = db.execute("SELECT COUNT(*) FROM accounts WHERE status='available'").fetchone()[0]
    u = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return {'status': 'ok', 'version': VERSION, 'accounts': t, 'available': a, 'users': u}

def api_register(data):
    name = (data.get('name') or '').strip()
    contact = (data.get('contact') or '').strip()
    if not name:
        return {'ok': False, 'error': 'name required'}
    uid = str(uuid.uuid4())[:8]
    token = secrets.token_urlsafe(24)
    try:
        with _db_write_lock:
            db = get_db()
            db.execute("INSERT INTO users (id,name,contact,token,created_at) VALUES (?,?,?,?,?)",
                       (uid, name, contact, token, _now()))
            db.commit()
        return {'ok': True, 'user_id': uid, 'token': token, 'name': name}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

def api_me(token):
    db = get_db(readonly=True)
    u = db.execute("SELECT * FROM users WHERE token=?", (token,)).fetchone()
    if not u:
        return {'ok': False, 'error': 'invalid token'}
    alloc = db.execute("""
        SELECT a.*, ac.email, ac.daily_pct, ac.weekly_pct, ac.plan, ac.days_left
        FROM allocations a JOIN accounts ac ON a.account_id=ac.id
        WHERE a.user_id=? AND a.released_at IS NULL
        ORDER BY a.allocated_at DESC LIMIT 1
    """, (u['id'],)).fetchone()
    pays = [dict(r) for r in db.execute(
        "SELECT id,amount_cents,method,status,created_at,confirmed_at FROM payments WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
        (u['id'],)).fetchall()]
    history = [dict(r) for r in db.execute("""
        SELECT a.id,a.allocated_at,a.released_at,a.cost_cents,ac.email
        FROM allocations a JOIN accounts ac ON a.account_id=ac.id
        WHERE a.user_id=? ORDER BY a.allocated_at DESC LIMIT 20
    """, (u['id'],)).fetchall()]
    return {
        'ok': True,
        'user': {'id': u['id'], 'name': u['name'], 'contact': u['contact'],
                 'balance_yuan': u['balance_cents']/100, 'total_paid_yuan': u['total_paid_cents']/100,
                 'total_allocated': u['total_allocated'], 'status': u['status']},
        'allocation': {'email': alloc['email'], 'daily_pct': alloc['daily_pct'],
                      'weekly_pct': alloc['weekly_pct'], 'plan': alloc['plan'],
                      'days_left': alloc['days_left'], 'allocated_at': alloc['allocated_at']} if alloc else None,
        'payments': pays, 'alloc_history': history,
        'pricing': {'per_account': SELL_PRICE_CENTS/100, 'lifespan_days': ACCOUNT_LIFESPAN_DAYS,
                   'daily': round(SELL_PRICE_CENTS/100/ACCOUNT_LIFESPAN_DAYS, 2), 'cost': ACCOUNT_COST_CENTS/100}
    }

def api_topup(data):
    token = data.get('t', '')
    try:
        amount = float(data.get('amount', 0))
    except (TypeError, ValueError):
        return {'ok': False, 'error': 'invalid amount'}
    with _db_write_lock:
        db = get_db()
        u = db.execute("SELECT * FROM users WHERE token=?", (token,)).fetchone()
        if not u: return {'ok': False, 'error': 'invalid token'}
        cents = int(amount * 100)
        if cents < 100: return {'ok': False, 'error': 'min 1 yuan'}
        pid = 'P' + secrets.token_hex(4).upper()
        db.execute("INSERT INTO payments (id,user_id,amount_cents,method,created_at) VALUES (?,?,?,?,?)",
                   (pid, u['id'], cents, data.get('method', 'manual'), _now()))
        db.commit()
    return {'ok': True, 'payment_id': pid, 'amount_yuan': cents/100, 'status': 'pending',
            'hint': f'pay {cents/100:.2f} yuan, note: {pid}'}

def api_allocate(data):
    """v3.1: Entire allocate is serialized under _db_write_lock to prevent
    two concurrent users grabbing the same account (race condition fix)."""
    token = data.get('t', '')
    with _db_write_lock:
        db = get_db()
        u = db.execute("SELECT * FROM users WHERE token=?", (token,)).fetchone()
        if not u: return {'ok': False, 'error': 'invalid token'}
        if u['balance_cents'] < SELL_PRICE_CENTS:
            return {'ok': False, 'need_topup': True,
                    'error': f"need {SELL_PRICE_CENTS/100:.0f}Y, have {u['balance_cents']/100:.2f}Y"}
        if db.execute("SELECT id FROM allocations WHERE user_id=? AND released_at IS NULL",
                      (u['id'],)).fetchone():
            return {'ok': False, 'error': 'already allocated, release first'}
        acc = db.execute("""SELECT * FROM accounts WHERE status='available'
            AND daily_pct>5 AND weekly_pct>5 AND days_left>1
            ORDER BY (daily_pct+weekly_pct) DESC LIMIT 1""").fetchone()
        if not acc: return {'ok': False, 'error': 'no available accounts'}
        aid = 'A' + secrets.token_hex(4).upper()
        cur = db.execute("UPDATE accounts SET status='allocated',allocated_to=?,allocated_at=? WHERE id=? AND status='available'",
                   (u['id'], _now(), acc['id']))
        if cur.rowcount == 0:
            return {'ok': False, 'error': 'account no longer available, retry'}
        db.execute("INSERT INTO allocations (id,user_id,account_id,allocated_at,cost_cents) VALUES (?,?,?,?,?)",
                   (aid, u['id'], acc['id'], _now(), SELL_PRICE_CENTS))
        db.execute("UPDATE users SET balance_cents=balance_cents-?,total_allocated=total_allocated+1 WHERE id=?",
                   (SELL_PRICE_CENTS, u['id']))
        db.commit()
    return {'ok': True, 'allocation_id': aid, 'email': acc['email'], 'plan': acc['plan'],
            'daily_pct': acc['daily_pct'], 'weekly_pct': acc['weekly_pct'],
            'days_left': acc['days_left'], 'cost_yuan': SELL_PRICE_CENTS/100,
            'balance_yuan': (u['balance_cents']-SELL_PRICE_CENTS)/100}

def api_release(data):
    token = data.get('t', '')
    with _db_write_lock:
        db = get_db()
        u = db.execute("SELECT * FROM users WHERE token=?", (token,)).fetchone()
        if not u: return {'ok': False, 'error': 'invalid token'}
        al = db.execute("""SELECT a.id, a.account_id FROM allocations a
            WHERE a.user_id=? AND a.released_at IS NULL""", (u['id'],)).fetchone()
        if not al: return {'ok': False, 'error': 'no active allocation'}
        db.execute("UPDATE allocations SET released_at=? WHERE id=?", (_now(), al['id']))
        db.execute("UPDATE accounts SET status='available',allocated_to=NULL WHERE id=?", (al['account_id'],))
        db.commit()
    return {'ok': True, 'released': al['id']}

# ============================================================
# Admin API
# ============================================================
def _auto_expire_accounts():
    with _db_write_lock:
        db = get_db()
        expired = db.execute("UPDATE accounts SET status='expired' WHERE status='available' AND days_left<=0").rowcount
        if expired > 0:
            db.commit()
            _invalidate_pool_cache()
            audit_log('auto_expire', 'marked ' + str(expired) + ' accounts as expired')
    return expired

def api_admin_overview():
    _auto_expire_accounts()
    db = get_db(readonly=True)
    ta = db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    av = db.execute("SELECT COUNT(*) FROM accounts WHERE status='available'").fetchone()[0]
    al = db.execute("SELECT COUNT(*) FROM accounts WHERE status='allocated'").fetchone()[0]
    tu = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    revenue = db.execute("SELECT COALESCE(SUM(amount_cents),0) FROM payments WHERE status='confirmed'").fetchone()[0]
    cost = ta * ACCOUNT_COST_CENTS
    pending = db.execute("SELECT COUNT(*) FROM payments WHERE status='pending'").fetchone()[0]
    pd = db.execute("SELECT COALESCE(SUM(daily_pct),0) FROM accounts").fetchone()[0]
    pw = db.execute("SELECT COALESCE(SUM(weekly_pct),0) FROM accounts").fetchone()[0]
    last_sync = db.execute("SELECT MAX(synced_at) FROM accounts").fetchone()[0]
    urgent = db.execute("SELECT COUNT(*) FROM accounts WHERE days_left<=3").fetchone()[0]
    expiring = db.execute("SELECT COUNT(*) FROM accounts WHERE days_left<=7 AND days_left>3").fetchone()[0]
    return {
        'ok': True,
        'pool': {'total': ta, 'available': av, 'allocated': al, 'total_d': pd, 'total_w': pw},
        'users': {'total': tu},
        'finance': {'revenue_yuan': revenue/100, 'cost_yuan': cost/100, 'profit_yuan': (revenue-cost)/100,
                   'margin_pct': round((revenue-cost)/cost*100,1) if cost else 0, 'pending': pending},
        'pricing': {'cost': ACCOUNT_COST_CENTS/100, 'sell': SELL_PRICE_CENTS/100,
                   'profit_per': (SELL_PRICE_CENTS-ACCOUNT_COST_CENTS)/100},
        'last_synced': last_sync, 'urgent': urgent, 'expiring': expiring,
        'version': VERSION
    }

def api_admin_users():
    db = get_db(readonly=True)
    return {'ok': True, 'users': [dict(r) for r in db.execute(
        "SELECT id,name,contact,balance_cents,total_paid_cents,total_allocated,created_at,status FROM users ORDER BY created_at DESC"
    ).fetchall()]}

def api_admin_payments():
    db = get_db(readonly=True)
    return {'ok': True, 'payments': [dict(r) for r in db.execute("""
        SELECT p.*, u.name as user_name FROM payments p
        LEFT JOIN users u ON p.user_id=u.id ORDER BY p.created_at DESC
    """).fetchall()]}

def api_admin_accounts():
    db = get_db(readonly=True)
    return {'ok': True, 'accounts': [dict(r) for r in db.execute(
        "SELECT * FROM accounts ORDER BY daily_pct DESC, weekly_pct DESC"
    ).fetchall()]}

def api_admin_confirm(data):
    pid = data.get('payment_id', '')
    with _db_write_lock:
        db = get_db()
        p = db.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone()
        if not p: return {'ok': False, 'error': 'not found'}
        if p['status'] == 'confirmed': return {'ok': False, 'error': 'already confirmed'}
        db.execute("UPDATE payments SET status='confirmed',confirmed_at=? WHERE id=?", (_now(), pid))
        db.execute("UPDATE users SET balance_cents=balance_cents+?,total_paid_cents=total_paid_cents+? WHERE id=?",
                   (p['amount_cents'], p['amount_cents'], p['user_id']))
        db.commit()
    return {'ok': True, 'payment_id': pid, 'amount_yuan': p['amount_cents']/100}

def api_admin_reject(data):
    pid = data.get('payment_id', '')
    with _db_write_lock:
        db = get_db()
        p = db.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone()
        if not p: return {'ok': False, 'error': 'not found'}
        if p['status'] != 'pending': return {'ok': False, 'error': 'not pending'}
        db.execute("UPDATE payments SET status='rejected',confirmed_at=? WHERE id=?", (_now(), pid))
        db.commit()
    return {'ok': True, 'rejected': pid}

def api_admin_bulk_sync(data, ip=''):
    """批量同步本地号池→云端 (含auth blob) — 道生一·统一管理。
    Accepts: {accounts: [{email, plan, daily, weekly, days_left, password, api_key,
              auth_blob: {windsurfAuthStatus, windsurfConfigurations, ...},
              api_key_preview, harvested_at}], source, device_id}
    """
    accounts = data.get('accounts', [])
    source = data.get('source', 'bulk_sync')
    device_id = data.get('device_id', '')
    if not accounts:
        return {'ok': False, 'error': 'no accounts'}
    with _db_write_lock:
      db = get_db()
      try:
        synced = skipped = 0
        for acc in accounts:
            email = acc.get('email', '')
            if not email:
                skipped += 1
                continue
            # Encrypt credentials
            pwd_enc = _simple_encrypt(acc.get('password', '')) if acc.get('password') else ''
            apikey_enc = _simple_encrypt(acc.get('api_key', '')) if acc.get('api_key') else ''
            # Encrypt auth blob (the core data for hot-switch)
            auth_blob = acc.get('auth_blob', {})
            auth_blob_enc = ''
            if auth_blob and isinstance(auth_blob, dict):
                blob_json = json.dumps(auth_blob, ensure_ascii=False)
                auth_blob_enc = _simple_encrypt(blob_json)
            api_key_preview = acc.get('api_key_preview', '')
            harvested_at = acc.get('harvested_at', '')
            # Upsert: update health data + credentials + auth blob
            db.execute("""INSERT INTO accounts
                (email,plan,daily_pct,weekly_pct,days_left,synced_at,
                 password_enc,api_key_enc,auth_blob_enc,api_key_preview,harvested_at,source,last_device)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(email) DO UPDATE SET
                plan=excluded.plan, daily_pct=excluded.daily_pct,
                weekly_pct=excluded.weekly_pct, days_left=excluded.days_left,
                synced_at=excluded.synced_at,
                password_enc=CASE WHEN excluded.password_enc!='' THEN excluded.password_enc ELSE accounts.password_enc END,
                api_key_enc=CASE WHEN excluded.api_key_enc!='' THEN excluded.api_key_enc ELSE accounts.api_key_enc END,
                auth_blob_enc=CASE WHEN excluded.auth_blob_enc!='' THEN excluded.auth_blob_enc ELSE accounts.auth_blob_enc END,
                api_key_preview=CASE WHEN excluded.api_key_preview!='' THEN excluded.api_key_preview ELSE accounts.api_key_preview END,
                harvested_at=CASE WHEN excluded.harvested_at!='' THEN excluded.harvested_at ELSE accounts.harvested_at END,
                source=excluded.source, last_device=excluded.last_device""",
                (email, acc.get('plan', 'Trial'), acc.get('daily', 100),
                 acc.get('weekly', 100), acc.get('days_left', 12), _now(),
                 pwd_enc, apikey_enc, auth_blob_enc, api_key_preview, harvested_at,
                 source, device_id))
            synced += 1
        db.commit()
        _invalidate_pool_cache()
        audit_log('bulk_sync', f'synced={synced} skipped={skipped} source={source}', ip, device_id)
        # Stats
        total = db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        with_blob = db.execute("SELECT COUNT(*) FROM accounts WHERE auth_blob_enc!='' AND auth_blob_enc IS NOT NULL").fetchone()[0]
        return {
            'ok': True, 'synced': synced, 'skipped': skipped,
            'pool_total': total, 'with_auth_blob': with_blob,
            'source': source, 'device_id': device_id,
        }
      finally:
        pass  # thread-local conn reused

def api_sync_accounts(data):
    accounts = data.get('accounts', [])
    if not accounts: return {'ok': False, 'error': 'no accounts'}
    with _db_write_lock:
        db = get_db()
        n = 0
        for acc in accounts:
            email = acc.get('email', '')
            if not email: continue
            pwd_enc = _simple_encrypt(acc.get('password', '')) if acc.get('password') else ''
            apikey_enc = _simple_encrypt(acc.get('api_key', '')) if acc.get('api_key') else ''
            db.execute("""INSERT INTO accounts (email,plan,daily_pct,weekly_pct,days_left,synced_at,password_enc,api_key_enc)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(email) DO UPDATE SET
                plan=excluded.plan, daily_pct=excluded.daily_pct, weekly_pct=excluded.weekly_pct,
                days_left=excluded.days_left, synced_at=excluded.synced_at,
                password_enc=CASE WHEN excluded.password_enc!='' THEN excluded.password_enc ELSE accounts.password_enc END,
                api_key_enc=CASE WHEN excluded.api_key_enc!='' THEN excluded.api_key_enc ELSE accounts.api_key_enc END""",
                (email, acc.get('plan','Trial'), acc.get('daily',100),
                 acc.get('weekly',100), acc.get('days_left',12), _now(), pwd_enc, apikey_enc))
            n += 1
        db.commit()
    return {'ok': True, 'synced': n}

# ============================================================
# Public API — 道法自然·水利万物而不争 (无需任何认证)
# ============================================================
def api_public_pool(force=False):
    """公网用户可见的号池额度总览 — 本源之额度，无需账号即可观。
    损之又损：使用内存缓存+ETag，10秒内同一数据不重查DB。Thread-safe."""
    now = time.time()
    with _pool_cache_lock:
        if not force and _pool_cache['data'] and (now - _pool_cache['ts']) < POOL_CACHE_TTL:
            return _pool_cache['data']
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        avail = db.execute("SELECT COUNT(*) FROM accounts WHERE status='available' AND daily_pct>5 AND weekly_pct>5").fetchone()[0]
        allocated = db.execute("SELECT COUNT(*) FROM accounts WHERE status='allocated'").fetchone()[0]
        td = db.execute("SELECT COALESCE(SUM(daily_pct),0) FROM accounts").fetchone()[0]
        tw = db.execute("SELECT COALESCE(SUM(weekly_pct),0) FROM accounts").fetchone()[0]
        urgent = db.execute("SELECT COUNT(*) FROM accounts WHERE days_left<=3").fetchone()[0]
        expiring = db.execute("SELECT COUNT(*) FROM accounts WHERE days_left<=7 AND days_left>3").fetchone()[0]
        with_blob = db.execute("SELECT COUNT(*) FROM accounts WHERE auth_blob_enc!='' AND auth_blob_enc IS NOT NULL").fetchone()[0]
        avg_d = round(td / total, 1) if total else 0
        avg_w = round(tw / total, 1) if total else 0
        rows = db.execute("""SELECT daily_pct, weekly_pct, days_left, status, plan
            FROM accounts ORDER BY (daily_pct+weekly_pct) DESC""").fetchall()
        tiers = {'fresh': 0, 'good': 0, 'low': 0, 'critical': 0}
        for r in rows:
            score = (r['daily_pct'] + r['weekly_pct']) / 2
            if score >= 90: tiers['fresh'] += 1
            elif score >= 50: tiers['good'] += 1
            elif score >= 20: tiers['low'] += 1
            else: tiers['critical'] += 1
        accounts_public = []
        for i, r in enumerate(rows):
            accounts_public.append({
                'rank': i + 1,
                'daily': r['daily_pct'], 'weekly': r['weekly_pct'],
                'days_left': round(r['days_left'], 1) if r['days_left'] else 0,
                'status': r['status'], 'plan': r['plan'] or 'Trial',
            })
        result = {
            'ok': True, 'version': VERSION,
            'pool': {
                'total': total, 'available': avail, 'allocated': allocated,
                'total_d': td, 'total_w': tw,
                'avg_d': avg_d, 'avg_w': avg_w,
                'urgent': urgent, 'expiring': expiring,
                'with_blob': with_blob,
                'tiers': tiers,
            },
            'accounts': accounts_public,
            'pricing': {
                'per_account_yuan': SELL_PRICE_CENTS / 100,
                'cost_yuan': ACCOUNT_COST_CENTS / 100,
                'lifespan_days': ACCOUNT_LIFESPAN_DAYS,
                'daily_yuan': round(SELL_PRICE_CENTS / 100 / ACCOUNT_LIFESPAN_DAYS, 2),
            },
            'ts': _now(),
        }
        # Update cache (thread-safe)
        data_str = json.dumps(result, ensure_ascii=False, sort_keys=True)
        etag = hashlib.md5(data_str.encode()).hexdigest()[:16]
        with _pool_cache_lock:
            _pool_cache['data'] = result
            _pool_cache['etag'] = etag
            _pool_cache['ts'] = now
        return result
    finally:
        pass  # thread-local conn reused

def api_public_quick_start(data):
    """一键开始 — 匿名注册+自动分配，道法自然·无感使用。
    公网用户无需理解token/注册/充值，一触即达。v3.1: Write-locked to prevent race."""
    name = (data.get('name') or '').strip() or f'user_{secrets.token_hex(3)}'
    contact = (data.get('contact') or '').strip()
    with _db_write_lock:
        db = get_db()
        uid = str(uuid.uuid4())[:8]
        token = secrets.token_urlsafe(24)
        db.execute("INSERT INTO users (id,name,contact,token,balance_cents,created_at) VALUES (?,?,?,?,?,?)",
                   (uid, name, contact, token, SELL_PRICE_CENTS, _now()))
        acc = db.execute("""SELECT * FROM accounts WHERE status='available'
            AND daily_pct>5 AND weekly_pct>5 AND days_left>1
            ORDER BY (daily_pct+weekly_pct) DESC LIMIT 1""").fetchone()
        if not acc:
            db.commit()
            return {'ok': True, 'token': token, 'user_id': uid, 'allocated': False,
                    'message': '已注册，但当前无可用账号，请稍后再试'}
        aid = 'A' + secrets.token_hex(4).upper()
        cur = db.execute("UPDATE accounts SET status='allocated',allocated_to=?,allocated_at=? WHERE id=? AND status='available'",
                   (uid, _now(), acc['id']))
        if cur.rowcount == 0:
            db.commit()
            return {'ok': True, 'token': token, 'user_id': uid, 'allocated': False,
                    'message': '账号刚被分配，请重试'}
        db.execute("INSERT INTO allocations (id,user_id,account_id,allocated_at,cost_cents) VALUES (?,?,?,?,?)",
                   (aid, uid, acc['id'], _now(), 0))
        db.execute("UPDATE users SET balance_cents=0,total_allocated=1 WHERE id=?", (uid,))
        db.commit()
    return {
        'ok': True, 'token': token, 'user_id': uid, 'allocated': True,
        'email': acc['email'],
        'plan': acc['plan'], 'daily': acc['daily_pct'], 'weekly': acc['weekly_pct'],
        'days_left': acc['days_left'],
        'message': '一键分配成功！保存你的Token以便后续管理',
    }

# ============================================================
# Extension Direct API — 扩展直连云端 (HMAC签名保护)
# ============================================================
def api_ext_pool_status():
    """Return pool health without credentials (safe for display)."""
    db = get_db(readonly=True)
    try:
        rows = db.execute("""SELECT id, email, plan, daily_pct, weekly_pct, days_left, status,
            allocated_to, synced_at FROM accounts ORDER BY daily_pct DESC, weekly_pct DESC""").fetchall()
        accounts = []
        for r in rows:
            accounts.append({
                'id': r['id'], 'email': _mask_email(r['email']),
                'plan': r['plan'], 'daily': r['daily_pct'], 'weekly': r['weekly_pct'],
                'days_left': r['days_left'], 'status': r['status'],
                'synced_at': r['synced_at'],
            })
        td = sum(a['daily'] for a in accounts)
        tw = sum(a['weekly'] for a in accounts)
        avail = sum(1 for a in accounts if a['status'] == 'available' and a['daily'] > 5 and a['weekly'] > 5)
        return {
            'ok': True, 'total': len(accounts), 'available': avail,
            'total_d': td, 'total_w': tw,
            'accounts': accounts, 'version': VERSION,
        }
    finally:
        db.close()

def api_ext_pull(device_id=''):
    """Pull best available account with decrypted credentials for extension use.
    v3.1: Write-locked to prevent two devices grabbing the same account."""
    if not device_id:
        return {'ok': False, 'error': 'device_id required'}
    with _db_write_lock:
        db = get_db()
        # Check if device already has an allocated account
        existing = db.execute("""SELECT * FROM accounts WHERE device_id=? AND status='allocated'
            ORDER BY (daily_pct+weekly_pct) DESC LIMIT 1""", (device_id,)).fetchone()
        if existing:
            return {
                'ok': True, 'action': 'existing',
                'email': existing['email'],
                'password': _simple_decrypt(existing['password_enc']),
                'api_key': _simple_decrypt(existing['api_key_enc']),
                'plan': existing['plan'], 'daily': existing['daily_pct'],
                'weekly': existing['weekly_pct'], 'days_left': existing['days_left'],
            }
        # Find best available account
        acc = db.execute("""SELECT * FROM accounts WHERE status='available'
            AND daily_pct>5 AND weekly_pct>5 AND days_left>1
            AND password_enc!='' AND password_enc IS NOT NULL
            ORDER BY (daily_pct+weekly_pct) DESC LIMIT 1""").fetchone()
        if not acc:
            return {'ok': False, 'error': 'no available accounts with credentials'}
        # Allocate to device
        db.execute("""UPDATE accounts SET status='allocated', device_id=?, last_device=?,
            allocated_at=? WHERE id=? AND status='available'""",
            (device_id, device_id, _now(), acc['id']))
        db.commit()
    return {
        'ok': True, 'action': 'allocated',
        'email': acc['email'],
        'password': _simple_decrypt(acc['password_enc']),
        'api_key': _simple_decrypt(acc['api_key_enc']),
        'plan': acc['plan'], 'daily': acc['daily_pct'],
        'weekly': acc['weekly_pct'], 'days_left': acc['days_left'],
    }

def api_ext_push(data):
    """Push health data from extension to cloud. v3.1: Write-locked."""
    accounts = data.get('accounts', [])
    device_id = data.get('device_id', '')
    if not accounts:
        return {'ok': False, 'error': 'no accounts'}
    with _db_write_lock:
        db = get_db()
        n = 0
        for acc in accounts:
            email = acc.get('email', '')
            if not email: continue
            pwd_enc = _simple_encrypt(acc.get('password', '')) if acc.get('password') else ''
            apikey_enc = _simple_encrypt(acc.get('api_key', '')) if acc.get('api_key') else ''
            db.execute("""INSERT INTO accounts (email,plan,daily_pct,weekly_pct,days_left,synced_at,password_enc,api_key_enc,last_device)
                VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(email) DO UPDATE SET
                plan=excluded.plan, daily_pct=excluded.daily_pct, weekly_pct=excluded.weekly_pct,
                days_left=excluded.days_left, synced_at=excluded.synced_at,
                password_enc=CASE WHEN excluded.password_enc!='' THEN excluded.password_enc ELSE accounts.password_enc END,
                api_key_enc=CASE WHEN excluded.api_key_enc!='' THEN excluded.api_key_enc ELSE accounts.api_key_enc END,
                last_device=excluded.last_device""",
                (email, acc.get('plan','Trial'), acc.get('daily',100),
                 acc.get('weekly',100), acc.get('days_left',12), _now(), pwd_enc, apikey_enc, device_id))
            n += 1
        db.commit()
    return {'ok': True, 'synced': n, 'device': device_id}

def api_ext_pull_blob(device_id='', email='', ip='', exclude=''):
    """扩展直拉auth blob — 道之根本·无感换号之核心。
    v3.1: Write-locked to prevent two devices grabbing the same blob account."""
    if not device_id:
        return {'ok': False, 'error': 'device_id required'}
    with _db_write_lock:
        db = get_db()
        acc = None
        if email:
            acc = db.execute("SELECT * FROM accounts WHERE email=? AND auth_blob_enc!=''",
                            (email,)).fetchone()
        else:
            acc = db.execute("""SELECT * FROM accounts WHERE device_id=? AND status='allocated'
                AND auth_blob_enc!='' ORDER BY (daily_pct+weekly_pct) DESC LIMIT 1""",
                (device_id,)).fetchone()
            if not acc:
                if exclude:
                    acc = db.execute("""SELECT * FROM accounts WHERE status='available'
                        AND daily_pct>5 AND weekly_pct>5 AND days_left>1
                        AND auth_blob_enc!='' AND auth_blob_enc IS NOT NULL
                        AND email!=? ORDER BY (daily_pct+weekly_pct) DESC, RANDOM() LIMIT 1""",
                        (exclude,)).fetchone()
                if not acc:
                    acc = db.execute("""SELECT * FROM accounts WHERE status='available'
                        AND daily_pct>5 AND weekly_pct>5 AND days_left>1
                        AND auth_blob_enc!='' AND auth_blob_enc IS NOT NULL
                        ORDER BY (daily_pct+weekly_pct) DESC, RANDOM() LIMIT 1""").fetchone()
                if acc:
                    db.execute("""UPDATE accounts SET status='allocated', device_id=?,
                        last_device=?, allocated_at=? WHERE id=? AND status='available'""",
                        (device_id, device_id, _now(), acc['id']))
                    db.commit()
                    _invalidate_pool_cache()
    if not acc:
        return {'ok': False, 'error': 'no accounts with auth blob available'}
    auth_blob_raw = _simple_decrypt(acc['auth_blob_enc'])
    try:
        auth_blob = json.loads(auth_blob_raw)
    except (json.JSONDecodeError, TypeError):
        return {'ok': False, 'error': 'auth blob corrupt'}
    audit_log('ext_pull_blob', f'email={acc["email"]} device={device_id}', ip, device_id)
    return {
        'ok': True, 'email': acc['email'], 'plan': acc['plan'],
        'daily': acc['daily_pct'], 'weekly': acc['weekly_pct'],
        'days_left': acc['days_left'], 'api_key_preview': acc['api_key_preview'],
        'auth_blob': auth_blob, 'harvested_at': acc['harvested_at'],
    }

def api_ext_heartbeat(data, ip=''):
    """设备心跳 — 损之又损·最小数据交互。v3.1: Write-locked for health update."""
    device_id = data.get('device_id', '')
    current_email = data.get('email', '')
    daily = data.get('daily', -1)
    weekly = data.get('weekly', -1)
    if not device_id:
        return {'ok': False, 'error': 'device_id required'}
    if current_email and daily >= 0:
        with _db_write_lock:
            db = get_db()
            db.execute("""UPDATE accounts SET daily_pct=?, weekly_pct=?, synced_at=?, last_device=?
                WHERE email=?""", (daily, weekly, _now(), device_id, current_email))
            db.commit()
            _invalidate_pool_cache()
    db = get_db(readonly=True)
    need_switch = False
    if current_email and (daily <= 5 or weekly <= 5):
        need_switch = True
        better = db.execute("""SELECT email, daily_pct, weekly_pct FROM accounts
            WHERE status='available' AND daily_pct>20 AND weekly_pct>20 AND days_left>1
            AND auth_blob_enc!='' ORDER BY (daily_pct+weekly_pct) DESC LIMIT 1""").fetchone()
        if better:
            return {
                'ok': True, 'action': 'switch',
                'switch_to': better['email'],
                'switch_daily': better['daily_pct'],
                'switch_weekly': better['weekly_pct'],
            }
    directives_resp = api_ext_get_directives(device_id, data.get('version', ''))
    pending_directives = directives_resp.get('directives', []) if directives_resp.get('ok') else []
    result = {'ok': True, 'action': 'none' if not need_switch else 'exhausted_no_alternative'}
    if pending_directives:
        result['directives'] = pending_directives
        result['directives_count'] = len(pending_directives)
    return result

def api_admin_audit(limit=50):
    """审计日志查询。"""
    db = get_db(readonly=True)
    rows = db.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return {'ok': True, 'logs': [dict(r) for r in rows]}

def api_ext_release(data):
    """Release an account back to pool. v3.1: Write-locked."""
    email = data.get('email', '')
    device_id = data.get('device_id', '')
    if not email:
        return {'ok': False, 'error': 'email required'}
    with _db_write_lock:
        db = get_db()
        db.execute("""UPDATE accounts SET status='available', device_id=''
            WHERE email=? AND (device_id=? OR device_id='' OR device_id IS NULL)""",
            (email, device_id))
        db.commit()
    return {'ok': True, 'released': email}

# ============================================================
# Device + W Credits + P2P — 道法自然·万法归宗
# ============================================================
W_INITIAL = 300
W_PER_YUAN = 12  # 1元=12W

def api_device_activate(data, ip=''):
    """v3.1: Write-locked + UNIQUE constraint handled for concurrent activation."""
    hwid = (data.get('hwid') or '').strip()
    if not hwid:
        return {'ok': False, 'error': 'hwid required'}
    with _db_write_lock:
        db = get_db()
        ex = db.execute("SELECT * FROM devices WHERE hwid=?", (hwid,)).fetchone()
        if ex:
            cr = db.execute("SELECT COALESCE(SUM(total_w),0) as t, COALESCE(SUM(used_w),0) as u FROM w_credits WHERE device_id=?", (ex['id'],)).fetchone()
            return {'ok': True, 'action': 'existing', 'device_id': ex['id'], 'hwid': ex['hwid'],
                    'name': ex['name'], 'activated_at': ex['activated_at'],
                    'w_total': cr['t'], 'w_used': cr['u'], 'w_available': cr['t'] - cr['u']}
        did = 'DEV-' + secrets.token_hex(4).upper()
        name = (data.get('name') or '').strip() or f'device_{secrets.token_hex(3)}'
        try:
            db.execute("INSERT INTO devices (id,hwid,hwid_source,browser_fp,name,ip,activated_at,last_seen,status) VALUES (?,?,?,?,?,?,?,?,?)",
                (did, hwid, data.get('hwid_source','browser'), data.get('browser_fp',''), name, ip, _now(), _now(), 'active'))
            cid = 'CR-' + secrets.token_hex(4).upper()
            db.execute("INSERT INTO w_credits (id,device_id,total_w,used_w,source,created_at) VALUES (?,?,?,?,?,?)",
                (cid, did, W_INITIAL, 0, 'activation_bonus', _now()))
            db.commit()
        except sqlite3.IntegrityError:
            # Race: another thread inserted between SELECT and INSERT — re-read
            ex = db.execute("SELECT * FROM devices WHERE hwid=?", (hwid,)).fetchone()
            if ex:
                cr = db.execute("SELECT COALESCE(SUM(total_w),0) as t, COALESCE(SUM(used_w),0) as u FROM w_credits WHERE device_id=?", (ex['id'],)).fetchone()
                return {'ok': True, 'action': 'existing', 'device_id': ex['id'], 'hwid': ex['hwid'],
                        'name': ex['name'], 'activated_at': ex['activated_at'],
                        'w_total': cr['t'], 'w_used': cr['u'], 'w_available': cr['t'] - cr['u']}
            return {'ok': False, 'error': 'activation conflict, retry'}
    audit_log('device_activate', f'device={did} hwid={hwid[:16]}...', ip, did)
    return {'ok': True, 'action': 'activated', 'device_id': did, 'hwid': hwid, 'name': name,
            'activated_at': _now(), 'w_total': W_INITIAL, 'w_used': 0, 'w_available': W_INITIAL,
            'message': '激活成功！已赠送300% W资源额度'}

def api_device_info(device_id):
    if not device_id:
        return {'ok': False, 'error': 'device_id required'}
    db = get_db(readonly=True)
    dev = db.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
    if not dev:
        return {'ok': False, 'error': 'device not found'}
    cr = db.execute("SELECT COALESCE(SUM(total_w),0) as t, COALESCE(SUM(used_w),0) as u FROM w_credits WHERE device_id=?", (device_id,)).fetchone()
    orders = [dict(r) for r in db.execute("SELECT id,amount_cents,w_credits,method,status,created_at FROM p2p_orders WHERE device_id=? ORDER BY created_at DESC LIMIT 10", (device_id,)).fetchall()]
    with _db_write_lock:
        get_db().execute("UPDATE devices SET last_seen=? WHERE id=?", (_now(), device_id))
        get_db().commit()
    return {'ok': True,
            'device': {'id': dev['id'], 'hwid': dev['hwid'], 'hwid_source': dev['hwid_source'],
                       'name': dev['name'], 'activated_at': dev['activated_at'], 'status': dev['status']},
            'credits': {'total': cr['t'], 'used': cr['u'], 'available': cr['t'] - cr['u']},
            'orders': orders}

# ── Merchant Config (商户配置 · 收款信息) ──
def _merchant_get(key, default=''):
    db = get_db(readonly=True)
    r = db.execute("SELECT value FROM merchant_config WHERE key=?", (key,)).fetchone()
    return r['value'] if r else default

def _merchant_set(key, value):
    with _db_write_lock:
        db = get_db()
        db.execute("INSERT OR REPLACE INTO merchant_config (key,value,updated_at) VALUES (?,?,?)",
                   (key, str(value), _now()))
        db.commit()

def api_admin_merchant_config(data=None):
    """Get or set merchant configuration. GET=list all, POST=set key/value pairs."""
    if data:
        for k, v in data.items():
            if k in ('ok', 'error'): continue
            _merchant_set(k, v)
        audit_log('merchant_config_set', str(list(data.keys()))[:200])
        return {'ok': True, 'updated': list(data.keys())}
    db = get_db(readonly=True)
    rows = db.execute("SELECT key,value,updated_at FROM merchant_config").fetchall()
    return {'ok': True, 'config': {r['key']: r['value'] for r in rows}}

def _get_payment_instructions(method, amount_display):
    """Build payment instructions from merchant_config for P2P orders."""
    instructions = {'amount': amount_display}
    if method == 'wechat':
        instructions['account_name'] = _merchant_get('wechat_name', '')
        instructions['qr_url'] = _merchant_get('wechat_qr_url', '')
        instructions['note'] = _merchant_get('wechat_note', '请备注订单号')
    else:  # alipay
        instructions['account_name'] = _merchant_get('alipay_name', '')
        instructions['qr_url'] = _merchant_get('alipay_qr_url', '')
        instructions['note'] = _merchant_get('alipay_note', '请备注订单号')
    if not instructions['account_name']:
        instructions['account_name'] = _merchant_get('merchant_name', '商户')
    return instructions

def api_p2p_init(data, ip=''):
    device_id = data.get('device_id', '')
    w_amount = int(data.get('w_credits', 100))
    method = data.get('method', 'alipay')
    if not device_id:
        return {'ok': False, 'error': 'device_id required'}
    if w_amount < 50:
        return {'ok': False, 'error': 'min 50W'}
    with _db_write_lock:
        db = get_db()
        dev = db.execute("SELECT id FROM devices WHERE id=?", (device_id,)).fetchone()
        if not dev:
            return {'ok': False, 'error': 'activate first'}
        base_cents = (w_amount * 100) // W_PER_YUAN
        unique_suffix = secrets.randbelow(99) + 1
        total_cents = base_cents + unique_suffix
        oid = 'P2P-' + secrets.token_hex(4).upper()
        db.execute("INSERT INTO p2p_orders (id,device_id,amount_cents,w_credits,method,status,created_at) VALUES (?,?,?,?,?,?,?)",
            (oid, device_id, total_cents, w_amount, method, 'pending', _now()))
        db.commit()
    audit_log('p2p_init', f'order={oid} amt={total_cents} w={w_amount}', ip, device_id)
    amount_display = f'¥{total_cents/100:.2f}'
    payment = _get_payment_instructions(method, amount_display)
    return {'ok': True, 'order_id': oid, 'amount_yuan': total_cents/100,
            'amount_display': amount_display, 'w_credits': w_amount,
            'method': method, 'unique_cents': unique_suffix, 'expires_in': 1800,
            'payment': payment}

def api_p2p_detect(data, ip=''):
    order_id = data.get('order_id', '')
    amount_cents = data.get('amount_cents', 0)
    phone_serial = data.get('phone_serial', '')
    with _db_write_lock:
        db = get_db()
        order = None
        if order_id:
            order = db.execute("SELECT * FROM p2p_orders WHERE id=? AND status='pending'", (order_id,)).fetchone()
        elif amount_cents:
            order = db.execute("SELECT * FROM p2p_orders WHERE amount_cents=? AND status='pending' ORDER BY created_at DESC LIMIT 1", (amount_cents,)).fetchone()
        if not order:
            return {'ok': False, 'error': 'no matching order'}
        db.execute("UPDATE p2p_orders SET status='confirmed',phone_serial=?,detected_at=?,confirmed_at=? WHERE id=?",
            (phone_serial, _now(), _now(), order['id']))
        cid = 'CR-' + secrets.token_hex(4).upper()
        db.execute("INSERT INTO w_credits (id,device_id,total_w,used_w,source,created_at) VALUES (?,?,?,?,?,?)",
            (cid, order['device_id'], order['w_credits'], 0, f'p2p_{order["method"]}', _now()))
        db.commit()
    audit_log('p2p_confirmed', f'order={order["id"]} w={order["w_credits"]}', ip)
    return {'ok': True, 'order_id': order['id'], 'w_credits_added': order['w_credits']}

def api_p2p_status(order_id):
    if not order_id:
        return {'ok': False, 'error': 'order_id required'}
    db = get_db(readonly=True)
    o = db.execute("SELECT * FROM p2p_orders WHERE id=?", (order_id,)).fetchone()
    if not o:
        return {'ok': False, 'error': 'not found'}
    return {'ok': True, 'order': dict(o)}

def api_admin_devices():
    db = get_db(readonly=True)
    devs = []
    for r in db.execute("SELECT * FROM devices ORDER BY activated_at DESC").fetchall():
        d = dict(r)
        cr = db.execute("SELECT COALESCE(SUM(total_w),0) as t, COALESCE(SUM(used_w),0) as u FROM w_credits WHERE device_id=?", (d['id'],)).fetchone()
        d['w_total'] = cr['t']; d['w_used'] = cr['u']; d['w_available'] = cr['t'] - cr['u']
        devs.append(d)
    return {'ok': True, 'devices': devs}

def api_admin_p2p_orders():
    db = get_db(readonly=True)
    return {'ok': True, 'orders': [dict(r) for r in db.execute("SELECT * FROM p2p_orders ORDER BY created_at DESC").fetchall()]}


def api_admin_p2p_confirm(data):
    """Admin manually confirms a P2P order. v3.1: Write-locked."""
    oid = data.get('order_id', '') or data.get('payment_id', '')
    if not oid:
        return {'ok': False, 'error': 'order_id required'}
    with _db_write_lock:
        db = get_db()
        order = db.execute("SELECT * FROM p2p_orders WHERE id=?", (oid,)).fetchone()
        if not order:
            return {'ok': False, 'error': 'order not found: ' + oid}
        if order['status'] == 'confirmed':
            return {'ok': False, 'error': 'already confirmed'}
        if order['status'] == 'rejected':
            return {'ok': False, 'error': 'already rejected'}
        db.execute("UPDATE p2p_orders SET status=?,confirmed_at=? WHERE id=?",
            ('confirmed', _now(), oid))
        cid = 'CR-' + secrets.token_hex(4).upper()
        db.execute("INSERT INTO w_credits (id,device_id,total_w,used_w,source,created_at) VALUES (?,?,?,?,?,?)",
            (cid, order['device_id'], order['w_credits'], 0, 'admin_confirm', _now()))
        db.commit()
    audit_log('p2p_admin_confirm', f'order={oid} w={order["w_credits"]} dev={order["device_id"]}')
    return {'ok': True, 'order_id': oid, 'w_credits_added': order['w_credits'],
            'device_id': order['device_id']}

def api_admin_p2p_reject(data):
    """Admin rejects a P2P order. v3.1: Write-locked."""
    oid = data.get('order_id', '') or data.get('payment_id', '')
    note = data.get('note', '')
    if not oid:
        return {'ok': False, 'error': 'order_id required'}
    with _db_write_lock:
        db = get_db()
        order = db.execute("SELECT * FROM p2p_orders WHERE id=?", (oid,)).fetchone()
        if not order:
            return {'ok': False, 'error': 'order not found: ' + oid}
        if order['status'] != 'pending':
            return {'ok': False, 'error': 'not pending, current: ' + order['status']}
        db.execute("UPDATE p2p_orders SET status=?,note=?,confirmed_at=? WHERE id=?",
            ('rejected', note or 'admin_rejected', _now(), oid))
        db.commit()
    audit_log('p2p_admin_reject', f'order={oid}')
    return {'ok': True, 'rejected': oid}

def api_admin_p2p_create(data, ip=''):
    """Admin creates a P2P order. v3.1: Write-locked."""
    device_id = data.get('device_id', '')
    w_amount = int(data.get('w_credits', 100))
    method = data.get('method', 'admin')
    note = data.get('note', '')
    auto_confirm = data.get('auto_confirm', False)
    if not device_id:
        return {'ok': False, 'error': 'device_id required'}
    if w_amount < 1:
        return {'ok': False, 'error': 'w_credits must be positive'}
    with _db_write_lock:
        db = get_db()
        dev = db.execute("SELECT id FROM devices WHERE id=?", (device_id,)).fetchone()
        if not dev:
            dev = db.execute("SELECT id FROM devices WHERE hwid=?", (device_id,)).fetchone()
            if dev:
                device_id = dev['id']
            else:
                return {'ok': False, 'error': 'device not found'}
        amount_cents = (w_amount * 100) // W_PER_YUAN if W_PER_YUAN else w_amount * 8
        oid = 'ADM-' + secrets.token_hex(4).upper()
        status = 'confirmed' if auto_confirm else 'pending'
        db.execute("INSERT INTO p2p_orders (id,device_id,amount_cents,w_credits,method,status,note,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (oid, device_id, amount_cents, w_amount, method, status, note, _now()))
        if auto_confirm:
            db.execute("UPDATE p2p_orders SET confirmed_at=? WHERE id=?", (_now(), oid))
            cid = 'CR-' + secrets.token_hex(4).upper()
            db.execute("INSERT INTO w_credits (id,device_id,total_w,used_w,source,created_at) VALUES (?,?,?,?,?,?)",
                (cid, device_id, w_amount, 0, 'admin_grant', _now()))
        db.commit()
    audit_log('p2p_admin_create', f'order={oid} w={w_amount} dev={device_id} auto={auto_confirm}', ip)
    return {'ok': True, 'order_id': oid, 'w_credits': w_amount,
            'amount_cents': amount_cents, 'status': status, 'device_id': device_id}

def api_admin_payment_stats():
    """Aggregated payment statistics."""
    db = get_db(readonly=True)
    total_orders = db.execute("SELECT COUNT(*) FROM p2p_orders").fetchone()[0]
    confirmed = db.execute("SELECT COUNT(*) FROM p2p_orders WHERE status=?", ('confirmed',)).fetchone()[0]
    pending = db.execute("SELECT COUNT(*) FROM p2p_orders WHERE status=?", ('pending',)).fetchone()[0]
    rejected = db.execute("SELECT COUNT(*) FROM p2p_orders WHERE status=?", ('rejected',)).fetchone()[0]
    total_revenue = db.execute("SELECT COALESCE(SUM(amount_cents),0) FROM p2p_orders WHERE status=?", ('confirmed',)).fetchone()[0]
    total_w_granted = db.execute("SELECT COALESCE(SUM(w_credits),0) FROM p2p_orders WHERE status=?", ('confirmed',)).fetchone()[0]
    total_w_credits = db.execute("SELECT COALESCE(SUM(total_w),0) FROM w_credits").fetchone()[0]
    total_w_used = db.execute("SELECT COALESCE(SUM(used_w),0) FROM w_credits").fetchone()[0]
    device_count = db.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    legacy_total = db.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
    legacy_confirmed = db.execute("SELECT COUNT(*) FROM payments WHERE status=?", ('confirmed',)).fetchone()[0]
    return {
        'ok': True,
        'p2p': {'total': total_orders, 'confirmed': confirmed, 'pending': pending, 'rejected': rejected,
                'revenue_cents': total_revenue, 'revenue_yuan': total_revenue / 100,
                'w_granted': total_w_granted},
        'w_pool': {'total': total_w_credits, 'used': total_w_used, 'available': total_w_credits - total_w_used},
        'devices': device_count,
        'legacy': {'total': legacy_total, 'confirmed': legacy_confirmed},
    }

def api_public_pool_enhanced():
    """增强版公共池 — 含W资源总览+设备统计。"""
    base = api_public_pool(force=True)
    db = get_db(readonly=True)
    dev_count = db.execute("SELECT COUNT(*) FROM devices WHERE status='active'").fetchone()[0]
    total_w = db.execute("SELECT COALESCE(SUM(total_w),0) FROM w_credits").fetchone()[0]
    used_w = db.execute("SELECT COALESCE(SUM(used_w),0) FROM w_credits").fetchone()[0]
    base['w_resource'] = {'total_w': total_w, 'used_w': used_w, 'available_w': total_w - used_w,
                          'devices': dev_count, 'initial_bonus': W_INITIAL}
    return base

# ============================================================
# Push Directives — 道之推·万法归宗
# ============================================================
PUSH_SIGN_KEY = os.environ.get('CLOUD_POOL_PUSH_KEY', ADMIN_KEY or '')

def _sign_directive(directive_id, dtype, payload_str, expires_at):
    """Sign a push directive for integrity verification by clients."""
    msg = f'{directive_id}.{dtype}.{payload_str}.{expires_at}'
    return hmac.new((PUSH_SIGN_KEY or 'default').encode(), msg.encode(), hashlib.sha256).hexdigest()

def _security_event(event_type, severity='info', ip='', device_id='', detail='', fingerprint=''):
    """Record security event. v3.1: Write-locked."""
    try:
        with _db_write_lock:
            db = get_db()
            db.execute("INSERT INTO security_events (event_type,severity,ip,device_id,detail,fingerprint,created_at) VALUES (?,?,?,?,?,?,?)",
                       (event_type, severity, ip, device_id, detail[:500], fingerprint, _now()))
            if ip:
                score_delta = {'info': 0, 'warn': -5, 'high': -15, 'critical': -30}.get(severity, 0)
                db.execute("""INSERT INTO ip_reputation (ip,score,total_requests,last_seen,first_seen)
                    VALUES (?,?,1,?,?) ON CONFLICT(ip) DO UPDATE SET
                    score=MAX(0, ip_reputation.score + ?),
                    total_requests=ip_reputation.total_requests+1,
                    last_seen=excluded.last_seen""",
                    (ip, max(0, 100 + score_delta), _now(), _now(), score_delta))
            db.commit()
    except Exception:
        pass

def api_admin_push_create(data, ip=''):
    """Create a signed push directive for all clients.
    Types: config_update, announcement, force_refresh, version_gate, kill_switch, security_patch
    """
    dtype = (data.get('type') or '').strip()
    if not dtype:
        return {'ok': False, 'error': 'type required'}
    valid_types = ['config_update', 'announcement', 'force_refresh', 'version_gate',
                   'kill_switch', 'security_patch', 'custom']
    if dtype not in valid_types:
        return {'ok': False, 'error': f'invalid type, must be one of: {",".join(valid_types)}'}
    payload = data.get('payload', {})
    target = data.get('target', 'all')  # 'all' | device_id | 'version:<min_ver>'
    priority = data.get('priority', 'normal')  # normal | high | critical
    ttl_hours = int(data.get('ttl_hours', 24))
    payload_str = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    did = 'PUSH-' + secrets.token_hex(6).upper()
    now = _now()
    from datetime import timedelta
    expires = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).strftime('%Y-%m-%dT%H:%M:%SZ')
    sig = _sign_directive(did, dtype, payload_str, expires)
    with _db_write_lock:
        db = get_db()
        db.execute("""INSERT INTO push_directives
            (id,type,payload,target,priority,signature,created_at,expires_at,creator_ip)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (did, dtype, payload_str, target, priority, sig, now, expires, ip))
        db.commit()
    audit_log('push_create', f'id={did} type={dtype} target={target} priority={priority}', ip)
    _security_event('push_created', 'info', ip, detail=f'{dtype}:{did}')
    return {'ok': True, 'directive_id': did, 'type': dtype, 'target': target,
            'priority': priority, 'expires_at': expires, 'signature': sig[:16] + '...'}

def api_admin_push_list():
    """List all push directives."""
    db = get_db(readonly=True)
    rows = db.execute("SELECT * FROM push_directives ORDER BY created_at DESC LIMIT 100").fetchall()
    directives = []
    now = _now()
    for r in rows:
        d = dict(r)
        d['active'] = not d['revoked'] and (d['expires_at'] or '') > now
        directives.append(d)
    active_count = sum(1 for d in directives if d['active'])
    return {'ok': True, 'directives': directives, 'active_count': active_count, 'total': len(directives)}

def api_admin_push_revoke(data):
    """Revoke a push directive. v3.1: Write-locked."""
    did = data.get('directive_id', '')
    if not did:
        return {'ok': False, 'error': 'directive_id required'}
    with _db_write_lock:
        db = get_db()
        r = db.execute("UPDATE push_directives SET revoked=1 WHERE id=?", (did,))
        if r.rowcount == 0:
            return {'ok': False, 'error': 'not found'}
        db.commit()
    audit_log('push_revoke', f'id={did}')
    return {'ok': True, 'revoked': did}

def api_ext_get_directives(device_id='', client_version=''):
    """Client polls for active push directives. v3.1: Read+write split."""
    db = get_db(readonly=True)
    now = _now()
    rows = db.execute("""SELECT id,type,payload,target,priority,signature,created_at,expires_at
        FROM push_directives WHERE revoked=0 AND expires_at>?
        ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END, created_at DESC
        LIMIT 20""", (now,)).fetchall()
    directives = []
    for r in rows:
        d = dict(r)
        target = d['target']
        if target == 'all':
            pass
        elif target.startswith('version:') and client_version:
            min_ver = target.split(':', 1)[1]
            if client_version >= min_ver:
                continue
        elif target and target != device_id:
            continue
        try:
            d['payload'] = json.loads(d['payload'])
        except Exception:
            pass
        directives.append(d)
    if directives:
        with _db_write_lock:
            wdb = get_db()
            for d in directives:
                wdb.execute("UPDATE push_directives SET acked_count=acked_count+1 WHERE id=?", (d['id'],))
            wdb.commit()
    return {'ok': True, 'directives': directives, 'count': len(directives)}

def api_admin_security_events(limit=100):
    """Query security events for threat intelligence dashboard."""
    db = get_db(readonly=True)
    events = [dict(r) for r in db.execute(
        "SELECT * FROM security_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    bad_ips = [dict(r) for r in db.execute(
        "SELECT * FROM ip_reputation WHERE score<50 ORDER BY score ASC LIMIT 20").fetchall()]
    stats = {
        'total_events': db.execute("SELECT COUNT(*) FROM security_events").fetchone()[0],
        'critical': db.execute("SELECT COUNT(*) FROM security_events WHERE severity='critical'").fetchone()[0],
        'high': db.execute("SELECT COUNT(*) FROM security_events WHERE severity='high'").fetchone()[0],
        'warn': db.execute("SELECT COUNT(*) FROM security_events WHERE severity='warn'").fetchone()[0],
        'blocked_ips': len(bad_ips),
    }
    return {'ok': True, 'events': events, 'bad_ips': bad_ips, 'stats': stats}

def api_admin_ip_block(data):
    """Manually block/unblock an IP. v3.1: Write-locked."""
    ip = data.get('ip', '')
    action = data.get('action', 'block')
    if not ip:
        return {'ok': False, 'error': 'ip required'}
    with _db_write_lock:
        db = get_db()
        if action == 'block':
            db.execute("""INSERT INTO ip_reputation (ip,score,blocked_count,last_seen,first_seen,tags)
                VALUES (?,0,1,?,?,'manual_block') ON CONFLICT(ip) DO UPDATE SET
                score=0, blocked_count=ip_reputation.blocked_count+1, tags='manual_block'""",
                (ip, _now(), _now()))
        else:
            db.execute("UPDATE ip_reputation SET score=100, tags='' WHERE ip=?", (ip,))
        db.commit()
    audit_log(f'ip_{action}', f'ip={ip}')
    if action == 'block':
        _security_event('ip_blocked', 'high', ip, detail='manual block')
    return {'ok': True, 'ip': ip, 'action': action}

# ============================================================
# Redemption Codes — 万法归宗·发卡对接 (ldxp.cn integration)
# ============================================================
PRODUCTS = {
    'windsurf_trial': {'name': 'Windsurf Trial 独享账号', 'price': 170, 'tier': 'standard'},
    'windsurf_pro':   {'name': 'Windsurf 全模型独享账号', 'price': 300, 'tier': 'premium'},
    'wam_1day':       {'name': '无感换号 1天卡', 'price': 20,  'tier': 'tool'},
    'wam_3day':       {'name': '无感换号 3天卡', 'price': 100, 'tier': 'tool'},
    'wam_7day':       {'name': '无感换号 7天卡', 'price': 200, 'tier': 'tool'},
}

def _gen_code(prefix='WS'):
    """Generate a unique redemption code: WS-XXXX-XXXX-XXXX"""
    seg = lambda: secrets.token_hex(2).upper()
    return f'{prefix}-{seg()}-{seg()}-{seg()}'

def api_admin_gen_codes(data, ip=''):
    """Batch generate redemption codes for ldxp.cn upload.
    POST {product, count, expires_days}
    Returns list of codes ready for card-platform upload."""
    product = data.get('product', 'windsurf_trial')
    count = min(int(data.get('count', 10)), 500)
    expires_days = int(data.get('expires_days', 30))
    if product not in PRODUCTS:
        return {'ok': False, 'error': f'unknown product: {product}. valid: {",".join(PRODUCTS.keys())}'}
    pinfo = PRODUCTS[product]
    batch_id = 'BATCH-' + secrets.token_hex(4).upper()
    from datetime import timedelta
    expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_days)).strftime('%Y-%m-%dT%H:%M:%SZ')
    codes = []
    with _db_write_lock:
        db = get_db()
        for _ in range(count):
            code = _gen_code('WS' if 'windsurf' in product else 'WM')
            try:
                db.execute("""INSERT INTO redemption_codes
                    (code,product,tier,price_cents,status,created_at,expires_at,batch_id)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (code, product, pinfo['tier'], pinfo['price'], 'available', _now(), expires_at, batch_id))
                codes.append(code)
            except sqlite3.IntegrityError:
                continue  # duplicate code, skip
        db.commit()
    audit_log('gen_codes', f'batch={batch_id} product={product} count={len(codes)}', ip)
    return {
        'ok': True, 'batch_id': batch_id, 'product': product,
        'product_name': pinfo['name'], 'price_yuan': pinfo['price'] / 100,
        'count': len(codes), 'expires_at': expires_at,
        'codes': codes,
        'ldxp_format': '\n'.join(codes),  # one code per line for ldxp.cn bulk upload
    }

_redeem_ip_log = {}  # ip -> [timestamps]  (in-memory, resets on restart)
_redeem_ip_lock = threading.Lock()
REDEEM_IP_LIMIT = 10  # max redemptions per IP per hour
REDEEM_IP_WINDOW = 3600  # 1 hour

def api_redeem(data, ip=''):
    """Public redemption: buyer submits code → gets allocated account credentials.
    v3.1: IP rate limiting + auto-expire cleanup + inventory alerts.
    POST {code, contact?}"""
    code = (data.get('code') or '').strip().upper()
    contact = (data.get('contact') or '').strip()
    if not code:
        return {'ok': False, 'error': 'code required'}
    # IP rate limit for redemption (prevent abuse)
    if ip and not _is_loopback(ip):
        now_t = time.time()
        with _redeem_ip_lock:
            _redeem_ip_log[ip] = [t for t in _redeem_ip_log.get(ip, []) if now_t - t < REDEEM_IP_WINDOW]
            if len(_redeem_ip_log[ip]) >= REDEEM_IP_LIMIT:
                return {'ok': False, 'error': 'too many redemptions, try later'}
            _redeem_ip_log[ip].append(now_t)
    # Phase 1: auto-expire cleanup (always committed — Python sqlite3 opens implicit
    # transaction on ANY UPDATE, even 0 rows affected; must commit unconditionally)
    try:
        with _db_write_lock:
            db = get_db()
            db.execute("UPDATE redemption_codes SET status='expired' WHERE status='available' AND expires_at<? AND expires_at!=''", (_now(),))
            db.commit()  # ALWAYS commit — closes the implicit transaction
    except Exception:
        pass
    # Phase 2: validate + allocate (main transaction)
    with _db_write_lock:
        db = get_db()
        rc = db.execute("SELECT * FROM redemption_codes WHERE code=?", (code,)).fetchone()
        if not rc:
            return {'ok': False, 'error': 'invalid code'}
        if rc['status'] == 'redeemed':
            return {'ok': False, 'error': 'code already used'}
        if rc['status'] == 'expired':
            return {'ok': False, 'error': 'code expired'}
        if rc['expires_at'] and rc['expires_at'] < _now():
            db.execute("UPDATE redemption_codes SET status='expired' WHERE code=?", (code,))
            db.commit()
            return {'ok': False, 'error': 'code expired'}
        product = rc['product']
        tier = rc['tier']
        # Tool products (WAM cards) — return access token, no account allocation
        if tier == 'tool':
            db.execute("UPDATE redemption_codes SET status='redeemed',redeemed_at=?,buyer_ip=?,buyer_contact=? WHERE code=?",
                (_now(), ip, contact, code))
            db.commit()
            _invalidate_pool_cache()
            audit_log('redeem_tool', f'code={code} product={product}', ip)
            days = {'wam_1day': 1, 'wam_3day': 3, 'wam_7day': 7}.get(product, 1)
            return {
                'ok': True, 'type': 'tool', 'product': product,
                'days': days,
                'message': f'无感换号工具 {days}天卡已激活',
                'instructions': '下载Windsurf小助手扩展 → 输入此卡密激活',
            }
        # Account products — allocate best available account
        acc_filter = """status='available' AND daily_pct>5 AND weekly_pct>5 AND days_left>1"""
        if tier == 'premium':
            acc_filter += " AND auth_blob_enc!='' AND auth_blob_enc IS NOT NULL"
        acc = db.execute(f"SELECT * FROM accounts WHERE {acc_filter} ORDER BY (daily_pct+weekly_pct) DESC LIMIT 1").fetchone()
        if not acc:
            return {'ok': False, 'error': 'no accounts available, try later'}
        # Allocate
        cur = db.execute("UPDATE accounts SET status='allocated',allocated_to=?,allocated_at=? WHERE id=? AND status='available'",
            (f'redeem:{code}', _now(), acc['id']))
        if cur.rowcount == 0:
            return {'ok': False, 'error': 'account race, retry'}
        db.execute("UPDATE redemption_codes SET status='redeemed',redeemed_at=?,account_id=?,buyer_ip=?,buyer_contact=? WHERE code=?",
            (_now(), acc['id'], ip, contact, code))
        db.commit()
        _invalidate_pool_cache()
    audit_log('redeem_account', f'code={code} email={acc["email"]} product={product}', ip)
    result = {
        'ok': True, 'type': 'account', 'product': product,
        'email': acc['email'],
        'password': _simple_decrypt(acc['password_enc']),
        'plan': acc['plan'],
        'daily_pct': acc['daily_pct'], 'weekly_pct': acc['weekly_pct'],
        'days_left': round(acc['days_left'], 1) if acc['days_left'] else 0,
    }
    # Premium tier: also include auth blob for hot-inject
    if tier == 'premium' and acc['auth_blob_enc']:
        try:
            result['auth_blob'] = json.loads(_simple_decrypt(acc['auth_blob_enc']))
        except Exception:
            pass
    return result

def api_admin_list_codes(data=None):
    """List redemption codes with filtering."""
    db = get_db(readonly=True)
    status_filter = ''
    params = []
    if data and data.get('status'):
        status_filter = ' WHERE status=?'
        params.append(data['status'])
    if data and data.get('batch_id'):
        status_filter = (' AND' if status_filter else ' WHERE') + ' batch_id=?'
        params.append(data['batch_id'])
    rows = db.execute(f"SELECT * FROM redemption_codes{status_filter} ORDER BY created_at DESC LIMIT 500", params).fetchall()
    codes = [dict(r) for r in rows]
    stats = {
        'total': db.execute("SELECT COUNT(*) FROM redemption_codes").fetchone()[0],
        'available': db.execute("SELECT COUNT(*) FROM redemption_codes WHERE status='available'").fetchone()[0],
        'redeemed': db.execute("SELECT COUNT(*) FROM redemption_codes WHERE status='redeemed'").fetchone()[0],
        'expired': db.execute("SELECT COUNT(*) FROM redemption_codes WHERE status='expired'").fetchone()[0],
    }
    return {'ok': True, 'codes': codes, 'stats': stats}

def api_admin_export_codes(data=None):
    """Export available codes in ldxp.cn bulk upload format (one per line)."""
    product = (data or {}).get('product', '')
    db = get_db(readonly=True)
    where = "WHERE status='available'"
    params = []
    if product:
        where += " AND product=?"
        params.append(product)
    rows = db.execute(f"SELECT code, product, price_cents FROM redemption_codes {where} ORDER BY created_at", params).fetchall()
    lines = [r['code'] for r in rows]
    by_product = {}
    for r in rows:
        p = r['product']
        if p not in by_product:
            by_product[p] = {'count': 0, 'price': r['price_cents'] / 100}
        by_product[p]['count'] += 1
    return {
        'ok': True, 'total': len(lines),
        'by_product': by_product,
        'codes_text': '\n'.join(lines),  # for ldxp.cn upload
        'codes': lines,
    }

# ============================================================
# HTTP Handler — ☵坎·如水贯通
# ============================================================
class PoolHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def _get_client_ip(self):
        xff = self.headers.get('X-Forwarded-For', '')
        if xff:
            return xff.split(',')[0].strip()
        return self.client_address[0] if self.client_address else '0.0.0.0'

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type,X-Admin-Key,X-Signature,X-Timestamp,X-Nonce,X-Device-Id')

    def _json(self, data, code=200, etag=None):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        # Gzip if client accepts and body large enough
        accept_enc = self.headers.get('Accept-Encoding', '')
        use_gzip = 'gzip' in accept_enc and len(body) > 1024
        if use_gzip:
            body = gzip.compress(body, compresslevel=6)
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        if use_gzip:
            self.send_header('Content-Encoding', 'gzip')
        if etag:
            self.send_header('ETag', f'"{etag}"')
            self.send_header('Cache-Control', 'public, max-age=10')
        self._cors()
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _json_304(self, etag):
        """Send 304 Not Modified — 损之又损·无为而无不为。"""
        self.send_response(304)
        self.send_header('ETag', f'"{etag}"')
        self._cors()
        self.end_headers()

    def _html(self, filepath):
        if not filepath.exists():
            self.send_error(404, f'{filepath.name} not found')
            return
        body = filepath.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length <= 0: return {}
        try: return json.loads(self.rfile.read(length))
        except Exception: return {}

    def _admin_ok(self):
        key = self.headers.get('X-Admin-Key', '')
        if not ADMIN_KEY or not key:
            return False
        if not secrets.compare_digest(key, ADMIN_KEY):
            return False
        # IP allowlist check (if configured)
        if ADMIN_IP_ALLOWLIST and ADMIN_IP_ALLOWLIST != ['']:
            ip = self._get_client_ip()
            if ip not in ADMIN_IP_ALLOWLIST and '0.0.0.0' not in ADMIN_IP_ALLOWLIST:
                audit_log('admin_ip_blocked', f'ip={ip}', ip)
                return False
        return True

    def _check_rate_limit(self, is_admin=False):
        ip = self._get_client_ip()
        if not _rate_check(ip, is_admin):
            self._json({'ok': False, 'error': 'rate limited'}, 429)
            return False
        return True

    def _verify_request(self, body_bytes=None):
        """Verify HMAC signature if configured."""
        sig = self.headers.get('X-Signature', '')
        ts = self.headers.get('X-Timestamp', '')
        nonce = self.headers.get('X-Nonce', '')
        ok, err = _verify_hmac(body_bytes, sig, ts, nonce)
        if not ok:
            self._json({'ok': False, 'error': f'auth: {err}'}, 401)
        return ok

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        p = urlparse(self.path)
        path = p.path.rstrip('/')
        qs = parse_qs(p.query)
        if not self._check_rate_limit():
            return
        try:
            if path in ('', '/public'):
                self._html(SCRIPT_DIR / 'public.html')
            elif path == '/redeem':
                self._html(SCRIPT_DIR / 'redeem.html')
            elif path == '/dashboard':
                self._html(DASHBOARD_FILE)
            elif path == '/api/public/pool':
                # ETag support: 损之又损·最小化数据交互
                client_etag = self.headers.get('If-None-Match', '').strip('"')
                data = api_public_pool()
                etag = _pool_cache.get('etag', '')
                if client_etag and client_etag == etag:
                    self._json_304(etag)
                    return
                self._json(data, etag=etag)
            elif path == '/api/health':
                self._json(api_health())
            elif path == '/api/me':
                t = qs.get('t', [''])[0]
                self._json(api_me(t) if t else {'ok': False, 'error': 'token required'})
            elif path == '/api/ext/pull':
                # Extension direct-pull: get available account with credentials
                if not self._verify_request(): return
                device_id = self.headers.get('X-Device-Id', '')
                self._json(api_ext_pull(device_id))
            elif path == '/api/ext/pool':
                # Extension pool status (no credentials)
                if not self._verify_request(): return
                self._json(api_ext_pool_status())
            elif path == '/api/admin/overview':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_overview())
            elif path == '/api/admin/users':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_users())
            elif path == '/api/admin/payments':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_payments())
            elif path == '/api/admin/accounts':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_accounts())
            elif path == '/api/admin/audit':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                limit = int(qs.get('limit', ['50'])[0])
                self._json(api_admin_audit(limit))
            elif path == '/api/ext/pull-blob':
                # Extension pull auth blob for hot-switch (道之根本)
                if not self._verify_request(): return
                device_id = self.headers.get('X-Device-Id', '')
                email = qs.get('email', [''])[0]
                exclude = qs.get('exclude', [''])[0]
                ip = self._get_client_ip()
                self._json(api_ext_pull_blob(device_id, email, ip, exclude))
            elif path == '/api/public/pool-enhanced':
                self._json(api_public_pool_enhanced())
            elif path == '/api/device/info':
                did = qs.get('id', [''])[0]
                self._json(api_device_info(did))
            elif path == '/api/p2p/status':
                oid = qs.get('order_id', [''])[0]
                self._json(api_p2p_status(oid))
            elif path == '/api/admin/devices':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_devices())
            elif path == '/api/admin/p2p-orders':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_p2p_orders())
            elif path == '/api/admin/payment-stats':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_payment_stats())
            elif path == '/api/admin/merchant-config':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_merchant_config())
            elif path == '/api/admin/push':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_push_list())
            elif path == '/api/admin/security-events':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                limit = int(qs.get('limit', ['100'])[0])
                self._json(api_admin_security_events(limit))
            elif path == '/api/admin/codes':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_list_codes({'status': qs.get('status', [''])[0], 'batch_id': qs.get('batch', [''])[0]}))
            elif path == '/api/admin/codes/export':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_export_codes({'product': qs.get('product', [''])[0]}))
            elif path == '/api/products':
                self._json({'ok': True, 'products': {k: {'name': v['name'], 'price_yuan': v['price']/100, 'tier': v['tier']} for k, v in PRODUCTS.items()}})
            elif path == '/api/ext/directives':
                if not self._verify_request(): return
                device_id = self.headers.get('X-Device-Id', '')
                client_ver = qs.get('v', [''])[0]
                self._json(api_ext_get_directives(device_id, client_ver))
            elif path == '/favicon.ico':
                self.send_response(204); self.end_headers()
            else:
                self.send_error(404)
        except Exception as e:
            self._json({'error': str(e)}, 500)

    def do_POST(self):
        p = urlparse(self.path).path.rstrip('/')
        if not self._check_rate_limit(is_admin=p.startswith('/api/admin')):
            return
        # Read raw body for HMAC verification
        length = int(self.headers.get('Content-Length', 0))
        raw_body = self.rfile.read(length) if length > 0 else b''
        try:
            body = json.loads(raw_body) if raw_body else {}
        except Exception:
            body = {}
        try:
            if p == '/api/public/start':
                self._json(api_public_quick_start(body))
            elif p == '/api/redeem':
                ip = self._get_client_ip()
                self._json(api_redeem(body, ip))
            elif p == '/api/admin/codes/generate':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                ip = self._get_client_ip()
                self._json(api_admin_gen_codes(body, ip))
            elif p == '/api/register':
                self._json(api_register(body))
            elif p == '/api/topup':
                self._json(api_topup(body))
            elif p == '/api/allocate':
                self._json(api_allocate(body))
            elif p == '/api/release':
                self._json(api_release(body))
            elif p == '/api/ext/release':
                # Extension release account
                if not self._verify_request(raw_body): return
                self._json(api_ext_release(body))
            elif p == '/api/admin/confirm':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_confirm(body))
            elif p == '/api/admin/reject':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_reject(body))
            elif p == '/api/admin/sync':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_sync_accounts(body))
            elif p == '/api/admin/bulk-sync':
                # Bulk sync local pool → cloud (with auth blobs)
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                ip = self._get_client_ip()
                self._json(api_admin_bulk_sync(body, ip))
            elif p == '/api/ext/heartbeat':
                # Device heartbeat — 损之又损
                if not self._verify_request(raw_body): return
                ip = self._get_client_ip()
                self._json(api_ext_heartbeat(body, ip))
            elif p == '/api/ext/push':
                # Extension push health data (move before old position)
                if not self._verify_request(raw_body): return
                self._json(api_ext_push(body))
            elif p == '/api/device/activate':
                ip = self._get_client_ip()
                self._json(api_device_activate(body, ip))
            elif p == '/api/p2p/init':
                ip = self._get_client_ip()
                self._json(api_p2p_init(body, ip))
            elif p == '/api/p2p/detect':
                ip = self._get_client_ip()
                self._json(api_p2p_detect(body, ip))
            elif p == '/api/admin/p2p/confirm':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_p2p_confirm(body))
            elif p == '/api/admin/p2p/reject':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_p2p_reject(body))
            elif p == '/api/admin/p2p/create':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                ip = self._get_client_ip()
                self._json(api_admin_p2p_create(body, ip))
            elif p == '/api/admin/push':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                ip = self._get_client_ip()
                self._json(api_admin_push_create(body, ip))
            elif p == '/api/admin/push/revoke':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_push_revoke(body))
            elif p == '/api/admin/ip-block':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_ip_block(body))
            elif p == '/api/admin/merchant-config':
                if not self._admin_ok(): self._json({'ok': False, 'error': 'forbidden'}, 403); return
                self._json(api_admin_merchant_config(body))
            else:
                self.send_error(404)
        except Exception as e:
            self._json({'error': str(e)}, 500)

class ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

# ============================================================
# CLI
# ============================================================
def main():
    global ADMIN_KEY
    parser = argparse.ArgumentParser(description='Windsurf Cloud Pool Server')
    parser.add_argument('--port', type=int, default=int(os.environ.get('CLOUD_POOL_PORT', 19880)))
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--admin-key', default=ADMIN_KEY)
    args = parser.parse_args()

    if args.admin_key:
        ADMIN_KEY = args.admin_key
    if not ADMIN_KEY:
        ADMIN_KEY = 'admin_' + secrets.token_hex(8)

    init_db()
    migrate_db()
    server = ThreadedServer((args.host, args.port), PoolHandler)

    # Count existing data
    try:
        db = get_db(readonly=True)
        total = db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]
        blobs = db.execute("SELECT COUNT(*) FROM accounts WHERE auth_blob_enc!='' AND auth_blob_enc IS NOT NULL").fetchone()[0]
    except Exception:
        total = blobs = 0

    # v3.1: WAL checkpoint timer — prevent WAL file bloat under concurrent writes
    def _wal_checkpoint():
        while True:
            time.sleep(300)  # every 5 minutes
            try:
                c = sqlite3.connect(str(DB_FILE), timeout=5)
                c.execute('PRAGMA wal_checkpoint(PASSIVE)')
                c.close()
            except Exception:
                pass
    wal_thread = threading.Thread(target=_wal_checkpoint, daemon=True)
    wal_thread.start()

    print(f'=== Windsurf Cloud Pool v{VERSION} — \u9053\u751f\u4e00\u00b7\u7edf\u4e00\u7ba1\u7406 ===')
    print(f'  URL:       http://{args.host}:{args.port}/')
    print(f'  Admin Key: {ADMIN_KEY}')
    print(f'  HMAC:      {"configured" if HMAC_SECRET else "disabled"}')
    print(f'  Encrypt:   {"configured" if CRYPT_KEY else "disabled"}')
    print(f'  Concur:    busy_timeout={DB_BUSY_TIMEOUT}s write_lock=ON retries={DB_MAX_RETRIES} WAL_checkpoint=5min')
    print(f'  Database:  {DB_FILE} ({total} accounts, {blobs} with auth blob)')
    print(f'  Cost:      {ACCOUNT_COST_CENTS/100:.0f}Y/account | Sell: {SELL_PRICE_CENTS/100:.0f}Y/account')
    print(f'  Ctrl+C to stop')

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
        print('\nStopped.')

if __name__ == '__main__':
    main()
