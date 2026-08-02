# astrbot_plugin_yebot

YeBot 是一个面向 QQ 群聊的 AstrBot 插件。项目按里程碑逐步启用能力：先观察消息和验证权限，再接入工具、Agent 编排、确认流程与后台任务。

当前版本已实现 M6-M8 的核心代码：M3 身份与权限、M4 工具网关、M5 Agent 编排、踢人确认与审计额度、提醒后台任务、受限文件/网页读取和发布门禁。写入型工具仍默认只返回 dry-run 预览，真实副作用需要显式关闭该开关并完成人工验收。

插件暴露群成员、踢人、禁言、解禁、发消息、踢人确认、提醒任务、文件读取、网页读取和 `yebot_delegate`。主 Agent 会根据自然语言意图自动选择工具，每次调用都会经过 YeBot 工具网关；只有踢人需要二次确认，SubAgent 默认只能读取群成员，不能直接发消息。

## 本地检查

```powershell
py -m pytest
py -m ruff check .
py -m ruff format --check .
py -m mypy yebot
```

## WSL 部署

源码位于 Windows `C:\code\astrbot_plugin_yebot`。运行中的 AstrBot 使用 WSL 项目 `/home/ubuntu/code/qq-ai-bot`，部署时只同步插件源码和配置到 `data/plugins/astrbot_plugin_yebot`，不复制 Git、缓存或密钥。
