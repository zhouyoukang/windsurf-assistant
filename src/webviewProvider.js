/**
 * 号池仪表盘 v6.9.0 — 官方对齐 · 计划感知 · 号池总值统计
 *
 * 核心: 用户看到的是号池，不是单个账号。
 * - 统一额度视图: 顶部显示所有账号的D%·W%总值(非均值)
 * - 号池健康指标 (可用/耗尽/限流/过期)
 * - 活跃账号信息: 1:1官方Plan显示(重置倒计时+计划过期+额外余额)
 * - 账号详情折叠 (默认打开)
 * - 添加账号 + 高级设置折叠
 *
 * v6.9: 1:1官方对齐 — 每账号显示计划过期/重置时间 + 过期视觉标记 + 智能管理
 */
const vscode = require('vscode');

class AccountViewProvider {
  constructor(extensionUri, accountManager, authService, onAction) {
    this._extensionUri = extensionUri;
    this._am = accountManager;
    this._auth = authService;
    this._onAction = onAction;
    this._view = null;
    this._detailExpanded = true; // default open — user wants to see accounts
  }

  resolveWebviewView(webviewView) {
    this._view = webviewView;
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this._extensionUri, 'media')]
    };
    this._render();

    webviewView.webview.onDidReceiveMessage(async (msg) => {
      try { await this._handleMessage(msg); } catch (e) {
        console.error('WAM webview error:', e.message);
        this._toast(`错误: ${e.message}`, true);
      }
    });

    this._am.onChange(() => this._render());
  }

  async _handleMessage(msg) {
    const act = this._onAction;
    switch (msg.type) {
      case 'remove':
        if (msg.index !== undefined) { this._am.remove(msg.index); this._render(); }
        break;
      case 'login':
        if (msg.index !== undefined && act) {
          this._setLoading(true);
          await act('login', msg.index);
          this._setLoading(false);
          this._render();
        }
        break;
      case 'preview':
        if (msg.text) {
          const { AccountManager } = require('./accountManager');
          const accounts = AccountManager.parseAccounts(msg.text);
          if (this._view) this._view.webview.postMessage({ type: 'previewResult', accounts });
        }
        break;
      case 'batchAdd':
        if (msg.text && act) {
          this._setLoading(true);
          const result = await act('batchAdd', msg.text);
          if (result && result.added > 0) {
            this._toast(`+${result.added} 账号，验证中...`);
            this._render();
            await act('refreshAll');
            this._toast('验证完成');
          } else if (result && result.skipped > 0) {
            this._toast(`${result.skipped} 个已存在`, true);
          } else {
            this._toast('未识别到有效账号', true);
          }
          this._setLoading(false);
          this._render();
        }
        break;
      case 'refresh':
      case 'refreshAllAndRotate':
        if (act) { this._setLoading(true); await act('refreshAll'); this._setLoading(false); this._toast('刷新完成'); this._render(); }
        break;
      case 'smartRotate':
        if (act) { this._setLoading(true); await act('smartRotate'); this._setLoading(false); this._render(); }
        break;
      case 'panicSwitch':
        if (act) { this._setLoading(true); await act('panicSwitch'); this._setLoading(false); this._render(); }
        break;
      case 'setMode':
        if (msg.mode && act) { act('setMode', msg.mode); this._render(); }
        break;
      case 'reprobeProxy':
        if (act) { this._setLoading(true); await act('reprobeProxy'); this._setLoading(false); this._render(); }
        break;
      case 'resetFingerprint':
        if (act) act('resetFingerprint');
        break;
      case 'removeEmpty':
        this._removeEmpty(); this._render();
        break;
      case 'toggleDetail':
        this._detailExpanded = !this._detailExpanded;
        break; // state only — DOM already toggled client-side, no re-render
      case 'setProxyPort':
        if (msg.port !== undefined) { const p = parseInt(msg.port); if (p > 0 && p < 65536 && act) act('setProxyPort', p); this._render(); }
        break;
      case 'setAutoRotate':
        if (act) act('setAutoRotate', msg.value);
        this._render();
        break;
      case 'setCreditThreshold':
        if (act) act('setCreditThreshold', msg.value);
        this._render();
        break;
      case 'exportAccounts':
        if (act) act('exportAccounts');
        break;
      case 'importAccounts':
        if (act) { await act('importAccounts'); this._render(); }
        break;
      case 'copyPwd':
        if (msg.index !== undefined) {
          const account = this._am.get(msg.index);
          if (account && this._view) this._view.webview.postMessage({ type: 'pwdResult', index: msg.index, pwd: account.password });
        }
        break;
    }
  }

  _removeEmpty() {
    const accounts = this._am.getAll();
    let removed = 0;
    for (let i = accounts.length - 1; i >= 0; i--) {
      const a = accounts[i];
      if (/test|x\.com|example/i.test(a.email) || (a.credits !== undefined && a.credits <= 0)) {
        this._am.remove(i); removed++;
      }
    }
    this._toast(`已清理 ${removed} 个无效账号`);
  }

  refresh() { this._render(); }
  _toast(msg, isError) { if (this._view) this._view.webview.postMessage({ type: 'toast', msg, isError: !!isError }); }
  _setLoading(on) { if (this._view) this._view.webview.postMessage({ type: 'loading', on }); }

  _render() {
    if (!this._view) return;
    const accounts = this._am.getAll();
    const currentIndex = this._onAction ? this._onAction('getCurrentIndex') : -1;
    this._view.webview.html = this._getHtml(accounts, currentIndex);
  }

  _getHtml(accounts, currentIndex) {
    const scriptUri = this._view.webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'media', 'panel.js'));
    const cspSource = this._view.webview.cspSource;
    const _e = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    const cfg = vscode.workspace.getConfiguration('wam');
    const threshold = cfg.get('creditThreshold', 5);
    const total = accounts.length;

    // Pool stats (v6.6: aggregate D/W across ALL accounts)
    const pool = this._am.getPoolStats ? this._am.getPoolStats(threshold) : { total, available: 0, depleted: 0, rateLimited: 0, bestRemaining: 0, health: 0, avgDaily: null, avgWeekly: null };
    const switchCount = this._onAction ? (this._onAction('getSwitchCount') || 0) : 0;

    // Active account info (v6.9: 1:1 official alignment — plan type + reset countdown + expiry)
    const activeQuota = this._am.getActiveQuota ? this._am.getActiveQuota(currentIndex) : null;
    let activeLabel = '', activeDailyPct = null, activeWeeklyPct = null;
    let activePlanTag = '', activeResetInfo = '', activeExpiryInfo = '';
    if (currentIndex >= 0 && accounts[currentIndex]) {
      const a = accounts[currentIndex];
      const u = a.usage || {};
      if (u.daily) activeDailyPct = u.daily.remaining;
      if (u.weekly) activeWeeklyPct = u.weekly.remaining;
      activeLabel = _e(a.email.split('@')[0]);
      if (activeQuota) {
        if (activeQuota.plan) activePlanTag = `<span style="color:var(--ac);font-size:9px;font-weight:600;padding:0 3px;border:1px solid var(--ac);border-radius:3px;margin-left:4px">${_e(activeQuota.plan)}</span>`;
        if (activeQuota.resetCountdown) activeResetInfo += `D重置:${_e(activeQuota.resetCountdown)}`;
        if (activeQuota.weeklyResetCountdown) activeResetInfo += `${activeResetInfo ? ' · ' : ''}W重置:${_e(activeQuota.weeklyResetCountdown)}`;
        if (activeQuota.planDays !== null) {
          const aUrg = this._am.getExpiryUrgency ? this._am.getExpiryUrgency(currentIndex) : -1;
          const urgColor = aUrg === 0 ? 'var(--rd)' : aUrg === 1 ? 'var(--yw)' : aUrg === 3 ? 'var(--rd)' : 'var(--gn)';
          const urgLabel = aUrg === 0 ? ' 紧急!' : aUrg === 1 ? ' 将到期' : '';
          activeExpiryInfo = activeQuota.planDays > 0 ? `<span style="color:${urgColor}">${activeQuota.planDays}d剩余${urgLabel}</span>` : '<span style="color:var(--rd)">已过期</span>';
        }
      }
    }
    const activeQuotaTag = activeDailyPct !== null
      ? `D${activeDailyPct}%${activeWeeklyPct !== null ? `·W${activeWeeklyPct}%` : ''}`
      : '';

    // Pool capacity bar (uses effective avg = min(D,W) — the TRUE capacity metric)
    const poolSumD = pool.sumDaily, poolSumW = pool.sumWeekly;
    const poolAvgD = pool.avgDaily, poolAvgW = pool.avgWeekly;
    const barEffective = pool.avgEffective !== null ? pool.avgEffective : ((poolAvgD !== null && poolAvgW !== null) ? Math.min(poolAvgD, poolAvgW) : (poolAvgD ?? poolAvgW));
    const barPct = barEffective !== null ? barEffective : (pool.avgCredits !== null ? Math.min(100, pool.avgCredits) : (pool.health || 0));
    const barColor = barPct > 30 ? 'var(--gn)' : barPct > 10 ? 'var(--yw)' : 'var(--rd)';
    const quotaLine = poolSumD !== null
      ? `D${poolSumD}%\u00b7W${poolSumW !== null ? poolSumW : '?'}%`
      : pool.sumCredits !== null ? `总${pool.sumCredits}分` : `${pool.health}%`;
    // Weekly bottleneck indicator
    const wBottleneck = pool.weeklyBottleneckRatio > 50;
    const bottleneckTag = wBottleneck ? ' <span style="color:var(--yw);font-size:8px">W瓶颈</span>' : '';

    // Compact account rows (v7.4: + UFEF expiry urgency badge + plan days)
    const { AccountManager: AM } = require('./accountManager');
    const rows = accounts.map((a, i) => {
      const cur = i === currentIndex;
      const u = a.usage || {};
      const rem = this._am.effectiveRemaining(i);
      const d = u.daily?.remaining, w = u.weekly?.remaining;
      const isQuota = u.mode === 'quota';
      const label = (d !== null && d !== undefined)
        ? (w !== null && w !== undefined ? `D${d}%·W${w}%` : `D${d}%`)
        : (w !== null && w !== undefined) ? `W${w}%`
        : (rem !== null && rem !== undefined ? `${rem}${isQuota ? '%' : '分'}` : '--');
      const isExpired = this._am.isExpired ? this._am.isExpired(i) : false;
      const cls = isExpired ? 'bad' : rem === null ? 'dm' : rem <= threshold ? 'bad' : rem <= threshold*3 ? 'warn' : 'ok';
      const rl = a.rateLimit && a.rateLimit.until > Date.now();
      const name = _e(a.email.split('@')[0]);
      const tn = name.length > 14 ? name.slice(0, 12) + '..' : name;
      // v7.4: Expiry badge with UFEF urgency color
      const planDays = this._am.getPlanDaysRemaining ? this._am.getPlanDaysRemaining(i) : null;
      const urgency = this._am.getExpiryUrgency ? this._am.getExpiryUrgency(i) : -1;
      const dayColor = isExpired ? 'var(--rd)' : urgency === 0 ? 'var(--rd)' : urgency === 1 ? 'var(--yw)' : urgency === 2 ? 'var(--gn)' : 'var(--dm)';
      const dayTag = isExpired ? '<span style="color:var(--rd);font-size:8px;margin-left:2px">过期</span>'
        : planDays !== null ? `<span style="color:${dayColor};font-size:8px;margin-left:2px">${planDays}d</span>` : '';
      return `<div class="r${cur ? ' cur' : ''}${rl ? ' rl' : ''}${isExpired ? ' exp' : ''}" id="row${i}"><b class="n ${cls}">${i+1}</b><span class="nm" title="${_e(a.email)}">${tn}${dayTag}</span><span class="cr ${cls}">${label}${rl?'⏳':''}</span><button class="bc${cur?' curbtn':''}" data-action="login" data-index="${i}">${cur?'✓':'⚡'}</button><button class="bcp" id="cp${i}" data-action="copyPwd" data-index="${i}">📋</button><button class="bx" id="bx${i}" data-action="remove" data-index="${i}">✕</button></div>`;
    }).join('');

    return `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
:root{--bg:#1e1e1e;--sf:#252526;--bd:#3c3c3c;--tx:#ccc;--dm:#858585;--ac:#007acc;--gn:#4ec9b0;--rd:#f44747;--yw:#dcdcaa;--og:#ce9178;--R:5px}
*{margin:0;padding:0;box-sizing:border-box}body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--tx);font-size:12px;padding:6px}
.pool{background:var(--sf);border:1px solid var(--bd);border-radius:var(--R);padding:8px 10px;margin-bottom:6px}
.pool-bar{height:6px;border-radius:3px;background:var(--bd);margin:6px 0;overflow:hidden}
.pool-fill{height:100%;border-radius:3px;transition:width .3s}
.pool-q{font-size:18px;font-weight:700;letter-spacing:-0.5px}
.pool-sub{font-size:10px;color:var(--dm);margin-top:2px}
.pool-stats{display:flex;gap:8px;font-size:10px;margin-top:4px;flex-wrap:wrap}
.pool-stats b{color:var(--tx)}
.r{display:flex;align-items:center;gap:4px;padding:3px 5px;border-radius:var(--R);border:1px solid var(--bd);margin-bottom:2px;background:var(--sf);transition:.15s;font-size:11px}
.r:hover{border-color:var(--ac)}.r.cur{border-color:var(--gn);background:rgba(78,201,176,.08)}.r.rl{opacity:.5;border-style:dashed}.r.exp{opacity:.35;border-style:dotted}
.n{font-size:11px;font-weight:700;min-width:14px;text-align:center}
.n.ok{color:var(--gn)}.n.warn{color:var(--yw)}.n.bad{color:var(--rd)}.n.dm{color:var(--dm)}
.nm{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dm{color:var(--dm);font-size:9px}
.bc{padding:1px 5px;border:none;border-radius:var(--R);cursor:pointer;font-size:10px;background:var(--ac);color:#fff}.bc:hover{opacity:.85}
.cr{padding:1px 4px;border-radius:8px;font-size:10px;font-weight:600;white-space:nowrap}
.cr.ok{background:rgba(78,201,176,.15);color:var(--gn)}.cr.warn{background:rgba(220,220,170,.15);color:var(--yw)}.cr.bad{background:rgba(244,71,71,.15);color:var(--rd)}.cr.dm{color:var(--dm)}
.bx{width:16px;height:16px;border:none;background:0;color:var(--rd);cursor:pointer;border-radius:50%;font-size:11px;opacity:.5;display:flex;align-items:center;justify-content:center}.bx:hover{opacity:1;background:rgba(244,71,71,.2)}
.bcp{width:16px;height:16px;border:none;background:0;color:var(--dm);cursor:pointer;border-radius:50%;font-size:8px;opacity:.4;display:flex;align-items:center;justify-content:center}.bcp:hover{opacity:1;color:var(--ac)}
.b{padding:2px 7px;border:1px solid var(--bd);background:var(--sf);color:var(--tx);border-radius:var(--R);cursor:pointer;font-size:10px}.b:hover{background:var(--ac);border-color:var(--ac);color:#fff}
.bp{background:var(--ac);border-color:var(--ac);color:#fff}.bw{background:var(--og);border-color:var(--og);color:#000}
.curbtn{background:var(--gn);color:#000}
.toast{position:fixed;bottom:6px;left:6px;right:6px;padding:5px 10px;border-radius:var(--R);font-size:11px;z-index:99;animation:fi .2s}
.tok{background:var(--gn);color:#000}.terr{background:var(--rd);color:#fff}
@keyframes fi{from{opacity:0;transform:translateY(4px)}to{opacity:1}}.loading{opacity:.4;pointer-events:none}
.fx{display:flex;gap:3px;flex-wrap:wrap;align-items:center}
.addbar{display:flex;gap:3px;margin-bottom:4px;align-items:stretch}
.addbar textarea{flex:1;padding:3px 6px;background:var(--bg);border:1px solid var(--bd);border-radius:var(--R);color:var(--tx);font-size:11px;font-family:inherit;resize:none;height:28px;min-height:28px;transition:height .2s}
.addbar textarea:focus{outline:0;border-color:var(--ac);height:64px}
.addbar button{padding:0 10px;white-space:nowrap}
#preview{font-size:9px;color:var(--gn);max-height:40px;overflow-y:auto;padding:0 2px}
#preview .pe{color:var(--dm)}#preview .pp{color:var(--yw)}#preview .pf{color:var(--dm);font-style:italic}
.sect{margin-top:5px;border-top:1px solid var(--bd);padding-top:4px}
.stog{cursor:pointer;font-size:10px;color:var(--dm);padding:2px 0;display:flex;align-items:center;gap:3px;user-select:none}
.stog:hover{color:var(--tx)}.sarr{transition:.2s}
.sbox{display:none;padding:4px 0}.sbox.open{display:block}
.empty{text-align:center;padding:20px 8px;color:var(--dm);font-size:11px;line-height:1.8}
</style>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src ${cspSource}; img-src ${cspSource} data:;">
</head><body>

<!-- ═══ 号池总览 (归一统计) ═══ -->
<div class="pool">
  <span class="pool-q" style="color:${barColor}">${quotaLine}</span><span style="font-size:9px;color:var(--dm);margin-left:6px">号池总值${bottleneckTag}</span>
  <div class="pool-bar"><div class="pool-fill" style="width:${barPct}%;background:${barColor}"></div></div>
  <div class="pool-stats">
    <span><b>${pool.available}</b>可用</span>
    <span><b>${pool.total}</b>总计</span>
    ${pool.depleted > 0 ? `<span style="color:var(--rd)"><b>${pool.depleted}</b>耗尽</span>` : ''}
    ${pool.rateLimited > 0 ? `<span style="color:var(--yw)"><b>${pool.rateLimited}</b>限流</span>` : ''}
    ${pool.expired > 0 ? `<span style="color:var(--dm)"><b>${pool.expired}</b>过期</span>` : ''}
    ${pool.urgentCount > 0 ? `<span style="color:var(--rd)"><b>${pool.urgentCount}</b>紧急(&le;3d)</span>` : ''}
    ${pool.soonCount > 0 ? `<span style="color:var(--yw)"><b>${pool.soonCount}</b>将到期</span>` : ''}
    ${pool.preResetWasteCount > 0 ? `<span style="color:var(--og)"><b>${pool.preResetWasteCount}</b>即将浪费</span>` : ''}
    ${switchCount > 0 ? `<span>切换<b>${switchCount}</b>次</span>` : ''}
    ${pool.nextReset ? `<span>刷新<b>${new Date(pool.nextReset).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</b></span>` : ''}
  </div>
  ${currentIndex >= 0 ? `<div class="pool-sub">活跃: #${currentIndex+1} ${activeLabel}${activePlanTag}${activeQuotaTag ? ' <span style="color:var(--ac)">'+activeQuotaTag+'</span>' : ''}${activeExpiryInfo ? ' <span style="font-size:9px;color:var(--dm)">'+activeExpiryInfo+'</span>' : ''}</div>${activeResetInfo ? '<div class="pool-sub" style="font-size:9px;color:var(--dm);margin-top:1px">'+activeResetInfo+'</div>' : ''}` : ''}
</div>

<!-- ═══ 操作栏 ═══ -->
<div class="fx" style="justify-content:space-between;margin-bottom:4px">
  <button class="b bw" data-action="refreshAllAndRotate" title="刷新号池">🔄刷新</button>
  <div class="fx">
    <button class="b" data-action="exportAccounts" title="导出">📤</button>
    <button class="b" data-action="importAccounts" title="导入">📥</button>
  </div>
</div>

<!-- ═══ 添加账号 ═══ -->
<div class="addbar">
  <textarea id="bi" rows="1" placeholder="粘贴账号 (自动识别格式)"></textarea>
  <button class="b bp" data-action="doBatch" title="添加">+</button>
</div>
<div id="preview"></div>

<!-- ═══ 号池详情 (折叠) ═══ -->
<div class="sect">
  <div class="stog" data-action="toggleDetail" id="detTog">
    <span class="sarr" id="detArr" style="${this._detailExpanded ? 'transform:rotate(90deg)' : ''}">▶</span>
    <span>${total}个账号</span>
  </div>
  <div class="sbox${this._detailExpanded ? ' open' : ''}" id="detBox">
    <div id="list">${total > 0 ? rows : `<div class="empty">号池为空<br><span style="color:var(--ac)">粘贴账号到上方输入框</span></div>`}</div>
  </div>
</div>

<script src="${scriptUri}"></script></body></html>`;
  }
}

/** 在编辑器区域打开管理面板 */
function openAccountPanel(context, am, auth, onAction, existingPanel) {
  if (existingPanel) {
    try { existingPanel.reveal(vscode.ViewColumn.One); return null; } catch {}
  }
  const panel = vscode.window.createWebviewPanel(
    'wam.panel', '无感切号 · 账号管理', vscode.ViewColumn.One,
    { enableScripts: true, retainContextWhenHidden: true, localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, 'media')] }
  );
  const provider = new AccountViewProvider(
    context.extensionUri, am, auth, onAction
  );
  const fakeView = { webview: panel.webview };
  Object.defineProperty(fakeView.webview, 'options', { set() {}, get() { return { enableScripts: true }; } });
  provider.resolveWebviewView(fakeView);
  panel.onDidDispose(() => { provider._view = null; });
  return { panel, provider };
}

module.exports = { AccountViewProvider, openAccountPanel };
