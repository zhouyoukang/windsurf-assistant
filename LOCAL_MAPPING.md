# 本地映射关系

> 本地工作目录 → GitHub 同步目录的对应关系

## 映射表

| 本地工作目录 (Windsurf万法归宗/) | GitHub 同步目录 (windsurf-assistant/) | 说明 |
|---|---|---|
| `080-号池管理_PoolAdmin/dist/` | `pool-admin/dist/` | 号池管理端 v2.0 (旗舰) |
| `040-切号_Switch/_wam_bundle/` | `wam-bundle/` | WAM 切号引擎 v7.2 源码 |
| `030-额度_Credits/engine/` | `engine/` | 道引擎 (Python后端) |
| `030-额度_Credits/pipeline/` | `pipeline/` | 注册管线 |
| `030-额度_Credits/cloud_pool/` | `cloud-pool/` | 云端号池 |
| `030-额度_Credits/toolkit/` | `tools/` | 工具集 |
| — | `diagnostics/` | 诊断工具 (已在repo) |
| — | `research/` | 研究脚本 (已在repo) |
| — | `scripts/` | 一键脚本 (已在repo) |
| — | `docs/` | 逆向文档 (已在repo) |

## 同步规则

1. **Pool Admin 更新**: 构建后将 `080-号池管理_PoolAdmin/dist/` 复制到 `pool-admin/dist/`
2. **WAM 源码更新**: 将 `040-切号_Switch/_wam_bundle/extension.js` 复制到 `wam-bundle/`，记得 sanitize `RELAY_HOST`
3. **引擎更新**: 对比 `030-额度_Credits/engine/` 与 `engine/` 目录

## 安全检查清单 (每次推送前)

- [ ] 无 RELAY_HOST 真实域名
- [ ] 无本地 IP 地址 (192.168.x.x)
- [ ] 无 Windows 用户名 (Administrator/zhou/zhouyoukang)
- [ ] 无账号邮箱/密码
- [ ] 无 API Token / Session 数据
- [ ] 无 .db / .log / .vsix 文件
- [ ] 无卡密/兑换码

## 快速同步命令

```powershell
# Pool Admin → GitHub
Copy-Item "V:\道\道生一\一生二\Windsurf万法归宗\080-号池管理_PoolAdmin\dist\*" "V:\道\道生一\一生二\github项目同步\windsurf-assistant\pool-admin\dist\" -Recurse -Force

# WAM Bundle → GitHub (需手动sanitize RELAY_HOST)
Copy-Item "V:\道\道生一\一生二\Windsurf万法归宗\040-切号_Switch\_wam_bundle\extension.js" "V:\道\道生一\一生二\github项目同步\windsurf-assistant\wam-bundle\" -Force
Copy-Item "V:\道\道生一\一生二\Windsurf万法归宗\040-切号_Switch\_wam_bundle\package.json" "V:\道\道生一\一生二\github项目同步\windsurf-assistant\wam-bundle\" -Force
```
