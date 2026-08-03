# Agent 编排

- 模块定位：让主 Agent 在统一工具网关上做可解释路由，并以受限步骤调用工具或 SubAgent。
- 对应代码：`yebot/runtime/agents/`、`main.py`
- 所属里程碑：[M5](../roadmap.md#m5)
- 当前状态：进行中
- 最近更新时间：2026-08-03

## 职责与边界

路由器只决定走忽略、直接回答、工具或 SubAgent 路径；计划器把决定转换成有限步骤；编排器负责步骤上限、并发上限、总超时、失败收敛和结果汇总。Agent 不直接持有 OneBot 客户端，工具步骤统一调用 `YeBot.execute_tool`。

SubAgent 只能拿到任务文本和工具白名单，不能获取 `message.send`、`send_message` 等对外发消息能力，也不能绕过工具网关。踢人确认、审计和额度控制由网关前置处理，禁言、解禁和发消息不弹确认。

## 结构与数据流

```text
AstrBot 主 Agent/function tool
    -> MessageSummary
    -> AgentRouter（固定原因）
    -> AgentPlanner（工具步骤或受限 SubAgent 步骤）
    -> AgentOrchestrator（步骤/并发/超时/失败边界）
    -> YeBot.execute_tool -> ToolGateway -> OneBot
    -> AgentRunResult（状态、步骤结果、汇总）
```

`MessageSummary` 只保留本次路由需要的用户、群、角色、是否 @ 和截断后的任务文本，不保存原始事件对象。`AgentPlan` 是不可变步骤集合，每个步骤有唯一 ID；相同 `parallel_group` 的连续步骤才会并发，默认预算为串行执行。

## 关键决策

- AstrBot 的 LLM function tool 只负责提供模型入口；每次调用先创建路由和计划，再进入 `YeBot.execute_tool`。
- `on_llm_request` 在请求包含 YeBot 工具时追加稳定的工具选择规则，并在开启配置时召回当前可见的少量记忆；主 Agent 根据自然语言意图自动选择工具，普通闲聊不会触发记忆写入。成员工具可传人名、QQ 号、回复对象和“他/刚才那个人”等指代，并统一交给[目标解析](目标解析.md)验证为唯一 QQ 号；歧义或未命中时，Agent 只追问目标，不执行写操作。主人明确的提醒命令会先由代码解析并直达提醒工具，成功或失败结果直接回传，防止聊天人设拒绝或重复调用；无法解析的时间、内容或目标会直接提示补充。主人请求虚构转发对话时，主 Agent 把意图拆成 3 到 12 条 `speaker/content` 草稿，再交给工具层补充当前群昵称和 `（虚构）` 标识。群管理意图中，“最近聊天”先查最近发言人，“随机”先查随机普通成员，再逐个调用禁言；未提供禁言时长时由模型自行选择，工具层提供 60 秒兜底。
- 路由必须携带固定原因，例如 `explicit_tool_request`、`explicit_subagent_request`、`bot_not_mentioned`，便于日志和后续审计。
- 默认预算为最多 6 步、并发 1、总超时 30 秒，可在插件配置中调整；达到步骤上限后不再执行剩余步骤。
- 单步异常只返回异常类型，编排器停止后续步骤并汇总失败原因，不把平台异常正文交给模型。
- SubAgent 的默认白名单只有 `group.get_members`；白名单构造时硬性拒绝对外消息工具。

## 当前实现

`models.py` 定义消息摘要、路由决定、任务步骤、计划、预算、SubAgent 请求/结果和运行结果。`router.py` 提供显式意图路由和计划构造。`orchestrator.py` 以串行步骤为默认，支持同组并发、总超时、步骤上限、异常收敛和稳定汇总。`tracker.py` 按请求 ID 累计主 Agent 连续工具调用，防止模型通过多次函数调用绕过总步骤和总超时预算。

`main.py` 已通过 `@filter.llm_tool` 暴露以下 AstrBot 工具，并通过 `@filter.on_llm_request` 提供自然语言工具选择规则和主人提醒直达入口：

- `yebot_group_get_members`
- `yebot_group_get_recent_speakers`
- `yebot_group_get_random_member`
- `yebot_group_kick_member`
- `yebot_group_mute_member`
- `yebot_group_unmute_member`
- `yebot_message_send`
- `yebot_forward_scene_send`
- `yebot_confirm_action`
- `yebot_reminder_create/list/cancel/pause/resume`
- `yebot_file_read`
- `yebot_web_fetch`
- `yebot_sticker_consider`
- `yebot_sticker_search`
- `yebot_sticker_send`
- `yebot_memory_remember`
- `yebot_memory_recall`
- `yebot_memory_forget`
- `yebot_delegate`

所有工具最终都调用 YeBot 工具网关。记忆工具由 `MemoryService` 负责用户/群/主人范围和生命周期，自动召回只注入当前身份可见的有限参考资料。`yebot_delegate` 使用 AstrBot `tool_loop_agent` 运行受限 SubAgent，只注入白名单工具并返回文本汇总；确认入口只能消费原操作者在原群生成的一次性编号。`observe_only=true` 和 `tool_dry_run=true` 仍保持默认值。

## 验证方式

`tests/test_agents.py` 覆盖可解释路由、工具/SubAgent 计划、SubAgent 发消息禁配、串行多工具、步骤上限、异常收敛、总超时和 SubAgent 结果汇总；`tests/test_agent_tracker.py` 覆盖跨函数调用的步骤上限、总超时和空请求隔离；`tests/test_memory.py` 和 `tests/test_onebot_tools.py` 覆盖记忆工具的持久化和网关范围。与 M4-M9 测试合并后，当前本地全量测试、Ruff 和 strict mypy 均通过。容器内的新增工具仍需重载后做运行态验收。

运行中的 AstrBot 验收需要：用自然语言询问群成员、创建提醒、读取测试文件或公开网页；提出禁言请求确认直接走 dry-run/OneBot action；提出踢人请求确认先返回一次性编号，再由原操作者明确确认；提出只读整理任务确认 SubAgent 只能使用只读白名单。

## 待扩展项

增加重复定时规则、人工接管、跨消息任务关联和更细的 SubAgent 配置。

## 改动历史

- 2026-07-31：确定主 Agent 与 SubAgent 的边界。
- 2026-08-01：实现可解释路由、不可变任务计划、步骤/并发/超时预算、失败收敛和结果汇总。
- 2026-08-01：接入 AstrBot function tools 与受限 `yebot_delegate`。
- 2026-08-02：接入确认、提醒、文件/网页只读工具，并更新容器注册验收。
- 2026-08-02：接入 M9 记忆自动召回与记住/回忆/忘记工具。
- 2026-08-03：修正群管理意图提示，增加最近/随机目标查询和禁言时长省略规则。
- 2026-08-03：增加主人提醒命令的代码侧直达、结果回传和重复事件防重。
- 2026-08-03：增加主人虚构转发对话编排，模型只能提交对话草稿，节点身份和虚构标识由工具层固定。
- 2026-08-03：成员工具接入统一目标解析，模型可传人名或指代，适配层验证唯一成员后才进入工具网关。
