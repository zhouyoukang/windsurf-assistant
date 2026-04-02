#!/usr/bin/env python3
"""
Update DaoEngineGuardian task to run as 'ai' user (pool owner).
This is the definitive fix: patrol runs in the context that has the 97-account pool.
"""
import subprocess, tempfile
from pathlib import Path

# ai user SID
AI_SID = 'S-1-5-21-2762161139-2962422226-247775911-1004'
DAO_SCRIPT = r'E:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\dao_engine.py'
DAO_DIR = r'E:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine'

XML = (
'<?xml version="1.0" encoding="UTF-16"?>\n'
'<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
'  <RegistrationInfo><Description>Dao Engine Guardian - ai user patrol</Description>'
'<URI>\\DaoEngineGuardian</URI></RegistrationInfo>\n'
'  <Principals><Principal id="Author">'
'<UserId>' + AI_SID + '</UserId>'
'<LogonType>S4U</LogonType>'
'<RunLevel>HighestAvailable</RunLevel>'
'</Principal></Principals>\n'
'  <Settings>'
'<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>'
'<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>'
'<ExecutionTimeLimit>PT2M</ExecutionTimeLimit>'
'<Hidden>true</Hidden>'
'<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>'
'</Settings>\n'
'  <Triggers><TimeTrigger>'
'<StartBoundary>2026-01-01T00:00:00</StartBoundary>'
'<Repetition><Interval>PT5M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>'
'<Enabled>true</Enabled>'
'</TimeTrigger></Triggers>\n'
'  <Actions Context="Author"><Exec>'
'<Command>C:\\ProgramData\\anaconda3\\pythonw.exe</Command>'
'<Arguments>"' + DAO_SCRIPT + '" patrol</Arguments>'
'<WorkingDirectory>' + DAO_DIR + '</WorkingDirectory>'
'</Exec></Actions>\n'
'</Task>'
)

tmp = Path(tempfile.gettempdir()) / 'DaoEngineGuardian_ai.xml'
tmp.write_text(XML, encoding='utf-16')
print(f'Written to: {tmp}')

r = subprocess.run(
    ['schtasks', '/Create', '/XML', str(tmp), '/TN', r'\DaoEngineGuardian', '/F'],
    capture_output=True, text=True, encoding='utf-8', errors='replace'
)
print(f'rc={r.returncode}: {(r.stdout or r.stderr).strip()[:80]}')
tmp.unlink(missing_ok=True)

# Verify
r2 = subprocess.run(
    ['schtasks', '/query', '/TN', r'\DaoEngineGuardian', '/XML', 'ONE'],
    capture_output=True, text=True, encoding='utf-8', errors='replace'
)
import re
uid = re.search(r'<UserId>([^<]+)</UserId>', r2.stdout)
print(f'Task UserId: {uid.group(1) if uid else "unknown"}')
