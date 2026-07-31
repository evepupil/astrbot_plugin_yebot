# astrbot_plugin_yebot

YeBot 是一个面向 QQ 群聊的 AstrBot 插件。项目按里程碑逐步启用能力：先观察消息和验证权限，再接入工具、Agent 编排、确认流程与后台任务。

当前版本处于 M3：插件已具备身份解析和权限判定核心，运行时仍保持只观察模式，不自动发言、不调用模型、不执行工具，也不保存完整原始消息。M3 的群管理员和普通群员真实群内验收待完成。

## 本地检查

```powershell
py -m pytest
py -m ruff check .
py -m ruff format --check .
py -m mypy yebot
```

## WSL 部署

源码位于 Windows `C:\code\astrbot_plugin_yebot`。运行中的 AstrBot 使用 WSL 项目 `/home/ubuntu/code/qq-ai-bot`，部署时只同步插件源码和配置到 `data/plugins/astrbot_plugin_yebot`，不复制 Git、缓存或密钥。
