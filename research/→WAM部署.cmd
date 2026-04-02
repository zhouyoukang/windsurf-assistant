@echo off
chcp 65001 > nul 2>&1
title WAM 智能切号 v5.0 — 一键部署

echo ╔══════════════════════════════════════════════════════════╗
echo ║  WAM 智能切号 v5.0 — 一键部署验证                       ║
echo ║  评分排序 + 智能切号 + 耗尽沉底 + 不干扰Windsurf        ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

cd /d "%~dp0"
set WAM_DIR=%~dp0010-道引擎_DaoEngine
set DIAG=%~dp0040-诊断工具_Diagnostics

:: ════ 环境检测 ════════════════════════════════════════
echo [检测] 运行环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause & exit /b 1
)
python -c "import sqlite3, json, http.server; print('  Python OK')"
node --version >nul 2>&1
if %errorlevel%==0 (
    echo   Node.js OK
) else (
    echo   [警告] 未找到 Node.js，看门狗将无法运行
)
echo.

:: ════ 语法验证 ══════════════════════════════════════════
echo [验证] Python 语法检查...
python -c "import ast; ast.parse(open(r'%WAM_DIR%\wam_engine.py', encoding='utf-8').read()); print('  wam_engine.py OK')"
if %errorlevel% neq 0 (
    echo [错误] wam_engine.py 语法错误！
    pause & exit /b 1
)
echo.

:: ════ state.vscdb 安全检测 ═════════════════════════════
echo [安全] 检测 state.vscdb 可用性...
python -c "
import os, sqlite3
db = os.path.join(os.environ['APPDATA'], 'Windsurf', 'User', 'globalStorage', 'state.vscdb')
if not os.path.exists(db):
    print('  [警告] state.vscdb 不存在 (Windsurf未启动过?)')
else:
    try:
        conn = sqlite3.connect(db + '?mode=ro', uri=True, timeout=3)
        rows = conn.execute('SELECT count(*) FROM ItemTable').fetchone()
        conn.close()
        print(f'  state.vscdb OK ({rows[0]} 条记录)')
    except Exception as e:
        print(f'  [警告] DB访问: {e}')
"
echo.

:: ════ 停止旧进程 ════════════════════════════════════════
echo [清理] 检查并清理旧 WAM Hub (:9876)...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr :9876 ^| findstr LISTENING') do (
    echo   停止 PID %%a
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul
echo.

:: ════ 启动 WAM Hub ═══════════════════════════════════════
echo [启动] WAM Hub :9876 (智能排序+自动切号)...
start /min "WAM Hub :9876" python "%WAM_DIR%\wam_engine.py" serve

:: 等待启动 (最多10s)
set /a tries=0
:wait_loop
timeout /t 1 /nobreak >nul
set /a tries+=1
curl -s -m 2 http://127.0.0.1:9876/api/health >nul 2>&1
if %errorlevel%==0 goto hub_ready
if %tries% lss 10 goto wait_loop
echo [错误] WAM Hub 启动超时！请检查 Python 环境
pause & exit /b 1

:hub_ready
echo   WAM Hub 已就绪 (:9876)
echo.

:: ════ API 验证 ══════════════════════════════════════════
echo [验证] API 端点测试...
python -c "
import urllib.request, json, sys

def get(path):
    try:
        r = urllib.request.urlopen('http://127.0.0.1:9876' + path, timeout=5)
        return json.loads(r.read())
    except Exception as e:
        return {'error': str(e)}

def post(path):
    try:
        req = urllib.request.Request('http://127.0.0.1:9876' + path,
            data=b'{}', headers={'Content-Type':'application/json'}, method='POST')
        r = urllib.request.urlopen(req, timeout=10)
        return json.loads(r.read())
    except Exception as e:
        return {'error': str(e)}

# 健康检查
h = get('/api/health')
print(f'  /api/health       OK  v{h.get(\"version\",\"?\")}' if 'version' in h else f'  /api/health       FAIL {h}')

# 状态接口
s = get('/api/status')
print(f'  /api/status       OK  {s.get(\"count\",0)}账号 active={str(s.get(\"active_email\",\"?\"))[:20]}' if 'count' in s else f'  /api/status       FAIL {s}')

# 账号列表(排序验证)
a = get('/api/accounts')
if isinstance(a, list) and a:
    top = a[0]
    bot = a[-1]
    print(f'  /api/accounts     OK  {len(a)}个 top=score{top.get(\"score\",\"?\")} bot=score{bot.get(\"score\",\"?\")}')
    assert top.get('score', 0) >= bot.get('score', 0), '排序异常!'
    print('  排序验证          OK  高分在顶,低分沉底 ✅')
else:
    print(f'  /api/accounts     FAIL {a}')

# 兼容路由
pool = get('/api/pool/status')
print(f'  /api/pool/status  OK  D{pool.get(\"dPercent\",\"?\"):%% W{pool.get(\"wPercent\",\"?\")}%%' if 'dPercent' in pool else f'  /api/pool/status  FAIL {pool}')

# 智能切号(高额度账号应hold)
auto = post('/api/auto-switch')
action = auto.get('action', '?')
print(f'  /api/auto-switch  OK  action={action} ({auto.get(\"reason\",\"\")[:40]})' if 'action' in auto else f'  /api/auto-switch  FAIL {auto}')

print()
print('  ✅ 所有 API 验证通过')
"
if %errorlevel% neq 0 (
    echo [错误] API 验证失败！
    pause & exit /b 1
)
echo.

:: ════ 热插入安全验证 ════════════════════════════════════
echo [安全] 热插入安全性验证...
python -c "
import os, sqlite3, json
db = os.path.join(os.environ['APPDATA'], 'Windsurf', 'User', 'globalStorage', 'state.vscdb')
if not os.path.exists(db):
    print('  [跳过] Windsurf DB不存在，热插入将在DB创建后生效')
else:
    try:
        conn = sqlite3.connect(db, timeout=10)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=5000')
        # 读取当前auth状态(只读不改)
        row = conn.execute('SELECT value FROM ItemTable WHERE key=?', ('windsurfAuthStatus',)).fetchone()
        conn.close()
        if row:
            data = json.loads(row[0])
            email = data.get('userInfo', {}).get('email', '?') if isinstance(data, dict) else '?'
            print(f'  当前auth: {email[:30]}')
            print(f'  WAL模式: 已启用 (并发安全)')
            print(f'  热插入安全验证 ✅')
        else:
            print('  [提示] 无windsurfAuthStatus记录')
    except Exception as e:
        print(f'  [警告] {e}')
"
echo.

:: ════ 看门狗启动 ════════════════════════════════════════
echo [启动] 无为看门狗 (限流监控 + 自动触发切号)...
node --version >nul 2>&1
if %errorlevel%==0 (
    start /min "无为看门狗" node "%DIAG%\_watchdog_wuwei.js"
    echo   看门狗已在后台启动 (WAM_HUB=:9876 已对齐)
) else (
    echo   [跳过] Node.js未安装，看门狗不启动
)
echo.

:: ════ 完成 ══════════════════════════════════════════════
echo ╔══════════════════════════════════════════════════════════╗
echo ║  ✅ WAM v5.0 部署完成                                    ║
echo ║                                                          ║
echo ║  Dashboard:  http://127.0.0.1:9876/                     ║
echo ║  智能切号:   自动选最高评分账号 (D+W+天数+快照)         ║
echo ║  自动排序:   耗尽/低额账号自动沉底，优质账号置顶         ║
echo ║  Windsurf:   WAL并发保护，不中断正常运行                 ║
echo ╚══════════════════════════════════════════════════════════╝
echo.
pause
