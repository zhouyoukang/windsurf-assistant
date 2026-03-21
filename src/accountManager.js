/**
 * Account Manager — 账号CRUD + 文件存储 + 多窗口同步
 * 零外部依赖，纯文件系统操作
 */
const fs = require('fs');
const path = require('path');
const os = require('os');

class AccountManager {
  constructor(storagePath, options) {
    this._filePath = null;
    this._persistentPaths = []; // Additional persistent paths outside extension dir
    this._accounts = [];
    this._watcher = null;
    this._writing = false;
    this._listeners = [];
    this._rateLimits = new Map(); // email -> { until: timestamp, model, resetsIn, maxMessages, messagesRemaining }
    this._modelRateLimits = new Map(); // "email|modelUid" -> { until, resetsIn, hitAt } — per-(account,model) bucket
    this._isolated = !!(options && options.isolated); // test isolation — skip persistent paths + discovery
    this._init(storagePath);
  }

  _init(storagePath) {
    try {
      if (!fs.existsSync(storagePath)) {
        fs.mkdirSync(storagePath, { recursive: true });
      }
    } catch (e) { console.error('WAM: storage dir failed:', e.message); }
    this._filePath = path.join(storagePath, 'windsurf-assistant-accounts.json');

    // === Triple-persistence: extension dir + globalStorage root + user home ===
    if (!this._isolated) {
      // P0: globalStorage root (survives extension reinstall)
      const rootPath = this._getGlobalStorageRootPath();
      if (rootPath) this._persistentPaths.push(rootPath);
      // P1: user home .wam dir (survives even Windsurf uninstall)
      const homePath = this._getUserHomePath();
      if (homePath) this._persistentPaths.push(homePath);
    }
    console.log(`WAM: [STORAGE] primary=${this._filePath}${this._isolated ? ' [ISOLATED]' : ''}`);
    if (!this._isolated) console.log(`WAM: [STORAGE] persistent=${this._persistentPaths.join(' | ')}`);

    // Multi-source merge: load from ALL known locations, keep union of all accounts
    this._loadAndMergeAll();
  }

  /** Get globalStorage ROOT path (not extension-specific) */
  _getGlobalStorageRootPath() {
    try {
      const p = process.platform;
      let base;
      if (p === 'win32') {
        const appdata = process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming');
        base = path.join(appdata, 'Windsurf', 'User', 'globalStorage');
      } else if (p === 'darwin') {
        base = path.join(os.homedir(), 'Library', 'Application Support', 'Windsurf', 'User', 'globalStorage');
      } else {
        base = path.join(os.homedir(), '.config', 'Windsurf', 'User', 'globalStorage');
      }
      return path.join(base, 'windsurf-assistant-accounts.json');
    } catch { return null; }
  }

  /** Get user home backup path (~/.wam/accounts-backup.json) */
  _getUserHomePath() {
    try {
      const wamDir = path.join(os.homedir(), '.wam');
      if (!fs.existsSync(wamDir)) fs.mkdirSync(wamDir, { recursive: true });
      return path.join(wamDir, 'accounts-backup.json');
    } catch { return null; }
  }

  /** Load accounts from a single file path, returns array or [] */
  _loadFrom(filePath) {
    try {
      if (filePath && fs.existsSync(filePath)) {
        const raw = fs.readFileSync(filePath, 'utf8');
        const data = JSON.parse(raw);
        if (Array.isArray(data)) return data;
      }
    } catch {}
    return [];
  }

  /** Auto-discover any extension storage dirs that contain accounts (handles publisher name changes) */
  _discoverExtensionAccounts() {
    const results = [];
    try {
      const rootPath = this._getGlobalStorageRootPath();
      if (!rootPath) return results;
      const gsRoot = path.dirname(rootPath);
      if (!fs.existsSync(gsRoot)) return results;
      const entries = fs.readdirSync(gsRoot, { withFileTypes: true });
      for (const entry of entries) {
        if (!entry.isDirectory()) continue;
        if (!entry.name.includes('windsurf-login') && !entry.name.includes('windsurf-assistant')) continue;
        const candidate1 = path.join(gsRoot, entry.name, 'windsurf-assistant-accounts.json');
        const candidate2 = path.join(gsRoot, entry.name, 'windsurf-login-accounts.json');
        const candidate = fs.existsSync(candidate1) ? candidate1 : candidate2;
        if (fs.existsSync(candidate) && candidate !== this._filePath) {
          const data = this._loadFrom(candidate);
          if (data.length > 0) {
            console.log(`WAM: [DISCOVERY] found ${data.length} accounts in ${entry.name}`);
            results.push(...data);
          }
        }
      }
    } catch (e) { console.warn('WAM: discovery error:', e.message); }
    return results;
  }

  /** Load from ALL known sources and merge into unified account list */
  _loadAndMergeAll() {
    // Source 1: Primary (extension storage)
    const primary = this._loadFrom(this._filePath);
    // Source 2+3: Persistent paths (globalStorage root + user home)
    const persistentSources = this._persistentPaths.map(p => this._loadFrom(p));
    // Source 4: Auto-discovered extension dirs (handles publisher name changes)
    const discovered = this._isolated ? [] : this._discoverExtensionAccounts();

    // Start with the largest source as base
    let allSources = [primary, ...persistentSources, discovered].filter(s => s.length > 0);
    if (allSources.length === 0) {
      this._accounts = [];
      return;
    }

    // Sort by size descending — largest first as base
    allSources.sort((a, b) => b.length - a.length);
    this._accounts = [...allSources[0]];

    // Merge remaining sources
    let merged = 0;
    for (let s = 1; s < allSources.length; s++) {
      for (const ext of allSources[s]) {
        if (!ext.email) continue;
        const existing = this._accounts.findIndex(a => a.email === ext.email);
        if (existing < 0) {
          this._accounts.push(ext);
          merged++;
        } else {
          // Keep fresher data
          const local = this._accounts[existing];
          if (ext.usage?.lastChecked > (local.usage?.lastChecked || 0)) {
            this._accounts[existing] = { ...local, ...ext, email: local.email };
          }
          if (ext.password && !local.password) {
            local.password = ext.password;
          }
        }
      }
    }

    if (merged > 0) {
      console.log(`WAM: [MERGE] recovered ${merged} accounts from persistent storage! Total: ${this._accounts.length}`);
      this._save(); // Persist the merged result to all locations
    } else {
      console.log(`WAM: [LOAD] ${this._accounts.length} accounts loaded`);
    }
  }

  _load() {
    // Legacy compat — just load primary file
    this._accounts = this._loadFrom(this._filePath);
  }

  _save() {
    const json = JSON.stringify(this._accounts, null, 2);
    // Write to primary (extension storage)
    try {
      this._writing = true;
      fs.writeFileSync(this._filePath, json, 'utf8');
      setTimeout(() => { this._writing = false; }, 200);
    } catch (e) {
      this._writing = false;
      console.error('AccountManager save error:', e);
    }
    // Write to ALL persistent paths (triple-persistence)
    for (const pp of this._persistentPaths) {
      try {
        const dir = path.dirname(pp);
        if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(pp, json, 'utf8');
      } catch (e) {
        console.warn(`WAM: [PERSIST] write failed ${pp}: ${e.message}`);
      }
    }
  }

  /** Start watching for external changes (other Windsurf windows) */
  startWatching() {
    if (this._watcher || !this._filePath) return;
    try {
      if (!fs.existsSync(this._filePath)) {
        fs.writeFileSync(this._filePath, '[]', 'utf8');
      }
      this._watcher = fs.watch(this._filePath, { persistent: false }, (eventType) => {
        if (eventType === 'change' && !this._writing) {
          setTimeout(() => {
            this._load();
            this._notify();
          }, 150);
        }
      });
    } catch {}
  }

  stopWatching() {
    if (this._watcher) {
      this._watcher.close();
      this._watcher = null;
    }
  }

  onChange(fn) { this._listeners.push(fn); }
  _notify() { this._listeners.forEach(fn => { try { fn(this._accounts); } catch {} }); }

  // ========== CRUD ==========

  getAll() { return [...this._accounts]; }
  count() { return this._accounts.length; }

  get(index) {
    return index >= 0 && index < this._accounts.length ? { ...this._accounts[index] } : null;
  }

  findByEmail(email) {
    const idx = this._accounts.findIndex(a => a.email === email);
    return idx >= 0 ? { index: idx, account: { ...this._accounts[idx] } } : null;
  }

  add(email, password) {
    if (!email || !password || !email.includes('@')) return false;
    if (this.findByEmail(email)) return false;
    this._accounts.push({ email, password, credits: undefined, loginCount: 0, addedAt: Date.now() });
    this._save();
    this._notify();
    return true;
  }

  remove(index) {
    if (index < 0 || index >= this._accounts.length) return false;
    this._accounts.splice(index, 1);
    this._save();
    this._notify();
    return true;
  }

  updateCredits(index, credits) {
    if (index < 0 || index >= this._accounts.length) return;
    this._accounts[index].credits = credits;
    // Only sync credits→daily.remaining for credits-mode accounts (not quota-mode)
    // Quota daily.remaining is a percentage (0-100), credits is a raw count — mixing them corrupts data
    const u = this._accounts[index].usage;
    if (u && u.daily && u.mode !== 'quota') {
      u.daily.remaining = credits;
    }
    this._pushCreditHistory(index, credits);
    this._save();
    this._notify();
  }

  /** Track last 5 credit readings for trend display */
  _pushCreditHistory(index, value) {
    if (value == null || index < 0 || index >= this._accounts.length) return;
    const a = this._accounts[index];
    if (!a.creditHistory) a.creditHistory = [];
    const last = a.creditHistory[a.creditHistory.length - 1];
    if (last && last.val === value && (Date.now() - last.ts) < 60000) return; // skip duplicate within 1min
    a.creditHistory.push({ ts: Date.now(), val: value });
    if (a.creditHistory.length > 5) a.creditHistory.shift();
  }

  /** Update comprehensive usage info (v6.9: + planStart/planEnd/gracePeriod for official alignment) */
  updateUsage(index, usageInfo) {
    if (index < 0 || index >= this._accounts.length || !usageInfo) return;
    const a = this._accounts[index];
    a.usage = {
      mode: usageInfo.mode || 'unknown',
      billingStrategy: usageInfo.billingStrategy || null,
      credits: usageInfo.credits,
      daily: usageInfo.daily || null,
      weekly: usageInfo.weekly || null,
      plan: usageInfo.plan || null,
      maxPremiumMessages: usageInfo.maxPremiumMessages || null,
      resetTime: usageInfo.resetTime || null,
      weeklyReset: usageInfo.weeklyReset || null,
      extraBalance: usageInfo.extraBalance || null,
      planStart: usageInfo.planStart || a.usage?.planStart || null,
      planEnd: usageInfo.planEnd || a.usage?.planEnd || null,
      gracePeriodEnd: usageInfo.gracePeriodEnd || null,
      gracePeriodStatus: usageInfo.gracePeriodStatus || null,
      lastChecked: Date.now(),
    };
    // v7.4: Estimate planEnd for Trial accounts if only planStart is known
    if (!a.usage.planEnd && a.usage.planStart && a.usage.plan) {
      const planName = (a.usage.plan || '').toLowerCase();
      if (planName.includes('trial') || planName === 'free') {
        a.usage.planEnd = a.usage.planStart + (14 * 24 * 3600 * 1000); // 14-day trial
      }
    }
    // Keep legacy credits field in sync
    if (usageInfo.credits !== null && usageInfo.credits !== undefined) {
      a.credits = usageInfo.credits;
      this._pushCreditHistory(index, usageInfo.credits);
    }
    this._save();
    this._notify();
  }

  /**
   * Get effective remaining "capacity" for an account (unified metric).
   * Quota mode: min(daily, weekly) — matches official Windsurf vpe formula.
   *   Official: vpe = Z => Math.min(Z.dailyQuotaRemainingPercent, Z.weeklyQuotaRemainingPercent)
   * Credits mode: credits remaining.
   * Returns number or null if unknown.
   */
  effectiveRemaining(index) {
    const a = this.get(index);
    if (!a) return null;
    if (a.usage && a.usage.mode === 'quota') {
      const d = a.usage.daily?.remaining;
      const w = a.usage.weekly?.remaining;
      if (d !== null && d !== undefined && w !== null && w !== undefined) return Math.min(d, w);
      if (d !== null && d !== undefined) return d;
      if (w !== null && w !== undefined) return w;
    }
    return a.credits !== undefined ? a.credits : null;
  }

  /**
   * Get effective reset time for an account (matches official ype formula).
   * Official logic:
   *   Both exhausted: max(dailyReset, weeklyReset) — take the later one
   *   Weekly more restrictive (weekly < daily): weeklyReset
   *   Daily more restrictive: dailyReset
   * Returns timestamp (ms) or null.
   */
  effectiveResetTime(index) {
    const a = this.get(index);
    if (!a || !a.usage) return null;
    const d = a.usage.daily?.remaining;
    const w = a.usage.weekly?.remaining;
    const dr = a.usage.resetTime;    // daily reset (ms)
    const wr = a.usage.weeklyReset;  // weekly reset (ms)
    if (d === null || d === undefined || w === null || w === undefined) return dr || wr || null;
    if (d <= 0 && w <= 0) return (dr && wr) ? Math.max(dr, wr) : (dr || wr || null);
    if (w < d) return wr || dr || null;
    return dr || wr || null;
  }

  /** Find best account for quota-aware rotation (highest effective remaining) */
  findBestForQuota(excludeIndex = -1, threshold = 0) {
    let best = -1, bestVal = -1;
    for (let i = 0; i < this._accounts.length; i++) {
      if (i === excludeIndex) continue;
      const rem = this.effectiveRemaining(i);
      if (rem !== null && rem > bestVal && rem > threshold) {
        bestVal = rem;
        best = i;
      }
    }
    return best >= 0 ? { index: best, remaining: bestVal } : null;
  }

  /** Check if all accounts are depleted (quota-aware) */
  allDepletedQuota(threshold = 0) {
    if (this._accounts.length === 0) return true;
    return this._accounts.every(a => {
      const rem = a.usage && a.usage.mode === 'quota' && a.usage.daily
        ? a.usage.daily.remaining
        : a.credits;
      return rem !== undefined && rem !== null && rem <= threshold;
    });
  }

  /** Get detected usage mode across all accounts ('quota'|'credits'|'mixed'|'unknown') */
  getDetectedMode() {
    const modes = this._accounts
      .filter(a => a.usage && a.usage.mode !== 'unknown')
      .map(a => a.usage.mode);
    if (modes.length === 0) return 'unknown';
    const unique = [...new Set(modes)];
    return unique.length === 1 ? unique[0] : 'mixed';
  }

  incrementLoginCount(index) {
    if (index < 0 || index >= this._accounts.length) return;
    this._accounts[index].loginCount = (this._accounts[index].loginCount || 0) + 1;
    this._save();
  }

  /** Find the account with most credits, excluding current index */
  findHighest(excludeIndex = -1) {
    let best = -1, bestCredits = -1;
    for (let i = 0; i < this._accounts.length; i++) {
      if (i === excludeIndex) continue;
      const c = this._accounts[i].credits;
      if (c !== undefined && c > bestCredits) {
        bestCredits = c;
        best = i;
      }
    }
    return best >= 0 ? { index: best, credits: bestCredits } : null;
  }

  /** Smart batch add — auto-detect ANY seller format
   *  Supports: email----pass | email:pass | email pass | 卡号/卡密 pairs | 账号/密码 pairs
   *  Returns: { added, skipped, errors, total, accounts: [{email, password}] } */
  addBatch(text) {
    const pairs = AccountManager.parseAccounts(text);
    let added = 0, skipped = 0;
    const addedAccounts = [];
    for (const {email, password} of pairs) {
      if (this.findByEmail(email)) { skipped++; continue; }
      this._accounts.push({ email, password, credits: undefined, loginCount: 0, addedAt: Date.now() });
      addedAccounts.push({email, password});
      added++;
    }
    if (added > 0) { this._save(); this._notify(); }
    return { added, skipped, errors: 0, total: pairs.length, accounts: addedAccounts };
  }

  /** Universal account format parser (static, testable)
   *  Handles: email----pass | email:pass | email pass
   *  Chinese label pairs: 卡号N: email + 卡密N: pass | 账号: email + 密码: pass
   *  Raw paste from any seller: auto-finds email+password pairs */
  static parseAccounts(text) {
    const lines = text.split(/\r?\n/).map(l => l.trim()).filter(l => l && !l.startsWith('#'));
    const EMAIL_RE = /[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/;
    const LABEL_EMAIL_RE = /^(?:卡号\d*|账号|邮箱|email|account|用户名?)\s*[:：\s]\s*(.+)/i;
    const LABEL_PASS_RE = /^(?:卡密\d*|密码|pass(?:word)?|pwd|口令)\s*[:：\s]\s*(.+)/i;
    const results = [];

    // Strategy 1: Try Chinese label pairs (卡号+卡密, 账号+密码)
    let pendingEmail = null;
    let usedLabelMode = false;
    for (const line of lines) {
      const em = line.match(LABEL_EMAIL_RE);
      if (em) {
        const val = em[1].trim();
        if (EMAIL_RE.test(val)) { pendingEmail = val; usedLabelMode = true; continue; }
      }
      const pm = line.match(LABEL_PASS_RE);
      if (pm && pendingEmail) {
        const pass = pm[1].trim();
        if (pass) { results.push({ email: pendingEmail, password: pass }); pendingEmail = null; continue; }
      }
      // If we see a new email label without consuming the pending, skip old
      if (em) pendingEmail = null;
    }
    if (usedLabelMode && results.length > 0) return results;

    // Strategy 2: Single-line formats — try delimiters in priority order
    // Supports: ---- | : | ; | = | \t | | | / | space
    const DELIMITERS = ['----', ':', ';', '=', '\t', '|', ' / ', ' '];
    for (const line of lines) {
      let email, password, found = false;
      for (const delim of DELIMITERS) {
        const idx = line.indexOf(delim);
        if (idx < 0) continue;
        const left = line.substring(0, idx).trim();
        const right = line.substring(idx + delim.length).trim();
        if (left && right && EMAIL_RE.test(left)) {
          email = left; password = right; found = true; break;
        }
      }
      if (!found) continue;
      if (email && password && EMAIL_RE.test(email)) results.push({ email, password });
    }
    if (results.length > 0) return results;

    // Strategy 3: Brute-force — find all emails, pair with next non-email line
    const emailLines = [], passLines = [];
    for (const line of lines) {
      const m = line.match(EMAIL_RE);
      if (m) {
        // Extract just the email if the line has extra content
        const cleanEmail = m[0];
        emailLines.push(cleanEmail);
      } else if (line.length >= 4 && !/^[-=\s*#]+$/.test(line) && !/^(质保|以下|全部|卡号|卡密|账号|密码|注意|说明|备注)/i.test(line)) {
        passLines.push(line);
      }
    }
    for (let i = 0; i < Math.min(emailLines.length, passLines.length); i++) {
      results.push({ email: emailLines[i], password: passLines[i] });
    }
    return results;
  }

  /** Export all accounts for sync (preserves all fields) */
  exportAll() {
    return this._accounts.map(a => ({
      email: a.email, password: a.password, credits: a.credits,
      loginCount: a.loginCount || 0, addedAt: a.addedAt || Date.now(),
      lastChecked: a.lastChecked || 0,
      rateLimit: a.rateLimit || null,
      usage: a.usage || null,
      creditHistory: a.creditHistory || []
    }));
  }

  /** Export to local file and return file path */
  exportToFile(storagePath) {
    const data = {
      version: 1,
      exportedAt: new Date().toISOString(),
      count: this._accounts.length,
      accounts: this.exportAll()
    };
    const fname = `wam-backup-${new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)}.json`;
    const fpath = path.join(storagePath || path.dirname(this._filePath || ''), fname);
    fs.writeFileSync(fpath, JSON.stringify(data, null, 2), 'utf8');
    return fpath;
  }

  /** Import from backup JSON (merge strategy) */
  importFromFile(filePath) {
    const raw = fs.readFileSync(filePath, 'utf8');
    const data = JSON.parse(raw);
    const accounts = data.accounts || data; // support both wrapped and raw array
    return this.merge(Array.isArray(accounts) ? accounts : []);
  }

  /** Merge external accounts into local pool
   *  - New emails: add
   *  - Existing emails: update credits/password if remote is fresher
   *  Returns: { added, updated, unchanged, total } */
  merge(externalAccounts) {
    if (!Array.isArray(externalAccounts)) return { added: 0, updated: 0, unchanged: 0, total: this._accounts.length };
    let added = 0, updated = 0, unchanged = 0;
    for (const ext of externalAccounts) {
      if (!ext.email || !ext.password) { unchanged++; continue; }
      const idx = this._accounts.findIndex(a => a.email === ext.email);
      if (idx < 0) {
        const newAccount = {
          email: ext.email, password: ext.password, credits: ext.credits,
          loginCount: ext.loginCount || 0, addedAt: ext.addedAt || Date.now(),
          lastChecked: ext.lastChecked || 0
        };
        if (ext.rateLimit && ext.rateLimit.until > Date.now()) {
          newAccount.rateLimit = ext.rateLimit;
          this._rateLimits.set(ext.email, ext.rateLimit);
        }
        this._accounts.push(newAccount);
        added++;
      } else {
        const local = this._accounts[idx];
        let changed = false;
        // Update credits if remote has fresher data
        if (ext.credits !== undefined && ext.lastChecked > (local.lastChecked || 0)) {
          local.credits = ext.credits;
          local.lastChecked = ext.lastChecked;
          changed = true;
        }
        // Update password if remote has one and it differs
        if (ext.password && ext.password !== local.password) {
          local.password = ext.password;
          changed = true;
        }
        // Sync rate limit state (remote RL always wins if still active)
        if (ext.rateLimit && ext.rateLimit.until > Date.now() && !local.rateLimit) {
          local.rateLimit = ext.rateLimit;
          this._rateLimits.set(local.email, ext.rateLimit);
          changed = true;
        }
        // Sync usage/quota state (fresher data wins)
        if (ext.usage && ext.usage.lastChecked > (local.usage?.lastChecked || 0)) {
          local.usage = ext.usage;
          changed = true;
        }
        if (changed) updated++; else unchanged++;
      }
    }
    if (added > 0 || updated > 0) { this._save(); this._notify(); }
    return { added, updated, unchanged, total: this._accounts.length };
  }

  // ========== Rate Limit State Tracking (v6.4: 动态冷却 + 提前恢复) ==========

  /** Mark an account as rate-limited with cooldown
   *  v6.4: cooldown根据type动态计算:
   *    message_rate: 60-90s (服务端通常1-2min恢复, 旧值1800s严重浪费号池)
   *    quota: 3600s (需等日重置)
   *    unknown: 使用传入值 */
  markRateLimited(index, resetsInSeconds = 3600, info = {}) {
    const a = this.get(index);
    if (!a) return;
    const until = Date.now() + (resetsInSeconds * 1000);
    this._rateLimits.set(a.email, {
      until,
      resetsIn: resetsInSeconds,
      type: info.type || 'unknown',
      model: info.model || null,
      trigger: info.trigger || null,
      maxMessages: info.maxMessages || null,
      messagesRemaining: info.messagesRemaining || 0,
      hitAt: Date.now(),
    });
    // Also store in account for persistence
    if (index >= 0 && index < this._accounts.length) {
      this._accounts[index].rateLimit = { until, resetsIn: resetsInSeconds, type: info.type || 'unknown', model: info.model || null };
      this._save();
    }
    console.log(`WAM: [RL] #${index+1} ${a.email.split('@')[0]} rate-limited ${resetsInSeconds}s (type=${info.type || '?'}, trigger=${info.trigger || '?'})`);
  }

  /** Check if an account is currently rate-limited
   *  v6.8: 提前恢复探测改进 — 适配1200s默认冷却
   *    - message_rate: 已过25%冷却期(min 60s)且额度>0 → 提前解锁
   *    - quota: 不支持提前恢复(必须等日重置) */
  isRateLimited(index) {
    const a = this.get(index);
    if (!a) return false;
    const rl = this._rateLimits.get(a.email);
    if (!rl) {
      // Check persisted state
      if (a.rateLimit && a.rateLimit.until > Date.now()) {
        // v6.8: message_rate提前恢复 — 已过25%冷却期(min 60s)且额度>0
        if (a.rateLimit.type === 'message_rate') {
          const totalCooldown = (a.rateLimit.resetsIn || 1200) * 1000;
          const elapsed = totalCooldown - (a.rateLimit.until - Date.now());
          const minRecoveryMs = Math.max(60000, totalCooldown * 0.25); // 25% of cooldown, min 60s
          if (elapsed >= minRecoveryMs) {
            const rem = this.effectiveRemaining(index);
            if (rem !== null && rem > 0) {
              delete this._accounts[index].rateLimit;
              this._save();
              return false;
            }
          }
        }
        return true;
      }
      return false;
    }
    if (rl.until <= Date.now()) {
      this._rateLimits.delete(a.email);
      if (index >= 0 && index < this._accounts.length) {
        delete this._accounts[index].rateLimit;
        this._save();
      }
      return false;
    }
    // v6.8: message_rate提前恢复探测 — 已过25%冷却期(min 60s)且额度>0
    if (rl.type === 'message_rate' && rl.hitAt) {
      const elapsed = Date.now() - rl.hitAt;
      const totalCooldown = (rl.resetsIn || 1200) * 1000;
      const minRecoveryMs = Math.max(60000, totalCooldown * 0.25);
      if (elapsed >= minRecoveryMs) {
        const rem = this.effectiveRemaining(index);
        if (rem !== null && rem > 0) {
          this._rateLimits.delete(a.email);
          if (index >= 0 && index < this._accounts.length) {
            delete this._accounts[index].rateLimit;
            this._save();
          }
          console.log(`WAM: [RL] #${index+1} early recovery from message_rate limit (elapsed=${Math.round(elapsed/1000)}s/${Math.round(totalCooldown/1000)}s, remaining=${rem})`);
          return false;
        }
      }
    }
    return true;
  }

  /** Get rate limit info for an account */
  getRateLimitInfo(index) {
    const a = this.get(index);
    if (!a) return null;
    const rl = this._rateLimits.get(a.email) || a.rateLimit;
    if (!rl || rl.until <= Date.now()) return null;
    return { ...rl, remainingCooldown: Math.ceil((rl.until - Date.now()) / 1000) };
  }

  /** Clear rate limit for an account */
  clearRateLimit(index) {
    const a = this.get(index);
    if (!a) return;
    this._rateLimits.delete(a.email);
    if (index >= 0 && index < this._accounts.length) {
      delete this._accounts[index].rateLimit;
      this._save();
    }
  }

  // ========== Per-Model Rate Limit Tracking (v7.2: per-(account,modelUid) bucket) ==========

  /** Mark a specific model as rate-limited on a specific account */
  markModelRateLimited(index, modelUid, resetsInSeconds = 600, info = {}) {
    const a = this.get(index);
    if (!a || !modelUid) return;
    const key = `${a.email}|${modelUid}`;
    this._modelRateLimits.set(key, {
      until: Date.now() + (resetsInSeconds * 1000),
      resetsIn: resetsInSeconds,
      hitAt: Date.now(),
      modelUid,
      trigger: info.trigger || null,
    });
    console.log(`WAM: [MODEL_RL] #${index+1} ${a.email.split('@')[0]} model ${modelUid} rate-limited ${resetsInSeconds}s`);
  }

  /** Check if a specific model is rate-limited on a specific account */
  isModelRateLimited(index, modelUid) {
    const a = this.get(index);
    if (!a || !modelUid) return false;
    const key = `${a.email}|${modelUid}`;
    const rl = this._modelRateLimits.get(key);
    if (!rl) return false;
    if (rl.until <= Date.now()) {
      this._modelRateLimits.delete(key);
      return false;
    }
    return true;
  }

  /** Find first non-rate-limited model variant for an account from a list of UIDs */
  findAvailableModelVariant(index, modelUids) {
    if (!Array.isArray(modelUids) || modelUids.length === 0) return null;
    for (const uid of modelUids) {
      if (!this.isModelRateLimited(index, uid)) return uid;
    }
    return null; // all variants limited on this account
  }

  /** Find best account that is NOT model-rate-limited for a specific modelUid */
  findBestForModel(modelUid, excludeIndex = -1, threshold = 0) {
    let best = -1, bestVal = -1;
    for (let i = 0; i < this._accounts.length; i++) {
      if (i === excludeIndex) continue;
      if (this.isRateLimited(i)) continue;
      if (this.isModelRateLimited(i, modelUid)) continue;
      if (this.isExpired && this.isExpired(i)) continue;
      const rem = this.effectiveRemaining(i);
      if (rem !== null && rem > bestVal && rem > threshold) {
        bestVal = rem;
        best = i;
      }
    }
    return best >= 0 ? { index: best, remaining: bestVal } : null;
  }

  /** Get all model rate limit entries (for diagnostics) */
  getModelRateLimits() {
    const result = [];
    for (const [key, rl] of this._modelRateLimits) {
      if (rl.until > Date.now()) {
        result.push({ key, ...rl, remainingCooldown: Math.ceil((rl.until - Date.now()) / 1000) });
      }
    }
    return result;
  }

  /** Find best account avoiding rate-limited ones (credits + rate limit aware) */
  findBestAvailable(excludeIndex = -1, threshold = 0) {
    let best = -1, bestVal = -1;
    for (let i = 0; i < this._accounts.length; i++) {
      if (i === excludeIndex) continue;
      if (this.isRateLimited(i)) continue;
      const rem = this.effectiveRemaining(i);
      if (rem !== null && rem > bestVal && rem > threshold) {
        bestVal = rem;
        best = i;
      }
    }
    return best >= 0 ? { index: best, remaining: bestVal } : null;
  }

  /** Get count of currently rate-limited accounts */
  rateLimitedCount() {
    let count = 0;
    for (let i = 0; i < this._accounts.length; i++) {
      if (this.isRateLimited(i)) count++;
    }
    return count;
  }

  /** Check if ALL accounts are depleted (credits <= threshold) — legacy */
  allDepleted(threshold = 0) {
    if (this._accounts.length === 0) return true;
    return this._accounts.every((a, i) => {
      const rem = this.effectiveRemaining(i);
      return rem !== undefined && rem !== null && rem <= threshold;
    });
  }

  // ========== POOL AGGREGATION (v6.0 号池引擎) ==========

  /** Get unified pool statistics — single call for dashboard/status bar */
  getPoolStats(threshold = 5) {
    const n = this._accounts.length;
    let available = 0, depleted = 0, rateLimited = 0, unknown = 0;
    let sumRemaining = 0, best = -Infinity, worst = Infinity;
    let nextReset = Infinity, nextWeeklyReset = Infinity;
    // v6.6: Aggregate D/W stats across ALL accounts (not just active)
    let sumDaily = 0, sumWeekly = 0, dailyCount = 0, weeklyCount = 0;
    let sumCredits = 0, creditsCount = 0;
    // Effective pool metrics (本源: effective = min(D,W) = 真实可用容量)
    let sumEffective = 0, effectiveCount = 0;
    let weeklyBottleneckCount = 0; // accounts where W < D (weekly is the binding constraint)
    let preResetWasteCount = 0, preResetWasteTotal = 0; // accounts with high remaining near reset

    for (let i = 0; i < n; i++) {
      const a = this._accounts[i];
      const rem = this.effectiveRemaining(i);
      const isRL = this.isRateLimited(i);
      if (isRL) { rateLimited++; }
      else if (rem === null || rem === undefined) { unknown++; }
      else if (rem <= threshold) { depleted++; }
      else { available++; }

      // Aggregate D/W regardless of status (pool-wide view)
      if (a.usage && a.usage.mode === 'quota') {
        const d = a.usage.daily?.remaining;
        const w = a.usage.weekly?.remaining;
        if (d !== null && d !== undefined) { sumDaily += d; dailyCount++; }
        if (w !== null && w !== undefined) { sumWeekly += w; weeklyCount++; }
      } else if (a.credits !== undefined && a.credits !== null) {
        sumCredits += a.credits; creditsCount++;
      }

      if (rem !== null && rem !== undefined && !isRL) {
        if (rem > threshold) sumRemaining += rem;
        if (rem > best) best = rem;
        if (rem < worst) worst = rem;
      }
      const effReset = this.effectiveResetTime(i);
      if (effReset && effReset > Date.now() && effReset < nextReset) nextReset = effReset;
      const u = a.usage;
      if (u?.weeklyReset && u.weeklyReset > Date.now() && u.weeklyReset < nextWeeklyReset) nextWeeklyReset = u.weeklyReset;

      // Effective capacity (min(D,W) per account — the TRUE usable quota)
      if (rem !== null && rem !== undefined && !isRL) {
        sumEffective += rem;
        effectiveCount++;
      }
      // Weekly bottleneck detection (W < D means weekly is the binding constraint)
      if (a.usage && a.usage.mode === 'quota') {
        const dd = a.usage.daily?.remaining;
        const ww = a.usage.weekly?.remaining;
        if (dd !== null && dd !== undefined && ww !== null && ww !== undefined && ww < dd) {
          weeklyBottleneckCount++;
        }
      }
      // Pre-reset waste detection (high remaining + weekly reset within 24h = quota will be wasted)
      if (!isRL && rem !== null && rem > 30) {
        const wr = a.usage?.weeklyReset;
        if (wr && wr > Date.now() && (wr - Date.now()) < 86400000) {
          preResetWasteCount++;
          preResetWasteTotal += rem;
        }
      }
    }

    // v7.4: Expiry distribution (UFEF awareness) + nearest plan expiry
    let expired = 0, nearestPlanEnd = Infinity;
    let urgentCount = 0, soonCount = 0, safeCount = 0, unknownExpiryCount = 0;
    for (let i = 0; i < n; i++) {
      const urg = this.getExpiryUrgency(i);
      if (urg === 3) expired++;
      else if (urg === 0) urgentCount++;
      else if (urg === 1) soonCount++;
      else if (urg === 2) safeCount++;
      else unknownExpiryCount++;
      const pe = this._accounts[i].usage?.planEnd;
      if (pe && pe > Date.now() && pe < nearestPlanEnd) nearestPlanEnd = pe;
    }

    return {
      total: n, available, depleted, rateLimited, unknown, expired, urgentCount, soonCount, safeCount, unknownExpiryCount,
      sumRemaining,
      bestRemaining: best === -Infinity ? 0 : best,
      worstRemaining: worst === Infinity ? 0 : worst,
      avgRemaining: available > 0 ? Math.round(sumRemaining / available) : 0,
      nextReset: nextReset === Infinity ? null : nextReset,
      nextWeeklyReset: nextWeeklyReset === Infinity ? null : nextWeeklyReset,
      nearestPlanEnd: nearestPlanEnd === Infinity ? null : nearestPlanEnd,
      health: n > 0 ? Math.round((available / n) * 100) : 0,
      mode: this.getDetectedMode(),
      sumDaily: dailyCount > 0 ? Math.round(sumDaily) : null,
      sumWeekly: weeklyCount > 0 ? Math.round(sumWeekly) : null,
      avgDaily: dailyCount > 0 ? Math.round(sumDaily / dailyCount) : null,
      avgWeekly: weeklyCount > 0 ? Math.round(sumWeekly / weeklyCount) : null,
      dailyCount, weeklyCount,
      sumCredits: creditsCount > 0 ? Math.round(sumCredits) : null,
      avgCredits: creditsCount > 0 ? Math.round(sumCredits / creditsCount) : null,
      creditsCount,
      // Effective pool metrics (本源推万法 — 从min(D,W)看真实容量)
      sumEffective: effectiveCount > 0 ? Math.round(sumEffective) : null,
      avgEffective: effectiveCount > 0 ? Math.round(sumEffective / effectiveCount) : null,
      effectiveCount,
      weeklyBottleneckCount, // accounts where W% < D% (weekly is binding)
      weeklyBottleneckRatio: effectiveCount > 0 ? +(weeklyBottleneckCount / effectiveCount * 100).toFixed(0) : 0,
      preResetWasteCount, // accounts with high remaining near weekly reset
      preResetWasteTotal: preResetWasteCount > 0 ? Math.round(preResetWasteTotal) : 0,
    };
  }

  /** Get active account quota snapshot for status bar (v6.9: + plan dates + countdowns) */
  getActiveQuota(index) {
    const a = this.get(index);
    if (!a) return null;
    const u = a.usage || {};
    const planDays = this.getPlanDaysRemaining(index);
    const resetCountdown = u.resetTime ? AccountManager.formatCountdown(u.resetTime) : null;
    const weeklyResetCountdown = u.weeklyReset ? AccountManager.formatCountdown(u.weeklyReset) : null;
    return {
      daily: u.daily?.remaining ?? null,
      weekly: u.weekly?.remaining ?? null,
      credits: a.credits ?? null,
      effective: this.effectiveRemaining(index),
      mode: u.mode || 'unknown',
      plan: u.plan || null,
      billingStrategy: u.billingStrategy || null,
      resetTime: this.effectiveResetTime(index),
      dailyResetRaw: u.resetTime || null,
      weeklyReset: u.weeklyReset || null,
      extraBalance: u.extraBalance || null,
      lastChecked: u.lastChecked || null,
      exhausted: this._isExhausted(index),
      expired: this.isExpired(index),
      planStart: u.planStart || null,
      planEnd: u.planEnd || null,
      planDays,
      resetCountdown,
      weeklyResetCountdown,
    };
  }

  /** Check if account is exhausted — official: daily≤0 OR weekly≤0 */
  _isExhausted(index) {
    const a = this.get(index);
    if (!a || !a.usage || a.usage.mode !== 'quota') return false;
    const d = a.usage.daily?.remaining;
    const w = a.usage.weekly?.remaining;
    return (d !== null && d !== undefined && d <= 0) || (w !== null && w !== undefined && w <= 0);
  }

  /** v6.9: Check if account's plan has expired (planEnd < now) */
  isExpired(index) {
    const a = this.get(index);
    if (!a || !a.usage) return false;
    const end = a.usage.planEnd;
    if (!end) return false;
    return end < Date.now();
  }

  /** v6.9: Get plan days remaining (null if unknown, negative if expired) */
  getPlanDaysRemaining(index) {
    const a = this.get(index);
    if (!a || !a.usage || !a.usage.planEnd) return null;
    return Math.ceil((a.usage.planEnd - Date.now()) / (24 * 3600 * 1000));
  }

  /** v7.4: Get expiry urgency tier for UFEF (Use-First-Expire-First) rotation
   *  0 = URGENT (≤3d), 1 = SOON (3-7d), 2 = SAFE (>7d), 3 = EXPIRED, -1 = UNKNOWN */
  getExpiryUrgency(index) {
    if (this.isExpired(index)) return 3;
    const days = this.getPlanDaysRemaining(index);
    if (days === null) return -1;
    if (days <= 3) return 0;
    if (days <= 7) return 1;
    return 2;
  }

  /** v7.4: Get plan summary for display */
  getPlanSummary(index) {
    const a = this.get(index);
    if (!a) return null;
    const u = a.usage || {};
    const days = this.getPlanDaysRemaining(index);
    const urgency = this.getExpiryUrgency(index);
    const urgencyLabels = { 0: '紧急', 1: '将到期', 2: '安全', 3: '已过期', [-1]: '未知' };
    return {
      plan: u.plan || null,
      billingStrategy: u.billingStrategy || null,
      days,
      urgency,
      urgencyLabel: urgencyLabels[urgency] || '未知',
      startDate: u.planStart ? new Date(u.planStart).toLocaleDateString() : null,
      endDate: u.planEnd ? new Date(u.planEnd).toLocaleDateString() : null,
      planStart: u.planStart || null,
      planEnd: u.planEnd || null,
    };
  }

  /** v6.9: Get countdown string for a timestamp (e.g. "2h30m" or "3d") */
  static formatCountdown(ts) {
    if (!ts) return null;
    const diff = ts - Date.now();
    if (diff <= 0) return '已过';
    const m = Math.floor(diff / 60000);
    if (m < 60) return `${m}m`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h${m % 60 > 0 ? (m % 60) + 'm' : ''}`;
    const d = Math.floor(h / 24);
    return `${d}d${h % 24 > 0 ? (h % 24) + 'h' : ''}`;
  }

  /** Select optimal account for seamless rotation (v7.4: UFEF — Use-First-Expire-First)
   *  Core philosophy: accounts expiring soon should be used first to avoid waste.
   *  Priority: 1) Expiry urgency (urgent→soon→safe)
   *           2) Highest remaining quota within urgency tier
   *           3) Fewest plan days (use expiring soonest within tier)
   *           4) Soonest reset (will replenish first) */
  selectOptimal(excludeIndex = -1, threshold = 5, excludeIndices = []) {
    const excluded = new Set(excludeIndices);
    if (excludeIndex >= 0) excluded.add(excludeIndex);
    const candidates = [];
    for (let i = 0; i < this._accounts.length; i++) {
      if (excluded.has(i)) continue;
      if (this.isRateLimited(i)) continue;
      if (this.isExpired(i)) continue;
      const rem = this.effectiveRemaining(i);
      if (rem !== null && rem !== undefined && rem > threshold) {
        const planDays = this.getPlanDaysRemaining(i);
        const urgency = this.getExpiryUrgency(i);
        const resetTs = this.effectiveResetTime(i);
        const resetProximity = resetTs ? Math.max(0, resetTs - Date.now()) : Infinity;
        // Weekly reset proximity for waste prevention (use before weekly resets)
        const weeklyResetMs = this._accounts[i].usage?.weeklyReset || 0;
        const weeklyResetProximity = weeklyResetMs > Date.now() ? weeklyResetMs - Date.now() : Infinity;
        candidates.push({ index: i, remaining: rem, planDays, urgency, resetProximity, weeklyResetProximity });
      }
    }
    // UFEF Sort: use expiring accounts first to avoid wasting quota
    candidates.sort((a, b) => {
      // Tier 1: Expiry urgency — lower value = more urgent = use first
      const aUrg = a.urgency < 0 ? 2 : a.urgency; // unknown treated as safe
      const bUrg = b.urgency < 0 ? 2 : b.urgency;
      if (aUrg !== bUrg) return aUrg - bUrg;
      // Tier 2: Highest remaining quota within same urgency
      // Waste prevention — when both have substantial & similar remaining,
      // prefer the one whose weekly resets sooner (use before quota is "wasted" at reset)
      if (a.remaining > 50 && b.remaining > 50 && Math.abs(a.remaining - b.remaining) <= 20) {
        const wDiff = a.weeklyResetProximity - b.weeklyResetProximity;
        if (Math.abs(wDiff) > 43200000) return wDiff < 0 ? -1 : 1; // >12h difference → prefer sooner
      }
      if (b.remaining !== a.remaining) return b.remaining - a.remaining;
      // Tier 3: Fewest plan days (use the one expiring soonest)
      const aDays = a.planDays ?? 999, bDays = b.planDays ?? 999;
      if (aDays !== bDays) return aDays - bDays;
      // Tier 4: Soonest reset (will replenish first)
      return a.resetProximity - b.resetProximity;
    });
    if (candidates.length > 0) return candidates[0];
    // Fallback: unknown remaining (might be fresh), excluding expired
    for (let i = 0; i < this._accounts.length; i++) {
      if (excluded.has(i)) continue;
      if (this.isRateLimited(i)) continue;
      if (this.isExpired(i)) continue;
      const rem = this.effectiveRemaining(i);
      if (rem === null || rem === undefined) return { index: i, remaining: null };
    }
    return null;
  }

  /** Get switch recommendation with reason (v7.4: + expiry urgency awareness) */
  shouldSwitch(activeIndex, threshold = 5) {
    if (activeIndex < 0 || activeIndex >= this._accounts.length) return { switch: true, reason: 'no_active' };
    if (this.isExpired(activeIndex)) return { switch: true, reason: 'expired' };
    const rem = this.effectiveRemaining(activeIndex);
    if (rem === null || rem === undefined) return { switch: false, reason: 'unknown' };
    if (rem <= 0) return { switch: true, reason: 'depleted' };
    if (rem <= threshold) return { switch: true, reason: 'low' };
    if (this.isRateLimited(activeIndex)) return { switch: true, reason: 'rate_limited' };
    // v7.4 UFEF: if active is safe(>7d) but urgent accounts(≤3d) exist with good quota → switch
    const activeUrg = this.getExpiryUrgency(activeIndex);
    if (activeUrg >= 2 || activeUrg < 0) {
      for (let i = 0; i < this._accounts.length; i++) {
        if (i === activeIndex) continue;
        if (this.isRateLimited(i) || this.isExpired(i)) continue;
        const iUrg = this.getExpiryUrgency(i);
        if (iUrg === 0) {
          const iRem = this.effectiveRemaining(i);
          if (iRem !== null && iRem > threshold) {
            return { switch: true, reason: 'ufef_urgent', urgentIndex: i, urgentRemaining: iRem };
          }
        }
      }
    }
    return { switch: false, reason: 'ok', remaining: rem };
  }

  dispose() {
    this.stopWatching();
    this._listeners = [];
  }
}

module.exports = { AccountManager };
