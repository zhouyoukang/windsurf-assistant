# Windsurf Assistant

> 道生一，一生二，二生三，三生万物。
> 万物负阴而抱阳，冲气以为和。

**Windsurf 无感号池引擎 + 全链路自动化体系**

无感切号 · 智能轮转 · 自动注册 · 云端号池 · 设备指纹重置 · 补丁系统 · 零中断

---

## 项目架构

```text
windsurf-assistant/
├── dist/                     # VSIX 扩展打包产物
│   └── extension.js          # Windsurf Login Helper v9.0.0 核心
├── engine/                   # 010-道引擎 (WAM Engine)
│   ├── wam_engine.py         # 无感账号管理引擎 (主控)
│   ├── dao_engine.py         # 道引擎：认证链+积分+轮转
│   ├── pool_engine.py        # 号池引擎：多账号调度
│   ├── pool_proxy.py         # 号池代理：远程中继
│   ├── hot_guardian.py       # 热守护：监控+自动恢复
│   ├── hot_patch.py          # 热补丁：运行时注入
│   ├── batch_harvest.py      # 批量收割：积分采集
│   ├── patch_continue_bypass.py  # P1-P4: maxGen+AutoContinue
│   ├── patch_rate_limit_bypass.py # P6-P8: Fail-Open+UI解锁
│   ├── telemetry_reset.py    # 设备指纹重置→新Trial
│   ├── upgrade_v9.2.py       # v9.2 升级脚本
│   ├── wam_dashboard.html    # WAM 管理面板
│   ├── HOT_LAUNCH.ps1        # 热启动脚本
│   ├── _cross_user_bridge.py # 跨用户桥接
│   └── _safety_check.py      # 安全检查
├── pipeline/                 # 020-注册管线
│   ├── _pipeline_v3.py       # 注册管线 v3 (最新)
│   ├── _pipeline_v2.py       # 注册管线 v2
│   ├── _register_one.py      # 单账号注册
│   ├── _gmail_alias_engine.py # Gmail+alias 引擎
│   ├── _universal_engine.py  # 通用注册引擎
│   ├── _yahoo_auto.py        # Yahoo 自动注册
│   ├── _zero_cost_engine.py  # 零成本引擎
│   └── turnstilePatch/       # Cloudflare Turnstile 绕过
│       ├── manifest.json
│       ├── inject.js
│       └── background.js
├── cloud-pool/               # 030-云端号池
│   ├── cloud_pool_server.py  # 云端号池服务 v3.1
│   ├── cloud_pool.html       # 管理面板
│   ├── public.html           # 公共查询页
│   ├── redeem.html           # 卡密兑换页
│   ├── sync_local_to_cloud.py # 本地→云端同步
│   └── deploy_v311.ps1       # 部署脚本
├── tools/                    # 工具集
│   ├── credit_toolkit.py     # 积分监控/委派/Dashboard
│   ├── ws_repatch.py         # 补丁系统 v4.0 (全静默)
│   ├── _model_matrix.py      # 模型积分矩阵提取
│   ├── _decode_models.py     # Protobuf 模型解码
│   ├── _health_check.py      # 系统健康检查
│   ├── check_plan_status.py  # 计划状态检查
│   ├── exchange_token.py     # Token 交换
│   ├── key_daemon.py         # 密钥守护进程
│   ├── hub_api.py            # Hub API 客户端
│   ├── quick_switch.js       # 快速切换脚本
│   ├── windsurf-multi.ps1    # 多实例管理
│   └── _complete_model_matrix.json # 102模型完整矩阵
├── scripts/                  # 一键脚本
│   ├── →一键万法.cmd          # 统一入口
│   ├── →无感启动.cmd          # 无感启动
│   ├── →WAM部署.cmd           # WAM部署
│   ├── →一键换号.cmd          # 一键切号
│   ├── →积分工具箱.cmd        # 积分工具
│   ├── →立即注册新账号.cmd    # 注册新号
│   ├── →重打补丁.cmd          # 重新Patch
│   ├── →注册自启动.ps1        # 开机自启
│   └── 一键万法.py            # Python入口
├── docs/                     # 文档
│   ├── DEEP_CREDIT_MECHANISM_v8.md  # 六层计费架构逆向 (主文档)
│   ├── ACCOUNT_ROOT_SOURCE.md       # 账号体系根源分析
│   ├── QUOTA_SYSTEM_v10.md          # 配额系统 v10
│   ├── RATE_LIMIT_ESSENCE.md        # 限流本质分析
│   ├── RATE_LIMIT_ROOT_CAUSE_v10.md # 限流根因 v10
│   ├── FULL_CHAIN_ANALYSIS_v2.md    # 全链路分析 v2
│   └── VCARD_BREAKTHROUGH_v1.md     # VCard 突破
├── media/
│   └── icon.svg              # 扩展图标
├── package.json              # VSIX 扩展清单
├── .vsixmanifest             # VSIX 包描述
└── LICENSE                   # MIT
```

## 五子工程

### 1. VSIX 扩展 (Windsurf Login Helper v9.0.0)

无感号池引擎，安装即用：

- **智能轮转**: 自动检测积分余量，切换到最优账号
- **主动容量探测**: 预判容量，提前切换避免中断
- **UFEF过期优先**: 优先消耗即将过期的额度
- **速度感知 + 斜率预测**: 基于消耗速率和历史趋势智能调度
- **零中断**: 强制LS重启 + 热重置，切换无感知
- **设备指纹轮转**: 切号时自动重置，防关联
- **紧急切换**: 限流时一键应急

### 2. 道引擎 (engine/)

Python 后端核心，管理认证链全流程：

- **wam_engine.py**: 主控引擎，协调所有模块
- **dao_engine.py**: Firebase认证 + Protobuf积分解析 + Token注入
- **pool_engine.py**: 多账号调度，余额排序，自动轮转
- **hot_guardian.py**: 7×24守护，异常自动恢复
- **补丁系统**: Continue绕过 + 限流Fail-Open + 设备指纹重置

### 3. 注册管线 (pipeline/)

自动注册 Windsurf 账号：

- **Gmail+alias**: 一个Gmail生成无限别名
- **Yahoo自动注册**: 全自动Yahoo邮箱+Windsurf注册
- **Turnstile绕过**: Chrome扩展注入，自动解决验证

### 4. 云端号池 (cloud-pool/)

阿里云部署的号池管理服务 v3.1：

- 120+账号统一管理
- Auth blob 加密存储 + 远程热切换
- 卡密系统 (ldxp.cn对接)
- 50线程并发安全 (WAL + busy_timeout + 连接复用)

### 5. 文档 (docs/)

源码级逆向知识库：六层计费架构 · 限流根因 · 配额系统 · 全链路分析

## 安装

### VSIX 扩展安装

```bash
# 方式一：从 Release 下载 .vsix
# Windsurf: Ctrl+Shift+P → Extensions: Install from VSIX...

# 方式二：手动安装
# 将 dist/ + media/ + package.json 复制到:
# ~/.windsurf/extensions/undefined_publisher.windsurf-login-helper-9.0.0/
```

### 后端部署

```bash
# 道引擎
python engine/wam_engine.py

# 云端号池
python cloud-pool/cloud_pool_server.py

# 一键万法 (全部启动)
python scripts/一键万法.py
```

## 核心策略

```text
P0: BYOK自带Key     → 0 Windsurf成本
P1: SWE-1.5(0x)执行  → 无限免费
P2: 减少Context/Rules → 新体系按token计费
P3: 并行tool calls   → 减少invocations
P4: 选高性价比模型    → GPT-4.1(1x) > Sonnet(2-4x) > Opus(4-12x)
```

## 许可证

MIT License © 2026 dao
