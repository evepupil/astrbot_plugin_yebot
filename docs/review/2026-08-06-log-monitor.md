# 2026-08-06 日志巡检 Review

- 本轮 review 起点 commit：`c80b316`
- 本轮 review 终点 commit：`5621be0`（追加增量复核，未修改代码）
- 本轮检查窗口：2026-08-06T14:39:33.193Z 至 2026-08-06T15:09:33.567Z。

## 问题 1：AstrBot 贴图工具循环错误级信号再次出现

- 状态：待决策；根因未确认，暂停 YeBot 业务代码修改。
- 证据：窗口共聚合 398 条日志行，其中 `astrbot` 271 条、`napcat` 127 条；AstrBot `tool_loop_agent` 错误级信号 23 条，其中 14 条带 `sticker.consider` 或 `yebot_sticker_consider` 标记。脱敏聚合没有提取到新的异常类名，也没有 `Traceback`、`execution_error`、`TypeError`、YeBot 导入失败、连接/DNS/TTS 失败。另有 1 次 `ActionFailed`（`retcode=1200`），没有贴图、转发或消息发送标记，暂不归因于本问题。
- 运行状态：`astrbot` 与 `napcat` 均为 running，`RestartCount=0`、`OOMKilled=false`；两者启动时间均为 `2026-08-06T11:04:36Z`。窗口内没有新的启动或插件加载标记。
- 影响：贴图自动收录的部分工具循环可能未完成；当前没有证据表明普通回复、容器可用性、TTS 或 OneBot 链路受到影响。
- 候选方案：
  1. 检查 AstrBot 当前本地工具循环与 YeBot function tool 的适配契约，确认后再决定是否升级或调整部署。
  2. 暂时关闭 `sticker_auto_collect`，降低自动收录失败噪声，但会改变现有产品行为。
  3. 保留功能并增加阶段/异常类型脱敏诊断，继续等待可复现根因。
- 需要决策：是否允许调整 AstrBot 版本或工具循环部署策略；是否暂时关闭自动收录；是否接受增加运行诊断日志。
- 处理：本轮不改业务代码、不调整运行配置；问题继续归入 [总览](./_剩余问题.md) 的待决策条目。

## 验证与边界

- 已执行：`git status --short --branch`、Docker Compose 状态检查、窗口日志脱敏聚合、容器重启/OOM 状态核验。
- 未执行代码测试：本轮没有代码变更；提交前仍执行仓库发布门禁和 `git diff --check`。
- 未完成：真实 QQ/人工验收；未读取或保存消息正文、提示词、Cookie、Token、密钥或整段 debug 上下文。

## 后续增量复核（2026-08-06T15:18:34.358Z 至 2026-08-06T15:39:33.996Z）

- 状态：待决策；与已记录的贴图工具循环问题一致，未发现新的可确认代码根因。
- 聚合：采集 77 条日志行（`astrbot` 52、`napcat` 25），出现 10 个贴图阶段和 3 条 AstrBot `tool_loop_agent` 错误级信号，其中 3 条带贴图错误标记；没有 Traceback、`execution_error`、TypeError、YeBot 导入失败、连接/DNS/TTS 失败或 `ActionFailed`。
- 运行状态：两个容器均为 running，`RestartCount=0`、`OOMKilled=false`，没有新的启动或插件加载标记。
- 处理：根因仍未确认，继续等待 AstrBot 工具循环/自动收录决策；本轮不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-06T17:11:15.231Z 至 2026-08-06T17:39:34.850Z）

- 状态：待决策；已知贴图工具循环异常持续，未发现新的可确认代码根因。
- 聚合：采集 434 条日志行（`astrbot` 325、`napcat` 110），出现 51 个贴图阶段、21 条 AstrBot `tool_loop_agent` 错误级信号和 17 条贴图错误级信号；没有 `Traceback`、`execution_error`、`TypeError`、`ImportError`、`ModuleNotFoundError`、连接/DNS/TTS 失败或 `ActionFailed`。两条宽泛的导入匹配同时带成功/已加载标记，未据此判定导入失败；`system_info` 标记没有形成独立执行错误。
- 运行状态：`astrbot` 于 `2026-08-06T17:28:33Z` 单独启动，`napcat` 未重启；两个容器当前均为 running，`RestartCount=0`、`OOMKilled=false`。重启后没有 Traceback、`execution_error` 或连接失败，且出现插件加载标记。
- 同步边界：当前 Windows 工作区存在未提交工具改动；`main.py` 与工具文件哈希和 WSL 运行副本不一致，系统信息模块文件哈希一致。本轮未执行同步或重启，避免覆盖并行开发内容。
- 处理：贴图问题根因仍未确认，继续等待 AstrBot 工具循环/自动收录决策；本轮不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-06T19:10:25.454Z 至 2026-08-06T19:39:37.522Z）

- 状态：待决策；已知贴图工具循环异常低量复现，未发现新的可确认代码根因。
- 聚合：采集 28 条日志行（`astrbot` 23、`napcat` 5），出现 12 个贴图阶段和 4 条 AstrBot `tool_loop_agent` 错误级信号；没有 `Traceback`、`execution_error`、`TypeError`、YeBot 导入失败、连接/DNS/TTS 失败、`ActionFailed` 或 `system_info` 异常。
- 运行状态：两个容器均为 running，`RestartCount=0`、`OOMKilled=false`，没有新的启动或插件加载标记。
- 处理：根因仍未确认，继续等待 AstrBot 工具循环/自动收录决策；本轮不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-06T16:41:32.472Z 至 2026-08-06T17:09:35.290Z）

- 状态：待决策；已知贴图工具循环异常持续，未发现新的可确认代码根因。
- 聚合：采集 227 条日志行（`astrbot` 161、`napcat` 66），出现 55 个贴图阶段、19 条 AstrBot `tool_loop_agent` 错误级信号和 4 条带贴图标记的 `execution_error`；没有 Traceback、TypeError、YeBot 导入失败、连接/DNS/TTS 失败或 `ActionFailed`。
- 运行状态：两个容器均为 running，`RestartCount=0`、`OOMKilled=false`，没有新的启动或插件加载标记。
- 处理：根因仍未确认，继续等待 AstrBot 工具循环/自动收录决策；本轮不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-06T15:41:55.876Z 至 2026-08-06T16:09:34.505Z）

- 状态：待决策；已知贴图工具循环异常明显复现，未发现新的可确认代码根因。
- 聚合：采集 347 条日志行（`astrbot` 246、`napcat` 101），出现 65 个贴图阶段、23 条 AstrBot `tool_loop_agent` 错误级信号和 3 条带贴图标记的 `execution_error`；3 条 `execution_error` 均未关联 `yebot_message_send` 或 `system_info`。没有 Traceback、TypeError、YeBot 导入失败、连接/DNS/TTS 失败或 `ActionFailed`。
- 运行状态：两个容器均为 running，`RestartCount=0`、`OOMKilled=false`，没有新的启动或插件加载标记。
- 处理：根因仍未确认，继续等待 AstrBot 工具循环/自动收录决策；本轮不改 YeBot 业务代码或运行配置。工作区既有用户代码改动未触碰。

## 后续增量复核（2026-08-06T16:12:03.470Z 至 2026-08-06T16:39:34.850Z）

- 状态：待决策；已知贴图工具循环异常持续，未发现新的可确认代码根因。
- 聚合：采集 180 条日志行（`astrbot` 131、`napcat` 49），出现 46 个贴图阶段和 15 条 AstrBot `tool_loop_agent` 错误级信号，均带贴图错误标记；没有 Traceback、`execution_error`、TypeError、YeBot 导入失败、连接/DNS/TTS 失败或 `ActionFailed`。
- 运行状态：两个容器均为 running，`RestartCount=0`、`OOMKilled=false`，没有新的启动或插件加载标记。
- 处理：根因仍未确认，继续等待 AstrBot 工具循环/自动收录决策；本轮不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-06T23:09:40.783Z 至 2026-08-06T23:39:41.259Z）

- 状态：待决策；已知贴图工具循环异常再次出现，未发现新的可确认代码根因。
- 聚合：采集 21 条日志行（`astrbot` 15、`napcat` 6），出现 6 个 `yebot_sticker_consider`/贴图工具循环信号和 2 条 AstrBot 工具循环错误级信号；另有 1 条 warning。没有 `execution_error`、Traceback、TypeError、YeBot 导入失败、连接/DNS/TTS 失败或 `ActionFailed`。
- 运行状态：两个容器均为 running，`RestartCount=0`、`OOMKilled=false`；窗口内没有新的启动或插件加载标记。
- 处理：根因仍未确认，继续等待 AstrBot 工具循环/自动收录决策；本轮不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-06T23:39:41.671Z 至 2026-08-07T00:09:41.671Z）

- 状态：待决策；已知贴图工具循环异常再次出现，未发现新的可确认代码根因。
- 聚合：采集 56 条日志行（`astrbot` 40、`napcat` 16），出现 9 个 `yebot_sticker_consider`/工具循环信号和 3 条 AstrBot 工具循环错误级信号；另有 7 条 provider/model warning，未包含失败或异常标记。没有 `execution_error`、Traceback、TypeError、YeBot 导入失败、连接/DNS/TTS 失败或 `ActionFailed`。
- 运行状态：两个容器均为 running，`RestartCount=0`、`OOMKilled=false`；窗口内没有新的启动、插件加载或连接成功标记。
- 处理：根因仍未确认，继续等待 AstrBot 工具循环/自动收录决策；本轮不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-07T00:09:41.671Z 至 2026-08-07T00:39:42.063Z）

- 状态：待决策；已知贴图工具循环异常明显复现，未发现新的可确认代码根因。
- 聚合：采集 320 条日志行（`astrbot` 230、`napcat` 90），出现 40 个贴图阶段、59 条 AstrBot `tool_loop_agent` 信号和 4 条 `execution_error`；4 条 `execution_error` 均关联 `sticker.consider`/`yebot_sticker_consider`。没有 Traceback、TypeError、YeBot 导入失败、连接/DNS/TTS 失败、非贴图 `execution_error` 或 `ActionFailed`。另有 19 条 provider/model warning，未包含失败或异常标记。
- 运行状态：两个容器均为 running，`RestartCount=0`、`OOMKilled=false`；窗口内没有新的启动、插件加载或连接成功标记。
- 处理：根因仍未确认，继续等待 AstrBot 工具循环/自动收录决策；本轮不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-07T00:39:42.063Z 至 2026-08-07T01:09:42.562Z）

- 状态：待决策；已知贴图工具循环错误级信号持续，未发现新的可确认代码根因。
- 聚合：采集 267 条日志行（`astrbot` 206、`napcat` 61），出现 33 个 `yebot_sticker_consider`/贴图阶段和 70 条 AstrBot `tool_loop_agent` 信号；其中 20 条为错误级信号，17 条带贴图标记。没有 `execution_error`、Traceback、TypeError、YeBot 导入失败、连接/DNS/TTS 失败或 `ActionFailed`。另有 14 条 provider/model warning，未包含失败或异常标记。
- 运行状态：两个容器均为 running，`RestartCount=0`、`OOMKilled=false`；窗口内没有新的启动、插件加载或连接成功标记。
- 处理：根因仍未确认，继续等待 AstrBot 工具循环/自动收录决策；本轮不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-07T01:09:42.562Z 至 2026-08-07T01:39:43.055Z）

- 状态：贴图工具循环问题待决策；新增外部模型 Provider 请求失败问题，待确认外部服务、请求契约或配置根因。
- 聚合：采集 1126 条日志行（`astrbot` 812、`napcat` 314），出现 88 个贴图阶段、165 条 AstrBot `tool_loop_agent` 信号和 9 条 `execution_error`；9 条 `execution_error` 均关联贴图流程。另有 1 次 Traceback，脱敏异常类型包含 16 条 `BadRequestError` 日志行和 5 条 `server_error`，调用路径出现 1 次 AstrBot `ProviderOpenAIOfficial._handle_api_error`；没有 TypeError、YeBot 导入失败、连接/DNS/TTS 失败、非贴图 `execution_error` 或 `ActionFailed`。另有 54 条 warning，其中 45 条带 provider/model 标记。
- 关联判断：`BadRequestError`/`server_error` 的直接日志行没有贴图标记；当前无法确认它们与已知贴图工具循环是否有因果关系，暂不合并两个问题。
- 运行状态：两个容器均为 running，`RestartCount=0`、`OOMKilled=false`；窗口内没有新的启动、插件加载或连接成功标记。
- 处理：不调整 Provider 配置、凭据、AstrBot 版本或重试策略；先按待确认问题记录，不改 YeBot 业务代码或运行配置。

## 问题 2：AstrBot 外部模型 Provider 请求失败

- 状态：待确认/待决策；当前证据指向 AstrBot Provider 请求或上游服务，尚未确认是请求契约、模型能力、配置、凭据还是上游波动。
- 证据：本轮 1126 条脱敏日志中出现 16 条 `BadRequestError` 日志行、5 条 `server_error`，以及 1 个 Traceback；异常路径聚合到 `ProviderOpenAIOfficial._handle_api_error`。这两类异常的直接日志行没有 `sticker` 标记；同一窗口另有 9 条贴图相关 `execution_error`，关联关系未确认。
- 影响：部分模型调用可能未完成；容器、OneBot/WS 链路和 YeBot 导入状态仍正常，尚无证据表明普通消息链路整体中断。
- 候选方向：核对 AstrBot 当前 Provider 的请求格式、模型能力与上游状态；确认后再决定是否调整 Provider 配置、AstrBot 版本或重试/降级策略；必要时增加不记录请求正文的 Provider 错误分类指标。
- 需要决策：是否允许检查或调整外部 Provider 配置、账号/凭据和部署策略；是否接受 Provider 重试或降级行为变化。

## 后续增量复核（2026-08-07T02:09:43.460Z 至 2026-08-07T02:39:43.940Z）

- 状态：贴图工具循环问题待决策；外部模型 Provider 请求失败继续出现，新增空模型输出/重试异常信号，根因仍未确认。
- 聚合：采集 1217 条日志行（`astrbot` 820、`napcat` 397），出现 88 个贴图阶段、131 条 AstrBot `tool_loop_agent` 信号和 4 条 `execution_error`；4 条 `execution_error` 均关联贴图流程。另有 1 次 Traceback，脱敏异常类型包含 `EmptyModelOutputError` 和 3 条 `RetryError`，调用路径出现 1 次 `ProviderOpenAIOfficial._handle_api_error`；没有 TypeError、`BadRequestError`、`server_error`、YeBot 导入失败、DNS/TTS 失败、非贴图 `execution_error` 或 `ActionFailed`。44 条 warning 中 38 条带 provider/model 标记。
- 关联判断：`EmptyModelOutputError`/`RetryError` 的直接日志行没有贴图标记；当前无法确认它们与已知贴图工具循环是否有因果关系，继续分别记录。
- 运行状态：两个容器均为 running，`RestartCount=0`、`OOMKilled=false`；窗口内没有新的启动、插件加载或连接成功标记。
- 处理：不调整 Provider 配置、凭据、AstrBot 版本或重试策略；先按待确认问题记录，不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-07T01:39:43.055Z 至 2026-08-07T02:09:43.460Z）

- 状态：待决策；已知贴图工具循环异常持续，未发现新的可确认代码根因。
- 聚合：采集 724 条日志行（`astrbot` 529、`napcat` 195），出现 160 个贴图阶段、215 条 AstrBot `tool_loop_agent` 信号和 6 条 `execution_error`；6 条 `execution_error` 均关联贴图流程。另有 1 个未关联 action 的 `ActionFailed`（`retcode=1200`）和 1 条未表现为失败的 WebSocket 信号；没有 Traceback、TypeError、Provider `BadRequestError`/`server_error`、YeBot 导入失败、DNS/TTS 失败或非贴图 `execution_error`。55 条 warning 中 41 条带 provider/model 标记，未包含失败或异常标记。
- 运行状态：两个容器均为 running，`RestartCount=0`、`OOMKilled=false`；窗口内没有新的启动、插件加载或连接成功标记。
- 处理：`ActionFailed` 暂无贴图、转发或明确 action 归因，继续观察；贴图问题根因仍未确认，本轮不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-07T02:39:43.940Z 至 2026-08-07T03:09:44.380Z）

- 状态：贴图工具循环问题待决策；未发现新的可确认代码根因。
- 聚合：采集 515 条脱敏日志行（`astrbot` 323、`napcat` 192），出现 40 个贴图阶段、42 条 AstrBot `tool_loop_agent` 信号和 2 条 `execution_error`；2 条 `execution_error` 均关联 `sticker.consider`/`yebot_sticker_consider`。没有 Traceback、TypeError、Provider 异常、YeBot 导入失败、连接/DNS/TTS 失败、非贴图 `execution_error` 或 `ActionFailed`。
- 运行状态：`qq-ai-bot-astrbot` 与 `qq-ai-bot-napcat` 均为 running，`RestartCount=0`、`OOMKilled=false`、退出码为 0；窗口内没有新的启动或插件加载标记。
- 处理：根因仍未确认，继续等待 AstrBot 工具循环/自动收录决策；本轮不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-07T03:09:44.380Z 至 2026-08-07T03:39:44.885Z）

- 状态：贴图工具循环问题待决策；未发现新的可确认代码根因。
- 聚合：采集 869 条脱敏日志行（`astrbot` 552、`napcat` 317），出现 82 个贴图阶段、91 条 AstrBot `tool_loop_agent` 信号和 2 条 `execution_error`；2 条 `execution_error` 均关联 `sticker.consider`/`yebot_sticker_consider`。没有 Traceback、TypeError、Provider 异常、YeBot 导入失败、连接/DNS/TTS 失败、非贴图 `execution_error` 或 `ActionFailed`。
- 运行状态：`qq-ai-bot-astrbot` 与 `qq-ai-bot-napcat` 均为 running，`RestartCount=0`、`OOMKilled=false`、退出码为 0；窗口内没有新的启动或插件加载标记。
- 处理：根因仍未确认，继续等待 AstrBot 工具循环/自动收录决策；本轮不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-07T03:39:44.885Z 至 2026-08-07T04:09:45.346Z）

- 状态：贴图工具循环问题待决策；未发现新的可确认代码根因。
- 聚合：采集 568 条脱敏日志行（`astrbot` 388、`napcat` 180），出现 102 个贴图阶段、105 条 AstrBot `tool_loop_agent` 信号和 6 条 `execution_error`；6 条 `execution_error` 均关联 `sticker.consider`/`yebot_sticker_consider`。没有 Traceback、TypeError、Provider 异常、YeBot 导入失败、连接/DNS/TTS 失败、非贴图 `execution_error` 或 `ActionFailed`。
- 运行状态：`qq-ai-bot-astrbot` 与 `qq-ai-bot-napcat` 均为 running，`RestartCount=0`、`OOMKilled=false`、退出码为 0；窗口内没有新的启动或插件加载标记。
- 处理：根因仍未确认，继续等待 AstrBot 工具循环/自动收录决策；本轮不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-07T04:09:45.346Z 至 2026-08-07T04:39:45.749Z）

- 状态：贴图工具循环问题待决策；未发现新的可确认代码根因。
- 聚合：采集 939 条脱敏日志行（`astrbot` 655、`napcat` 284），出现 125 个贴图阶段、155 条 AstrBot `tool_loop_agent` 信号和 7 条 `execution_error`；7 条 `execution_error` 均关联 `sticker.consider`/`yebot_sticker_consider`。没有 Traceback、TypeError、Provider 异常、YeBot 导入失败、连接/DNS/TTS 失败、非贴图 `execution_error` 或 `ActionFailed`。
- 运行状态：`qq-ai-bot-astrbot` 与 `qq-ai-bot-napcat` 均为 running，`RestartCount=0`、`OOMKilled=false`、退出码为 0；窗口内没有新的启动或插件加载标记。
- 处理：根因仍未确认，继续等待 AstrBot 工具循环/自动收录决策；本轮不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-07T04:39:45.749Z 至 2026-08-07T05:09:46.141Z）

- 状态：贴图工具循环问题待决策；未发现新的可确认代码根因。
- 聚合：采集 1207 条脱敏日志行（`astrbot` 795、`napcat` 412），出现 178 个贴图阶段、184 条 AstrBot `tool_loop_agent` 信号和 5 条 `execution_error`；5 条 `execution_error` 均关联 `sticker.consider`/`yebot_sticker_consider`。没有 Traceback、TypeError、Provider 异常、YeBot 导入失败、连接/DNS/TTS 失败、非贴图 `execution_error` 或 `ActionFailed`。
- 运行状态：`qq-ai-bot-astrbot` 与 `qq-ai-bot-napcat` 均为 running，`RestartCount=0`、`OOMKilled=false`、退出码为 0；窗口内没有新的启动或插件加载标记。
- 处理：根因仍未确认，继续等待 AstrBot 工具循环/自动收录决策；本轮不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-07T05:09:46.141Z 至 2026-08-07T05:39:46.566Z）

- 状态：贴图工具循环问题待决策；未发现新的可确认代码根因。
- 聚合：采集 603 条脱敏日志行（`astrbot` 408、`napcat` 195），出现 84 个贴图阶段、95 条 AstrBot `tool_loop_agent` 信号和 6 条 `execution_error`；6 条 `execution_error` 均关联 `sticker.consider`/`yebot_sticker_consider`。没有 Traceback、TypeError、Provider 异常、YeBot 导入失败、连接/DNS/TTS 失败、非贴图 `execution_error` 或 `ActionFailed`。
- 运行状态：`qq-ai-bot-astrbot` 与 `qq-ai-bot-napcat` 均为 running，`RestartCount=0`、`OOMKilled=false`、退出码为 0；窗口内没有新的启动或插件加载标记。
- 处理：根因仍未确认，继续等待 AstrBot 工具循环/自动收录决策；本轮不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-07T05:39:46.566Z 至 2026-08-07T06:09:46.975Z）

- 状态：贴图工具循环问题待决策；新增未关联贴图的 AstrBot 工具循环异常信号，待确认外部适配根因。
- 聚合：采集 770 条脱敏日志行（`astrbot` 544、`napcat` 226），出现 123 个贴图阶段、159 条 AstrBot `tool_loop_agent` 信号和 4 条 `execution_error`；4 条 `execution_error` 均关联 `sticker.consider`/`yebot_sticker_consider`。另有 2 组 Traceback/TypeError，异常形态均为 `unexpected-keyword`，两组均聚合到 AstrBot 工具循环，其中 1 组带贴图标记、1 组没有贴图标记；结构指纹为 `88c502f5ace51b6a971a02ab94dd518bb9d651100a947a1d58edf38af09a53cf` 与 `e3f3e40c3028b5a77c94d969013e2bca0764cdb51b7eddbcec8e68a18deb9d20`。没有 Provider、DNS/TTS、导入、连接或 `ActionFailed` 信号。
- 根因边界：Windows 与 WSL 运行副本的 `main.py`、`yebot/runtime/tools/catalog.py` 哈希一致；当前 YeBot 贴图工具签名包含默认参数，暂未发现插件副本过期或本地参数定义不一致证据。未关联贴图的异常不与贴图问题合并，继续按外部 AstrBot 工具循环问题待确认。
- 运行状态：`qq-ai-bot-astrbot` 与 `qq-ai-bot-napcat` 均为 running，`RestartCount=0`、`OOMKilled=false`、退出码为 0；窗口内没有新的启动或插件加载标记。
- 处理：不调整 AstrBot 版本、工具循环配置、Provider 或 YeBot 业务代码；等待允许检查外部工具调用契约/部署策略后再决定处理方式。

## 后续增量复核（2026-08-07T06:09:46.975Z 至 2026-08-07T07:09:47.873Z）

- 状态：贴图工具循环问题待决策；未发现新的异常类型或可确认代码根因。
- 聚合：采集 529 条脱敏日志行（`astrbot` 344、`napcat` 187），出现 73 个贴图阶段、76 条 AstrBot `tool_loop_agent` 信号和 2 条 `execution_error`；2 条 `execution_error` 均关联 `sticker.consider`/`yebot_sticker_consider`。没有 Traceback、TypeError、Provider 异常、YeBot 导入失败、连接/DNS/TTS 失败、非贴图 `execution_error` 或 `ActionFailed`。
- 运行状态：`qq-ai-bot-astrbot` 与 `qq-ai-bot-napcat` 均为 running，`RestartCount=0`、`OOMKilled=false`、退出码为 0；窗口内没有新的启动或插件加载标记。
- 处理：继续等待贴图工具循环与外部 AstrBot 工具循环问题的决策；本轮不改 YeBot 业务代码或运行配置。

## 后续增量复核（2026-08-07T07:09:47.873Z 至 2026-08-07T07:39:48.332Z）

- 对应 commit 范围：`3d4ec1f` 至 `3d4ec1f`；本轮仅追加运行记录，未修改业务代码。
- 状态：贴图工具循环问题待决策；新增未关联的图片功能错误、`ActionFailed` 与 WebSocket 状态信号，根因未确认。
- 聚合：采集 566 条脱敏日志行（`astrbot` 345、`napcat` 223），出现 27 个贴图阶段、39 条 AstrBot `tool_loop_agent` 信号和 0 条 `execution_error`。另有 3 条未关联贴图的图片功能错误、1 次未关联 action 的 `ActionFailed`（`retcode=1200`）和 1 条 WebSocket 状态标记；没有 Traceback、TypeError、Provider、DNS/TTS、YeBot 导入失败或非贴图 `execution_error`。WebSocket 信号未表现为断线或连接失败。
- 运行状态：`qq-ai-bot-astrbot` 与 `qq-ai-bot-napcat` 均为 running，`RestartCount=0`、`OOMKilled=false`、退出码为 0；窗口内没有新的启动或插件加载标记。
- 处理：新增信号没有暴露 YeBot handler、图片存储或 OneBot action 的明确根因，不调整业务代码、运行配置或部署；贴图工具循环与未关联运行信号继续分别等待决策/根因确认。

## 后续增量复核（2026-08-07T07:39:48.332Z 至 2026-08-07T08:14:48.790Z）

- 对应 commit 范围：`abd7303` 至 `abd7303`；本轮仅追加运行记录，未修改业务代码。
- 状态：新增普通消息发送中的 At 未结构化问题，待产品/权限边界决策；既有贴图工具循环问题继续待决策，未关联贴图的工具循环异常单独观察。
- 聚合：采集 1068 条脱敏日志行（`astrbot` 719、`napcat` 349），出现 212 条 AstrBot `tool_loop_agent` 信号、6 条贴图相关 `execution_error`、1 组未关联贴图的 `Traceback/TypeError` 和 1 次未关联 action 的 `ActionFailed`。没有 Provider、DNS/TTS、YeBot 导入失败或连接断线信号；6 条 `execution_error` 均属于贴图流程。
- At 证据：窗口内有 6 条 `yebot_message_send` 信号和 2 次 `send_group_msg`；`16:04:59.303` 的工具发送与 `16:04:59.590` 的 OneBot 发送均只有普通 `at` 文本标记，没有 `CQ:at` 或结构化 `type=at`。窗口内唯一 `CQ:at` 信号没有关联发送 action。
- 根因边界：`main.py` 的 `yebot_message_send` 只接收字符串，`yebot/runtime/tools/onebot.py` 将其原样作为 `send_group_msg.message` 发送；目标字段和结构化 At 生成均不存在。提醒确认路径还会把已解析 QQ 号拼进 `Plain("@QQ")`。目标解析、当前群校验和普通消息工具的 At 语义仍需要明确，不能把所有 `@数字` 文本直接转换。
- 运行状态：`qq-ai-bot-astrbot` 与 `qq-ai-bot-napcat` 均为 running，`RestartCount=0`、`OOMKilled=false`；窗口内没有新的启动或插件加载标记。
- 处理：不修改业务代码或运行配置；普通消息工具的结构化 At、目标校验和提醒确认输出方式列入待决策项，贴图与外部工具循环问题继续分别观察。

## 后续增量复核（2026-08-07T08:14:48.790Z 至 2026-08-07T08:44:49.326Z）

- 对应 commit 范围：`5621be0` 至 `5621be0`；本轮仅追加运行记录，未修改业务代码。
- 状态：At 发送问题本窗口未复现；既有贴图工具循环问题继续待决策，未发现新的异常类型或可确认代码根因。
- 聚合：采集 761 条脱敏日志行（`astrbot` 521、`napcat` 240），出现 172 条 AstrBot `tool_loop_agent` 信号和 3 条 `execution_error`，3 条均关联贴图流程。窗口内有 2 次 `send_group_msg`，没有 `yebot_message_send`、At 结构化段、Traceback、TypeError、Provider、DNS/TTS、导入失败、ActionFailed 或连接断线信号。
- 运行状态：`qq-ai-bot-astrbot` 与 `qq-ai-bot-napcat` 均为 running，`RestartCount=0`、`OOMKilled=false`；窗口内没有新的启动或插件加载标记。
- 处理：At 问题继续等待真实 QQ 验收或明确工具语义；贴图工具循环继续等待 AstrBot 适配/自动收录决策；本轮不改 YeBot 业务代码或运行配置。
