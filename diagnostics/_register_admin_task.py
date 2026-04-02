#!/usr/bin/env python3
"""注册Administrator登录时WAM启动的计划任务"""
import subprocess, os
from pathlib import Path

TASK_NAME = 'WindsurfAdminWAM'
SCRIPT = r'e:\道\道生一\一生二\Windsurf无限额度\→Administrator_启动.cmd'
CMD_EXE = r'C:\Windows\System32\cmd.exe'

task_xml = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>WAM Administrator: clear pool key + apply patches on logon</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>DESKTOP-THVMJP3\\Administrator</UserId>
      <Delay>PT15S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal>
      <UserId>DESKTOP-THVMJP3\\Administrator</UserId>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Hidden>true</Hidden>
  </Settings>
  <Actions>
    <Exec>
      <Command>{CMD_EXE}</Command>
      <Arguments>/c "{SCRIPT}"</Arguments>
    </Exec>
  </Actions>
</Task>'''

# Write XML to temp file
import tempfile
xml_file = Path(tempfile.gettempdir()) / '_admin_wam_task.xml'
xml_file.write_text(task_xml, encoding='utf-16')
print(f'XML: {xml_file}')

# Delete existing task if any
r = subprocess.run(['schtasks', '/Delete', '/TN', TASK_NAME, '/F'],
    capture_output=True, timeout=10, encoding='utf-8', errors='replace')
print(f'Delete existing: rc={r.returncode}')

# Create task from XML
r = subprocess.run(
    ['schtasks', '/Create', '/TN', TASK_NAME, '/XML', str(xml_file), '/F'],
    capture_output=True, timeout=15, encoding='utf-8', errors='replace'
)
print(f'Create: rc={r.returncode}')
print(r.stdout.strip() or r.stderr.strip())

xml_file.unlink(missing_ok=True)

# Verify
r2 = subprocess.run(
    ['schtasks', '/Query', '/TN', TASK_NAME, '/FO', 'LIST'],
    capture_output=True, timeout=10, encoding='utf-8', errors='replace'
)
if r2.returncode == 0:
    for line in r2.stdout.strip().split('\n')[:8]:
        print(f'  {line.rstrip()}')
    print('Task registered OK')
else:
    print(f'Query failed: {r2.stderr.strip()[:200]}')
    # Fallback: try registry approach
    print('Trying registry fallback...')
    import winreg
    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
        r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList',
        0, winreg.KEY_READ)
    winreg.CloseKey(key)
