#!/usr/bin/env python3
"""注册Administrator登录时WAM启动的计划任务 v2"""
import subprocess, tempfile, os
from pathlib import Path

TASK_NAME = 'WindsurfAdminWAM'
SCRIPT = r'e:\道\道生一\一生二\Windsurf无限额度\→Administrator_启动.cmd'

task_xml = '''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>WAM Administrator: clear pool key and apply patches on logon</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>DESKTOP-MASTER\\Administrator</UserId>
      <Delay>PT20S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal>
      <UserId>DESKTOP-MASTER\\Administrator</UserId>
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
      <Command>C:\\Windows\\System32\\cmd.exe</Command>
      <Arguments>/c "e:\\道\\道生一\\一生二\\Windsurf无限额度\\→Administrator_启动.cmd"</Arguments>
    </Exec>
  </Actions>
</Task>'''

xml_file = Path(tempfile.gettempdir()) / '_admin_wam_task.xml'
xml_file.write_text(task_xml, encoding='utf-16')

# Delete existing, ignore error
subprocess.run(['schtasks', '/Delete', '/TN', TASK_NAME, '/F'],
    capture_output=True, timeout=10)

# Create from XML
r = subprocess.run(
    ['schtasks', '/Create', '/TN', TASK_NAME, '/XML', str(xml_file), '/F'],
    capture_output=True, timeout=15
)
xml_file.unlink(missing_ok=True)

if r.returncode == 0:
    print('Task WindsurfAdminWAM registered OK')
else:
    stdout = r.stdout.decode('utf-8', errors='replace').strip()
    stderr = r.stderr.decode('utf-8', errors='replace').strip()
    print(f'schtasks rc={r.returncode}')
    print(f'stdout: {stdout[:200]}')
    print(f'stderr: {stderr[:200]}')

# Verify
r2 = subprocess.run(
    ['schtasks', '/Query', '/TN', TASK_NAME],
    capture_output=True, timeout=10
)
out2 = r2.stdout.decode('utf-8', errors='replace').strip()
if TASK_NAME in out2:
    print(f'Verified: task exists in scheduler')
else:
    print(f'Verify output: {out2[:100]}')
