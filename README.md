# astrbot_plugin_yebot

YeBot 是一个面向 QQ 群聊的 AstrBot 插件。项目按里程碑逐步启用能力：先观察消息和验证权限，再接入工具、Agent 编排、确认流程与后台任务。

当前版本处于 M5：M3 身份与权限、M4 工具网关已完成，插件已具备可解释的主 Agent 路由、受限 SubAgent 编排和 AstrBot function tools。`group.get_members` 可读取当前群成员，写入型工具默认只返回 dry-run 预览；高风险动作确认仍由 M6 负责。

M5 暴露 `yebot_group_get_members`、`yebot_group_kick_member`、`yebot_group_mute_member`、`yebot_group_unmute_member`、`yebot_message_send` 和 `yebot_delegate`。主 Agent 会根据自然语言意图自动选择工具，每次调用都会经过 YeBot 工具网关；SubAgent 默认只能读取群成员，不能直接发消息。

## 本地检查

```powershell
py -m pytest
py -m ruff check .
py -m ruff format --check .
py -m mypy yebot
```

## WSL 部署

源码位于 Windows `C:\code\astrbot_plugin_yebot`。运行中的 AstrBot 使用 WSL 项目 `/home/ubuntu/code/qq-ai-bot`，部署时只同步插件源码和配置到 `data/plugins/astrbot_plugin_yebot`，不复制 Git、缓存或密钥。
