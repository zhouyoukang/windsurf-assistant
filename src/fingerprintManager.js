/**
 * Fingerprint Manager — Windsurf设备指纹(机器码)管理
 * 
 * Windsurf通过6个ID识别设备:
 *   1. machineid文件 (UUID格式, %APPDATA%/Windsurf/machineid)
 *   2. storage.serviceMachineId (同machineid, in storage.json)
 *   3. telemetry.devDeviceId (UUID格式)
 *   4. telemetry.macMachineId (32位hex, 无短横)
 *   5. telemetry.machineId (32位hex, 无短横)
 *   6. telemetry.sqmId (32位hex, 无短横)
 * 
 * 重置这些ID → Windsurf视为全新设备 → 解除Rate limit绑定
 * 零外部依赖，纯Node.js
 */
const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');

const TELEMETRY_KEYS = [
  'storage.serviceMachineId',
  'telemetry.devDeviceId',
  'telemetry.macMachineId',
  'telemetry.machineId',
  'telemetry.sqmId',
];

function _uuid() { return crypto.randomUUID(); }
function _hex32() { return crypto.randomBytes(16).toString('hex'); }

/** Discover fingerprint file paths based on platform */
function getFingerPrintPaths() {
  const p = process.platform;
  let globalBase;
  if (p === 'win32') {
    const appdata = process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming');
    globalBase = path.join(appdata, 'Windsurf');
  } else if (p === 'darwin') {
    globalBase = path.join(os.homedir(), 'Library', 'Application Support', 'Windsurf');
  } else {
    globalBase = path.join(os.homedir(), '.config', 'Windsurf');
  }
  return {
    globalBase,
    machineid: path.join(globalBase, 'machineid'),
    storageJson: path.join(globalBase, 'User', 'globalStorage', 'storage.json'),
    backupDir: path.join(globalBase, 'User', 'globalStorage', 'wam-fingerprint-backups'),
  };
}

/** Read current device fingerprint (all 6 IDs) */
function readFingerprint() {
  const paths = getFingerPrintPaths();
  const result = { paths, ids: {}, count: 0 };

  try {
    if (fs.existsSync(paths.machineid)) {
      result.ids.machineid = fs.readFileSync(paths.machineid, 'utf8').trim();
      result.count++;
    }
  } catch {}

  try {
    if (fs.existsSync(paths.storageJson)) {
      const data = JSON.parse(fs.readFileSync(paths.storageJson, 'utf8'));
      for (const k of TELEMETRY_KEYS) {
        if (data[k]) { result.ids[k] = data[k]; result.count++; }
      }
    }
  } catch {}

  return result;
}

/**
 * Reset device fingerprint — generate new UUIDs for all 6 IDs
 * @param {object} options - { backup: true (default), dryRun: false }
 * @returns {{ ok, old, new, backupPath, error, requiresRestart }}
 */
function resetFingerprint(options = {}) {
  const paths = getFingerPrintPaths();
  const backup = options.backup !== false;
  const dryRun = options.dryRun === true;
  const result = { ok: false, old: {}, new: {}, backupPath: null, requiresRestart: false };

  // Read current
  const current = readFingerprint();
  result.old = current.ids;

  // Generate new IDs
  const newMachineId = _uuid();
  const newIds = {
    'machineid': newMachineId,
    'storage.serviceMachineId': newMachineId,
    'telemetry.devDeviceId': _uuid(),
    'telemetry.macMachineId': _hex32(),
    'telemetry.machineId': _hex32(),
    'telemetry.sqmId': _hex32(),
  };
  result.new = newIds;

  if (dryRun) { result.ok = true; return result; }

  // Backup old fingerprint
  if (backup) {
    try {
      if (!fs.existsSync(paths.backupDir)) fs.mkdirSync(paths.backupDir, { recursive: true });
      const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      const backupFile = path.join(paths.backupDir, `fingerprint-${ts}.json`);
      fs.writeFileSync(backupFile, JSON.stringify({
        timestamp: ts,
        ids: current.ids,
        paths: { machineid: paths.machineid, storageJson: paths.storageJson },
      }, null, 2), 'utf8');
      result.backupPath = backupFile;
    } catch (e) { console.warn('WAM: fingerprint backup failed:', e.message); }
  }

  try {
    // Write machineid file
    if (fs.existsSync(path.dirname(paths.machineid))) {
      fs.writeFileSync(paths.machineid, newMachineId, 'utf8');
    }

    // Update storage.json
    let storageData = {};
    try {
      if (fs.existsSync(paths.storageJson)) {
        storageData = JSON.parse(fs.readFileSync(paths.storageJson, 'utf8'));
      }
    } catch { storageData = {}; }

    for (const k of TELEMETRY_KEYS) {
      storageData[k] = newIds[k];
    }

    const storageDir = path.dirname(paths.storageJson);
    if (!fs.existsSync(storageDir)) fs.mkdirSync(storageDir, { recursive: true });
    fs.writeFileSync(paths.storageJson, JSON.stringify(storageData, null, '\t'), 'utf8');

    result.ok = true;
  } catch (e) {
    result.error = e.message;
  }

  return result;
}

/** Restore fingerprint from a backup file */
function restoreFingerprint(backupPath) {
  try {
    const data = JSON.parse(fs.readFileSync(backupPath, 'utf8'));
    if (!data.ids) return { ok: false, error: 'Invalid backup format' };

    const paths = getFingerPrintPaths();

    // Restore machineid
    if (data.ids.machineid) {
      fs.writeFileSync(paths.machineid, data.ids.machineid, 'utf8');
    }

    // Restore storage.json keys
    let storageData = {};
    try {
      if (fs.existsSync(paths.storageJson)) {
        storageData = JSON.parse(fs.readFileSync(paths.storageJson, 'utf8'));
      }
    } catch {}

    for (const k of TELEMETRY_KEYS) {
      if (data.ids[k]) storageData[k] = data.ids[k];
    }
    fs.writeFileSync(paths.storageJson, JSON.stringify(storageData, null, '\t'), 'utf8');

    return { ok: true, restored: data.ids, timestamp: data.timestamp };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/** List fingerprint reset history */
function listResetHistory() {
  const paths = getFingerPrintPaths();
  if (!fs.existsSync(paths.backupDir)) return [];
  try {
    return fs.readdirSync(paths.backupDir)
      .filter(f => f.startsWith('fingerprint-') && f.endsWith('.json'))
      .sort().reverse()
      .map(f => {
        const fp = path.join(paths.backupDir, f);
        try {
          const data = JSON.parse(fs.readFileSync(fp, 'utf8'));
          return { name: f, path: fp, timestamp: data.timestamp, ids: Object.keys(data.ids).length };
        } catch { return { name: f, path: fp }; }
      });
  } catch { return []; }
}

/**
 * Ensure all fingerprint IDs exist. Fill in any missing ones without changing existing.
 * P3 FIX: Missing macMachineId may cause server to flag device as abnormal.
 * @returns {{ fixed: string[], alreadyComplete: boolean }}
 */
function ensureComplete() {
  const paths = getFingerPrintPaths();
  const fixed = [];

  try {
    // Check machineid file
    if (!fs.existsSync(paths.machineid)) {
      const newId = _uuid();
      const dir = path.dirname(paths.machineid);
      if (fs.existsSync(dir)) {
        fs.writeFileSync(paths.machineid, newId, 'utf8');
        fixed.push('machineid');
      }
    }

    // Check storage.json keys
    let storageData = {};
    try {
      if (fs.existsSync(paths.storageJson)) {
        storageData = JSON.parse(fs.readFileSync(paths.storageJson, 'utf8'));
      }
    } catch { storageData = {}; }

    let changed = false;
    for (const k of TELEMETRY_KEYS) {
      if (!storageData[k]) {
        if (k === 'telemetry.machineId' || k === 'telemetry.macMachineId') {
          storageData[k] = _hex32();
        } else {
          storageData[k] = _uuid();
        }
        fixed.push(k);
        changed = true;
      }
    }

    if (changed) {
      const dir = path.dirname(paths.storageJson);
      if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(paths.storageJson, JSON.stringify(storageData, null, '\t'), 'utf8');
    }
  } catch (e) {
    console.warn('WAM: ensureComplete error:', e.message);
  }

  return { fixed, alreadyComplete: fixed.length === 0 };
}

/**
 * Hot-verify: confirm state.vscdb machine IDs match expected values.
 * Call after injection to verify LS restart picked up new fingerprint.
 * @param {object} expectedIds - { 'storage.serviceMachineId': '...', ... }
 * @returns {{ verified, mismatches: string[], dbIds: object }}
 */
function hotVerify(expectedIds) {
  if (!expectedIds || Object.keys(expectedIds).length === 0) return { verified: true, mismatches: [], dbIds: {} };
  const paths = getFingerPrintPaths();
  const dbPath = path.join(path.dirname(paths.storageJson), 'state.vscdb');
  if (!fs.existsSync(dbPath)) return { verified: false, mismatches: ['state.vscdb not found'], dbIds: {} };

  try {
    const { execSync } = require('child_process');
    const keysToCheck = Object.keys(expectedIds).filter(k => TELEMETRY_KEYS.includes(k) || k === 'machineid');
    const pyKeys = keysToCheck.map(k => k === 'machineid' ? 'storage.serviceMachineId' : k);
    // fix: JSON.stringify produced bare Python identifiers with dots → NameError
    // Solution: pass keys as a JSON string and parse inside Python
    const pyKeysJson = JSON.stringify(pyKeys).replace(/"/g, '\\"');
    const pyCmd = `python -c "import sqlite3,json;ks=json.loads(\\"${pyKeysJson}\\");db=sqlite3.connect(r'${dbPath.replace(/\\/g, '\\\\')}');c=db.cursor();r={};[c.execute('SELECT value FROM ItemTable WHERE key=?',(k,)) or r.update({k:(c.fetchone() or [None])[0]}) for k in ks];db.close();print(json.dumps(r))"`;
    const raw = execSync(pyCmd, { timeout: 5000, encoding: 'utf8', maxBuffer: 50 * 1024 }).trim();
    const dbIds = JSON.parse(raw);
    const mismatches = [];
    for (const k of keysToCheck) {
      const dbKey = k === 'machineid' ? 'storage.serviceMachineId' : k;
      const expected = k === 'machineid' ? expectedIds[k] : expectedIds[k];
      const actual = dbIds[dbKey];
      if (actual && actual !== expected) {
        mismatches.push(`${dbKey}: expected=${expected?.slice(0,8)} actual=${actual?.slice(0,8)}`);
      }
    }
    return { verified: mismatches.length === 0, mismatches, dbIds };
  } catch (e) {
    return { verified: false, mismatches: [`verify error: ${e.message}`], dbIds: {} };
  }
}

module.exports = { readFingerprint, resetFingerprint, restoreFingerprint, listResetHistory, getFingerPrintPaths, ensureComplete, hotVerify };
