# 项目结构说明

这个项目是一个用于学习 Agent 架构的最小本地框架。当前结构目标是：主循环稳定，工具、模型、计划、机器人等能力分别模块化，后续新增功能尽量放到对应模块中，避免频繁修改核心流程。

## 总体结构

```text
self-test/
  agent/          Agent 后端核心代码
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
  message_builder.py  消息格式构造
  context.py          动态 system prompt 组装
  prompt.py           Prompt 系统兼容入口
  prompts/            Prompt 规则模块
  permissions.py      工具调用权限检查

  tools.py            工具系统兼容入口
  toolkit/            工具模块

  model_adapter.py    模型系统兼容入口
  models/             模型适配模块

  plans.py            计划系统兼容入口
  planning/           计划模块

  memory.py           状态系统兼容入口
  tasks.py            状态系统兼容入口
  approvals.py        状态系统兼容入口
  hooks.py            状态系统兼容入口
  skills.py           状态系统兼容入口
  state/              状态与知识模块

  robot/              机器人控制模块
```

## 核心边界

### 主循环

位置：

```text
agent/agent_loop.py
```

职责：

- 接收用户输入
- 调用模型
- 检查工具权限
- 执行工具
- 把工具结果写回消息历史
- 生成最终回复

原则：主循环尽量保持稳定，不直接写具体业务逻辑。新增能力优先放到工具、模型、计划或机器人模块中。

### 工具系统

位置：

```text
agent/tools.py
agent/toolkit/
```

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
6. 如需要，在 prompt.py 或 demo.py 中补充使用说明或测试路由
7. 运行最小验证
```

### 模型系统

位置：

```text
agent/model_adapter.py
agent/models/
```

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
4. 如需兼容旧导入，在 models/__init__.py 或 model_adapter.py 中导出
```

### Prompt 系统

位置：

```text
agent/prompt.py
agent/prompts/
```

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

顶层的 `prompt.py` 是兼容入口。新 prompt 规则优先放到 `agent/prompts/` 中。

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

位置：

```text
agent/plans.py
agent/planning/
```

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

位置：

```text
agent/memory.py
agent/tasks.py
agent/approvals.py
agent/hooks.py
agent/skills.py
agent/state/
```

当前分类：

```text
agent/state/
  memory_store.py      长期记忆，读写 .agent_state/memory.md
  task_store.py        任务列表，读写 .agent_state/tasks.json
  approval_store.py    人工审批，读写 .agent_state/approvals.json
  event_log.py         工具事件日志，写入 .agent_state/tool_events.jsonl
  skill_store.py       内置技能说明
```

顶层的 `memory.py`、`tasks.py`、`approvals.py`、`hooks.py`、`skills.py` 是兼容入口。新逻辑优先放到 `agent/state/` 中。

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
- 放行机器人工具，但机器人动作仍需要经过 robot_safety

原则：任何能访问文件、执行命令、调用外部能力或控制硬件的工具，都要先经过权限设计。

### 机器人系统

位置：

```text
agent/robot/
```

当前分类：

```text
agent/robot/
  robot_protocol.py   命令、状态、结果数据结构
  robot_safety.py     运动限制和计划校验
  robot_simulator.py  本地模拟器
  robot_adapter.py    HTTP、Socket 等外部适配器
  robot_tools.py      暴露给模型的机器人工具
```

原则：模型不能直接控制底层硬件。真实硬件必须放在 adapter 后面，并经过 safety 检查。

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
5. 扩展机器人能力：放入 robot
6. Web 功能复杂后，再考虑拆 web_server.py
7. agent_loop.py 暂时保持稳定，不优先拆
```

当前项目的主要扩展点：

```text
工具扩展点：agent/toolkit/
模型扩展点：agent/models/
计划扩展点：agent/planning/
状态扩展点：agent/state/
机器人扩展点：agent/robot/
```
