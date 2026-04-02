"""
cascade_client_final.py
=======================
Windsurf Cascade 后端直调客户端 — 生产版

功能:
  - 自动读取 cascade-auth.json key (有 Claude 权限)
  - 完整 cascade 流：Init → StartCascade → SendUserCascadeMessage → Stream
  - 支持 claude-sonnet-4-6 / claude-opus-4-6 / gpt-4.1 等模型
  - 交互式对话模式

用法:
  python cascade_client_final.py                          # 交互模式
  python cascade_client_final.py "你的问题"               # 单次提问
  python cascade_client_final.py --model claude-sonnet-4-6 "问题"
"""

import sys, json, sqlite3, struct, time, requests, re, os

# ===== 配置 =====
LS_PORT = 64958
DEFAULT_MODEL = "claude-opus-4-6"  # 支持: claude-opus-4-6, claude-sonnet-4-6, gpt-4.1 等

# ===== 认证 =====
def get_auth():
    """始终使用当前 WAM 轮换 key（state.vscdb），该 key 随账号切换实时更新"""
    db_path = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
    try:
        con = sqlite3.connect(db_path); cur = con.cursor()
        cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
        row = cur.fetchone(); con.close()
        if row:
            return json.loads(row[0]).get('apiKey', '')
    except: pass
    return ''

def get_csrf():
    """从进程环境获取 CSRF token"""
    import subprocess
    try:
        r = subprocess.run(
            ['powershell', '-Command',
             '(Get-WmiObject Win32_Process | Where-Object {$_.Name -like "*windsurf*" -and '
             '$_.ProcessId -eq (Get-NetTCPConnection -LocalPort 64958 -ErrorAction SilentlyContinue | '
             'Select-Object -First 1 -ExpandProperty OwningProcess)} | '
             'Select-Object -ExpandProperty ProcessId) 2>$null'],
            capture_output=True, text=True, timeout=5
        )
        pid = r.stdout.strip()
        if pid.isdigit():
            # Read env from process memory (simplified - use stored CSRF)
            pass
    except: pass
    # Use known working CSRF token
    return '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'

CSRF = get_csrf()

def make_meta():
    """每次调用时获取最新 WAM key"""
    return {
        "ideName": "Windsurf", "ideVersion": "1.108.2",
        "extensionVersion": "3.14.2", "extensionName": "Windsurf",
        "extensionPath": r"D:\Windsurf\resources\app\extensions\windsurf",
        "apiKey": get_auth(), "locale": "en-US", "os": "win32",
        "url": "https://server.codeium.com",
    }

HDR = {
    'Content-Type': 'application/grpc-web+json',
    'Accept': 'application/grpc-web+json',
    'x-codeium-csrf-token': CSRF,
    'x-grpc-web': '1',
}

def _post(method, body, meta=None, timeout=8):
    if meta is None:
        meta = make_meta()
    if 'metadata' not in body:
        body['metadata'] = meta
    b = json.dumps(body).encode()
    r = requests.post(
        f'http://127.0.0.1:{LS_PORT}/exa.language_server_pb.LanguageServerService/{method}',
        data=b'\x00' + struct.pack('>I', len(b)) + b,
        headers=HDR, timeout=timeout, stream=True
    )
    raw = b''.join(r.iter_content(chunk_size=None))
    frames = []; pos = 0
    while pos + 5 <= len(raw):
        flag = raw[pos]; n = struct.unpack('>I', raw[pos+1:pos+5])[0]; pos += 5
        frames.append((flag, raw[pos:pos+n])); pos += n
    return frames

def start_session(meta=None):
    """初始化 cascade session，返回 cascade_id"""
    if meta is None:
        meta = make_meta()
    _post("InitializeCascadePanelState", {"metadata": meta, "workspaceTrusted": True}, meta)
    _post("UpdateWorkspaceTrust", {"metadata": meta, "workspaceTrusted": True}, meta)
    f1 = _post("StartCascade", {"metadata": meta, "source": "CORTEX_TRAJECTORY_SOURCE_USER"}, meta)
    for flag, data in f1:
        if flag == 0:
            try: return json.loads(data).get('cascadeId'), meta
            except: pass
    return None, meta

def send_message(cascade_id, message, model=DEFAULT_MODEL, meta=None):
    """发送用户消息，返回 (success, error_msg)"""
    if meta is None:
        meta = make_meta()
    f2 = _post("SendUserCascadeMessage", {
        "metadata": meta,
        "cascadeId": cascade_id,
        "items": [{"text": message}],
        "cascadeConfig": {"plannerConfig": {
            "requestedModelUid": model,
            "conversational": {}
        }},
    }, meta)
    trailer = next((d.decode('utf-8', 'replace') for flag, d in f2 if flag == 0x80), '')
    return 'grpc-status: 0' in trailer, trailer.strip()

def stream_response(cascade_id, timeout=30):
    """流式读取 AI 响应 — 等待 RUNNING 状态后提取实际 AI 文本"""
    sb = json.dumps({"id": cascade_id, "protocolVersion": 1}).encode()
    sd = b'\x00' + struct.pack('>I', len(sb)) + sb
    
    # System-prompt/context strings to skip
    SKIP_FRAGS = [
        'You are Cascade', 'The USER is interacting', 'communication_style',
        'tool_calling', 'making_code_changes', 'Before each tool call',
        'You have the ability to call tools', 'citation_guidelines',
        'Prefer minimal', 'EXTREMELY IMPORTANT', 'Keep dependent',
        'Batch independent', 'No MEMORIES were retrieved',
        'read_file', 'run_command', 'grep_search', 'find_by_name',
        'write_to_file', 'edit_notebook', 'view_content_chunk',
        'search_web', 'todo_list', 'browser_preview', 'read_terminal',
        'Spin up a browser', 'Check the status', 'Performs a', 'Lists files',
        'Lists all', 'Read content', 'Reads the', 'Reads a file',
        '{"$schema"', 'additionalProperties', 'description":',
        'CodeContent', 'TargetFile', 'CommandLine', 'SearchPath',
        'long-horizon workflow', 'Bug fixing discipline', 'Planning cadence',
        'Testing discipline', 'Verification tools', 'Progress notes',
        'Modifier keys to press', 'Available skills',
    ]
    
    all_strings = []
    frame_n = 0
    seen = set()
    
    def collect(obj, depth=0):
        if depth > 25: return
        if isinstance(obj, str) and 4 < len(obj) < 400:
            if obj not in seen:
                seen.add(obj)
                all_strings.append((frame_n, obj))
        elif isinstance(obj, dict):
            for v in obj.values(): collect(v, depth+1)
        elif isinstance(obj, list):
            for item in obj: collect(item, depth+1)
    
    try:
        r3 = requests.post(
            f'http://127.0.0.1:{LS_PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
            data=sd, headers=HDR, timeout=timeout + 2, stream=True
        )
        buf = b''; t0 = time.time()
        for chunk in r3.iter_content(chunk_size=128):
            buf += chunk
            while len(buf) >= 5:
                n = struct.unpack('>I', buf[1:5])[0]
                if len(buf) < 5 + n: break
                flag = buf[0]; frame_data = buf[5:5+n]; buf = buf[5+n:]
                if flag == 0x80: break
                try:
                    parsed = json.loads(frame_data)
                    frame_n += 1
                    collect(parsed)
                except: pass
            if time.time() - t0 > timeout: break
    except: pass
    
    # Filter out system prompt / context strings
    # The AI response comes from the LATER frames (after frame 5 typically)
    # and should not match any known system context patterns
    response_candidates = []
    for fn, s in all_strings:
        if fn < 4: continue  # Skip early context frames
        if any(frag in s for frag in SKIP_FRAGS): continue
        if any(x in s for x in ['MODEL_', 'grpc-', 'D:\\', 'exa.', 'CiQ', 'C:\\',
                                  'http://', 'https://', '.exe', '.ipynb',
                                  'kubectl', 'terraform', 'gsutil', 'gcloud',
                                  'CORTEX_', 'CACHE_CONTROL', 'CASCADE_',
                                  'CHAT_MESSAGE_SOURCE', 'CONVERSATIONAL_PLANNER',
                                  'SECTION_OVERRIDE', 'REPLACE_TOOL']): continue
        response_candidates.append(s)
    
    # Yield first few response candidates
    for s in response_candidates[:8]:
        yield s

def chat(message, model=DEFAULT_MODEL, verbose=False, max_retries=5):
    """完整聊天调用，返回 AI 响应。permission_denied 时自动重试（等待 WAM 轮换）"""
    if verbose:
        print(f"[Model: {model}]", file=sys.stderr)
    
    for attempt in range(max_retries):
        meta = make_meta()
        cid, meta = start_session(meta)
        if not cid:
            if attempt < max_retries - 1:
                time.sleep(3); continue
            return "[Error: Could not start cascade session]"
        
        ok, status = send_message(cid, message, model, meta)
        if not ok:
            return f"[Error: Message send failed - {status}]"
        
        responses = []
        errors = []
        for s in stream_response(cid, timeout=25):
            if 'denied' in s.lower() or 'error occurred' in s.lower():
                errors.append(s)
            else:
                responses.append(s)
        
        if errors and not responses:
            if attempt < max_retries - 1:
                if verbose:
                    print(f"[Attempt {attempt+1}: permission_denied, retrying with new WAM key...]", file=sys.stderr)
                time.sleep(5)
                continue
            return f"[Backend Error: {errors[0][:200]}]"
        
        if responses:
            filtered = [r for r in responses if message[:50] not in r and len(r) > 10]
            return '\n'.join((filtered or responses)[:5])
        
        return "[No response received - try again]"
    
    return "[Max retries exceeded - no Claude-capable WAM key available]"


if __name__ == '__main__':
    # Parse args
    model = DEFAULT_MODEL
    args = sys.argv[1:]
    if '--model' in args:
        i = args.index('--model')
        if i + 1 < len(args):
            model = args[i+1]
            args = args[:i] + args[i+2:]
    
    print(f"Windsurf Cascade Client | Model: {model}")
    print(f"API Key: {get_auth()[:30]}... | Port: {LS_PORT}")
    print()
    
    if args:
        # Single query mode
        question = ' '.join(args)
        print(f"Q: {question}")
        print()
        response = chat(question, model=model, verbose=True)
        print(f"A: {response}")
    else:
        # Interactive mode
        print("Interactive mode (type 'quit' to exit, 'model <name>' to switch model)")
        print()
        while True:
            try:
                user_input = input(f"[{model}] You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye!")
                break
            
            if not user_input:
                continue
            if user_input.lower() == 'quit':
                print("Bye!")
                break
            if user_input.lower().startswith('model '):
                model = user_input[6:].strip()
                print(f"Switched to model: {model}")
                continue
            
            print("AI: ", end='', flush=True)
            response = chat(user_input, model=model)
            print(response)
            print()
