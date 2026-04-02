#!/usr/bin/env python3
"""
_fix_sqlite_settings.py — 直接修改 SQLite 数据库中的 autoContinue 设置
道法自然 · 从存储根源强制 ENABLED
"""
import sqlite3, json, sys, struct, base64, os

DB_GLOBAL = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'

# AutoContinueOnMaxGeneratorInvocations:
# UNSPECIFIED=0, ENABLED=1, DISABLED=2

def scan_db(db_path):
    """扫描数据库，找 autoContinue 相关键"""
    conn = sqlite3.connect(db_path)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print(f"Tables in {os.path.basename(db_path)}:")
    for t in tables:
        print(f"  {t[0]}")

    print()
    for t in [row[0] for row in tables]:
        try:
            # Get column info
            cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
            col_names = [c[1] for c in cols]
            if 'key' not in col_names and 'Key' not in col_names:
                continue
            key_col = 'key' if 'key' in col_names else 'Key'
            val_col = 'value' if 'value' in col_names else 'Value'
            
            # Search for relevant keys
            rows = conn.execute(
                f"SELECT {key_col}, {val_col} FROM {t} WHERE "
                f"{key_col} LIKE '%autoContinue%' OR "
                f"{key_col} LIKE '%userSettings%' OR "
                f"{key_col} LIKE '%UserSettings%' OR "
                f"{key_col} LIKE '%codeium%' OR "
                f"{key_col} LIKE '%cascade%settings%'"
            ).fetchall()
            for k, v in rows:
                vstr = str(v)[:300] if v is not None else 'NULL'
                print(f"  [{t}] KEY={k}")
                print(f"    VAL={repr(vstr[:300])}")
                print()
        except Exception as e:
            print(f"  [{t}] error: {e}")
    conn.close()


def search_all_keys(db_path, search_term=''):
    """搜索数据库中所有 key"""
    conn = sqlite3.connect(db_path)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    for t in [row[0] for row in tables]:
        try:
            cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
            col_names = [c[1] for c in cols]
            if not any(c in col_names for c in ['key','Key']):
                continue
            key_col = 'key' if 'key' in col_names else 'Key'
            rows = conn.execute(f"SELECT {key_col} FROM {t}").fetchall()
            for row in rows:
                k = str(row[0])
                if not search_term or search_term.lower() in k.lower():
                    print(f"  [{t}] {k}")
        except Exception as e:
            pass
    conn.close()


def try_set_autocontinue(db_path):
    """尝试在数据库中找到并修改 autoContinue 设置"""
    conn = sqlite3.connect(db_path)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    
    modified = 0
    for t in [row[0] for row in tables]:
        try:
            cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
            col_names = [c[1] for c in cols]
            if not any(c in col_names for c in ['key', 'Key']):
                continue
            key_col = 'key' if 'key' in col_names else 'Key'
            val_col = 'value' if 'value' in col_names else 'Value'
            
            # Look for any key containing autoContinue or UserSettings
            rows = conn.execute(
                f"SELECT {key_col}, {val_col} FROM {t} WHERE "
                f"LOWER({key_col}) LIKE '%autocontinue%' OR "
                f"LOWER({key_col}) LIKE '%usersettings%'"
            ).fetchall()
            
            for k, v in rows:
                print(f"Found key: {k} = {repr(str(v)[:200])}")
                # Try to parse and modify
                if v is not None:
                    try:
                        # Try JSON
                        data = json.loads(v)
                        if isinstance(data, dict) and 'autoContinueOnMaxGeneratorInvocations' in data:
                            old = data['autoContinueOnMaxGeneratorInvocations']
                            data['autoContinueOnMaxGeneratorInvocations'] = 1  # ENABLED
                            conn.execute(
                                f"UPDATE {t} SET {val_col}=? WHERE {key_col}=?",
                                (json.dumps(data), k)
                            )
                            print(f"  ✅ JSON updated: {old} → 1 (ENABLED)")
                            modified += 1
                        elif isinstance(data, dict):
                            print(f"  JSON keys: {list(data.keys())[:10]}")
                    except (json.JSONDecodeError, TypeError):
                        # Binary/protobuf data
                        print(f"  Binary data ({len(v) if v else 0} bytes)")
        except Exception as e:
            print(f"  [{t}] error: {e}")
    
    if modified:
        conn.commit()
        print(f"\n✅ 已修改 {modified} 条记录")
    else:
        print("\n⚠️  未找到可直接修改的 autoContinue 记录")
    conn.close()
    return modified


def dump_all_codeium_keys(db_path):
    """显示所有 codeium/windsurf 相关 key"""
    conn = sqlite3.connect(db_path)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print("Codeium/Windsurf related keys:")
    for t in [row[0] for row in tables]:
        try:
            cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
            col_names = [c[1] for c in cols]
            if not any(c in col_names for c in ['key', 'Key']):
                continue
            key_col = 'key' if 'key' in col_names else 'Key'
            val_col = 'value' if 'value' in col_names else 'Value'
            rows = conn.execute(
                f"SELECT {key_col}, {val_col} FROM {t} WHERE "
                f"LOWER({key_col}) LIKE '%codeium%' OR "
                f"LOWER({key_col}) LIKE '%windsurf%' OR "
                f"LOWER({key_col}) LIKE '%cascade%'"
            ).fetchall()
            for k, v in rows[:20]:
                vstr = repr(str(v)[:150]) if v else 'NULL'
                print(f"  [{t}] {k}: {vstr}")
        except Exception as e:
            pass
    conn.close()


if __name__ == '__main__':
    args = set(sys.argv[1:])
    
    if '--scan' in args:
        scan_db(DB_GLOBAL)
    elif '--keys' in args:
        search_all_keys(DB_GLOBAL, sys.argv[-1] if len(sys.argv) > 2 else '')
    elif '--codeium' in args:
        dump_all_codeium_keys(DB_GLOBAL)
    elif '--fix' in args:
        try_set_autocontinue(DB_GLOBAL)
    else:
        print("=== 扫描主数据库 ===")
        scan_db(DB_GLOBAL)
        print()
        print("=== Codeium/Windsurf 相关键 ===")
        dump_all_codeium_keys(DB_GLOBAL)
        print()
        print("=== 尝试修改 autoContinue ===")
        try_set_autocontinue(DB_GLOBAL)
