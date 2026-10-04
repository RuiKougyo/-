from pathlib import Path

import yaml

from tiktok_mc import events as ev
from tiktok_mc import main as main_module
from tiktok_mc.main import parse_test_command

SAMPLE = Path(__file__).resolve().parent.parent / "config.sample.yaml"


def test_parse_gift_with_count_and_coins():
    event = parse_test_command("gift Finger Heart 3 5")
    assert (event.kind, event.gift_name, event.count, event.coins) == (ev.GIFT, "Finger Heart", 3, 5)


def test_parse_gift_defaults():
    event = parse_test_command("gift Rose")
    assert (event.gift_name, event.count, event.coins) == ("Rose", 1, 1)


def test_parse_other_commands():
    assert parse_test_command("like 250").count == 250
    assert parse_test_command("comment ジャンプ して").comment == "ジャンプ して"
    assert parse_test_command("follow").kind == ev.FOLLOW
    assert parse_test_command("sub").kind == ev.SUBSCRIBE
    assert parse_test_command("quit") == "quit"
    assert parse_test_command("なにこれ") is None


def test_dry_run_test_mode_end_to_end(tmp_path, monkeypatch, caplog):
    """設定サンプルを使い、テストモード＋送信のふりで、入力→コマンド送信まで通す。"""
    raw = yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))
    raw["tiktok"]["username"] = "me"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    lines = iter(["gift Rose 2", "follow", "gift Lion 1 29999", "quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    monkeypatch.setattr(main_module, "base_dir", lambda: tmp_path)
    sent: list[str] = []

    async def fake_command(self, text):
        sent.append(text)
        return ""

    monkeypatch.setattr(main_module.DryRunSender, "command", fake_command)
    assert main_module.main(["--config", str(config_path), "--test", "--dry-run"]) == 0
    assert sent.count("execute at Steve run summon zombie ~ ~ ~3 {Tags:[\"tiktok\"]}") == 2
    assert any("フォローしてくれました" in s for s in sent)
    assert "execute at Steve run summon ravager ~6 ~ ~ {Tags:[\"tiktok\"]}" in sent
    assert (tmp_path / "logs" / "live.log").exists()
