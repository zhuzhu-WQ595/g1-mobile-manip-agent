def test_state_stores_use_temp_state_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    from agent.state import event_log, memory_store, task_store

    state_dir = tmp_path / ".agent_state"

    monkeypatch.setattr(memory_store, "STATE_DIR", state_dir)
    monkeypatch.setattr(memory_store, "MEMORY_FILE", state_dir / "memory.md")

    monkeypatch.setattr(task_store, "STATE_DIR", state_dir)
    monkeypatch.setattr(task_store, "TASKS_FILE", state_dir / "tasks.json")

    monkeypatch.setattr(event_log, "STATE_DIR", state_dir)
    monkeypatch.setattr(event_log, "HOOK_LOG", state_dir / "tool_events.jsonl")

    assert memory_store.load_memory() == ""

    memory_store.remember("hello memory")
    assert "hello memory" in memory_store.load_memory()

    created = task_store.create_task("demo task")
    assert "Created task_" in created
    assert "demo task" in task_store.list_tasks()

    event_log.record_tool_event({"tool": "demo", "status": "ok"})
    recent_events = event_log.read_recent_events()
    assert "Recent tool events:" in recent_events
    assert "| # | Time | Tool | Status | Arguments | Result |" in recent_events
    assert "| 1 |" in recent_events
    assert "`demo`" in recent_events
    assert "`{\"tool\": \"demo\"}`" not in recent_events
    assert "`{\"status\": \"ok\", \"tool\": \"demo\"}`" not in recent_events
    assert "`{}`" in recent_events

    recent_one = event_log.read_recent_events(limit=1)
    assert recent_one.count("| 1 |") == 1
    assert "`demo`" in recent_one


def test_planning_create_and_execute_count_step(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sample.py").write_text("print('hello')", encoding="utf-8")

    from agent.planning import store
    from agent.planning.actions import create_plan
    from agent.planning.executor import execute_plan_step

    state_dir = tmp_path / ".agent_state"
    monkeypatch.setattr(store, "STATE_DIR", state_dir)
    monkeypatch.setattr(store, "PLANS_FILE", state_dir / "plans.json")

    result = create_plan("demo plan", ["count python files"])
    plan_id = result.split(":", 1)[0]

    output = execute_plan_step(plan_id, 1)

    assert "Executed step 1" in output
    assert "Extension: .py" in output
    assert "Count: 1" in output
