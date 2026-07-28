# self-test Agent 框架阶段汇报

汇报日期：2026-07-28

## 一、阶段目标

这两天的核心目标是把项目从“能调用单个工具的演示程序”，推进到“具备完整 Agent 运行周期的本地框架”。

目标链路如下：

```text
自然语言输入
  -> 任务创建
  -> 计划生成
  -> 步骤执行
  -> 工具调用
  -> 状态写回
  -> 过程报告
  -> 后续可继续操作
```

重点不是增加更多工具，而是让已有的任务、计划、工具、状态、审批和 Web 展示形成稳定闭环。

## 二、主要完成内容

### 1. 完整任务运行周期

新增 `run_task_cycle` 作为端到端任务入口。

它负责把一次用户需求串成完整过程：

```text
create_task
create_task_plan
validate_task_plan
start_task
execute_next_plan_step
complete_task / fail_task
```

现在可以直接输入：

```text
帮我完整检查一下当前项目结构，并总结结果
```

系统会自动进入完整任务周期，而不是只返回一段普通回答。

### 2. 过程可见化输出

`run_task_cycle` 的最终输出改为执行报告格式，包含：

- Task ID
- Plan ID
- Task status
- Plan progress
- Execution trace
- Plan steps
- Final result

示例结构：

```text
Task cycle report

| Field | Value |
| Task ID | task_xxx |
| Plan ID | plan_xxx |
| Task status | done |

Execution trace
| # | Phase | Tool | Status | Result |

Plan steps
| Step | Status | Executor | Result |
```

这样可以清楚看到 Agent 内部做了什么，而不是只看到模型整理后的总结。

### 3. 自然语言触发完整周期

补充了自然语言路由和 prompt 规则。

现在支持：

```text
运行任务 检查项目结构 :: workspace summary; list files in agent; read README.md; summarize results
帮我完整检查一下当前项目结构，并总结结果
```

对于真实模型，例如 DeepSeek，系统提示中也明确说明：

```text
当用户要求完整检查、完整执行、自动规划并执行时，优先调用 run_task_cycle。
```

### 4. 计划别名解析

扩展了计划引用方式，减少用户手动复制 ID 的需求。

现在计划工具支持：

```text
current plan
latest plan
recent plan
当前计划
最近计划
刚才的计划
```

例如：

```text
execute next step of current plan
执行当前计划下一步
```

底层会自动解析到真实的 `plan_id`。

### 5. Web 端工具轨迹展示优化

Web 页面继续强化了“工具调用可观察性”：

- 左侧展示运行状态、常用指令和验证方向
- 中间保留对话区
- 右侧累计展示工具调用轨迹
- 每次工具调用拆分展示参数和结果
- 支持快速验证工作区摘要、计划状态、文件统计、README 预览等能力

这样 Web 端更适合演示 Agent 的执行过程，而不是只像普通聊天窗口。

### 6. 测试覆盖增强

测试从原来的 38 项增强到 42 项，新增保护内容包括：

- 完整任务周期可以端到端执行
- `run_task_cycle` 返回过程报告
- 自然语言可以触发完整任务周期
- Agent 直接返回过程报告，不被模型二次总结覆盖
- `current plan` / `最近计划` / `刚才的计划` 可以解析到最近计划
- 当前计划可以继续执行下一步

## 三、当前项目能力

目前 `self-test` 已经具备一个比较完整的本地 Agent 框架雏形：

```text
agent_loop.py
  负责模型 -> 工具 -> 结果的主循环

models/
  负责 demo 模型和 OpenAI-compatible 模型适配

toolkit/
  负责文件、命令、工作区、状态、实验记录等工具

state/
  负责任务、审批、记忆、技能和工具事件日志

planning/
  负责计划创建、计划执行、步骤映射、失败诊断、完整任务周期

prompts/
  负责系统提示拆分和能力规则

web/
  负责网页端对话与工具轨迹展示

robot/
  负责机器人协议、安全、模拟器、适配器和高层工具
```

从运行逻辑看，目前框架已经可以表达：

```text
用户输入
  -> 模型理解
  -> 工具选择
  -> 权限检查
  -> 工具执行
  -> 状态记录
  -> 结果写回
  -> 可视化展示
```

## 四、验证结果

已执行：

```powershell
python -m compileall agent
python -m pytest -q
```

结果：

```text
42 passed
```

实际交互验证：

```text
帮我完整检查一下当前项目结构，并总结结果
```

预期并已验证的行为：

```text
调用 run_task_cycle
生成 task_id
生成 plan_id
执行计划步骤
输出 Task cycle report
```

## 五、阶段意义

这一阶段解决了两个关键问题。

第一，系统不再只是“能调用工具”，而是可以形成完整任务闭环。

第二，用户不需要每一步都复制 ID。任务和计划仍然有 ID，保证系统内部可追踪；但交互层逐步支持自然语言和 `current/latest/recent` 引用。

这使项目更接近一个真正 Agent 框架：

```text
ID 是内部状态管理机制
自然语言是用户交互方式
工具和计划是执行层
报告和日志是可观察性
```

## 六、下一步建议

建议后续按下面顺序推进：

1. 审批别名解析

支持：

```text
批准最近审批
取消最近审批
查看最近审批
```

2. 阻塞步骤自然恢复

支持：

```text
诊断当前阻塞步骤
解决当前阻塞步骤 :: 人工处理结果
```

3. Web 端过程报告增强

把 `Task cycle report` 中的表格进一步在 Web 端结构化展示，区分：

```text
任务信息
执行轨迹
计划步骤
最终结果
```

4. 外部连接层 connectors

后续如果要对接机器人或外部应用，建议增加：

```text
connectors/
```

用于隔离 Agent 工具和真实外部系统。

## 七、当前结论

目前项目已经完成从“工具调用练习”到“本地 Agent 执行框架”的关键过渡。

当前阶段可以归纳为：

```text
自然语言可触发
任务周期可执行
计划状态可追踪
工具过程可观察
后续操作可继续
测试体系可保护
```

下一阶段重点应继续围绕“自然交互”和“执行可观察性”推进，而不是盲目增加更多工具。
