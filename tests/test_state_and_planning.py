import pytest


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


def test_task_lifecycle_transitions_and_details(tmp_path, monkeypatch):
    from agent.state import task_store

    state_dir = tmp_path / ".agent_state"
    monkeypatch.setattr(task_store, "STATE_DIR", state_dir)
    monkeypatch.setattr(task_store, "TASKS_FILE", state_dir / "tasks.json")

    created = task_store.create_task("verify structure", "run focused checks")
    task_id = created.split(":", 1)[0].removeprefix("Created ")

    assert "Status: pending" in task_store.get_task_details(task_id)
    assert task_store.complete_task(task_id, "too early") == f"Cannot move {task_id} from pending to done"

    assert "from pending to in_progress" in task_store.start_task(task_id)
    assert "from in_progress to failed" in task_store.fail_task(task_id, "tests failed")
    assert "Error: tests failed" in task_store.get_task_details(task_id)

    assert "from failed to in_progress" in task_store.retry_task(task_id)
    retried_details = task_store.get_task_details(task_id)
    assert "Last error: tests failed" in retried_details
    assert "Error: tests failed" not in retried_details

    assert "from in_progress to done" in task_store.complete_task(task_id, "20 tests passed")
    completed_details = task_store.get_task_details(task_id)
    assert "Status: done" in completed_details
    assert "Result: 20 tests passed" in completed_details
    assert task_store.retry_task(task_id) == f"Cannot move {task_id} from done to in_progress"

    cancelled_id = task_store.create_task("obsolete task").split(":", 1)[0].removeprefix("Created ")
    assert "from pending to cancelled" in task_store.cancel_task(cancelled_id, "not needed")
    assert "Cancel reason: not needed" in task_store.get_task_details(cancelled_id)
    assert "[cancelled] obsolete task" in task_store.list_tasks()


def test_task_aliases_resolve_to_active_recent_task(tmp_path, monkeypatch):
    from agent.state import task_store

    state_dir = tmp_path / ".agent_state"
    monkeypatch.setattr(task_store, "STATE_DIR", state_dir)
    monkeypatch.setattr(task_store, "TASKS_FILE", state_dir / "tasks.json")

    first_id = task_store.create_task("first task").split(":", 1)[0].removeprefix("Created ")
    second_id = task_store.create_task("second task").split(":", 1)[0].removeprefix("Created ")

    assert task_store.resolve_task_ref("latest task") == second_id
    assert task_store.resolve_task_ref("当前任务") == second_id
    assert "from pending to in_progress" in task_store.start_task("current task")
    assert "Status: in_progress" in task_store.get_task_details("最新任务")
    assert "from in_progress to done" in task_store.complete_task("刚才那个任务", "done by alias")

    assert task_store.resolve_task_ref("current task") == first_id
    assert "Status: pending" in task_store.get_task_details(first_id)


def test_task_lifecycle_rejects_invalid_input(tmp_path, monkeypatch):
    from agent.state import task_store

    state_dir = tmp_path / ".agent_state"
    monkeypatch.setattr(task_store, "STATE_DIR", state_dir)
    monkeypatch.setattr(task_store, "TASKS_FILE", state_dir / "tasks.json")

    assert task_store.create_task("   ") == "Task title cannot be empty"
    assert task_store.get_task_details("task_404") == "Task not found: task_404"

    task_id = task_store.create_task("failure check").split(":", 1)[0].removeprefix("Created ")
    task_store.start_task(task_id)
    assert task_store.fail_task(task_id, "   ") == "Task failure reason cannot be empty"
    assert task_store.update_task(task_id, "failed") == "Task failure reason cannot be empty"


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


def test_task_plan_link_executes_in_order_without_auto_completing_task(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("linked plan readme", encoding="utf-8")
    (tmp_path / "sample.py").write_text("print('hello')", encoding="utf-8")

    from agent import permissions
    from agent.planning import store
    from agent.planning.actions import create_task_plan, get_task_plan, validate_task_plan
    from agent.planning.executor import execute_next_plan_step, execute_plan_step
    from agent.state import task_store

    state_dir = tmp_path / ".agent_state"
    monkeypatch.setattr(permissions, "WORKSPACE_ROOT", tmp_path.resolve())
    monkeypatch.setattr(store, "STATE_DIR", state_dir)
    monkeypatch.setattr(store, "PLANS_FILE", state_dir / "plans.json")
    monkeypatch.setattr(task_store, "STATE_DIR", state_dir)
    monkeypatch.setattr(task_store, "TASKS_FILE", state_dir / "tasks.json")

    task_id = task_store.create_task("verify linked plan").split(":", 1)[0].removeprefix("Created ")
    created = create_task_plan(task_id, ["read README.md", "count python files", "summarize results"])
    plan_id = created.split(":", 1)[0]

    assert f"linked task: {task_id}" in created
    assert "executor: tool=read_file" in created
    assert "Automatic steps: 3/3" in validate_task_plan(task_id)
    assert f"Plan ID: {plan_id}" in task_store.get_task_details(task_id)
    assert create_task_plan(task_id, ["another step"]) == f"Task {task_id} is already linked to {plan_id}"
    assert execute_next_plan_step(plan_id) == (
        f"Linked task {task_id} is pending; start or retry it before executing plan steps"
    )

    task_store.start_task(task_id)
    assert execute_plan_step(plan_id, 2) == "Cannot execute step 2 before step 1 is done"

    first = execute_next_plan_step(plan_id)
    assert "Executed step 1" in first
    assert "linked plan readme" in first
    assert "Progress: 1/3 done" in get_task_plan(task_id)

    second = execute_next_plan_step(plan_id)
    assert "Executed step 2" in second
    assert "Count: 1" in second

    third = execute_next_plan_step(plan_id)
    assert "Executed step 3" in third
    assert f"Complete linked task {task_id} explicitly" in third
    assert "Status: in_progress" in task_store.get_task_details(task_id)

    task_store.complete_task(task_id, "plan verified")
    assert "Status: done" in task_store.get_task_details(task_id)
    assert "Progress: 3/3 done" in get_task_plan(task_id)


def test_task_plan_validation_marks_unknown_steps_manual(tmp_path, monkeypatch):
    from agent.planning import store
    from agent.planning.actions import create_task_plan, validate_task_plan
    from agent.planning.executor import execute_next_plan_step
    from agent.state import task_store

    state_dir = tmp_path / ".agent_state"
    monkeypatch.setattr(store, "STATE_DIR", state_dir)
    monkeypatch.setattr(store, "PLANS_FILE", state_dir / "plans.json")
    monkeypatch.setattr(task_store, "STATE_DIR", state_dir)
    monkeypatch.setattr(task_store, "TASKS_FILE", state_dir / "tasks.json")

    task_id = task_store.create_task("manual plan").split(":", 1)[0].removeprefix("Created ")
    created = create_task_plan(task_id, ["contact the project owner"])
    plan_id = created.split(":", 1)[0]
    validation = validate_task_plan(task_id)

    assert "Automatic steps: 0/1" in validation
    assert "manual=No supported automatic tool mapping" in validation
    task_store.start_task(task_id)
    blocked = execute_next_plan_step(plan_id)
    assert "not supported for automatic execution" in blocked
    assert "Progress: 0/1 done, 1 blocked" in blocked


def test_chinese_plan_steps_map_to_supported_executors():
    from agent.planning.step_mapping import map_plan_step

    assert map_plan_step("读取 README.md") == {
        "mode": "tool",
        "tool": "read_file",
        "arguments": {"path": "README.md"},
    }
    assert map_plan_step("统计 Python 文件") == {
        "mode": "tool",
        "tool": "count_files_by_extension",
        "arguments": {"extension": ".py"},
    }
    assert map_plan_step("总结结果") == {"mode": "summary"}


def test_task_plan_executes_search_preview_and_pytest_steps(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("alpha\nneedle\nomega\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    from agent import permissions
    from agent.planning import store
    from agent.planning.actions import create_task_plan, validate_task_plan
    from agent.planning.executor import execute_next_plan_step
    from agent.state import task_store

    state_dir = tmp_path / ".agent_state"
    monkeypatch.setattr(permissions, "WORKSPACE_ROOT", tmp_path.resolve())
    monkeypatch.setattr(store, "STATE_DIR", state_dir)
    monkeypatch.setattr(store, "PLANS_FILE", state_dir / "plans.json")
    monkeypatch.setattr(task_store, "STATE_DIR", state_dir)
    monkeypatch.setattr(task_store, "TASKS_FILE", state_dir / "tasks.json")

    task_id = task_store.create_task("execute richer plan").split(":", 1)[0].removeprefix("Created ")
    created = create_task_plan(
        task_id,
        [
            "search needle",
            "preview first 2 lines of README.md",
            "run pytest",
            "summarize results",
        ],
    )
    plan_id = created.split(":", 1)[0]

    validation = validate_task_plan(task_id)
    assert "Automatic steps: 4/4" in validation
    assert "tool=search_files" in validation
    assert "tool=preview_file_head" in validation
    assert "tool=run_command" in validation

    task_store.start_task(task_id)
    search = execute_next_plan_step(plan_id)
    preview = execute_next_plan_step(plan_id)
    pytest_result = execute_next_plan_step(plan_id)
    summary = execute_next_plan_step(plan_id)

    assert "text: README.md:2: needle" in search
    assert "1: alpha" in preview
    assert "2: needle" in preview
    assert "exit_code=0" in pytest_result
    assert "1 passed" in pytest_result
    assert "Summary from previous completed steps:" in summary
    assert "Progress: 4/4 done, 0 blocked" in summary


def test_plan_steps_map_to_search_preview_and_pytest():
    from agent.planning.step_mapping import map_plan_step

    assert map_plan_step("list files in agent") == {
        "mode": "tool",
        "tool": "list_files",
        "arguments": {"path": "agent"},
    }
    assert map_plan_step("search README") == {
        "mode": "tool",
        "tool": "search_files",
        "arguments": {"path": ".", "query": "README"},
    }
    assert map_plan_step("search agent for TODO") == {
        "mode": "tool",
        "tool": "search_files",
        "arguments": {"path": "agent", "query": "TODO"},
    }
    assert map_plan_step("preview first 10 lines of README.md") == {
        "mode": "tool",
        "tool": "preview_file_head",
        "arguments": {"lines": 10, "path": "README.md"},
    }
    assert map_plan_step("run pytest") == {
        "mode": "tool",
        "tool": "run_command",
        "arguments": {"command": "python -m pytest -q"},
    }
    assert map_plan_step('tool search_files {"path": "agent", "query": "executor"}') == {
        "mode": "tool",
        "tool": "search_files",
        "arguments": {"path": "agent", "query": "executor"},
    }
    assert map_plan_step('tool unknown_tool {"x": 1}') == {
        "mode": "manual",
        "reason": "Tool is not enabled for plan execution: unknown_tool",
    }


def test_task_plan_executes_explicit_tool_steps_and_safe_edit_request(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("alpha\nneedle\nomega\n", encoding="utf-8")

    from agent import permissions
    from agent.planning import store
    from agent.planning.actions import create_task_plan, validate_task_plan
    from agent.planning.executor import execute_next_plan_step
    from agent.state import approval_store, task_store

    state_dir = tmp_path / ".agent_state"
    monkeypatch.setattr(permissions, "WORKSPACE_ROOT", tmp_path.resolve())
    monkeypatch.setattr(store, "STATE_DIR", state_dir)
    monkeypatch.setattr(store, "PLANS_FILE", state_dir / "plans.json")
    monkeypatch.setattr(task_store, "STATE_DIR", state_dir)
    monkeypatch.setattr(task_store, "TASKS_FILE", state_dir / "tasks.json")
    monkeypatch.setattr(approval_store, "STATE_DIR", state_dir)
    monkeypatch.setattr(approval_store, "APPROVALS_FILE", state_dir / "approvals.json")

    task_id = task_store.create_task("generic tool plan").split(":", 1)[0].removeprefix("Created ")
    created = create_task_plan(
        task_id,
        [
            'tool list_files {"path": "."}',
            'tool search_files {"path": ".", "query": "needle"}',
            'tool request_edit_file {"path": "README.md", "old_text": "needle", "new_text": "changed"}',
        ],
    )
    plan_id = created.split(":", 1)[0]

    validation = validate_task_plan(task_id)
    assert "Automatic steps: 3/3" in validation
    assert "tool=list_files" in validation
    assert "tool=request_edit_file" in validation

    task_store.start_task(task_id)
    listed = execute_next_plan_step(plan_id)
    searched = execute_next_plan_step(plan_id)
    edit_request = execute_next_plan_step(plan_id)

    assert "file  README.md" in listed
    assert "text: README.md:2: needle" in searched
    assert "Approval required before editing a file." in edit_request
    assert "Approval ID: approval_001" in edit_request
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "alpha\nneedle\nomega\n"


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
    assert "Or: cancel approval_001" in request
    assert "--- a/notes/example.txt" in request
    assert "-hello" in request
    assert "+hello world" in request
    assert "approval_001: edit_file" in approval_store.list_pending_approvals()

    result = approval_store.approve_pending_action("approval_001")

    assert result.startswith("Approved approval_001; edited ")
    assert file_path.read_text(encoding="utf-8") == "alpha\nhello world\nomega\n"
    assert approval_store.list_pending_approvals() == "(no pending approvals)"
    assert approval_store._load_approvals()["approval_001"]["status"] == "approved"


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
    assert approval_store._load_approvals()["approval_001"]["status"] == "cancelled"


def test_pending_approval_can_be_cancelled_without_reusing_id(tmp_path, monkeypatch):
    approval_store = _configure_approval_store(tmp_path, monkeypatch)

    first_request = approval_store.request_overwrite_file("cancelled.txt", "blocked")
    assert "Approval ID: approval_001" in first_request

    result = approval_store.cancel_pending_action("approval_001")

    assert result == "Cancelled approval_001; overwrite_file for cancelled.txt was not executed"
    assert not (tmp_path / "cancelled.txt").exists()
    assert approval_store.list_pending_approvals() == "(no pending approvals)"
    assert approval_store.approve_pending_action("approval_001") == "Approval approval_001 is already cancelled"

    second_request = approval_store.request_overwrite_file("next.txt", "next")
    assert "Approval ID: approval_002" in second_request
    approvals = approval_store._load_approvals()
    assert approvals["approval_001"]["status"] == "cancelled"
    assert approvals["approval_002"]["status"] == "pending"


def test_approval_history_and_details_are_read_only(tmp_path, monkeypatch):
    approval_store = _configure_approval_store(tmp_path, monkeypatch)
    file_path = tmp_path / "example.txt"
    file_path.write_text("hello", encoding="utf-8")

    approval_store.request_edit_file("example.txt", "hello", "hello world")
    approval_store.approve_pending_action("approval_001")
    approval_store.request_overwrite_file("next.txt", "next")
    approval_store.cancel_pending_action("approval_002")

    recent = approval_store.list_approval_history(limit=1)
    assert "Approval history:" in recent
    assert "approval_002" in recent
    assert "cancelled" in recent
    assert "approval_001" not in recent

    history = approval_store.list_approval_history(limit=10)
    assert history.index("approval_002") < history.index("approval_001")
    assert "approved" in history

    details = approval_store.get_approval_details("approval_001")
    assert "Status: approved" in details
    assert "Action: edit_file" in details
    assert "--- a/example.txt" in details
    assert "-hello" in details
    assert "+hello world" in details
    assert approval_store.get_approval_details("approval_999") == "Approval not found: approval_999"

    with pytest.raises(ValueError, match="between 1 and 100"):
        approval_store.list_approval_history(limit=0)
    with pytest.raises(ValueError, match="integer between 1 and 100"):
        approval_store.list_approval_history(limit="many")

    approvals = approval_store._load_approvals()
    assert approvals["approval_001"]["status"] == "approved"
    assert approvals["approval_002"]["status"] == "cancelled"
