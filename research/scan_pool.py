#!/usr/bin/env python3
"""
scan_pool.py — 扫描 cloud_pool.db，找有 cascade 访问权限的账号
"""
import sys, io, sqlite3, json, time, struct, threading, requests, base64, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DB_POOL = r'e:\道\道生一\一生二\Windsurf无限额度\030-云端号池_CloudPool\cloud_pool.db'

# Step 1: Inspect pool DB
con = sqlite3.connect(DB_POOL)
tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print('Tables:', [t[0] for t in tables])
for t in tables:
    tn = t[0]
    cols = [c[1] for c in con.execute(f'PRAGMA table_info("{tn}")').fetchall()]
    count = con.execute(f'SELECT COUNT(*) FROM "{tn}"').fetchone()[0]
    print(f'  {tn}: {count} rows, cols={cols}')
    # Show first 3 rows
    rows = con.execute(f'SELECT * FROM "{tn}" LIMIT 3').fetchall()
    for r in rows:
        # truncate long values
        display = tuple(str(v)[:50] if v else v for v in r)
        print(f'    {display}')
con.close()
