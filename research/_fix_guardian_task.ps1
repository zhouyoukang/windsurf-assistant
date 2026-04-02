# 重新注册DaoEngineGuardian任务，仅保留TimeTrigger，移除LogonTrigger（根除双重patrol）
$xml = @'
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Dao Engine Guardian — 五行合一·自动巡逻 (TimerOnly)</Description>
    <URI>\DaoEngineGuardian</URI>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <UserId>DESKTOP-MASTER\Administrator</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT2M</ExecutionTimeLimit>
    <Hidden>true</Hidden>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <IdleSettings>
      <StopOnIdleEnd>true</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
  </Settings>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>2026-01-01T00:00:00</StartBoundary>
      <Repetition>
        <Interval>PT5M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>C:\ProgramData\anaconda3\pythonw.exe</Command>
      <Arguments>"E:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\dao_engine.py" patrol</Arguments>
      <WorkingDirectory>E:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
'@

$tmpFile = "$env:TEMP\DaoEngineGuardian.xml"
[System.IO.File]::WriteAllText($tmpFile, $xml, [System.Text.Encoding]::Unicode)
$result = schtasks /Create /XML $tmpFile /TN "\DaoEngineGuardian" /F 2>&1
Write-Host "Task update result: $result"
Remove-Item $tmpFile -ErrorAction SilentlyContinue

# 验证
schtasks /query /TN "\DaoEngineGuardian" /fo LIST 2>$null | Select-String "Triggers|Repeat"
