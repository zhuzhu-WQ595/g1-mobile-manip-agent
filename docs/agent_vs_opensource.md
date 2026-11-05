# 自研 Agent vs 开源 Agent:架构对比与开发学习指南

> 对比对象:本仓库 `agent/` + `contracts/`(Isaac G1 移动操作 Agent)
> 参照:LangChain/LangGraph、AutoGPT、OpenAI Agents SDK、Semantic Kernel、smolagents、SayCan(RT 系)、MCP

---

## 1. 你的 Agent 架构拆解

### 1.1 主循环:`agent/agent_loop.py`(ReAct 变体)

```
user text
  → 关键词选 capability 子集(CAPABILITY_REGISTRY.select)
  → 组 system prompt + tool schemas
  → loop (max_steps):
      model.complete(messages, tools)
      → message? → 结束
      → tool_calls? → 逐个:
          权限检查(未选中 capability / 参数校验 / 运动-感知一致性)
          → DISPATCHER.dispatch(ExecutionRequest)
          → tool_result 追加进 messages
          → 命中"请求任务完成"→ 追加一次无工具总结调用 → 结束
          → 错误熔断 / 成功即停启发式
```

这就是教科书式 **ReAct loop**(Yao et al. 2022):推理(选工具)→ 行动(执行)→ 观察(结果回填)→ 循环。区别是你在标准循环外挂了五层安全网,多数开源 demo 一层都没有。

### 1.2 四层执行栈(你独有的部分)

| 层 | 文件 | 职责 |
|---|---|---|
| 意图路由 | `routing/intent_parser.py` | 关键词→capability 组子集;强制 tool_call;停/继续启发式 |
| 能力契约 | `contracts/capability.py` + `capabilities/registry.py` | 每个工具声明 domain/target/risk/tags,启动时校验目录与 schema 一一对应 |
| 调度 | `scheduling/dispatcher.py` + `resources.py` | ExecutionRequest → 资源选择 → mark_busy → 执行 → ExecutionEvent → 心跳/失败计数 |
| 执行体 | `toolkit/` + `robot/` + `scheduling/remote.py` | 本地 handler / 机器人 adapter / HTTP 远程服务 |

开源框架里这套东西是**平铺**的(tools 列表直接进 LLM);你加了显式的契约层和资源健康层——这更接近 ROS action server + capability server 的思想,也比大多数 agent 框架"工程化"。

### 1.3 目标驱动模式:`execution/runner.py` + `cli.py`

`--mobile-manip` 用的是 `GoalRunner`:限定工具集(`MOBILE_MANIP_GOAL_TOOLS`)+ 目标规则(`MOBILE_MANIP_RULES`)+ 每步 verifier(物理移动后实测位移校验)+ JSON 报告。这是 AutoGPT 式"给一个终态目标自己跑到完"的简化版,但加了 SayCan 式的执行后验证。

---

## 2. 逐项对比

| 维度 | 你的实现 | LangGraph | OpenAI Agents SDK | AutoGPT | smolagents | SayCan(机器人参考) |
|---|---|---|---|---|---|---|
| **循环范式** | ReAct + 启发式终止 | 状态图(节点/边) | Runner + handoff | task loop | CodeAct(写代码当动作) | LLM 选技能 + affordance 打分 |
| **工具契约** | CapabilitySpec(domain/target/risk/tags) | Tool 装饰器 + schema | FunctionTool + guardrail | command JSON | Python 函数 + type hints | 技能 affordance 函数 |
| **权限/安全** | 选中集 + 参数校验 + 审批队列 + 运动-感知一致性 | interrupt() 人工断点 | guardrail 装饰器 | 无 | 沙箱提示 | affordance 可行性 |
| **执行资源** | ResourceRegistry(busy/heartbeat/failures) | 无(外部自管) | 无 | 无 | 无 | robot API 直调 |
| **结果验证** | robot_move 位移核对 + VLM vision_verify + /world 真值 | 自定义节点 | 无内置 | self-critique | 无 | affordance 再估计 |
| **记忆** | remember/read/clear 工具 + event_log | checkpointer + store | session memory | vector/file memory | 无 | 无 |
| **规划** | LLM 调 plan 工具(create_plan/execute_step/diagnose) | graph 即计划 | 无显式 planner | task 分解 | 无 | 无 |
| **多智能体** | 无 | graph 节点多 agent | handoff | 无 | 无 | 无 |
| **可观测** | event_log + JSON report + 录制视频 | LangSmith trace | trace | 日志 | 无 | 无 |

### 逐点解读

**你的亮点(大多数开源 demo 没有的)**

- **契约化能力目录**。每个工具必须声明 execution_target(local/state/robot/remote)和 risk_level,启动时强校验目录与 schema 一致性——加工具忘了分组会直接拒绝启动。这就是 MCP 的 annotations + ROS capability server 的组合,比"tools 列表"严谨。
- **资源健康层**。dispatcher 会给执行资源(如 Isaac 桥)记心跳、连续失败数、busy 状态;连接被拒会反映在 resource_health 里。开源框架里机器人执行几乎全是"调用即信"。
- **物理事实核验**。`robot_move` 执行后用前后位姿实测位移<50%就判 obstacle_detected;`vision_verify` 用 VLM 问"苹果是否放上桌了";`/world` 直接读真值。这正是 SayCan "affordance" 思想的工程版——LLM 决定的行动必须由物理/视觉反馈收口。
- **审批队列**。覆盖写文件等高风险动作走 `request_overwrite_file` → 人工批 → 再执行。LangGraph 的 interrupt 是通用版,你的 approval_store 是专门化的。

**你的短板(学开源能补的)**

- **工具路由是关键词匹配**。`select()` 靠中英文关键词命中 capability 组,漏词就全量开放(50+ schema 进 context)。主流做法是 embedding 语义检索工具(LangChain 的 `ToolRegistry` + vector store,OpenAI 的 tool search preview),或干脆全量 + 强 system prompt。关键词法在小工具集够用,扩到 200 个工具会崩。
- **无 checkpoint/恢复**。`agent_loop` 的 `self.messages` 是纯内存,任务中断就丢。LangGraph 的 checkpointer 让你能"暂停-人工介入-继续";你只有 approval 这一种介入点。
- **上下文管理缺失**。messages 全量进每次 complete,长任务(20 步 × 每条 tool_result 一大段 JSON)会逼近窗口上限。LangChain 有 summarization middleware;LangGraph 有 pre_model_hook 裁剪。你现在是 `max_steps≤20` 硬顶兜着。
- **线性控制流**。循环里的"该不该停"全靠 intent_parser 一堆启发式硬编(强制 call、成功即停、错误熔断、重复动作保护)。LangGraph 把这些表达成显式图的边和条件,可读性/可测试性都好得多——你的启发式本质是手写的状态机。
- **无异步/流式**。`step()` 是阻塞的 env.step,一次 tool_call 几十秒期间没法取消。AutoGPT/LangGraph 都是异步执行;`robot_execute_plan` 已是串行执行器,可以进一步做"提交 action_id → 轮询"的异步模式(你的 `_execute_and_wait` 已经是半异步,但没暴露给 LLM 当两步)。
- **规划工具化**。你的 plan 是通过 LLM 调 `create_task_plan` 工具写出来的,模型自己当 planner。Semantic Kernel 的 StepwisePlanner / LangGraph 的 plan-and-execute 模式是把规划单独成一个 LLM 调用(先整出完整计划再逐步执行),减少逐步漂移;你的 run_task_cycle 已经接近,但仍是同一轮 prompt 里完成的。

**和 SayCan/RT 系的对应**(你是做机器人的,这条最相关)

| SayCan 概念 | 你的对应 |
|---|---|
| LLM 选高层技能 | LLM 选 `nav_go_to_place` / `vla_run_skill` |
| affordance 打分(技能可行度) | `FRIDGE_FRONT`/`TABLE` 可达范围检查 + `check_motion_against_latest_perception` |
| 低层策略执行 | `isaac_bridge` 脚本化技能(铰链插值 + 关节 PD) |
| 重评分再选 | `vision_verify` + `/world` 终检 |

你现在的差距不在"会不会选技能",在**技能本身是脚本化**的——开源 VLA(pi0.5、OpenVLA、RT-2)是神经网络 policy 直接输出关节/末端轨迹。你 `agent_mode.py` 那条线(MiniMax-VLA)已经在往这走了,Isaac 这条线目前是"LLM 调度 + 脚本技能",和 SayCan 完全同构。

---

## 3. 概念映射速查(以后看开源源码不会懵)

| 你的概念 | 通用叫法 |
|---|---|
| `Agent.run_turn` 循环 | agent loop / ReAct loop / ReWOO-style loop |
| `CAPABILITY_REGISTRY.select` | tool retrieval / tool routing |
| `CapabilitySpec` | tool descriptor / capability manifest |
| `DISPATCHER` | executor / tool runtime / action server |
| `ExecutionRequest/Event` | action/event log(LangSmith 叫 span) |
| `intent_parser` 的停启发式 | termination condition / guardrails |
| `approval_store` | human-in-the-loop / interrupt |
| `GoalRunner` | autonomous agent runner / task agent |
| `isaac_bridge` | runtime backend / embodiment interface / robot driver |
| `vision_verify` | affordance check / VLM critic / self-verification |
| `event_log` | trajectory / trace / telemetry |

---

## 4. 建议的学习路径

1. **读 ReAct 原文**(Yao et al., ICLR'23)——你的 loop 就是带安全网的 ReAct,5 页纸建立理论锚点。
2. **读 SayCan**(Ichnowski et al.)——把"LLM 选技能 × affordance 打分"看明白,你的可达性检查+VLM 核验就是它的简化实现,看完能自然过渡到给技能接神经 policy。
3. **拆 LangGraph 的 ToolNode + checkpointer**——重点看它怎么把"暂停/恢复/人工断点"做成可持久化状态,对照你纯内存的 messages;然后**试把 mobile-manip 循环用 LangGraph 重写出来**,这是最好的练习。
4. **看 MCP 协议**(modelcontextprotocol.io)——你的 contracts 层已经比 MCP 的 tool descriptor 丰富;把 `isaac_bridge` 的 `/navigate` `/vla` 包成 MCP server,立刻能用 Claude Desktop/Cline 当你的 LLM 前端,等于白嫖一套生态。
5. **补两件最值钱的基础设施**:
   - **上下文管理**:tool_result 截断/摘要(长 JSON 结果占 70% token),参考 LangChain summarization 中间件;
   - **语义工具检索**:关键词换成 embedding 检索(`select()` 一个方法替换),工具数上 50 必备。
6. **学 smolagents 的 CodeAct**——它让 LLM 直接写 Python 而不是选固定工具,对你"技能脚本化"的现状是个有趣的替代方向(脚本动作可以直接 code-gen 而不是手写插值)。

**一句话**:你的 agent 在"契约、安全、物理核验"上已经超过多数开源 demo;要补的是"状态持久化、上下文管理、语义路由"这三件 LangGraph 系早就工程化的事——而 SayCan 那条线你已经是同构实现,只差把脚本技能换成 learned policy。
