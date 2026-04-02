#!/usr/bin/env python3
"""Clean up stress test data from cloud_pool.db"""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent / 'cloud_pool.db'
db = sqlite3.connect(str(DB), timeout=10)

r1 = db.execute("DELETE FROM users WHERE name LIKE 'stress_%' OR name LIKE 'storm_%' OR name LIKE 'e2e_%'").rowcount
r2 = db.execute("DELETE FROM accounts WHERE email LIKE 'stress_%' OR email LIKE 'storm_%'").rowcount
r3 = db.execute("DELETE FROM devices WHERE hwid LIKE 'STRESS-%' OR hwid LIKE 'E2E-%' OR hwid LIKE 'p2p-hwid-%'").rowcount
r4 = db.execute("DELETE FROM p2p_orders WHERE method='stress_test' OR note LIKE 'stress_%'").rowcount
r6 = db.execute("UPDATE accounts SET status='available', device_id='', allocated_to=NULL WHERE device_id LIKE 'TEST-DEV-%'").rowcount
db.commit()

t = db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]
a = db.execute("SELECT COUNT(*) FROM accounts WHERE status='available'").fetchone()[0]
u = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
d = db.execute('SELECT COUNT(*) FROM devices').fetchone()[0]
db.close()

print(f'Cleaned: users={r1} accounts={r2} devices={r3} orders={r4} released={r6}')
print(f'DB: {t} accounts ({a} available), {u} users, {d} devices')
