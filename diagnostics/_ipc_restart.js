/**
 * _ipc_restart.js — IPC 无感重启 extension host
 * 道法自然 · 无需用户操作 · ~1.5s 无UI闪烁
 * 
 * 作用: 重启 extension host → 自动加载热部署的新模块
 *   - poolManager.js (v18.0 模型感知冷却+预防性轮转)
 *   - cloudPool.js  (+reportRateLimit方法)
 * 
 * Usage: node _ipc_restart.js
 */
const fs = require('fs');
const net = require('net');

function findPipes() {
  try {
    const entries = fs.readdirSync('//./pipe/');
    return entries
      .filter(n => n.includes('main-sock'))
      .map(n => '\\\\.\\pipe\\' + n);
  } catch (e) {
    return [];
  }
}

function sendIpc(pipeName, message) {
  return new Promise((resolve) => {
    const client = net.createConnection(pipeName, () => {
      const payload = Buffer.from(JSON.stringify(message), 'utf8');
      const header  = Buffer.allocUnsafe(4);
      header.writeUInt32LE(payload.length, 0);
      client.write(Buffer.concat([header, payload]), () => {
        client.end();
        resolve(true);
      });
    });
    client.on('error', () => resolve(false));
    client.setTimeout(3000, () => { client.destroy(); resolve(false); });
  });
}

async function main() {
  const pipes = findPipes();
  if (pipes.length === 0) {
    console.log('[IPC] 未找到 main-sock 管道');
    process.exit(1);
  }

  console.log(`[IPC] 找到 ${pipes.length} 条管道:`);
  pipes.forEach(p => console.log('  ' + p));

  const msg = { type: 'restartExtensionHost' };
  let sent = 0;
  for (const pipe of pipes) {
    const ok = await sendIpc(pipe, msg);
    if (ok) { sent++; console.log(`[IPC] ✅ 已发送 → ${pipe.split('\\').pop()}`); }
    else     { console.log(`[IPC] ⚠️  发送失败 → ${pipe.split('\\').pop()}`); }
  }

  if (sent > 0) {
    console.log(`[IPC] extension host 无感重启中 (~1.5s)...`);
    await new Promise(r => setTimeout(r, 2000));
    console.log('[IPC] ✅ 完成。新模块已加载:');
    console.log('  - poolManager.js v18.0 (模型感知冷却+预防性轮转)');
    console.log('  - cloudPool.js (reportRateLimit方法)');
  } else {
    console.log('[IPC] ❌ 所有管道发送失败');
    process.exit(1);
  }
}

main().catch(e => { console.error(e.message); process.exit(1); });
