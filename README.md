# Windsurf小助手 v1.0.0

> 无感号池引擎 · 主动容量探测 · 即时切换 · 速率拦截 · 智能轮转 · 零中断

## 功能

- **无感切号**: 96+账号池自动轮转，用户无感知
- **10层防御**: 从容量探测到输出拦截，全方位rate limit防护
- **主动容量探测**: 调用CheckUserMessageRateLimit gRPC端点，实时获取容量数据
- **Opus预算守卫**: 追踪per-(account,model)消息数，预算达标即切号
- **Tab感知分摊**: 多Tab并发时自动分摊消息预算
- **输出通道拦截**: 0延迟检测rate limit错误，即时切号
- **多窗口协调**: 文件级状态共享，窗口间账号隔离
- **智能选号**: 综合D%/W%/过期时间/rate limit状态选择最优账号
- **指纹轮转**: 切号时自动轮转设备指纹，防关联
- **三重持久化**: 扩展目录+globalStorage+用户主目录，账号数据永不丢失

## 安装

1. 下载 [Releases](https://github.com/zhouyoukang/windsurf-assistant/releases) 中的 `.vsix` 文件
2. Windsurf 中: `Ctrl+Shift+P` → `Extensions: Install from VSIX...` → 选择下载的文件
3. 重载窗口: `Ctrl+Shift+P` → `Reload Window`

## 使用

- 侧边栏 **Windsurf小助手** 图标 → 管理面板
- `Ctrl+Shift+P` → 输入 `Windsurf小助手` 查看所有命令
- Hub API: `http://127.0.0.1:9870/api/pool/status`

## 命令

| 命令 | 说明 |
|------|------|
| 切换账号 | 手动触发账号切换 |
| 智能轮转 | 查全部积分·切最优账号 |
| 紧急切换 | 限流应急即时切换 |
| 刷新积分 | 刷新当前账号积分 |
| 批量添加账号 | 粘贴邮箱:密码批量导入 |
| 重置设备指纹 | 重置5维设备指纹 |

## 防御架构

```
Layer 1-2: Context Key轮询 (quota检测)
Layer 3-4: Context Key轮询 (model/tier限流)
Layer 5:   容量主动探测 (CheckUserMessageRateLimit)
Layer 6:   斜率预测 (线性外推quota%趋势)
Layer 7:   速度检测器 (120s突变检测)
Layer 8:   Opus消息预算守卫 (计数+预防)
Layer 9:   输出通道实时拦截 (0延迟检测)
Layer 10:  多窗口协调 (账号隔离+心跳)
```

## License

MIT
