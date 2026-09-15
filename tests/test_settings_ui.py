from pathlib import Path

from performance_ai.settings_ui import run_settings


def test_settings_zero_exits_without_saving(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    answers = iter(["0"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    run_settings(str(config_path))

    assert not config_path.exists()


def test_settings_save_and_exit(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    answers = iter(["9"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    run_settings(str(config_path))

    assert config_path.exists()
    assert '"advisor_mode"' in config_path.read_text(encoding="utf-8")


def test_settings_quit_alias_exits_without_saving(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    answers = iter(["quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    run_settings(str(config_path))

    assert not config_path.exists()
