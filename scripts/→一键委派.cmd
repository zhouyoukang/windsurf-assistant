@echo off
chcp 65001 >nul
echo ======================================
echo  Windsurf 多模型委派中枢 v1.0
echo  反者道之动，弱者道之用
echo ======================================
echo.
echo  [1] 创建委派任务 (写入dispatch/task文件)
echo  [2] 查看积分状态
echo  [3] g4f外部推理测试 (Groq Llama70B)
echo  [4] 启动Model Router (:18881)
echo  [5] CLI Bridge状态
echo  [6] 查看已有委派任务
echo  [7] 查看委派指南
echo.
set /p c="选择 (1-7): "

if "%c%"=="1" (
    set /p desc="任务描述: "
    set /p steps="执行步骤: "
    python "%~dp0credit_toolkit.py" delegate "%desc%" "%steps%"
    echo.
    echo === 下一步 ===
    echo 1. Ctrl+L 打开新Cascade面板
    echo 2. 模型选择器 → SWE-1.5 Free
    echo 3. 粘贴: 读取并执行上述task文件路径
    echo 4. SWE-1.5执行 (0 credits)
    echo 5. 切回当前面板验证结果
)
if "%c%"=="2" python "%~dp0credit_toolkit.py" monitor
if "%c%"=="3" python -c "import os;os.environ['G4F_PROXY']='http://127.0.0.1:7890';from g4f.client import Client;from g4f import Provider;c=Client(provider=Provider.Groq);r=c.chat.completions.create(model='llama-3.3-70b-versatile',messages=[{'role':'user','content':'Hello, reply with OK and your model name'}],timeout=30);print(r.choices[0].message.content)"
if "%c%"=="4" start "ModelRouter" python "%~dp0..\龙虾资源\model_router.py" & echo Model Router starting on :18881...
if "%c%"=="5" python -c "import urllib.request,json;r=json.loads(urllib.request.urlopen('http://127.0.0.1:19850/api/status',timeout=3).read());print(json.dumps(r,indent=2,ensure_ascii=False))"
if "%c%"=="6" dir /b "%~dp0..\多模型协作\dispatch\*.md" 2>nul || echo 无委派任务
if "%c%"=="7" start "" "%~dp0DELEGATION_GUIDE.md"

pause
