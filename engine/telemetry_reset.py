"""
Windsurf Telemetry Reset Tool v1.0
===================================
重置storage.json中的遥测标识符，使Windsurf将当前设备视为"新设备"。
配合新账号注册可获得新的Trial额度(10000 messages)。

原理: Windsurf通过5个UUID标识设备身份:
  - telemetry.machineId
  - telemetry.macMachineId  
  - telemetry.devDeviceId
  - telemetry.sqmId
  - storage.serviceMachineId

重置这些值 = 设备指纹变化 = 服务端视为新设备。

用法:
  python telemetry_reset.py              # 重置遥测ID
  python telemetry_reset.py --show       # 仅显示当前ID
  python telemetry_reset.py --restore    # 从备份恢复
  python telemetry_reset.py --cache      # 同时重置cachedPlanInfo
"""
import json, os, sys, uuid, shutil, time, sqlite3

STORAGE_JSON = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\storage.json')
STATE_VSCDB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')

TELEMETRY_KEYS = [
    'telemetry.machineId',
    'telemetry.macMachineId',
    'telemetry.devDeviceId',
    'telemetry.sqmId',
    'storage.serviceMachineId',
]

def gen_id(with_dashes=True, sha256=False):
    """Generate a random identifier.
    sha256=True: 64-char hex (matches Windsurf's actual machineId format from generateFingerprint)
    with_dashes=False: 32-char hex (UUID without dashes)
    with_dashes=True: standard UUID format
    """
    if sha256:
        return os.urandom(32).hex()  # 64-char hex, matches real machineId
    u = uuid.uuid4()
    return str(u) if with_dashes else u.hex

def show_current():
    """Show current telemetry IDs"""
    print("=== Current Telemetry IDs ===")
    if not os.path.exists(STORAGE_JSON):
        print(f"  [!] {STORAGE_JSON} not found")
        return
    with open(STORAGE_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    for key in TELEMETRY_KEYS:
        val = data.get(key, '<not set>')
        print(f"  {key} = {val}")
    
    # Also show cached plan info from state.vscdb
    if os.path.exists(STATE_VSCDB):
        try:
            conn = sqlite3.connect(STATE_VSCDB)
            cur = conn.cursor()
            cur.execute("SELECT value FROM ItemTable WHERE key='windsurf.settings.cachedPlanInfo'")
            row = cur.fetchone()
            if row:
                plan = json.loads(row[0])
                print(f"\n=== Cached Plan Info ===")
                print(f"  Plan: {plan.get('planName','?')}")
                usage = plan.get('usage', {})
                print(f"  Messages: {usage.get('usedMessages',0)}/{usage.get('messages',0)} (remaining: {usage.get('remainingMessages',0)})")
                print(f"  FlowActions: {usage.get('usedFlowActions',0)}/{usage.get('flowActions',0)}")
                start = plan.get('startTimestamp', 0)
                end = plan.get('endTimestamp', 0)
                if start:
                    import datetime
                    print(f"  Period: {datetime.datetime.fromtimestamp(start/1000).strftime('%Y-%m-%d')} → {datetime.datetime.fromtimestamp(end/1000).strftime('%Y-%m-%d')}")
                print(f"  Grace: {plan.get('gracePeriodStatus', '?')}")
            conn.close()
        except Exception as e:
            print(f"  [!] state.vscdb error: {e}")

def reset_telemetry(also_cache=False):
    """Reset all telemetry IDs to random values"""
    if not os.path.exists(STORAGE_JSON):
        print(f"[!] {STORAGE_JSON} not found")
        return False
    
    # Backup
    backup = STORAGE_JSON + f'.bak_{int(time.time())}'
    shutil.copy2(STORAGE_JSON, backup)
    print(f"[*] Backup: {backup}")
    
    with open(STORAGE_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print("\n=== Resetting Telemetry IDs ===")
    for key in TELEMETRY_KEYS:
        old = data.get(key, '<not set>')
        # machineId uses 64-char SHA256 hex (逆向WF v5.6.29确认)
        # macMachineId uses 32-char hex (UUID without dashes)
        if key == 'telemetry.machineId':
            new_val = gen_id(sha256=True)  # 64-char hex
        elif 'machineId' in key and key != 'storage.serviceMachineId':
            new_val = gen_id(with_dashes=False)  # 32-char hex
        else:
            new_val = gen_id(with_dashes=True)
        data[key] = new_val
        print(f"  {key}: {old[:12]}... → {new_val[:12]}...")
    
    # Also reset first/last session dates to look like fresh install
    if 'telemetry.firstSessionDate' in data:
        data['telemetry.firstSessionDate'] = time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime())
        print(f"  telemetry.firstSessionDate → {data['telemetry.firstSessionDate']}")
    if 'telemetry.lastSessionDate' in data:
        data['telemetry.lastSessionDate'] = time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime())
    if 'telemetry.currentSessionDate' in data:
        data['telemetry.currentSessionDate'] = time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime())
    
    with open(STORAGE_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent='\t')
    print(f"\n[OK] storage.json updated")
    
    # Optionally reset cached plan info
    if also_cache and os.path.exists(STATE_VSCDB):
        reset_plan_cache()
    
    print("\n[!] 完成。请:")
    print("    1. 完全关闭Windsurf (包括所有后台进程)")
    print("    2. 注销当前账号 或 使用新邮箱注册")
    print("    3. 重新启动Windsurf")
    print("    4. 登录新账号 → 获得新Trial额度")
    return True

def reset_plan_cache():
    """Reset cached plan info in state.vscdb"""
    if not os.path.exists(STATE_VSCDB):
        print(f"[!] {STATE_VSCDB} not found")
        return
    
    backup = STATE_VSCDB + f'.bak_{int(time.time())}'
    shutil.copy2(STATE_VSCDB, backup)
    print(f"[*] state.vscdb backup: {backup}")
    
    conn = sqlite3.connect(STATE_VSCDB)
    cur = conn.cursor()
    
    # Delete cached plan info (will be re-fetched from server)
    cur.execute("DELETE FROM ItemTable WHERE key='windsurf.settings.cachedPlanInfo'")
    
    # Delete auth sessions (force re-login)
    cur.execute("DELETE FROM ItemTable WHERE key LIKE '%windsurf_auth%'")
    
    # Delete telemetry dates
    cur.execute("DELETE FROM ItemTable WHERE key LIKE 'telemetry.%'")
    
    conn.commit()
    deleted = conn.total_changes
    conn.close()
    print(f"[OK] state.vscdb: {deleted} entries cleared")

def restore():
    """Restore from latest backup"""
    import glob
    backups = sorted(glob.glob(STORAGE_JSON + '.bak_*'))
    if not backups:
        print("[!] No backups found")
        return
    latest = backups[-1]
    shutil.copy2(latest, STORAGE_JSON)
    print(f"[OK] Restored from {latest}")

def main():
    print("=" * 50)
    print("Windsurf Telemetry Reset Tool v1.0")
    print("=" * 50)
    
    if '--show' in sys.argv:
        show_current()
    elif '--restore' in sys.argv:
        restore()
    elif '--cache' in sys.argv:
        reset_telemetry(also_cache=True)
    else:
        reset_telemetry(also_cache=False)

if __name__ == '__main__':
    main()
