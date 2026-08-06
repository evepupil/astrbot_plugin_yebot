# Token 计算

- 模块定位：复用 TokenCal 的公开公式，计算 AI 编程会话的 Token 综合单价和预计费用。
- 对应代码：`yebot/runtime/token_calculator/`、`yebot/runtime/tools/catalog.py`、`yebot/runtime/tools/onebot.py`、`main.py`
- 所属里程碑：[M7](../roadmap.md#m7)
- 当前状态：进行中
- 最近更新时间：2026-08-03

## 职责与边界

模块只实现 [TokenCal](https://tokencal.chaosyn.com/) 页面当前公开的本地计算公式，不抓取页面、不发送用户数据，也不接受任意 URL。调用方必须提供总 Token 数，单位为百万 M；模型不能凭空估算未提供的数量。实际运行中的 Token usage 统计由[系统运维工具](系统运维工具.md)单独负责。

## 结构与数据流

`yebot_token_calculate` -> `ToolGateway` 权限与参数校验 -> `TokenCalculator` -> 固定公式 -> Agent 整理综合单价和预计账单。

页面提供两个场景：国产 / Agent 交互使用 `245 : 1`，国外 / 长上下文重用使用 `480 : 1`。设场景比例为 `base`，缓存命中率为 `Rcache`，价格单位为 `$ / M`，公式为：

```text
effective_input_price = (1 - Rcache) * Pin + Rcache * Pcache
average_price = (base * effective_input_price + Pout) / (base + 1)
estimated_total_cost = average_price * total_tokens_million
```

## 关键决策

- 采用本地纯函数，页面没有独立后端接口，避免依赖 DOM、脚本顺序和远程可用性。
- 保留页面默认值：`Pin=1.40`、`Pout=4.40`、`Pcache=0.26`、`Rcache=92.2%`，场景默认为国产 / Agent 交互。
- 工具权限为 `token.calculate`，所有角色均可全局只读查询，不要求当前群，也不调用 OneBot 写操作。
- `token.calculate` 的输入是用户明确提供的估算数量，不能读取或冒充 AstrBot 的实际 usage 统计。
- 价格、缓存命中率和总 Token 数都限制为有限非负数；缓存命中率最大为 100%，避免模型传入无意义计算。
- 结果同时返回原始数值和页面格式化文本，并标记固定来源，便于机器人简洁复述。

## 当前实现

`models.py` 定义场景和结果对象，支持页面值及常见中文场景别名；`client.py` 实现公式、输入范围校验和结果格式化。`catalog.py` 声明 `token.calculate`，`permissions.py` 给普通成员提供全局只读权限，`onebot.py` 和 `main.py` 分别接入网关 handler 与 Agent/function tool。`token_calculator_enabled` 可关闭工具，默认启用。真实 usage 统计不复用本模块的计算参数。

## 验证方式

- `tests/test_token_calculator.py`：覆盖页面默认值、两个场景、中文别名、公式结果和异常输入。
- `tests/test_onebot_tools.py`：覆盖普通成员调用、结果返回和无 OneBot 写操作。
- 提交前运行 pytest、Ruff、strict mypy、配置 JSON 解析和 `git diff --check`。
- 部署后在 AstrBot 运行态使用明确的百万 M 数量进行一次自然语言验收。

## 待扩展项

如果 TokenCal 后续增加输入/输出 Token 分项、更多模型价格或公开 API，应先确认新统计口径，再扩展独立参数和版本化数据模型。

## 改动历史

- 2026-08-03：新增 TokenCal 本地公式、只读工具、Agent 路由和单测。
