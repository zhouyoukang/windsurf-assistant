"""
get_csrf.py — 从 language_server 进程读取 WINDSURF_CSRF_TOKEN 环境变量
使用 Windows ReadProcessMemory API 读取 PEB 中的环境块
"""
import ctypes, ctypes.wintypes, sys, re, struct, subprocess

PROCESS_VM_READ          = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS       = 0x00000002

k32 = ctypes.windll.kernel32
nt  = ctypes.windll.ntdll

def open_process(pid):
    h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    return h

def read_memory(handle, addr, size):
    buf  = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t(0)
    ok   = k32.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(read))
    if not ok:
        return None
    return buf.raw[:read.value]

def get_process_env(pid):
    """读取进程环境块，返回 dict"""
    h = open_process(pid)
    try:
        is64 = sys.maxsize > 2**32

        # 1. PROCESS_BASIC_INFORMATION → PebBaseAddress
        pbi_size = 48  # 64-bit: 6 × 8 bytes
        pbi      = ctypes.create_string_buffer(pbi_size)
        ret_len  = ctypes.c_ulong(0)
        nt.NtQueryInformationProcess(h, 0, pbi, pbi_size, ctypes.byref(ret_len))

        # PebBaseAddress is at offset 8 in 64-bit PROCESS_BASIC_INFORMATION
        peb_addr = struct.unpack_from('Q', pbi, 8)[0]
        print(f"  PEB @ 0x{peb_addr:016x}")

        # 2. Read PEB (we need ProcessParameters pointer at offset 0x20 in 64-bit PEB)
        peb = read_memory(h, peb_addr, 0x400)
        if not peb:
            print("  Failed to read PEB")
            return {}

        proc_params_addr = struct.unpack_from('Q', peb, 0x20)[0]
        print(f"  ProcessParameters @ 0x{proc_params_addr:016x}")

        # 3. Read RTL_USER_PROCESS_PARAMETERS
        # Environment offset in RTL_USER_PROCESS_PARAMETERS (64-bit):
        #   0x80 = Environment pointer
        #   0x03F0 = EnvironmentSize (varies by Windows version, usually 0x3F0 or 0x400)
        params = read_memory(h, proc_params_addr, 0x500)
        if not params:
            print("  Failed to read params")
            return {}

        env_addr = struct.unpack_from('Q', params, 0x80)[0]
        try:
            env_size = struct.unpack_from('Q', params, 0x3F0)[0]
            if env_size > 1024*1024: env_size = 65536  # cap at 64K
        except: env_size = 32768
        print(f"  Environment @ 0x{env_addr:016x}, size={env_size}")

        # 4. Read environment block
        env_block = read_memory(h, env_addr, env_size)
        if not env_block:
            print("  Failed to read env block")
            return {}

        # 5. Parse: UTF-16LE null-terminated strings, double-null terminated
        env_str = env_block.decode('utf-16-le', errors='replace')
        env_dict = {}
        for entry in env_str.split('\x00'):
            if '=' in entry:
                k, _, v = entry.partition('=')
                if k.strip():
                    env_dict[k] = v
            if entry == '':
                break

        return env_dict

    finally:
        k32.CloseHandle(h)

def find_ls_pids():
    """找所有 language_server_windows_x64.exe 进程"""
    try:
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             'Get-Process -Name language_server_windows_x64 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id'],
            capture_output=True, text=True, timeout=10
        )
        pids = re.findall(r'\d+', r.stdout)
        if pids:
            return [int(p) for p in pids]
    except Exception:
        pass
    # fallback: known PIDs
    return [54108, 31872]

if __name__ == '__main__':
    print("查找 language_server 进程...")
    pids = find_ls_pids()
    if not pids:
        # 手动指定
        pids = [54108, 31872]
    print(f"找到 PIDs: {pids}")

    for pid in pids:
        print(f"\n=== PID {pid} ===")
        try:
            env = get_process_env(pid)
            csrf = env.get('WINDSURF_CSRF_TOKEN', '')
            api  = env.get('CODEIUM_API_KEY', env.get('WINDSURF_API_KEY', ''))
            print(f"  WINDSURF_CSRF_TOKEN = {csrf[:60] if csrf else '(not found)'}")
            print(f"  API_KEY env         = {api[:30] if api else '(not found)'}")
            # Print all windsurf/codeium env vars
            for k, v in sorted(env.items()):
                if any(x in k.upper() for x in ['WINDSURF', 'CODEIUM', 'CSRF', 'TOKEN', 'PORT', 'API']):
                    print(f"  {k} = {v[:80]}")
        except Exception as e:
            print(f"  Error: {e}")
