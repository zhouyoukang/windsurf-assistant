// L2 真捕验证 · 取 v4.4 实流量之 SP · 经 v4.5 走全链 · 验真剥
// 反者道之动: 自证之上, 复有真证. 道法自然, 不诳不诬.

const http = require("http");
const path = require("path");

const O = require(path.join(
  __dirname,
  "..",
  "vendor",
  "bundled-origin",
  "source.js",
));

// 1. 取 v4.4 (8937) 之实捕 before
function fetch(url) {
  return new Promise((resolve, reject) => {
    http
      .get(url, (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          try {
            resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
          } catch (e) {
            reject(e);
          }
        });
      })
      .on("error", reject);
  });
}

(async () => {
  console.log("═══ L2 真捕验证 ═══");
  let lastInject;
  try {
    lastInject = await fetch("http://127.0.0.1:8937/origin/lastinject?full=1");
  } catch (e) {
    console.log("✗ 取 8937 lastinject 失:", e.message);
    process.exit(1);
  }
  if (!lastInject.has_inject) {
    console.log("✗ 8937 无 has_inject (Admin Windsurf 须有近聊话)");
    process.exit(1);
  }
  const before = lastInject.before;
  console.log(`├ 真捕 before chars = ${before.length}`);
  console.log(
    `├ 真捕 含 <user_rules>     = ${before.includes("<user_rules>")}`,
  );
  console.log(
    `├ 真捕 含 <MEMORY[         = ${before.includes("<MEMORY[")}`,
  );
  console.log(
    `└ 真捕 含 道德经           = ${before.includes("道可道")}`,
  );

  // 2. 包成 proto envelope (chat_messages[0] = SP, role=0)
  //    顶层 field 10 (Windsurf v2 主路径)
  const nested = O.serializeProto({
    1: [{ w: 0, v: 0 }],
    2: [{ w: 2, b: Buffer.from(before, "utf8") }],
  });
  const top = O.serializeProto({ 10: [{ w: 2, b: nested }] });
  const frame = O.buildFrame(0, top);
  console.log(`\n├ 包封 proto: frame=${frame.length}B`);

  // 3. 经 v4.5 modifySPProto
  const mod = O.modifySPProto(frame);
  console.log(`├ 走 v4.5 modifySPProto: out=${mod.length}B`);

  // 4. 解出 after
  const topOut = O.parseProto(O.parseFrames(mod)[0].payload);
  const nestOut = O.parseProto(Buffer.from(topOut[10][0].b));
  const after = Buffer.from(nestOut[2][0].b).toString("utf8");
  console.log(`└ after chars = ${after.length}`);

  // 5. 道法验
  console.log("\n═══ 道法验 ═══");
  const checks = [
    ["前置 TAO_HEADER", after.startsWith("You are Cascade. 你的唯一本源")],
    ["含 道德经 81 章首句", after.includes("道可道，非常道")],
    ["含 道德经 末篇 '为而不争'", after.includes("为而不争")],
    ["含 '---' 分隔", after.includes("\n---\n")],
    ["保 <workspace_information>", after.includes("<workspace_information>")],
    ["保 <tool_calling>", after.includes("<tool_calling>")],
    ["保 <user_information>", after.includes("<user_information>")],
    ["剥 <user_rules>...</user_rules>", !/<user_rules>[\s\S]*?<\/user_rules>/.test(after)],
    ["剥 <MEMORY[*]>...</MEMORY[*]>", !/<MEMORY\[[^\]]+\]>[\s\S]*?<\/MEMORY\[[^\]]+\]>/.test(after)],
    ["剥 <skills>", !/<skills>[\s\S]*?<\/skills>/.test(after)],
    ["剥 <workflows>", !/<workflows>[\s\S]*?<\/workflows>/.test(after)],
    ["剥 <flows>", !/<flows>[\s\S]*?<\/flows>/.test(after)],
    ["剥 <memories>", !/<memories>[\s\S]*?<\/memories>/.test(after)],
  ];
  let pass = 0;
  let fail = 0;
  for (const [name, ok] of checks) {
    console.log((ok ? "  ✓ " : "  ✗ ") + name);
    if (ok) pass++;
    else fail++;
  }
  console.log(`\n通过: ${pass}/${checks.length}`);
  process.exit(fail === 0 ? 0 : 1);
})();
