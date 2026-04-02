@echo off
chcp 65001 >nul
echo ========================================================
echo  Gmail+alias 批量注册 — 道法自然·上善若水
echo  全链路已验证: 表单+Turnstile+密码+邮件 全部通过
echo ========================================================
echo.
echo  当前状态:
echo    GMAIL_BASE: zhouyoukang1234@gmail.com
echo    turnstilePatch: 已加载(自动解决Turnstile)
echo    注册流程: 全自动填表 + Turnstile自动 + 手动验证邮件
echo.
echo  流程说明:
echo    1. Chrome自动打开并填写注册表单
echo    2. Turnstile自动解决(无需操作)
echo    3. 出现"按Enter确认已验证"时:
echo       a. 检查 zhouyoukang1234@gmail.com 收件箱
echo       b. 找Windsurf/Codeium验证邮件
echo       c. 点击邮件中的验证链接
echo       d. 回到此终端按 Enter
echo.
echo  如已配置 GMAIL_APP_PASSWORD，步骤3全自动无需手动!
echo.
set /p n="注册几个账号? [默认5]: "
if "%n%"=="" set n=5
echo.
echo  开始批量注册 %n% 个账号...
echo.
C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe "%~dp0020-注册管线_Pipeline\_gmail_alias_engine.py" batch %n% --manual
echo.
echo  注册完成! 查看结果:
C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe "%~dp0020-注册管线_Pipeline\_gmail_alias_engine.py" status
pause
