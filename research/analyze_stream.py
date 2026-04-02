"""analyze_stream.py — 分析 stream_frames.json + 找 AI 响应文本位置"""
import json, base64, re

with open(r'e:\道\道生一\一生二\Windsurf无限额度\stream_frames.json', 'r', encoding='utf-8') as f:
    frames = json.load(f)

print(f"Total frames: {len(frames)}")
print()

# Decode fullState
if frames and 'fullState' in frames[0]:
    fs_b64 = frames[0]['fullState']
    try:
        # Add padding
        pad = 4 - len(fs_b64) % 4
        if pad < 4: fs_b64 += '=' * pad
        raw = base64.b64decode(fs_b64)
        print(f"fullState: {len(raw)} bytes")
        # Find ALL printable strings > 4 chars
        texts = re.findall(rb'[\x20-\x7e]{5,}', raw)
        print("Strings in fullState:")
        for t in texts[:40]:
            s = t.decode('utf-8', 'replace')
            print(f"  {repr(s)}")
    except Exception as e:
        print(f"Decode error: {e}")

print()

# Analyze diff frames
print("=== Diff frames analysis ===")
for i, frame in enumerate(frames[1:], 1):
    if 'diff' not in frame: continue
    diff = frame['diff']
    
    def walk(obj, path=''):
        if isinstance(obj, dict):
            for k, v in obj.items():
                new_path = f"{path}.{k}"
                if k == 'stringValue' and isinstance(v, str) and len(v) > 3:
                    print(f"  Frame#{i+1} {new_path}: {repr(v[:200])}")
                elif k == 'base64Value' and isinstance(v, str):
                    try:
                        pad = 4 - len(v) % 4
                        if pad < 4: v += '='*pad
                        decoded = base64.b64decode(v)
                        texts = re.findall(rb'[\x20-\x7e]{5,}', decoded)
                        for t in texts[:5]:
                            s = t.decode('utf-8', 'replace')
                            print(f"  Frame#{i+1} {new_path}(b64 text): {repr(s)}")
                    except: pass
                walk(v, new_path)
        elif isinstance(obj, list):
            for j, item in enumerate(obj[:5]):
                walk(item, f"{path}[{j}]")
    
    walk(diff)
