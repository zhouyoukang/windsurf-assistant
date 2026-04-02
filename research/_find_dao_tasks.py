import subprocess
r = subprocess.run(['schtasks', '/query', '/fo', 'LIST', '/v'],
    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
lines = r.stdout.splitlines()
block = {}
current_folder = '\\'
for line in lines:
    if line.startswith('Folder:'):
        current_folder = line.split(':', 1)[1].strip()
    elif line.startswith('TaskName:'):
        block = {'folder': current_folder, 'name': line.split(':', 1)[1].strip()}
    elif line.startswith('Run As User:'):
        block['user'] = line.split(':', 1)[1].strip()
    elif line.startswith('Task To Run:'):
        block['cmd'] = line.split(':', 1)[1].strip()
        if 'dao_engine' in block.get('cmd', '').lower() or 'DaoEngine' in block.get('name', ''):
            print(block.get('folder', '?') + '\\' + block.get('name', '?'))
            print('  User:', block.get('user', '?'))
            print('  Cmd:', block.get('cmd', '?')[:80])
            print()
