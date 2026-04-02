#!/usr/bin/env python3
"""
WAM Login Helper v9.0 → v9.2 Upgrade Script
=============================================
根因修复:
  1. Opus预算守卫: 降低预算 4→3, 预防比 0.75→0.5, Tab感知分摊
  2. 容量探测: 加速Opus探测 15s→5s, 添加installationId到protobuf请求
  3. 模型UID检测: 修复null问题, 增加多路径读取
  4. 输出通道实时监控: 拦截Cascade错误消息, 0延迟检测rate limit
  5. 容量探测backoff: 5次失败→3次, 5min→2min (减少盲区)

使用:
  python upgrade_v9.2.py status   # 查看当前状态
  python upgrade_v9.2.py apply    # 应用升级
  python upgrade_v9.2.py revert   # 回滚
"""
import os, sys, shutil, re
from datetime import datetime

EXT_DIR = os.path.join(
    os.environ.get('USERPROFILE', ''),
    '.windsurf', 'extensions',
    'zhouyoukang.windsurf-assistant-1.0.0'
)
SRC_EXT = os.path.join(EXT_DIR, 'src', 'extension.js')
SRC_AUTH = os.path.join(EXT_DIR, 'src', 'authService.js')
BACKUP_DIR = os.path.join(os.path.dirname(__file__), '_wam_upgrade_backups')

# ============================================================
# Patch Definitions — (find, replace, description)
# ============================================================

PATCHES_EXT = [
    # === P1: Lower Opus budget 4→3 ===
    {
        'id': 'P1_OPUS_BUDGET',
        'desc': 'Opus消息预算 4→3 (更保守)',
        'find': "const OPUS_MSG_BUDGET = 4;",
        'replace': "const OPUS_MSG_BUDGET = 3; // v9.2: 4→3 更保守",
    },
    # === P2: Lower preempt ratio 0.75→0.5 ===
    {
        'id': 'P2_PREEMPT_RATIO',
        'desc': 'Opus预防比 0.75→0.5 (2条后即切)',
        'find': "const OPUS_PREEMPT_RATIO = 0.75;",
        'replace': "const OPUS_PREEMPT_RATIO = 0.5; // v9.2: 0.75→0.5 2条后即切",
    },
    # === P3: Tab-aware budget in _isNearOpusBudget ===
    {
        'id': 'P3_TAB_BUDGET',
        'desc': 'Tab感知预算分摊 (多Tab时更激进)',
        'find': "function _isNearOpusBudget(accountIndex) {\n  return _getOpusMsgCount(accountIndex) >= Math.floor(OPUS_MSG_BUDGET * OPUS_PREEMPT_RATIO);\n}",
        'replace': """function _isNearOpusBudget(accountIndex) {
  // v9.2: Tab-aware budget — 多Tab时分摊预算, 更激进
  const tabCount = Math.max(1, _cascadeTabCount);
  const effectiveBudget = tabCount > 1 ? Math.max(2, Math.ceil(OPUS_MSG_BUDGET / tabCount)) : OPUS_MSG_BUDGET;
  const preemptAt = Math.max(1, Math.floor(effectiveBudget * OPUS_PREEMPT_RATIO));
  return _getOpusMsgCount(accountIndex) >= preemptAt;
}""",
    },
    # === P4: Faster capacity probe for Opus ===
    {
        'id': 'P4_CAPACITY_FAST',
        'desc': '容量探测加速 15s→5s(Opus活跃时)',
        'find': "const CAPACITY_CHECK_FAST = 15000;",
        'replace': "const CAPACITY_CHECK_FAST = 5000; // v9.2: 15s→5s Opus活跃时更频繁",
    },
    # === P5: Reduce backoff threshold ===
    {
        'id': 'P5_BACKOFF',
        'desc': '容量探测backoff阈值 5→3次, 5min→2min',
        'find': "if (_capacityProbeFailCount >= 5) {\n    // After 5 consecutive failures, only try every 5 minutes\n    if (Date.now() - _lastCapacityCheck < 300000) return _lastCapacityResult;\n  }",
        'replace': "if (_capacityProbeFailCount >= 3) {\n    // v9.2: After 3 consecutive failures, only try every 2 minutes (was 5/5min)\n    if (Date.now() - _lastCapacityCheck < 120000) return _lastCapacityResult;\n  }",
    },
    # === P6: Capacity preempt remaining 2→1 ===
    {
        'id': 'P6_PREEMPT_REMAINING',
        'desc': '容量预防阈值 ≤2→≤1条 (只在真正有数据时生效)',
        'find': "const CAPACITY_PREEMPT_REMAINING = 2;",
        'replace': "const CAPACITY_PREEMPT_REMAINING = 1; // v9.2: 只剩1条即切",
    },
    # === P7: Output channel rate limit interception ===
    {
        'id': 'P7_OUTPUT_INTERCEPT',
        'desc': '输出通道实时拦截 — 0延迟检测rate limit错误',
        'find': """// ═══ 结构化日志系统 (v6.2 P1) ═══""",
        'replace': """// ═══ v9.2 Layer 9: Output Channel Rate Limit Interception ═══
// 核心突破: 监控所有输出通道(包括Cascade)的rate limit错误消息
// 相比轮询(8-45s延迟), 输出拦截实现0延迟检测
let _outputInterceptActive = false;
let _lastInterceptSwitch = 0;
const INTERCEPT_COOLDOWN = 5000; // 拦截触发切换的冷却 5s (防抖)
const RATE_LIMIT_PATTERNS = [
  /rate\s*limit\s*exceeded/i,
  /permission\s*denied.*rate\s*limit/i,
  /reached.*message.*(?:rate\s*)?limit/i,
  /try\s*again\s*in\s*about\s*an?\s*hour/i,
  /too\s*many\s*requests/i,
];

function _setupOutputInterception(context) {
  if (_outputInterceptActive) return;
  try {
    // 监控所有输出通道变化(包括Windsurf Language Server和Cascade)
    const disposable = vscode.workspace.onDidChangeTextDocument(event => {
      // 只监控scheme为'output'的文档(VS Code输出面板)
      if (event.document.uri.scheme !== 'output') return;
      const changes = event.contentChanges;
      if (!changes || changes.length === 0) return;
      for (const change of changes) {
        const text = change.text;
        if (!text || text.length < 20 || text.length > 2000) continue;
        for (const pattern of RATE_LIMIT_PATTERNS) {
          if (pattern.test(text)) {
            _onRateLimitIntercepted(context, text);
            return;
          }
        }
      }
    });
    context.subscriptions.push(disposable);
    _outputInterceptActive = true;
    _logInfo('INTERCEPT', 'v9.2 Layer 9: 输出通道rate limit拦截已激活');
  } catch (e) {
    _logWarn('INTERCEPT', '输出拦截初始化失败(非致命):', e.message);
  }
}

async function _onRateLimitIntercepted(context, errorText) {
  if (Date.now() - _lastInterceptSwitch < INTERCEPT_COOLDOWN) return; // 防抖
  if (_switching) return;
  _lastInterceptSwitch = Date.now();
  const model = _readCurrentModelUid();
  const gateType = _classifyRateLimit(errorText, null);
  _logWarn('INTERCEPT', `⚡ 实时拦截到rate limit! type=${gateType} model=${model} text="${errorText.substring(0, 100)}"`);
  _pushRateLimitEvent({ type: gateType, trigger: 'output_intercept_L9', model, text: errorText.substring(0, 200) });
  
  if (gateType === 'tier_cap') {
    await _handleTierRateLimit(context, 3600);
  } else if (gateType === 'per_model' && model) {
    await _handlePerModelRateLimit(context, model, OPUS_COOLDOWN_DEFAULT);
  } else {
    // 通用: 直接紧急切号
    _activateBoost();
    _invalidateApiKeyCache();
    await _doPoolRotate(context, true);
  }
}

// ═══ 结构化日志系统 (v6.2 P1) ═══""",
    },
    # === P8: Fix model UID detection robustness ===
    {
        'id': 'P8_MODEL_UID_FIX',
        'desc': '模型UID检测增强 — 多路径读取+缓存修复',
        'find': """function _readCurrentModelUid() {
  try {
    if (!auth) return _currentModelUid;
    const cw = auth.readCachedValue && auth.readCachedValue('codeium.windsurf');
    if (cw) {
      const d = JSON.parse(cw);
      const uids = d['windsurf.state.lastSelectedCascadeModelUids'];
      if (Array.isArray(uids) && uids.length > 0) {
        _currentModelUid = uids[0];
        return _currentModelUid;
      }
    }
  } catch {}
  // v8.0 fallback: 如果state.vscdb读取失败但有缓存值则返回缓存
  // 防止_currentModelUid为null导致Gate 3 handler被跳过
  return _currentModelUid || 'claude-opus-4-6-thinking-1m'; // 默认假设Opus(保守策略)
}""",
        'replace': """function _readCurrentModelUid() {
  try {
    if (!auth) return _currentModelUid || 'claude-opus-4-6-thinking-1m';
    // v9.2: 多路径读取 — 优先级: codeium.windsurf → windsurfConfigurations → editor context
    const paths = ['codeium.windsurf', 'windsurfConfigurations'];
    for (const key of paths) {
      try {
        const cw = auth.readCachedValue && auth.readCachedValue(key);
        if (!cw) continue;
        const d = JSON.parse(cw);
        // Path 1: lastSelectedCascadeModelUids
        const uids = d['windsurf.state.lastSelectedCascadeModelUids'];
        if (Array.isArray(uids) && uids.length > 0) {
          _currentModelUid = uids[0];
          return _currentModelUid;
        }
        // Path 2: selectedModel
        const selected = d['windsurf.selectedModel'] || d['selectedModel'];
        if (selected) {
          const uid = typeof selected === 'string' ? selected : (selected.modelUid || selected.uid || selected.name);
          if (uid) { _currentModelUid = uid; return uid; }
        }
      } catch {}
    }
    // v9.2 Path 3: VS Code context (editor.selectedModel)
    try {
      const editorModel = vscode.workspace.getConfiguration('windsurf').get('selectedModel');
      if (editorModel) { _currentModelUid = editorModel; return editorModel; }
    } catch {}
  } catch {}
  return _currentModelUid || 'claude-opus-4-6-thinking-1m';
}""",
    },
]

PATCHES_AUTH = [
    # === PA1: Add installationId to capacity probe request ===
    {
        'id': 'PA1_INSTALLATION_ID',
        'desc': '容量探测请求添加installationId (获取完整容量数据)',
        'find': """  _encodeCheckRateLimitRequest(apiKey, modelUid) {
    // Inner: metadata message with api_key as field 1
    const apiKeyBytes = Buffer.from(apiKey, 'utf8');
    const innerTag = 0x0a; // field 1, wire type 2
    const innerLen = this._encodeVarintBuf(apiKeyBytes.length);
    const metadataPayload = Buffer.concat([Buffer.from([innerTag]), innerLen, apiKeyBytes]);

    // Outer field 1: metadata (wire type 2 = length-delimited)
    const outerTag1 = 0x0a; // field 1, wire type 2
    const outerLen1 = this._encodeVarintBuf(metadataPayload.length);

    // Outer field 3: model_uid (wire type 2 = length-delimited)
    const modelBytes = Buffer.from(modelUid, 'utf8');
    const outerTag3 = 0x1a; // field 3, wire type 2 = (3 << 3) | 2
    const outerLen3 = this._encodeVarintBuf(modelBytes.length);

    return Buffer.concat([
      Buffer.from([outerTag1]), outerLen1, metadataPayload,
      Buffer.from([outerTag3]), outerLen3, modelBytes,
    ]);
  }""",
        'replace': """  _encodeCheckRateLimitRequest(apiKey, modelUid) {
    // v9.2: Enhanced metadata — add installationId + ideName for fuller server response
    // Inner metadata message: field 1=api_key, field 5=installation_id, field 6=ide_name
    const apiKeyBytes = Buffer.from(apiKey, 'utf8');
    const innerParts = [];
    // field 1: api_key
    innerParts.push(Buffer.from([0x0a])); // tag: field 1, wire type 2
    innerParts.push(this._encodeVarintBuf(apiKeyBytes.length));
    innerParts.push(apiKeyBytes);
    // field 5: installation_id (read from storage.json or state.vscdb)
    const installId = this._getInstallationId();
    if (installId) {
      const installBytes = Buffer.from(installId, 'utf8');
      innerParts.push(Buffer.from([0x2a])); // tag: field 5, wire type 2 = (5<<3)|2
      innerParts.push(this._encodeVarintBuf(installBytes.length));
      innerParts.push(installBytes);
    }
    // field 6: ide_name
    const ideBytes = Buffer.from('windsurf', 'utf8');
    innerParts.push(Buffer.from([0x32])); // tag: field 6, wire type 2 = (6<<3)|2
    innerParts.push(this._encodeVarintBuf(ideBytes.length));
    innerParts.push(ideBytes);

    const metadataPayload = Buffer.concat(innerParts);

    // Outer field 1: metadata (wire type 2 = length-delimited)
    const outerTag1 = 0x0a;
    const outerLen1 = this._encodeVarintBuf(metadataPayload.length);

    // Outer field 3: model_uid (wire type 2 = length-delimited)
    const modelBytes = Buffer.from(modelUid, 'utf8');
    const outerTag3 = 0x1a; // field 3, wire type 2
    const outerLen3 = this._encodeVarintBuf(modelBytes.length);

    return Buffer.concat([
      Buffer.from([outerTag1]), outerLen1, metadataPayload,
      Buffer.from([outerTag3]), outerLen3, modelBytes,
    ]);
  }""",
    },
    # === PA2: Add _getInstallationId helper ===
    {
        'id': 'PA2_GET_INSTALL_ID',
        'desc': '添加installationId读取函数',
        'find': "  dispose() {\n    this._saveCache();\n  }",
        'replace': """  /** v9.2: Read installationId from Windsurf storage */
  _getInstallationId() {
    try {
      const p = process.platform;
      let storagePath;
      if (p === 'win32') {
        const appdata = process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming');
        storagePath = path.join(appdata, 'Windsurf', 'User', 'globalStorage', 'storage.json');
      } else if (p === 'darwin') {
        storagePath = path.join(os.homedir(), 'Library', 'Application Support', 'Windsurf', 'User', 'globalStorage', 'storage.json');
      } else {
        storagePath = path.join(os.homedir(), '.config', 'Windsurf', 'User', 'globalStorage', 'storage.json');
      }
      if (fs.existsSync(storagePath)) {
        const data = JSON.parse(fs.readFileSync(storagePath, 'utf8'));
        return data['telemetry.machineId'] || data['storage.serviceMachineId'] || null;
      }
    } catch {}
    return null;
  }

  dispose() {
    this._saveCache();
  }""",
    },
]

# ============================================================
# Apply / Status / Revert
# ============================================================

def backup_file(filepath):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    name = os.path.basename(filepath)
    backup = os.path.join(BACKUP_DIR, f'{name}.{ts}.bak')
    shutil.copy2(filepath, backup)
    return backup

def check_status():
    print(f'\nWAM v9.2 Upgrade Status')
    print(f'{"="*60}')
    
    for filepath, patches, label in [
        (SRC_EXT, PATCHES_EXT, 'extension.js'),
        (SRC_AUTH, PATCHES_AUTH, 'authService.js'),
    ]:
        print(f'\n  {label} ({os.path.basename(filepath)}):')
        if not os.path.exists(filepath):
            print(f'    ❌ FILE NOT FOUND: {filepath}')
            continue
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        print(f'    Size: {len(content):,} chars')
        
        for p in patches:
            has_original = p['find'] in content
            has_patched = p['replace'] in content
            if has_patched:
                status = '✅ APPLIED'
            elif has_original:
                status = '⬜ NOT APPLIED'
            else:
                status = '⚠️  NOT FOUND (code changed?)'
            print(f'    {p["id"]}: {status} — {p["desc"]}')
    
    print(f'\n  Backup dir: {BACKUP_DIR}')
    if os.path.exists(BACKUP_DIR):
        backups = os.listdir(BACKUP_DIR)
        print(f'  Backups: {len(backups)} files')
    print(f'{"="*60}\n')

def apply_patches():
    print(f'\nWAM v9.2 Upgrade — Applying patches...')
    print(f'{"="*60}')
    
    success = 0
    failed = 0
    skipped = 0
    
    for filepath, patches, label in [
        (SRC_EXT, PATCHES_EXT, 'extension.js'),
        (SRC_AUTH, PATCHES_AUTH, 'authService.js'),
    ]:
        if not os.path.exists(filepath):
            print(f'  ❌ {label}: FILE NOT FOUND')
            failed += len(patches)
            continue
        
        # Backup
        backup = backup_file(filepath)
        print(f'  📦 {label} backed up → {os.path.basename(backup)}')
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        for p in patches:
            if p['replace'] in content:
                print(f'  ⏭️  {p["id"]}: Already applied')
                skipped += 1
                continue
            if p['find'] not in content:
                print(f'  ❌ {p["id"]}: Pattern not found — {p["desc"]}')
                failed += 1
                continue
            content = content.replace(p['find'], p['replace'], 1)
            print(f'  ✅ {p["id"]}: {p["desc"]}')
            success += 1
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
    
    print(f'\n  Results: {success} applied, {skipped} skipped, {failed} failed')
    print(f'  ⚡ Reload Windsurf window (Ctrl+Shift+P → "Reload Window") to activate')
    print(f'{"="*60}\n')
    return failed == 0

def revert():
    print(f'\nWAM v9.2 Upgrade — Reverting...')
    if not os.path.exists(BACKUP_DIR):
        print('  ❌ No backups found')
        return
    
    for target, filename in [
        (SRC_EXT, 'extension.js'),
        (SRC_AUTH, 'authService.js'),
    ]:
        backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith(filename)], reverse=True)
        if backups:
            latest = os.path.join(BACKUP_DIR, backups[0])
            shutil.copy2(latest, target)
            print(f'  ✅ {filename} reverted from {backups[0]}')
        else:
            print(f'  ⚠️  No backup for {filename}')
    
    print(f'  ⚡ Reload Windsurf window to activate')

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if cmd == 'status':
        check_status()
    elif cmd == 'apply':
        apply_patches()
    elif cmd == 'revert':
        revert()
    else:
        print(f'Usage: python upgrade_v9.2.py [status|apply|revert]')

if __name__ == '__main__':
    main()
