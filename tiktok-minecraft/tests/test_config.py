from pathlib import Path

import pytest
import yaml

from tiktok_mc.config import ConfigError, load_config, parse_config

SAMPLE = Path(__file__).resolve().parent.parent / "config.sample.yaml"


def sample_raw() -> dict:
    raw = yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))
    raw["tiktok"]["username"] = "@my_live"
    return raw


def test_sample_config_is_valid():
    config = parse_config(sample_raw())
    assert config.tiktok.username == "my_live"  # 先頭の@は外す
    assert config.minecraft.player == "Steve"
    assert config.gifts[0].gifts == ["Rose"]
    assert config.likes.every == 100
    assert config.join is None  # enabled: false は無効扱い
    assert config.timers[0].every_minutes == 10


def test_untouched_sample_asks_for_username(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ConfigError, match="username"):
        load_config(path)


def test_password_required():
    raw = sample_raw()
    raw["minecraft"]["password"] = ""
    with pytest.raises(ConfigError, match="password"):
        parse_config(raw)


def test_gift_rule_needs_gift_or_coins():
    raw = sample_raw()
    raw["gifts"] = [{"name": "なにか", "commands": ["say hi"]}]
    with pytest.raises(ConfigError, match="なにか"):
        parse_config(raw)


def test_leading_slash_is_removed():
    raw = sample_raw()
    raw["gifts"] = [{"gift": "Rose", "commands": ["/say hi"]}]
    assert parse_config(raw).gifts[0].commands == ["say hi"]


def test_broken_yaml_reports_line(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("tiktok:\n  username: [abc\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="行目"):
        load_config(path)


def test_number_validation():
    raw = sample_raw()
    raw["minecraft"]["commands_per_second"] = "はやい"
    with pytest.raises(ConfigError, match="commands_per_second"):
        parse_config(raw)
