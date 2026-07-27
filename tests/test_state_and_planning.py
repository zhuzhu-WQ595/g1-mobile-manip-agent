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


def _configure_approval_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    from agent import permissions
    from agent.state import approval_store

    state_dir = tmp_path / ".agent_state"
    monkeypatch.setattr(permissions, "WORKSPACE_ROOT", tmp_path.resolve())
    monkeypatch.setattr(approval_store, "STATE_DIR", state_dir)
    monkeypatch.setattr(approval_store, "APPROVALS_FILE", state_dir / "approvals.json")
    return approval_store


def test_edit_requires_approval_and_returns_diff(tmp_path, monkeypatch):
    approval_store = _configure_approval_store(tmp_path, monkeypatch)
    file_path = tmp_path / "notes" / "example.txt"
    file_path.parent.mkdir()
    file_path.write_text("alpha\nhello\nomega\n", encoding="utf-8")

    request = approval_store.request_edit_file("notes/example.txt", "hello", "hello world")

    assert file_path.read_text(encoding="utf-8") == "alpha\nhello\nomega\n"
    assert "Approval ID: approval_001" in request
    assert "--- a/notes/example.txt" in request
    assert "-hello" in request
    assert "+hello world" in request
    assert "approval_001: edit_file" in approval_store.list_pending_approvals()

    result = approval_store.approve_pending_action("approval_001")

    assert result.startswith("Approved approval_001; edited ")
    assert file_path.read_text(encoding="utf-8") == "alpha\nhello world\nomega\n"
    assert approval_store.list_pending_approvals() == "(no pending approvals)"


def test_edit_approval_rejects_ambiguous_match(tmp_path, monkeypatch):
    approval_store = _configure_approval_store(tmp_path, monkeypatch)
    file_path = tmp_path / "example.txt"
    file_path.write_text("hello hello", encoding="utf-8")

    result = approval_store.request_edit_file("example.txt", "hello", "hi")

    assert result == "Found 2 matches; refine old_text before requesting approval"
    assert file_path.read_text(encoding="utf-8") == "hello hello"
    assert approval_store.list_pending_approvals() == "(no pending approvals)"


def test_edit_approval_is_cancelled_when_file_changes(tmp_path, monkeypatch):
    approval_store = _configure_approval_store(tmp_path, monkeypatch)
    file_path = tmp_path / "example.txt"
    file_path.write_text("hello", encoding="utf-8")
    approval_store.request_edit_file("example.txt", "hello", "hi")
    file_path.write_text("changed elsewhere", encoding="utf-8")

    result = approval_store.approve_pending_action("approval_001")

    assert result == "Cancelled approval_001; file changed after approval was requested"
    assert file_path.read_text(encoding="utf-8") == "changed elsewhere"
    assert approval_store.list_pending_approvals() == "(no pending approvals)"
