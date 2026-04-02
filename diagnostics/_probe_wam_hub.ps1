$ErrorActionPreference = "Continue"
$TARGET_IP   = "192.168.31.179"
$TARGET_USER = "zhouyoukang"
$TARGET_PASS = "wsy057066wsy"

$sp = New-Object System.Security.SecureString
$TARGET_PASS.ToCharArray() | ForEach-Object { $sp.AppendChar($_) }
$cr = New-Object System.Management.Automation.PSCredential($TARGET_USER, $sp)
Set-Item WSMan:\localhost\Client\TrustedHosts -Value $TARGET_IP -Force -ErrorAction SilentlyContinue

$result = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ScriptBlock {
    # 探测WAM Hub所有端点
    Write-Host "=== WAM Hub API探测 ===" -ForegroundColor Cyan

    $endpoints = @(
        @{method="GET";  url="http://127.0.0.1:9870/"},
        @{method="GET";  url="http://127.0.0.1:9870/api/pool/status"},
        @{method="GET";  url="http://127.0.0.1:9870/api/pool/best"},
        @{method="GET";  url="http://127.0.0.1:9870/api/health"},
        @{method="GET";  url="http://127.0.0.1:9870/api/accounts"},
        @{method="GET";  url="http://127.0.0.1:9870/api/current"},
        @{method="GET";  url="http://127.0.0.1:9870/api/active"},
        @{method="GET";  url="http://127.0.0.1:9870/api/status"}
    )

    foreach ($ep in $endpoints) {
        try {
            $r = Invoke-WebRequest $ep.url -Method $ep.method -UseBasicParsing -TimeoutSec 3
            $body = $r.Content
            if ($body.Length -gt 300) { $body = $body.Substring(0,300) + "..." }
            Write-Host "OK:$($ep.url):$body"
        } catch {
            Write-Host "FAIL:$($ep.url):$($_.Exception.Message)"
        }
    }

    # 找WAM Hub进程和脚本
    Write-Host "`n=== WAM Hub进程详情 ===" -ForegroundColor Cyan
    $procs = Get-WmiObject Win32_Process -Filter "Name='python.EXE' OR Name='python311.EXE' OR Name='python3.EXE'" -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        if ($p.CommandLine -like "*9870*" -or $p.CommandLine -like "*wam*" -or $p.CommandLine -like "*hub*" -or $p.CommandLine -like "*pool*") {
            Write-Host "HUB_PROC:PID=$($p.ProcessId):CMD=$($p.CommandLine)"
        }
    }

    # 找wam_hub.py脚本内容
    Write-Host "`n=== wam_hub.py路径探测 ===" -ForegroundColor Cyan
    $task = Get-ScheduledTask -TaskName "WAMHub" -ErrorAction SilentlyContinue
    if ($task) {
        $args = $task.Actions[0].Arguments
        $cwd  = $task.Actions[0].WorkingDirectory
        Write-Host "TASK_ARGS:$args"
        Write-Host "TASK_CWD:$cwd"
        # 提取脚本路径
        if ($args -match "(-u\s+|--?\w+\s+)*([A-Za-z]:[\\\/][^\s]+\.py)") {
            $scriptPath = $matches[2]
            Write-Host "SCRIPT:$scriptPath"
            if (Test-Path $scriptPath) {
                # 读取脚本前50行了解API
                $lines = Get-Content $scriptPath -TotalCount 80 -ErrorAction SilentlyContinue
                $lines | ForEach-Object { Write-Host "SRC:$_" }
            }
        }
    }
} -ErrorAction Stop

$result | ForEach-Object { Write-Host $_ }
