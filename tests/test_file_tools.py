from agent import permissions
from agent.toolkit.file_tools import write_file


def test_write_file_creates_new_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(permissions, "WORKSPACE_ROOT", tmp_path.resolve())

    result = write_file("notes/example.txt", "hello")

    assert "Wrote 5 characters" in result
    assert (tmp_path / "notes" / "example.txt").read_text(encoding="utf-8") == "hello"


def test_write_file_does_not_overwrite_existing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(permissions, "WORKSPACE_ROOT", tmp_path.resolve())
    file_path = tmp_path / "example.txt"
    file_path.write_text("original", encoding="utf-8")

    result = write_file("example.txt", "replacement")

    assert result == "File already exists: example.txt; use request_overwrite_file"
    assert file_path.read_text(encoding="utf-8") == "original"
