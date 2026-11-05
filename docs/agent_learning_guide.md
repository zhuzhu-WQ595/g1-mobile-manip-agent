# 从 0 搭建一个 Agent：本项目的实际路径 + 学习清单

> 回答两个问题:①这个 agent 当初是怎么一步步搭起来的(`docs/target.md` 记录的就是当时的真实阶段)
> ②要自己做出来,需要掌握什么。

---

## 一、这个项目实际是怎么从 0 搭起来的

AI 帮你搭的过程不是"一次生成",而是**严格按增量阶段推进、每阶段先测后扩**。`target.md` 就是当时的施工日志,还原出来是这 7 步:

### 阶段 1:最小 loop 跑通(先有骨架)
先写最小的 `agent_loop.py`:messages 列表 → `model.complete()` → 有 tool_calls 就执行回填 → 直到返回 message。
同时配三件配套:`context.py`(system prompt)、`message_builder.py`(OpenAI 消息格式构造)、`models/`(model adapter,先用 DemoModel 假模型跑通,再接真模型)。
**验证:对话 + 读文件工具能动。**——此时整个 agent 约 200 行。

### 阶段 2:理解骨架,再扩展工具
`target.md` 第二部分整章是"梳理核心模块职责"——**先读懂,再动手**。之后加工具的固定四步:
```
写 schema → 写 handler → 注册进 TOOL_HANDLERS → 加权限放行
```
每个新工具单独测(阶段三~五):无参 → 带参 → 带参+规则校验。这是工具层开发的标准模板。

### 阶段 3:状态与记录(让 agent 有记忆)
`agent/state/` + `agent/toolkit/state_tools.py`:任务存储、事件日志 `record_tool_event`、记忆工具。
关键决定:状态不是塞在 messages 里骗 LLM,而是**独立存储 + 工具读写**——这样状态可持久化、可审计。

### 阶段 4:安全层(权限 + 审批)
`permissions.py`(调用前参数/目标校验)+ `state/approval_store.py`(高风险动作挂起等人工批)。
**顺序很重要:先让 agent 能用,再管它能干什么。**权限和审批是后加的护栏,不是一开始就设计死的。

### 阶段 5:计划执行(多步任务)
`planning/`:`create_plan → execute_plan_step → execute_next_plan_step → diagnose_blocked_step`。
把"做计划"也做成工具让 LLM 自己调,而不是单独一个 planner 模块——这是当时的选择,也是和 LangGraph 显式图最大的分歧点。

### 阶段 6:契约化重构(小代码 → 工程)
`# 模块化处理` 之后的大重构:把散落的 tools 拆成 `toolkit/` + `robot/` + `contracts/` + `capabilities/` + `scheduling/`。
每个工具补声明:domain/execution_target/risk_level → `CapabilityRegistry` 启动时强校验目录一致性。
再加 `ExecutionRequest/Event` 契约对象和 `Dispatcher`(选资源→busy→执行→健康上报)。
**这是从"demo"变"系统"的那一步**——也是你和其他开源 demo 拉开差距的地方。

### 阶段 7:接仿真/机器人(能力落地)
`robot_runtime/` 网关 + `scripts/isaac_bridge.py`(Isaac Sim 同进程 HTTP 桥)。
执行链:LLM 选 `nav_go_to_place` → `IsaacSimBackend` → HTTP → bridge → internutopia。
再接 VLM 核验、双机位录制——就是你昨晚跑的那条全链。

---

## 二、从施工过程能提炼的"开发 agent"方法论

1. **先骨架后血肉**:loop 先跑通(哪怕假模型),工具一个个加,每加一个测一个
2. **读懂再改**:第二阶段整整一章只做"梳理模块职责"——AI 写的不等于你懂,维护/调试时还是要你懂
3. **四步加工具模板**:schema → handler → 注册 → 放行(这个模板所有 agent 框架通用)
4. **状态独立存储**:别把任务状态塞进 prompt,独立存 + 工具读写
5. **护栏后装**:功能先跑通,权限/审批/熔断再一层层加
6. **契约化升级**:工具 >20 个就必须引入显式契约(target/risk/ownership),否则权限会失控
7. **真值核验**:机器人任务必须"执行后物理验证"(位移实测/VLM 判问/世界态终检),不能信回执

---

## 三、要独立做 agent,需要掌握的知识

按重要性分层,标注在哪能学、你当前项目里对应什么:

### 第一层:基础(没有这层后面全是空中楼阁)
| 知识 | 本项目对应 | 怎么学 |
|---|---|---|
| **LLM function calling** 协议(messages/roles/tool_calls/并行调用) | `message_builder.py` + `models/base.py` | 通读 OpenAI function calling 文档,把 `tool_calls` 字段结构手写出来 |
| **ReAct 循环** | `agent_loop.py` 全文 | 读 ReAct 原文(Yao'23);自己手写一个 50 行版(不用任何框架) |
| **Tool schema 设计** | `robot/tools.py` 的 `_schema()` + `ROBOT_TOOL_SCHEMAS` | 学 JSON Schema 子集(type/properties/required/enum);理解"描述写得清 LLM 才会选对" |
| **Prompt 工程(系统提示+工具摘要+结果回填)** | `context.py` + `prompt_summary()` | 观察每次 complete 的 messages 长什么样(打个 log 自己看) |

### 第二层:系统工程(做出能用的 agent)
| 知识 | 本项目对应 |
|---|---|
| **执行契约/结果对象**(ExecutionRequest/Event、ok/error/status 统一返回) | `contracts/execution.py` |
| **调度与资源管理**(选资源、busy、心跳、失败计数) | `scheduling/dispatcher.py` + `resources.py` |
| **权限与审批**(风险分级、参数校验、人工断点) | `permissions.py` + `approval_store.py` |
| **长任务管理**(step 上限、重复动作检测、错误熔断) | `agent_loop.py` 的启发式 + `runner.py` 的 repeat guard |
| **上下文管理**(messages 长度、tool_result 截断/摘要) | **你这里缺**——开源看 LangChain summarization middleware |

### 第三层:机器人/具身(你的垂直方向)
| 知识 | 本项目对应 |
|---|---|
| **skill abstraction**(LLM 选高层技能,底层策略执行) | `vla_run_skill` ↔ SayCan 模式 |
| **affordance / 可行性检查**(可达范围、前置条件) | `FRIDGE_FRONT` 检查 + `check_motion_against_latest_perception` |
| **物理核验**(执行后实测+VLM+真值) | `robot_move` 位移核对 + `vision_verify` + `/world` |
| **仿真接口层**(LLM 不直接碰 sim,走 HTTP 桥) | `isaac_bridge.py` + `robot_runtime/isaac_sim.py` |
| **VLA/学习策略**(脚本技能 → learned policy) | 你的 MiniMax-VLA 线;pi0.5/OpenVLA/RT-2 |

### 第四层:生态与对标(知道业内怎么做的)
- **LangGraph**:把 loop 画成图,checkpoint/interrupt——你最该学的工程化部分
- **MCP**:tool descriptor + JSON-RPC,把 `isaac_bridge` 包成 MCP server 就能接生态
- **Semantic Kernel / AutoGPT / smolagents**:分别对应"显式 planner"、"自主 runner"、"code-act"三种主流范式
- **SayCan / RT-2 / OpenVLA**:机器人 agent 的直系血统

---

## 四、给 AI 写代码时代的特别建议

你的情况特殊——代码全是 AI 写的。那学习的重心要换:**你不需要会"写出"这些代码,需要会"读懂+掌控"它们**。具体说:

- **每接一个 AI 写的模块,先让它画数据流**(哪进哪出、谁调谁、错误怎么传)——你第二阶段就是这么做的,保持
- **保留"先测后扩"的节奏**——target.md 每阶段都有验证截图,这比代码本身值钱
- **学会追问契约**:AI 写了一个工具,你要能问出"它的 target 是什么、risk 是什么、失败会返回什么"——这三个问题答不上来就是没懂
- **练读 debug**:OOM、bridge 连不上、tool_call 超时——这些事故才是你真正学会的时刻
- **把 AI 当 pair 不当黑盒**:每次让它改完,自己读 diff;读不懂就问它为什么这么改

---

## 五、最快见效的下一步(按收益排序)

1. **把 `isaac_bridge.py` 包成 MCP server**——你的 contracts 层已够用,纯封装工作量;学会后任何 MCP 客户端都能用你的 agent,瞬间接上生态
2. **补上下文管理**——给 `tool_result` 加截断/摘要逻辑,解决 max_steps≤20 的硬顶(代码改动小,收益立竿见影)
3. **把 `--mobile-manip` 循环用 LangGraph 重画一遍**(哪怕只在纸上画成图)——体会"启发式硬编 vs 显式状态机"的差距
4. **给 `select()` 换 embedding 语义检索**——关键词法上 50 个工具必崩,这一步是工业界标配
5. **写一个 50 行的最小 ReAct loop 从零跑通**——只用 model.complete + 一个 read_file 工具,不用任何框架;做完你对所有 agent 框架都"见过鬼"

最后一句话:你的这个 agent 在"契约、安全、物理核验"上已经比多数教程级代码强;你现在要补的不是"怎么写",而是**"为什么这么设计"**——把上一篇 `agent_vs_opensource.md` 的对比表当作检查清单逐项问自己,答得出来的就是你会的,答不上来的就是该学的。
