# Agent 编排

- 模块定位：让主 Agent 在统一工具网关上做可解释路由，并以受限步骤调用工具或 SubAgent。
- 对应代码：`yebot/runtime/agents/`、`main.py`
- 所属里程碑：[M5](../roadmap.md#m5)
- 当前状态：进行中
- 最近更新时间：2026-08-05

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

`MessageSummary` 只保留本次路由需要的用户、群、角色、真实 @ 状态、唤醒命令状态和截断后的任务文本，不保存原始事件对象。真实 @、AstrBot 已识别的唤醒前缀（例如“叶桐”）以及引用段后的配置唤醒前缀都会标记为已叫到机器人。`AgentPlan` 是不可变步骤集合，每个步骤有唯一 ID；相同 `parallel_group` 的连续步骤才会并发，默认预算为串行执行。

AstrBot 原生 `active_agent` 定时任务使用 `CronMessageEvent`，这个事件没有可供 OneBot 解析的原始消息映射。YeBot 从 `cron_payload.session`、`sender_id` 和 `cron_job` 元数据构造 `BackgroundToolContext`，显式保存任务群号、执行者 `Identity`、本次运行 ID、平台 action 客户端和原事件引用。群管理员角色通过 `get_group_member_info` 查询，查询失败时按普通群员处理。工具仍进入同一个 `ToolGateway`，定时任务不会通过伪造 QQ 消息绕过权限。

## 关键决策

- AstrBot 的 LLM function tool 只负责提供模型入口；每次调用先创建路由和计划，再进入 `YeBot.execute_tool`。
- 转发对话草稿允许模型用 `speaker=target` 或已解析的目标昵称表示目标，工具层会统一归一化后再构造 OneBot 节点。
- `on_llm_request` 在请求包含 YeBot 工具时追加稳定的工具选择规则，并在开启配置时召回当前可见的少量记忆；主 Agent 根据自然语言意图自动选择工具，普通闲聊不会触发记忆写入。成员工具可传人名、QQ 号、回复对象和“他/刚才那个人”等指代，并统一交给[目标解析](目标解析.md)验证为唯一 QQ 号；歧义或未命中时，Agent 只追问目标，不执行写操作。主人明确的提醒命令会先由代码解析并直达提醒工具，成功或失败结果直接回传，防止聊天人设拒绝或重复调用；无法解析的时间、内容或目标会直接提示补充。群聊中，真实 @ 机器人或使用已配置的唤醒前缀后，主 Agent 都可以进入工具网关；主人、群管理员和普通成员仍分别经过工具权限、确认、额度和审计。管理员或主人撤回消息时，回复目标优先；没有回复时，主 Agent 先查询当前群最近消息并按内容选择目标。候选消息 ID 仅绑定当前事件，撤回工具只接受这次查询返回的 ID，工具层仍会复查该消息属于当前群。主人请求生成转发对话（聊天记录）场景时，主 Agent 把意图拆成 3 到 12 条 `speaker/content` 草稿，再交给工具层用当前群昵称渲染节点昵称。群管理意图中，“最近聊天”先查最近发言人，“随机”先查随机普通成员，再逐个调用禁言；未提供禁言时长时由模型自行选择，工具层提供 60 秒兜底。
- 路由必须携带固定原因，例如 `explicit_tool_request`、`owner_explicit_tool_request`、`explicit_subagent_request`、`bot_not_addressed`，便于日志和后续审计。未被真实 @ 或唤醒前缀叫到的工具调用会返回失败，不会再被编排器汇总为“已执行”。
- 默认预算为最多 6 步、并发 1、总超时 30 秒，可在插件配置中调整；达到步骤上限后不再执行剩余步骤。
- 单步异常只返回异常类型，编排器停止后续步骤并汇总失败原因，不把平台异常正文交给模型。
- SubAgent 的默认白名单只有 `group.get_members`；白名单构造时硬性拒绝对外消息工具。
- 后台 Agent 的工具调用允许没有 @ 机器人的消息地址状态，但只接受 `BackgroundToolContext` 提供的群范围和执行者身份；普通提醒继续由 YeBot `JobScheduler` 负责持久化和执行。

## 当前实现

`models.py` 定义消息摘要、路由决定、任务步骤、计划、预算、SubAgent 请求/结果和运行结果。`router.py` 提供显式意图路由和计划构造。`orchestrator.py` 以串行步骤为默认，支持同组并发、总超时、步骤上限、异常收敛和稳定汇总。`tracker.py` 按请求 ID 累计主 Agent 连续工具调用，防止模型通过多次函数调用绕过总步骤和总超时预算。

`main.py` 已通过 `@filter.llm_tool` 暴露以下 AstrBot 工具，并通过 `@filter.on_llm_request` 提供自然语言工具选择规则和主人提醒直达入口：

- `yebot_group_get_members`
- `yebot_group_get_recent_speakers`
- `yebot_message_get_recent_for_recall`
- `yebot_group_get_random_member`
- `yebot_group_kick_member`
- `yebot_group_mute_member`
- `yebot_group_unmute_member`
- `yebot_message_send`
- `yebot_message_recall`
- `yebot_forward_scene_send`
- `yebot_confirm_action`
- `yebot_reminder_create/list/cancel/pause/resume`
- `yebot_file_read`
- `yebot_web_fetch`
- `yebot_sticker_consider`
- `yebot_sticker_search`
- `yebot_sticker_send`
- `yebot_sticker_list`
- `yebot_sticker_delete`
- `yebot_memory_remember`
- `yebot_memory_recall`
- `yebot_memory_forget`
- `yebot_delegate`

所有工具最终都调用 YeBot 工具网关。记忆工具由 `MemoryService` 负责用户/群/主人范围和生命周期，自动召回只注入当前身份可见的有限参考资料。`yebot_delegate` 使用 AstrBot `tool_loop_agent` 运行受限 SubAgent，只注入白名单工具并返回文本汇总；确认入口只能消费原操作者在原群生成的一次性编号。`observe_only=true` 和 `tool_dry_run=true` 仍保持默认值。

## 验证方式

`tests/test_background.py` 覆盖 Cron 元数据、群角色查询、主人身份、无原始消息时的目标解析和上下文绑定；`tests/test_onebot_tools.py` 覆盖从 AstrBot 平台上下文恢复定时任务 action 客户端。

`tests/test_agents.py` 覆盖可解释路由、主人未 @ 的工具直达、唤醒前缀直达、普通成员未被 @ 或唤醒的拒绝、工具/SubAgent 计划、SubAgent 发消息禁配、串行多工具、步骤上限、异常收敛、总超时和 SubAgent 结果汇总；`tests/test_replies.py`、`tests/test_permissions.py` 和 `tests/test_onebot_tools.py` 覆盖引用解析、撤回工具的引用或候选入口、角色权限、候选排除当前指令、当前群校验和 OneBot action。与 M4-M9 测试合并后，当前本地全量测试、Ruff 和 strict mypy 均通过。容器内的新增工具仍需重载后做运行态验收。

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
- 2026-08-05：转发对话节点不再追加 `（虚构）` 标识，节点昵称直接使用目标解析结果，呈现更接近真实聊天记录。
- 2026-08-05：兼容模型将已解析目标昵称直接写入 `speaker` 的转发草稿，归一为目标节点后再提交 OneBot。
- 2026-08-03：成员工具接入统一目标解析，模型可传人名或指代，适配层验证唯一成员后才进入工具网关。
- 2026-08-03：主人未 @ 时，已由主 Agent 选择的工具可直达工具网关；未 @ 的其他成员工具调用明确返回失败，避免模型误报执行成功。
- 2026-08-04：统一真实 @ 与 AstrBot 唤醒前缀的地址判定，普通成员和群管理员也可用“叶桐 + 指令”进入工具路由，同时保留原有权限和确认检查。
- 2026-08-03：接入引用式消息撤回入口，主 Agent 只把当前唯一回复目标交给工具网关，防止模型凭上下文猜测消息 ID。
- 2026-08-03：撤回支持自然语言自动选择，主 Agent 先读取最近消息再使用当前事件内的候选 ID；引用目标仍优先。
- 2026-08-03：表情收录 Agent 改为提交明确类别、独立反应资格和置信度；主人可通过新增表情库查看与删除工具清理误收内容。
- 2026-08-04：为 AstrBot 原生 active-agent 定时事件增加显式后台工具上下文，传递群号、执行者身份、运行请求 ID 和平台 action 客户端；角色查询失败按最低权限处理。
- 2026-08-05：补充引用段后的唤醒前缀地址恢复，保留工具权限、确认和额度边界。
