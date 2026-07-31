# self-test agent

A minimal local agent scaffold for learning agent architecture.

It starts with text input and tool use, but the internal message format uses
content parts so image/audio/file parts can be added later without rewriting the
main loop.

## Run

```powershell
cd C:\Users\86186\Desktop\claude\self-test
python -m agent.main
```

Default mode uses a local demo model, so it runs without an API key. Try:

```text
list files
read README.md
write notes/new-note.txt :: hello from my agent
python version
q
```

## Configure a model

Put the common model settings in `.env`:

```env
API_KEY=your_api_key
MODEL_ID=deepseek-v4-flash
BASE_URL=https://api.deepseek.com
```

For the current adapter, `BASE_URL` must be an OpenAI-compatible chat-completions
endpoint root. For DeepSeek, use `https://api.deepseek.com`, not the `/anthropic`
compatibility endpoint.

The program still accepts older provider-specific names such as
`DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, `AGENT_MODEL`, and `ANTHROPIC_BASE_URL`,
but `API_KEY`, `MODEL_ID`, and `BASE_URL` take priority.

## Use another OpenAI-compatible chat-completions model

Set environment variables before running:

```powershell
$env:AGENT_PROVIDER = "openai_compatible"
$env:AGENT_API_KEY = "your_api_key"
$env:AGENT_MODEL = "your_model_name"
$env:AGENT_BASE_URL = "https://api.openai.com/v1"
python -m agent.main
```

The agent uses `/chat/completions` style tool calls. Many providers expose this
format. If your provider uses a different API, add or update an adapter in
`agent/models/`.

## Evaluate real-model decisions

After configuring a real model, run the built-in read-only decision evaluation:

```powershell
python -m evaluations.runner
```

It checks natural-language tool selection, arguments, execution, and final
completion. JSON reports are written under `.agent_state/evaluations/`. See
`docs/goal_driven_execution.md` for case IDs and result interpretation.

## Run a feedback-driven goal

Use goal mode when the model should choose one action at a time from live tool
feedback instead of following a saved plan:

```powershell
python -m agent.execution.cli "Verify that this project has model, tool, and permission layers"
```

From the interactive CLI, prefix the natural-language goal with `/goal `. Goal
traces are written under `.agent_state/goal_runs/`. See
`docs/goal_driven_execution.md` for behavior and safety limits.

For a robot goal, use the separate feedback-gated mode:

```text
/robot-goal Move forward 0.2 meters and confirm completion from robot feedback
```

This mode exposes only high-level robot tools. A model answer is not marked
complete until structured gateway feedback reaches a supported terminal state
and a separate no-tool semantic critic confirms that the observed result matches
the original goal. A rejected answer is fed back to the executor for correction.
The critic currently reuses the configured model backend, so each completion
attempt adds one model request.
The standalone equivalent is:

```powershell
python -m agent.execution.cli "Move forward 0.2 meters and confirm completion" --robot
```

Evaluate how a real model reacts to empty results, temporary tool errors,
permission denial, and ambiguous goals:

```powershell
python -m evaluations.runner --suite fault
```

The evaluator injects one controlled result before a real read-only tool runs;
it does not modify workspace files or permission rules. Evaluation reports and
scenario details are documented in `docs/goal_driven_execution.md`.

## Project shape

```text
agent/
  main.py             CLI entry
  agent_loop.py       model -> tool -> result loop
  capabilities/       normalized capability catalog and goal-based selection
  execution/          feedback-driven execution, verification, and reports
  routing/            deterministic intent parsing and explicit constraints
  scheduling/         execution-target validation and dispatch
  robot/              Agent-side robot clients and LLM tools
  message_builder.py  internal content-part message helpers
  permissions.py      simple safety checks
  prompts/            grouped prompt rules and builder
  models/             grouped model adapters and loader
  planning/           grouped plan storage, actions, execution, and diagnosis
  state/              grouped state stores, event log, and skill notes
  toolkit/            grouped tool modules and registry
contracts/            stable cross-process data contracts
robot_runtime/        robot-side gateway, simulator, and safety enforcement
services/             remote service registry and local HTTP boundary demo
evaluations/          development decision and fault-recovery evaluation
```

Each registered tool is represented by a capability with a domain, execution
target, risk level, input schema, and tool binding. For recognizable goals, the
Agent sends only matching capabilities to the model. Ambiguous goals fall back
to the complete catalog, and tool calls outside the selected set are rejected.

Every tool invocation also produces a contract-backed execution event from
`contracts/execution.py`. Events use one lifecycle vocabulary across local
tools, goal runs, and robot actions:

```text
created -> accepted -> running -> waiting_feedback
        -> succeeded | failed | cancelled | timed_out
```

The trace keeps `tool` and `arguments` for debugging while adding
`execution_id`, `capability`, `execution_target`, the selected `resource_id`,
structured `error`, optional `observation`, and the normalized status.

`agent/scheduling/dispatcher.py` is the single runtime execution entry point.
It validates the capability-to-target binding, runs permission checks, and
routes requests to `local_toolkit`, `agent_state`, `robot_gateway`, or
`remote_service`. The Agent
loop and GoalRunner no longer call `TOOL_HANDLERS` directly. A future external
service can reuse the same `ExecutionRequest` and `ExecutionEvent` contract.

Concrete execution resources are registered separately from capabilities.
`agent/scheduling/selector.py` automatically filters resources by capability,
target, and runtime status, then prefers an available resource with lower load
and higher priority. Callers normally omit `resource_id`; an explicit resource
is supported only for administration and deterministic tests. Resource-specific
handlers allow two robots or services offering the same capability to use
different adapters without changing the Agent loop.

## Verify the remote service boundary

Start the local development service in one PowerShell terminal:

```powershell
cd C:\Users\86186\Desktop\claude\self-test
python -m services.demo_server --port 9020
```

In a second PowerShell terminal, configure the symbolic service whitelist and
start the Agent:

```powershell
cd C:\Users\86186\Desktop\claude\self-test
$env:REMOTE_SERVICES='{"demo":"http://127.0.0.1:9020"}'
python -m agent.main
```

Then enter:

```text
call service demo operation inspect
call service demo operation echo :: {"message":"hello"}
```

The model supplies only `demo`, an operation, and a JSON payload. Endpoint URLs
come from `REMOTE_SERVICES`; unconfigured names and direct URLs are rejected.
`services.demo_server` is a communication test process, not a hardware driver.

## Verify perception-driven motion gating

Start the independent perception service with one controlled scene:

```powershell
cd C:\Users\86186\Desktop\claude\self-test
python -m services.perception --port 9030 --scene blocked
```

Available scenes are `clear`, `blocked`, and `failure`. In another PowerShell
terminal, configure the service and start the Agent:

```powershell
cd C:\Users\86186\Desktop\claude\self-test
$env:REMOTE_SERVICES='{"perception":"http://127.0.0.1:9030"}'
$env:ROBOT_MODE='simulated'
python -m agent.main
```

The deterministic demo model can verify one perception call:

```text
check path forward 0.2
```

The deterministic demo model can also verify the complete decision loop:

```text
/robot-goal Check the path and move forward 0.2 meters only if it is clear.
```

The standalone equivalent is:

```powershell
python -B -m agent.execution.cli "Check the path and move forward 0.2 meters only if it is clear." --robot --allow-demo
```

With `scene=blocked`, the expected trace contains only
`perception_check_path`; withholding motion is accepted as the correct result.
With `scene=clear`, the trace contains `perception_check_path` followed by
`robot_move`. A configured real model uses the same tools and policy with an
additional semantic Critic check.

`perception_check_path` returns a structured `Observation`. If the latest
perception failed, omitted structured evidence, or returned `path_clear=false`,
Agent-side policy rejects `robot_move` before its Handler is called. The
simulated service validates feedback flow only; it does not perform real vision.

Robot runtime processes use their canonical entry point:

```powershell
python -m robot_runtime.gateway_server
```

## First extension points

1. Add a new tool in the matching `agent/toolkit/*_tools.py` module.
2. Add permission rules in `agent/permissions.py`.
3. Swap or customize the model in `agent/models/`.
4. Extend plan behavior in `agent/planning/`.
5. Extend state behavior in `agent/state/`.
6. Extend prompt rules in `agent/prompts/`.
7. Add image/audio/file input parts in `agent/message_builder.py`.
## Run the web UI

```powershell
cd C:\Users\86186\Desktop\claude\self-test
python -m agent.web_server
```

Then open:

```text
http://127.0.0.1:8765
```
## Backend capabilities

The agent now has these backend modules:

```text
agent/context.py                  Dynamic system prompt assembly
agent/state/memory_store.py       Long-term markdown memory in .agent_state/memory.md
agent/state/event_log.py          Tool event logging in .agent_state/tool_events.jsonl
agent/state/task_store.py         Local task list in .agent_state/tasks.json
agent/state/approval_store.py     Human approval state in .agent_state/approvals.json
agent/state/skill_store.py        Small built-in skill notes
```

Useful tool prompts:

```text
remember this project prefers small focused edits
memory
create task add edit_file tests
tasks
start task_123
complete task_123 :: all tests passed
fail task_123 :: tests failed
retry task_123
cancel task_123 :: no longer needed
task task_123
start current task
complete latest task :: all tests passed
开始当前任务
完成最新任务 :: 全部通过
create task plan task_123 :: read README.md; count python files; summarize results
create task plan current task :: search README; preview first 10 lines of README.md; run pytest; summarize results
create task plan current task :: tool list_files {"path": "agent"}; tool search_files {"path": "agent", "query": "executor"}; summarize results
task plan task_123
validate task plan task_123
run task inspect project :: workspace summary; list files in agent; read README.md; summarize results
运行任务 检查项目结构 :: workspace summary; list files in agent; read README.md; summarize results
帮我完整检查一下当前项目结构，并总结结果
为当前任务创建计划 :: read README.md; count python files; summarize results
查看当前任务计划
验证当前任务计划
skills
search README
append notes/example.txt :: hello
edit notes/example.txt :: hello => hello world
approve approval_001
cancel approval_001
approval history
approval approval_001
```

The `.agent_state/` folder is local runtime state and is ignored by git.
## Robot Control Architecture

Robot control is split into stable layers:

```text
contracts/robot.py              Command, state, and result data structures
agent/robot/client.py           HTTP/Socket gateway clients
agent/robot/tools.py            High-level tools exposed to the LLM
robot_runtime/adapter.py        Stable simulator/hardware adapter boundary
robot_runtime/safety.py         Robot-side motion safety enforcement
robot_runtime/simulator.py      Default simulator, no hardware needed
robot_runtime/gateway_server.py Independent asynchronous HTTP robot gateway
```

The architecture references and staged path to real hardware are documented in
[`docs/robot_agent_development_roadmap.md`](docs/robot_agent_development_roadmap.md).

Default mode is simulated:

```powershell
python -m agent.web_server
```

To verify the real process and HTTP boundary, start the independent simulated
gateway in one PowerShell terminal:

```powershell
python -m robot_runtime.gateway_server
```

The gateway selects its lower runtime through `ROBOT_RUNTIME_ADAPTER`. The
current implementation is `simulated`; a future Gazebo, ROS 2, or vendor SDK
adapter implements the same `RobotRuntimeAdapter` protocol without changing the
Agent, HTTP contract, lifecycle handling, or safety gateway:

```powershell
$env:ROBOT_RUNTIME_ADAPTER = "simulated"
python -m robot_runtime.gateway_server
```

Robot poses use meters. Heading is zero on the +x axis and increases
counterclockwise, matching the common ROS planar convention.
Long-running motion is started inside `execute_motion`; the adapter reports
normalized progress, observes cancellation and timeout, and returns a terminal
`RobotResult`. The gateway remains responsible for authorization, resource
locking, watchdog handling, and HTTP lifecycle state.

In a second PowerShell terminal, connect the Agent through HTTP:

```powershell
$env:ROBOT_MODE = "http"
$env:ROBOT_BASE_URL = "http://127.0.0.1:9000"
$env:ROBOT_ALLOW_MOTION = "1"
python -m agent.main
```

Use `/robot-goal ...` to exercise asynchronous `pending`/`running`/terminal
feedback. The gateway supports cancellation, action timeouts, an inactivity
watchdog, emergency stop, and duplicate `action_id` protection. It binds to
loopback only and is a simulation boundary, not a production hardware gateway.

Useful robot prompts:

```text
robot_get_status
Move forward 0.3 meters slowly
Turn left 45 degrees
Stop the robot
Emergency stop the robot
Check action action_xxx
Cancel action action_xxx
Capture a camera frame
Create a safe plan to move forward and inspect the area
```

To connect external hardware later, keep the same robot tools and switch the adapter:

```env
ROBOT_MODE=http
ROBOT_BASE_URL=http://127.0.0.1:9000
ROBOT_ALLOW_MOTION=1
```

or:

```env
ROBOT_MODE=socket
ROBOT_HOST=127.0.0.1
ROBOT_PORT=9000
ROBOT_ALLOW_MOTION=1
```

`ROBOT_ALLOW_MOTION` is only an Agent-side enable switch. A real gateway must
still authenticate requests and enforce its own safety policy.

The canonical HTTP gateway contract is:

```text
POST /robot/actions                     submit a high-level action
GET  /robot/actions/{action_id}         query status and feedback
POST /robot/actions/{action_id}/cancel  request cancellation
POST /robot/emergency-stop              latch emergency stop
GET  /robot/state                       read current observation
```

An action request uses a bounded, high-level schema:

```json
{
  "action_id": "action_...",
  "action": "move",
  "params": {"distance": 0.3, "direction": "forward", "speed": 0.2},
  "timeout_s": 30.0
}
```

The LLM-facing tool registry does not expose direct wheel-speed control. Keep
real hardware credentials, motor control, watchdogs, and physical emergency
stops inside the independent gateway and robot controller.
