"""Send reload command to Windsurf via IPC pipe"""
import socket, json, struct, sys, os

def send_ipc(pipe_path, msg):
    """Send a message to Windsurf IPC pipe (4-byte LE length header + JSON)"""
    payload = json.dumps(msg).encode('utf-8')
    header = struct.pack('<I', len(payload))
    
    # On Windows, named pipes are accessed differently
    import win32file, win32pipe
    try:
        handle = win32file.CreateFile(
            pipe_path,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0, None,
            win32file.OPEN_EXISTING,
            0, None
        )
        win32file.WriteFile(handle, header + payload)
        # Try to read response
        try:
            hr, data = win32file.ReadFile(handle, 65536)
            if len(data) >= 4:
                resp_len = struct.unpack('<I', data[:4])[0]
                resp_json = data[4:4+resp_len].decode('utf-8', errors='replace')
                print(f"  Response: {resp_json[:200]}")
        except:
            pass
        win32file.CloseHandle(handle)
        return True
    except Exception as e:
        print(f"  Error: {e}")
        return False

pipes = [
    r'\\.\pipe\e2b129e5-1.108.2-main-sock',
    r'\\.\pipe\04fe5883-1.108.2-main-sock',
]

for pipe in pipes:
    print(f"Trying {pipe}...")
    msg = {"type": "reloadWindow"}
    ok = send_ipc(pipe, msg)
    if ok:
        print(f"  ✅ Reload sent!")
        break
    print(f"  Failed, trying next...")
