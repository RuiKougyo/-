from pathlib import Path

import pytest
import yaml

from ec_monitor.config_loader import load_config, minimum_interval_minutes, parse_config
from ec_monitor.errors import ConfigError
from helpers import make_config, valid_raw_config

ROOT = Path(__file__).resolve().parent.parent


def test_正しい設定を読み込める():
    config = make_config()
    assert config.rakuten.access_key == "pk_testkey"
    watch = config.watches[0]
    assert watch.sites == ["rakuten"]
    assert watch.exclude_keywords == ["中古"]
    assert watch.sort == "newest"


def test_サンプルのままだと分かりやすいエラーになる():
    raw = yaml.safe_load((ROOT / "config.sample.yaml").read_text(encoding="utf-8"))
    with pytest.raises(ConfigError) as exc:
        parse_config(raw)
    message = str(exc.value)
    assert "webhook_url" in message
    assert "application_id" in message
    assert "access_key" in message
    assert "allowed_website" in message


def test_サンプルにキーを入れれば読み込める():
    raw = yaml.safe_load((ROOT / "config.sample.yaml").read_text(encoding="utf-8"))
    raw["discord"]["webhook_url"] = "https://discord.com/api/webhooks/1/x"
    raw["rakuten"] = valid_raw_config()["rakuten"]
    config = parse_config(raw)
    assert len(config.watches) == 2


def test_アクセスキーの取り違えを指摘する():
    raw = valid_raw_config()
    raw["rakuten"]["access_key"] = "2fc160ec-1111"
    with pytest.raises(ConfigError, match="pk_"):
        parse_config(raw)


def test_価格の上限下限が逆ならエラー():
    with pytest.raises(ConfigError, match="min_price"):
        make_config(min_price=5000, max_price=1000)


def test_名前の重複はエラー():
    raw = valid_raw_config()
    raw["watches"].append(dict(raw["watches"][0]))
    with pytest.raises(ConfigError, match="重複"):
        parse_config(raw)


def test_yahooはまだ使えないと案内する():
    with pytest.raises(ConfigError, match="Yahoo"):
        make_config(site="yahoo")


def test_監視間隔の最小値はAPI上限から計算される():
    config = make_config(max_pages=1)
    assert minimum_interval_minutes(config.watches, "rakuten") == 5
    # 10ページ×20条件＝200リクエスト×2秒×2倍＝800秒 → 14分
    many = config.watches * 20
    for w in many:
        w.max_pages = 10
    assert minimum_interval_minutes(many, "rakuten") == 14


def test_BOM付きUTF8でも読み込める(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(valid_raw_config(), allow_unicode=True), encoding="utf-8-sig")
    assert load_config(path).watches[0].name == "テスト条件"


def test_書き方の誤りは行番号付きで案内する(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("discord:\n  webhook_url: \"a\"\n watches: [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="行目"):
        load_config(path)
