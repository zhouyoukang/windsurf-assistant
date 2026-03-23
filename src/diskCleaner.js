/**
 * diskCleaner.js — 无感磁盘卫士
 *
 * 道: 水善利万物而不争。安装后悄然清理，用户无感，磁盘自洁。
 *
 * 根因: Windsurf历史版本遗留大量implicit cache (.pb文件)、
 *       日志、CachedData、GPUCache等，积累可达数十GB。
 *       本插件旧版本升级后残留旧目录，Codeium LS旧二进制累积。
 *
 * 11类清理目标:
 *   1. implicit .pb cache (最大元凶，3天)
 *   2. Windsurf日志 (7天)
 *   3. CachedData旧版本bundle (14天)
 *   4. GPUCache (30天)
 *   5. Codeium indexer日志 (3-7天)
 *   6. workspaceStorage过期工作区 (60天)
 *   7. 旧版windsurf-assistant扩展目录 (仅保留最新版) ← 根源修复
 *   8. 旧版Codeium LS二进制 (保留最新2版)
 *   9. Crash dumps崩溃报告 (7天)
 *  10. Extension Host日志子目录 (7天)
 *  11. Windows更新缓存 (7天)
 *
 * 策略:
 *   - 安装/首次激活后立即执行一次深度清理
 *   - 此后每24小时后台执行一次维护清理
 *   - 全程异步非阻塞，无通知，不影响用户操作
 *   - 仅清理已知安全目录，绝不碰用户代码/配置
 */

"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");

const CLEAN_INTERVAL_MS = 24 * 60 * 60 * 1000; // 24小时清理一次
const MARKER_FILE = ".wam_disk_clean_ts";

let _log = () => {};

/** 注入日志函数 (由extension.js调用) */
function setLogger(logFn) {
  _log = logFn || (() => {});
}

/**
 * 获取所有需要清理的目标列表
 * 每条: { dir, ext, maxAgeDays, description, mode }
 * mode: 'ext'=按扩展名递归删文件 | 'allfiles'=目录下所有文件 | 'subdirs'=删过期子目录
 */
function _getCleanTargets() {
  const home = os.homedir();
  const p = process.platform;
  const T = [];

  // ══════════════════════════════════════════════════════
  // 1. implicit cache — 最大元凶
  //    ~/.codeium/windsurf/implicit/*.pb
  //    protobuf上下文缓存，无上限增长，可达数十GB
  // ══════════════════════════════════════════════════════
  T.push({
    dir: path.join(home, ".codeium", "windsurf", "implicit"),
    ext: ".pb",
    maxAgeDays: 3,
    description: "implicit .pb cache",
    mode: "ext",
  });

  // ══════════════════════════════════════════════════════
  // 2. Windsurf日志文件
  // ══════════════════════════════════════════════════════
  const logDirs =
    p === "win32"
      ? [
          path.join(home, "AppData", "Roaming", "Windsurf", "logs"),
          path.join(home, "AppData", "Roaming", "windsurf", "logs"),
        ]
      : p === "darwin"
        ? [
            path.join(home, "Library", "Logs", "Windsurf"),
            path.join(
              home,
              "Library",
              "Application Support",
              "Windsurf",
              "logs",
            ),
          ]
        : [
            path.join(home, ".config", "Windsurf", "logs"),
            path.join(home, ".windsurf", "logs"),
          ];
  for (const d of logDirs) {
    T.push({ dir: d, ext: ".log", maxAgeDays: 7, description: "Windsurf logs", mode: "ext" });
  }

  // ══════════════════════════════════════════════════════
  // 3. CachedData — 旧版本JS bundle缓存
  //    每次Windsurf升级都留一份，累积占用大量空间
  // ══════════════════════════════════════════════════════
  const cachedDataDir =
    p === "win32"
      ? path.join(home, "AppData", "Roaming", "Windsurf", "CachedData")
      : p === "darwin"
        ? path.join(home, "Library", "Application Support", "Windsurf", "CachedData")
        : path.join(home, ".config", "Windsurf", "CachedData");
  T.push({
    dir: cachedDataDir,
    ext: null,
    maxAgeDays: 14,
    description: "CachedData bundles",
    mode: "subdirs",
  });

  // ══════════════════════════════════════════════════════
  // 4. GPUCache — GPU着色器缓存
  // ══════════════════════════════════════════════════════
  const gpuDir =
    p === "win32"
      ? path.join(home, "AppData", "Roaming", "Windsurf", "GPUCache")
      : p === "darwin"
        ? path.join(home, "Library", "Application Support", "Windsurf", "GPUCache")
        : path.join(home, ".config", "Windsurf", "GPUCache");
  T.push({
    dir: gpuDir,
    ext: null,
    maxAgeDays: 30,
    description: "GPU cache",
    mode: "allfiles",
  });

  // ══════════════════════════════════════════════════════
  // 5. Codeium indexer日志 & 过期cache
  // ══════════════════════════════════════════════════════
  const codeiumBase = path.join(home, ".codeium", "windsurf");
  T.push({
    dir: codeiumBase,
    ext: ".log",
    maxAgeDays: 7,
    description: "codeium logs",
    mode: "ext",
  });
  T.push({
    dir: path.join(codeiumBase, "indexer_logs"),
    ext: null,
    maxAgeDays: 3,
    description: "indexer logs",
    mode: "allfiles",
  });

  // ══════════════════════════════════════════════════════
  // 6. workspaceStorage — 过期工作区状态
  //    每打开一个文件夹就产生一个子目录，永不自动清理
  // ══════════════════════════════════════════════════════
  const wsStorageDir =
    p === "win32"
      ? path.join(home, "AppData", "Roaming", "Windsurf", "User", "workspaceStorage")
      : p === "darwin"
        ? path.join(home, "Library", "Application Support", "Windsurf", "User", "workspaceStorage")
        : path.join(home, ".config", "Windsurf", "User", "workspaceStorage");
  T.push({
    dir: wsStorageDir,
    ext: null,
    maxAgeDays: 60,
    description: "workspaceStorage",
    mode: "subdirs",
  });

  // ══════════════════════════════════════════════════════
  // 7. 旧版windsurf-assistant扩展目录 — 本插件根源问题
  //    升级后旧版目录残留在extensions/下，每版含dist+data可达数MB
  //    仅保留当前运行版本，其余全部清理
  // ══════════════════════════════════════════════════════
  const extBase =
    p === "win32"
      ? path.join(home, ".windsurf", "extensions")
      : p === "darwin"
        ? path.join(home, ".windsurf", "extensions")
        : path.join(home, ".windsurf", "extensions");
  T.push({
    dir: extBase,
    ext: null,
    maxAgeDays: 0,
    description: "旧版windsurf-assistant",
    mode: "old-self",
  });

  // ══════════════════════════════════════════════════════
  // 8. 旧版Codeium Language Server二进制
  //    每次LS升级都下载新版本(100MB+)，旧版永不清理
  //    ~/.codeium/windsurf/ 下有多个版本号目录
  // ══════════════════════════════════════════════════════
  T.push({
    dir: path.join(home, ".codeium", "windsurf"),
    ext: null,
    maxAgeDays: 0,
    description: "旧版Codeium LS",
    mode: "old-ls",
  });

  // ══════════════════════════════════════════════════════
  // 9. Windsurf崩溃报告 / crash dumps
  // ══════════════════════════════════════════════════════
  const crashDirs =
    p === "win32"
      ? [
          path.join(home, "AppData", "Roaming", "Windsurf", "Crashpad", "completed"),
          path.join(home, "AppData", "Roaming", "Windsurf", "Crash Reports"),
        ]
      : p === "darwin"
        ? [
            path.join(home, "Library", "Application Support", "Windsurf", "Crashpad", "completed"),
          ]
        : [
            path.join(home, ".config", "Windsurf", "Crashpad", "completed"),
          ];
  for (const d of crashDirs) {
    T.push({ dir: d, ext: null, maxAgeDays: 7, description: "crash dumps", mode: "allfiles" });
  }

  // ══════════════════════════════════════════════════════
  // 10. Extension Host日志 — exthost输出日志累积
  // ══════════════════════════════════════════════════════
  const exthostLogDir =
    p === "win32"
      ? path.join(home, "AppData", "Roaming", "Windsurf", "logs")
      : p === "darwin"
        ? path.join(home, "Library", "Application Support", "Windsurf", "logs")
        : path.join(home, ".config", "Windsurf", "logs");
  T.push({
    dir: exthostLogDir,
    ext: null,
    maxAgeDays: 7,
    description: "exthost logs",
    mode: "subdirs",
  });

  // ══════════════════════════════════════════════════════
  // 11. Windsurf更新缓存 / 旧版安装包残留
  // ══════════════════════════════════════════════════════
  if (p === "win32") {
    T.push({
      dir: path.join(home, "AppData", "Local", "windsurf-updater"),
      ext: null,
      maxAgeDays: 7,
      description: "update cache",
      mode: "allfiles",
    });
  }

  return T;
}

/** 安全删除单个文件，失败静默 */
function _safeUnlink(fp) {
  try { fs.unlinkSync(fp); return true; } catch { return false; }
}

/** 安全递归删除目录，失败静默 */
function _safeRmDir(dp) {
  try { fs.rmSync(dp, { recursive: true, force: true }); return true; } catch { return false; }
}

/** 递归计算目录大小 (字节) */
function _dirSize(dir) {
  let total = 0;
  try {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const fp = path.join(dir, entry.name);
      if (entry.isDirectory()) total += _dirSize(fp);
      else { try { total += fs.statSync(fp).size; } catch {} }
    }
  } catch {}
  return total;
}

/** 格式化字节数 */
function _fmt(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + " MB";
  return (bytes / 1073741824).toFixed(2) + " GB";
}

/**
 * 清理单个目标，返回 { deleted, freedBytes }
 */
function _cleanTarget(target) {
  const { dir, ext, maxAgeDays, description, mode } = target;
  let deleted = 0;
  let freedBytes = 0;
  if (!fs.existsSync(dir)) return { deleted, freedBytes };

  const cutoff = Date.now() - maxAgeDays * 86400000;

  try {
    if (mode === "old-self") {
      // 特殊模式: 清理本插件旧版本目录
      // extensions/下匹配 *windsurf-assistant-* 的目录，保留最新版
      const PREFIX = "windsurf-assistant-";
      const dirs = [];
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (!entry.isDirectory()) continue;
        // 匹配 publisher.windsurf-assistant-x.y.z 格式
        if (entry.name.includes(PREFIX)) {
          const sub = path.join(dir, entry.name);
          try { dirs.push({ name: entry.name, path: sub, mtime: fs.statSync(sub).mtimeMs }); } catch {}
        }
      }
      if (dirs.length > 1) {
        // 按修改时间降序，保留最新的
        dirs.sort((a, b) => b.mtime - a.mtime);
        for (let i = 1; i < dirs.length; i++) {
          const sz = _dirSize(dirs[i].path);
          if (_safeRmDir(dirs[i].path)) { deleted++; freedBytes += sz; }
        }
      }
    } else if (mode === "old-ls") {
      // 特殊模式: 清理旧版Codeium Language Server二进制
      // ~/.codeium/windsurf/ 下有纯数字版本号子目录 (如 1.20.9)
      // 保留最新2个版本，删除其余
      const verDirs = [];
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (!entry.isDirectory()) continue;
        // 版本号目录: 全数字+点 (如 "1.20.9", "1.22.0")
        if (/^\d+\.\d+/.test(entry.name)) {
          const sub = path.join(dir, entry.name);
          try { verDirs.push({ name: entry.name, path: sub, mtime: fs.statSync(sub).mtimeMs }); } catch {}
        }
      }
      if (verDirs.length > 2) {
        verDirs.sort((a, b) => b.mtime - a.mtime);
        for (let i = 2; i < verDirs.length; i++) {
          const sz = _dirSize(verDirs[i].path);
          if (_safeRmDir(verDirs[i].path)) { deleted++; freedBytes += sz; }
        }
      }
    } else if (mode === "subdirs") {
      // 删除过期子目录 (CachedData / workspaceStorage)
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (!entry.isDirectory()) continue;
        const sub = path.join(dir, entry.name);
        try {
          if (fs.statSync(sub).mtimeMs < cutoff) {
            const sz = _dirSize(sub);
            if (_safeRmDir(sub)) { deleted++; freedBytes += sz; }
          }
        } catch {}
      }
    } else if (mode === "allfiles") {
      // 删除目录下所有过期文件 (不递归)
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (!entry.isFile()) continue;
        const fp = path.join(dir, entry.name);
        try {
          const st = fs.statSync(fp);
          if (st.mtimeMs < cutoff) {
            freedBytes += st.size;
            if (_safeUnlink(fp)) deleted++;
          }
        } catch {}
      }
    } else {
      // mode === 'ext': 递归按扩展名删文件
      _walkDelete(dir, ext, cutoff, (d, b) => { deleted += d; freedBytes += b; });
    }
  } catch {}

  if (deleted > 0) {
    _log(`[${description}] 清理 ${deleted} 项，释放 ${_fmt(freedBytes)}`);
  }
  return { deleted, freedBytes };
}

/** 递归遍历目录，删除匹配扩展名的过期文件 */
function _walkDelete(dir, ext, cutoff, cb) {
  let d = 0, b = 0;
  try {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const fp = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        _walkDelete(fp, ext, cutoff, (dd, bb) => { d += dd; b += bb; });
      } else if (entry.isFile()) {
        if (ext && !fp.endsWith(ext)) continue;
        try {
          const st = fs.statSync(fp);
          if (st.mtimeMs < cutoff) { b += st.size; if (_safeUnlink(fp)) d++; }
        } catch {}
      }
    }
  } catch {}
  cb(d, b);
}

/** 读取上次清理时间戳 */
function _readTs(markerDir) {
  try {
    const ts = parseInt(
      fs.readFileSync(path.join(markerDir, MARKER_FILE), "utf8").trim(),
      10,
    );
    return isNaN(ts) ? 0 : ts;
  } catch {
    return 0;
  }
}

/** 写入当前清理时间戳 */
function _writeTs(markerDir) {
  try {
    fs.mkdirSync(markerDir, { recursive: true });
    fs.writeFileSync(path.join(markerDir, MARKER_FILE), String(Date.now()), "utf8");
  } catch {}
}

/**
 * 执行完整清理流程 (主入口)
 * @param {string} markerDir - globalStorageUri路径，用于存放清理时间戳
 * @param {boolean} force    - 忽略24h限制，强制执行
 */
async function runClean(markerDir, force) {
  if (!force && Date.now() - _readTs(markerDir) < CLEAN_INTERVAL_MS) return;

  _log("开始后台磁盘维护...");
  let totalDeleted = 0, totalFreed = 0;

  for (const target of _getCleanTargets()) {
    await new Promise((r) => setImmediate(r)); // yield，不阻塞事件循环
    const { deleted, freedBytes } = _cleanTarget(target);
    totalDeleted += deleted;
    totalFreed += freedBytes;
  }

  _writeTs(markerDir);

  if (totalDeleted > 0) {
    _log(`完成 — 清理 ${totalDeleted} 项，共释放 ${_fmt(totalFreed)}`);
  } else {
    _log("完成 — 磁盘整洁，无需清理");
  }
}

module.exports = { runClean, setLogger };
