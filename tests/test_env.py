"""Tests for the minimal .env loader."""

from harness.env import load_env_file


def test_loads_simple_assignments(tmp_path, monkeypatch):
    monkeypatch.delenv("U3_TEST_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("U3_TEST_KEY=hello\n", encoding="utf-8")
    loaded = load_env_file(env)
    assert loaded["U3_TEST_KEY"] == "hello"
    import os

    assert os.environ["U3_TEST_KEY"] == "hello"


def test_skips_comments_and_blank_lines(tmp_path, monkeypatch):
    monkeypatch.delenv("U3_TEST_KEY2", raising=False)
    env = tmp_path / ".env"
    env.write_text("# comment\n\nU3_TEST_KEY2=v\n", encoding="utf-8")
    loaded = load_env_file(env)
    assert loaded == {"U3_TEST_KEY2": "v"}


def test_strips_quotes_and_export_prefix(tmp_path, monkeypatch):
    monkeypatch.delenv("U3_TEST_KEY3", raising=False)
    env = tmp_path / ".env"
    env.write_text('export U3_TEST_KEY3="quoted value"\n', encoding="utf-8")
    loaded = load_env_file(env)
    assert loaded["U3_TEST_KEY3"] == "quoted value"


def test_does_not_override_existing_env(tmp_path, monkeypatch):
    monkeypatch.setenv("U3_TEST_KEY4", "already-set")
    env = tmp_path / ".env"
    env.write_text("U3_TEST_KEY4=from-file\n", encoding="utf-8")
    loaded = load_env_file(env)
    import os

    assert os.environ["U3_TEST_KEY4"] == "already-set"
    assert "U3_TEST_KEY4" not in loaded


def test_missing_file_returns_empty(tmp_path):
    assert load_env_file(tmp_path / "nope.env") == {}
