# 项目结构说明

这个项目是一个用于学习 Agent 架构的最小本地框架。当前结构目标是：主循环稳定，工具、模型、计划、机器人等能力分别模块化，后续新增功能尽量放到对应模块中，避免频繁修改核心流程。

## 总体结构

```text
self-test/
  agent/          Agent 后端核心代码
  contracts/      跨进程公共数据协议
  robot_runtime/  机器人边缘执行、模拟和安全
  services/       远程服务注册与通信边界验证
  evaluations/    开发评测，不参与线上运行
  web/            Web 前端页面
  docs/           学习文档和结构说明
  notes/          实验笔记和临时记录
  .agent_state/   本地运行状态，已被 .gitignore 忽略
```

## Agent 后端结构

```text
agent/
  main.py             CLI 启动入口
  web_server.py       Web 服务入口
  agent_loop.py       Agent 主循环
  capabilities/       能力目录、元数据和目标匹配
  execution/          目标执行、完成验证和报告
  routing/            显式指令解析和路由约束
  scheduling/         执行目标校验与统一分发
  message_builder.py  消息格式构造
  context.py          动态 system prompt 组装
  prompts/            Prompt 规则模块
  permissions.py      工具调用权限检查

  toolkit/            工具模块

  models/             模型适配模块

  planning/           计划模块

  state/              状态与知识模块

  robot/              Agent 侧机器人客户端和工具
```

## 核心边界

### 能力系统

位置：

```text
contracts/capability.py
agent/capabilities/registry.py
```

每个工具必须登记为一个 Capability，并统一描述：

```text
name
domain
execution_target
risk_level
tool_name
input_schema
tags
```

普通 Agent 根据当前目标选择相关能力并缩小工具 Schema；无法识别的开放目标回退到完整能力目录。确定性路由要求的工具会自动并入本轮能力集合，任何未被选择的工具调用都会在执行前被拒绝。

### 执行资源注册与选择

位置：

```text
contracts/resource.py               执行资源和运行状态协议
agent/scheduling/resources.py       资源注册、注销和运行状态更新
agent/scheduling/selector.py        能力到具体资源的选择规则
agent/scheduling/dispatcher.py      使用选择结果执行请求
```

Capability 表示“系统会做什么”，ExecutionResource 表示“当前由谁执行”。一个资源登记：

```text
resource_id
execution_target
capabilities
status       available / degraded / busy / offline
load         0.0 - 1.0
priority
last_seen_at
consecutive_failures
last_error
heartbeat_timeout_s
failure_threshold
metadata
```

调用方默认不填写 `resource_id`。Selector 先筛选支持目标 Capability 和 execution target 的资源，排除 busy 和 offline，再依次比较可用状态、负载、优先级和稳定 ID。显式指定资源只用于管理、调试或固定路由，并且仍需通过能力和状态检查。

默认环境为四种 execution target 分别注册一个内置逻辑资源。接入多台机器人或多个外部执行器时，为相同 Capability 注册不同资源及其 Handler 即可，不需要修改 Agent 主循环。

资源健康规则：

```text
开始执行                    -> busy
执行成功或收到心跳           -> available，并清零连续失败
第一次可重试故障             -> degraded
连续故障达到 failure_threshold -> offline
权限、参数等非资源故障         -> 释放资源，不累计失败
超过半个 heartbeat_timeout    -> degraded
超过完整 heartbeat_timeout    -> offline
新的有效心跳                  -> available，重新参与调度
```

只有配置了 `heartbeat_timeout_s` 的外部资源才根据失联时间变化；本地内置逻辑资源不会因为长时间没有任务而离线。失联状态会在资源选择和 Web 状态查询前刷新。Web 通过 `GET /api/resources` 返回资源快照，页面每 5 秒更新一次，但网页轮询本身不改变资源健康数据。

### 统一执行协议

位置：`contracts/execution.py`

公共对象：

```text
ExecutionRequest   一次能力执行请求
ExecutionEvent     执行过程或终态反馈
ExecutionResult    终态结果摘要
ExecutionError     结构化错误
ExecutionStatus    统一生命周期状态
```

统一状态：

```text
created
accepted
running
waiting_feedback
succeeded
failed
cancelled
timed_out
```

普通工具和 GoalRunner 会为每次调用创建 `ExecutionRequest`，Dispatcher 选择具体资源后将结果写成 `ExecutionEvent`。事件保留 `tool`、`arguments` 等调试字段，同时增加执行 ID、Capability、执行目标、资源 ID、结构化错误和观察数据。机器人 `ActionStatus` 会映射到同一状态集合，但目标运行整体的 `completed/blocked` 仍属于 GoalRunner 结果，不与单次执行状态混用。

### 统一执行分发

位置：`agent/scheduling/dispatcher.py`

Dispatcher 是运行时唯一的工具执行入口，职责是：

- 根据 Capability 校验 `execution_target`
- 根据 Capability、状态、负载和优先级选择具体执行资源
- 将请求分发到 `local_toolkit`、`agent_state`、`robot_gateway` 或 `remote_service`
- 在 Handler 执行前统一调用 `check_tool_call()`
- 将成功或异常统一转换为 `ExecutionEvent`
- 通过 `remote_service` 通信适配器连接白名单中的外部服务

本地、状态和机器人目标复用已有 Python Handler；`remote_service` 由 `agent/scheduling/remote.py` 通过 HTTP 发送统一执行协议。服务地址只允许从 `REMOTE_SERVICES` 白名单读取，模型不能提供 URL。后续接入外部软件时，只需要实现 `/executions` 协议；接入真实机器人时仍经过专用机器人网关，不让通用远程调用绕过机器人安全层。

远程服务通信链：

```text
LLM 选择 invoke_remote_service
  -> ExecutionRequest
  -> Dispatcher(remote_service)
  -> ServiceRegistry 解析符号服务名
  -> POST /executions
  -> 外部服务返回 ExecutionEvent
  -> Dispatcher 校验 execution_id / capability / target
  -> 结果回填给 LLM
```

### 感知反馈边界

位置：

```text
contracts/observation.py       结构化 Observation 协议
services/perception.py         可切换场景的独立模拟感知服务
agent/toolkit/service_tools.py perception_observe / perception_check_path
agent/robot/policy.py          根据最新感知结果约束机器人移动
```

感知能力使用 `remote_service` 通道，但模型不需要填写服务名和 HTTP 操作。调度层会将类型化能力固定映射到 `perception` 服务。`Observation` 统一保存来源、对象、障碍物、路径是否畅通、置信度和图像引用。

移动约束：

```text
最新感知 path_clear=true  -> 允许继续进入机器人权限和安全检查
最新感知 path_clear=false -> Agent 侧拒绝移动
最新感知失败              -> Agent 侧拒绝移动
没有结构化 observation     -> Agent 侧拒绝移动
方向或距离超出路径检查范围 -> Agent 侧拒绝移动
已经执行过一次移动          -> 必须重新感知
```

该约束不能替代 `robot_runtime/safety.py`。Agent 侧负责根据语义观察做决策，机器人网关仍负责速度、距离、超时、急停等执行安全。

本地 `DemoModel` 对“仅在路径安全时移动”的目标实现了一条确定性多轮路径，用于无 API 验证：先调用 `perception_check_path`，再读取 `Observation`；畅通时调用一次参数匹配的 `robot_move`，阻塞时停止。真实模型不依赖这条规则，而是根据相同工具 Schema、Prompt 和反馈自行决策。`RobotFeedbackVerifier` 会把“条件目标中因障碍而正确不移动”认定为有效完成。

### 主循环

位置：

```text
agent/agent_loop.py
```

职责：

- 接收用户输入
- 调用模型
- 创建统一执行请求并交给 Dispatcher
- 把工具结果写回消息历史
- 生成最终回复

原则：主循环尽量保持稳定，不直接写具体业务逻辑。新增能力优先放到工具、模型、计划或机器人模块中。

### 工具系统

位置：`agent/toolkit/`

当前分类：

```text
agent/toolkit/
  schema.py            工具 schema 构造
  registry.py          汇总 TOOL_SCHEMAS 和 TOOL_HANDLERS
  file_tools.py        文件读写、搜索、预览
  workspace_tools.py   工作区摘要、文件统计
  command_tools.py     白名单命令执行
  experiment_tools.py  实验记录
  state_tools.py       memory、tasks、plans、approvals、skills 暴露给模型
```

新增工具流程：

```text
1. 找到对应的 agent/toolkit/*_tools.py
2. 新增工具 schema
3. 新增 handler 函数
4. 注册到该模块的 *_TOOL_HANDLERS
5. 如需要，在 permissions.py 中加入权限规则
6. 如需要，在 prompts/ 或 models/demo.py 中补充使用说明或测试路由
7. 运行最小验证
```

### 模型系统

位置：`agent/models/`

当前分类：

```text
agent/models/
  base.py                 ModelAdapter 协议和通用消息读取
  env.py                  .env 加载和环境变量读取
  demo.py                 本地 DemoModel
  openai_compatible.py    OpenAI-compatible chat completions 适配
  deepseek.py             DeepSeek 默认配置
  loader.py               load_model_from_env
```

新增模型流程：

```text
1. 在 agent/models/ 新增模型适配文件
2. 实现 complete(messages, tools, system_prompt)
3. 在 loader.py 中加入 provider 路由
4. 在 models/__init__.py 中导出公共模型接口
```

### Prompt 系统

位置：`agent/prompts/`

当前分类：

```text
agent/prompts/
  base.py          基础身份和总定位
  capabilities.py  当前能力清单
  tools.py         工具使用规则
  safety.py        权限、审批和失败重试规则
  planning.py      计划创建、执行、诊断和解析规则
  robot.py         机器人控制规则
  style.py         输出风格规则
  builder.py       汇总生成 SYSTEM_PROMPT
```

扩展 Prompt 时，优先判断规则属于哪一类：

```text
基础身份        -> base.py
新增能力描述    -> capabilities.py
工具选择倾向    -> tools.py
权限和审批      -> safety.py
计划执行规则    -> planning.py
机器人规则      -> robot.py
输出风格        -> style.py
拼接方式        -> builder.py
```

### 计划系统

位置：`agent/planning/`

当前分类：

```text
agent/planning/
  store.py       plans.json 读取、保存和状态常量
  actions.py     创建、列表、更新、解除阻塞
  executor.py    建议下一步、执行单步、执行下一步
  diagnosis.py   blocked 步骤诊断
  formatter.py   计划输出格式
  summary.py     前置步骤结果和汇总步骤判断
```

扩展计划系统时，优先判断改动属于哪一类：

```text
计划存储格式        -> store.py
计划基础操作        -> actions.py
自动执行规则        -> executor.py
失败原因分析        -> diagnosis.py
输出展示格式        -> formatter.py
汇总和前置结果处理  -> summary.py
```

### 状态与知识系统

位置：`agent/state/`

当前分类：

```text
agent/state/
  memory_store.py      长期记忆，读写 .agent_state/memory.md
  task_store.py        任务列表，读写 .agent_state/tasks.json
  approval_store.py    人工审批，读写 .agent_state/approvals.json
  event_log.py         工具事件日志，写入 .agent_state/tool_events.jsonl
  skill_store.py       内置技能说明
```

状态与工具的关系：

```text
模型请求状态能力
  -> toolkit/state_tools.py 暴露为工具
  -> agent/state/*_store.py 执行真实读写
  -> .agent_state/ 保存运行数据
```

### 权限系统

位置：

```text
agent/permissions.py
```

职责：

- 限制路径工具只能访问工作区内部
- 限制命令工具只能执行白名单命令
- 放行安全状态工具
- 放行机器人工具，但机器人动作仍需要经过 `robot_runtime/safety.py`

原则：任何能访问文件、执行命令、调用外部能力或控制硬件的工具，都要先经过权限设计。

### 机器人系统

当前分类：

```text
agent/robot/
  client.py           HTTP、Socket 网关客户端
  tools.py            暴露给模型的高层机器人工具
  policy.py           Agent 侧计划结构校验

contracts/
  robot.py            命令、状态、结果公共数据协议

robot_runtime/
  adapter.py          模拟器、仿真环境或硬件驱动的稳定适配协议与工厂
  safety.py           执行端运动安全强制检查
  simulator.py        本地模拟执行器
  gateway_server.py   异步 HTTP 机器人网关
```

原则：模型不能直接控制底层硬件。Agent 只调用客户端；真实驱动放在 `robot_runtime/`，并在执行端再次进行安全检查。

依赖方向固定为：

```text
contracts
  ↑              ↑
agent/robot   robot_runtime
  ↑
Agent / Web / evaluations
```

- `contracts/` 不依赖 Agent 或机器人运行时。
- `agent/robot/` 只保留客户端、高层工具和决策侧策略，不实现网关、模拟器或硬件安全。
- `robot_runtime/` 不依赖模型、Prompt、计划或 Agent 状态。
- `gateway_server.py` 只依赖 `RobotRuntimeAdapter`，不直接依赖具体模拟器或硬件 SDK。
- 长动作由适配器的 `execute_motion` 实际执行，并通过回调返回进度；网关负责线程、取消、看门狗和统一终态。
- 适配器统一输出米制位姿；航向角以 +x 为零，逆时针为正。设备原生坐标由适配器负责转换。
- 本地 `simulated` 模式允许 Agent 进程直接加载模拟器，仅用于开发测试。
- HTTP/Socket 模式必须经过独立网关，真实硬件接入统一使用该模式。

## 运行状态

运行状态统一放在：

```text
.agent_state/
```

典型内容：

```text
memory.md
tasks.json
plans.json
approvals.json
tool_events.jsonl
robot_state.json
```

这些文件属于本地运行状态，不作为项目源码维护。

## 后续扩展建议

优先级建议：

```text
1. 新增普通能力：先做成 toolkit 工具
2. 新增模型：放入 models
3. 扩展计划能力：放入 planning
4. 扩展状态能力：放入 state
5. 扩展机器人高层工具：放入 agent/robot
6. 扩展机器人执行和硬件：放入 robot_runtime
7. Web 功能复杂后，再考虑拆 web_server.py
8. agent_loop.py 保持稳定，显式路由放入 routing
```

当前项目的主要扩展点：

```text
工具扩展点：agent/toolkit/
模型扩展点：agent/models/
计划扩展点：agent/planning/
状态扩展点：agent/state/
执行扩展点：agent/execution/
路由扩展点：agent/routing/
机器人客户端扩展点：agent/robot/
机器人执行扩展点：robot_runtime/
跨层协议扩展点：contracts/
```
