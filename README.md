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
format. If your provider uses a different API, only change `agent/model_adapter.py`.

## Project shape

```text
agent/
  main.py             CLI entry
  agent_loop.py       model -> tool -> result loop
  model_adapter.py    compatibility entry for model adapters
  message_builder.py  internal content-part message helpers
  permissions.py      simple safety checks
  prompt.py           compatibility entry for system prompt
  prompts/            grouped prompt rules and builder
  tools.py            tool schemas and handlers
  models/             grouped model adapters and loader
  planning/           grouped plan storage, actions, execution, and diagnosis
  state/              grouped state stores, event log, and skill notes
  toolkit/            grouped tool modules and registry
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
create task plan task_123 :: read README.md; count python files; summarize results
task plan task_123
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
agent/robot/robot_protocol.py   Command, state, and result data structures
agent/robot/robot_safety.py     Motion limits and plan validation
agent/robot/robot_simulator.py  Default local simulator, no hardware needed
agent/robot/robot_adapter.py    Replaceable communication adapters
agent/robot/robot_tools.py      High-level tools exposed to the LLM
```

Default mode is simulated:

```powershell
python -m agent.web_server
```

Useful robot prompts:

```text
robot_get_status
Move forward 0.3 meters slowly
Turn left 45 degrees
Stop the robot
Capture a camera frame
Create a safe plan to move forward and inspect the area
```

To connect external hardware later, keep the same robot tools and switch the adapter:

```env
ROBOT_MODE=http
ROBOT_BASE_URL=http://127.0.0.1:9000
```

or:

```env
ROBOT_MODE=socket
ROBOT_HOST=127.0.0.1
ROBOT_PORT=9000
```

The robot backend expects adapters to accept high-level JSON commands such as:

```json
{"action":"move","params":{"distance":0.3,"direction":"forward","speed":0.2}}
```

Do not let the LLM directly control motors. Keep real hardware behind adapter and safety checks.
