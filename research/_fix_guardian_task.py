#!/usr/bin/env python3
"""Remove LogonTrigger from DaoEngineGuardian task — fixes double patrol issue."""
import subprocess, tempfile, os
from pathlib import Path

XML = '''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Dao Engine Guardian - TimerOnly</Description>
    <URI>\\DaoEngineGuardian</URI>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <UserId>DESKTOP-MASTER\\Administrator</UserId>
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
      <Command>C:\\ProgramData\\anaconda3\\pythonw.exe</Command>
      <Arguments>"E:\\dao\\dao_engine.py" patrol</Arguments>
      <WorkingDirectory>E:\\dao</WorkingDirectory>
    </Exec>
  </Actions>
</Task>'''

# Use actual paths
DAO_SCRIPT = r'E:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\dao_engine.py'
DAO_DIR    = r'E:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine'
XML = XML.replace(r'E:\\dao\\dao_engine.py', DAO_SCRIPT.replace('\\', '\\\\'))
XML = XML.replace(r'E:\\dao', DAO_DIR.replace('\\', '\\\\'))

# Write UTF-16 LE (required by schtasks)
tmp = Path(tempfile.gettempdir()) / 'DaoEngineGuardian_fix.xml'
tmp.write_text(XML, encoding='utf-16')
print(f'Written XML to: {tmp}')

r = subprocess.run(
    ['schtasks', '/Create', '/XML', str(tmp), '/TN', r'\DaoEngineGuardian', '/F'],
    capture_output=True, text=True, encoding='utf-8', errors='replace'
)
print(f'schtasks result: rc={r.returncode}')
print(r.stdout.strip() or r.stderr.strip())

tmp.unlink(missing_ok=True)

# Verify
r2 = subprocess.run(
    ['schtasks', '/query', '/TN', r'\DaoEngineGuardian', '/XML', 'ONE'],
    capture_output=True, text=True, encoding='utf-8', errors='replace'
)
import re
triggers = re.findall(r'<(LogonTrigger|TimeTrigger)[^/]', r2.stdout)
print(f'Remaining triggers: {triggers}')
if 'LogonTrigger' not in [t for t in triggers]:
    print('SUCCESS: LogonTrigger removed — double patrol eliminated')
else:
    print('WARNING: LogonTrigger still present')
