# astrbot_plugin_yebot

YeBot 是一个面向 QQ 群聊的 AstrBot 插件。项目按里程碑逐步启用能力：先观察消息和验证权限，再接入工具、Agent 编排、确认流程与后台任务。

当前版本处于 M4：M3 身份与权限验收已完成，插件已具备细粒度工具权限、统一工具网关和 OneBot action 适配器。`group.get_members` 可读取当前群成员，写入型工具默认只返回 dry-run 预览；Agent 编排和高风险动作确认仍待后续里程碑。

## 本地检查

```powershell
py -m pytest
py -m ruff check .
py -m ruff format --check .
py -m mypy yebot
```

## WSL 部署

源码位于 Windows `C:\code\astrbot_plugin_yebot`。运行中的 AstrBot 使用 WSL 项目 `/home/ubuntu/code/qq-ai-bot`，部署时只同步插件源码和配置到 `data/plugins/astrbot_plugin_yebot`，不复制 Git、缓存或密钥。
