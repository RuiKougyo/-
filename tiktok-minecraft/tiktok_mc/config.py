"""設定ファイル（config.yaml）の読み込みと、書き間違いのチェック。

書き間違いがあったときは、どこが悪いのかを日本語で伝えて止まります。
（配信中に変な動きをするより、起動時に止まった方が安全なため）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """設定ファイルの内容に問題があるときのエラー。"""


@dataclass
class Rule:
    """「この出来事が起きたら、このコマンドを実行する」という1つの決まり。"""

    label: str
    commands: list[str]
    # ギフト用：ギフト名またはギフトIDの一覧（空なら名前では絞らない）
    gifts: list[str] = field(default_factory=list)
    min_coins: int | None = None
    max_coins: int | None = None
    # ギフト用：個数ぶんコマンドを繰り返すか
    repeat: bool = True
    # 1個あたりの繰り返し回数（例：2なら、バラ3個で6回）
    times: int = 1
    # コメント用：この言葉を含むコメントに反応
    keywords: list[str] = field(default_factory=list)
    # 同じ人が続けて発動できない秒数
    cooldown_seconds: float = 0
    # 誰であっても続けて発動できない秒数
    global_cooldown_seconds: float = 0
    # フォロー用：1人1回だけ反応するか
    once_per_user: bool = False
    # いいね用：何いいねごとに発動するか
    every: int = 0
    # タイマー用：何分ごとに発動するか
    every_minutes: float = 0
    enabled: bool = True


@dataclass
class TikTokSettings:
    username: str
    sign_api_key: str = ""
    check_interval_seconds: float = 60


@dataclass
class MinecraftSettings:
    host: str = "127.0.0.1"
    port: int = 25575
    password: str = ""
    player: str = ""
    commands_per_second: float = 10
    max_queue: int = 1000
    max_repeat: int = 50


@dataclass
class Config:
    tiktok: TikTokSettings
    minecraft: MinecraftSettings
    gift_mode: str = "immediate"
    gift_announce: list[str] = field(default_factory=list)
    gifts: list[Rule] = field(default_factory=list)
    unknown_gift: Rule | None = None
    follow: Rule | None = None
    share: Rule | None = None
    likes: Rule | None = None
    join: Rule | None = None
    subscribe: Rule | None = None
    comments: list[Rule] = field(default_factory=list)
    timers: list[Rule] = field(default_factory=list)
    log_level: str = "INFO"


GIFT_MODES = ("immediate", "streak_end")


def load_config(path: Path) -> Config:
    """設定ファイルを読み込み、チェック済みの設定を返す。"""
    if not path.exists():
        raise ConfigError(f"設定ファイルが見つかりません: {path}")
    try:
        with path.open(encoding="utf-8-sig") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"（{mark.line + 1}行目付近）" if mark else ""
        raise ConfigError(
            f"設定ファイルの書き方に誤りがあります{where}。"
            "字下げ（先頭の空白）や「:」の後の空白を確認してください。"
        ) from e
    return parse_config(raw)


def parse_config(raw: Any) -> Config:
    """読み込んだYAMLの中身（辞書）をチェックして、設定に変換する。"""
    if not isinstance(raw, dict):
        raise ConfigError("設定ファイルの中身が空か、形式が正しくありません。")

    tiktok_raw = _section(raw, "tiktok")
    username = str(tiktok_raw.get("username") or "").strip().lstrip("@")
    if not username or username == "your_tiktok_id":
        raise ConfigError("tiktok → username に、配信するTikTokアカウントのID（@の後ろ）を書いてください。")
    tiktok = TikTokSettings(
        username=username,
        sign_api_key=str(tiktok_raw.get("sign_api_key") or "").strip(),
        check_interval_seconds=_number(tiktok_raw, "check_interval_seconds", 60, "tiktok", minimum=10),
    )

    mc_raw = _section(raw, "minecraft")
    password = str(mc_raw.get("password") or "")
    if not password:
        raise ConfigError(
            "minecraft → password に、server.properties の rcon.password と同じものを書いてください。"
        )
    minecraft = MinecraftSettings(
        host=str(mc_raw.get("host") or "127.0.0.1"),
        port=int(_number(mc_raw, "port", 25575, "minecraft", minimum=1)),
        password=password,
        player=str(mc_raw.get("player") or "").strip(),
        commands_per_second=_number(mc_raw, "commands_per_second", 10, "minecraft", minimum=0.1),
        max_queue=int(_number(mc_raw, "max_queue", 1000, "minecraft", minimum=1)),
        max_repeat=int(_number(mc_raw, "max_repeat", 50, "minecraft", minimum=1)),
    )

    gift_mode = str(raw.get("gift_mode") or "immediate")
    if gift_mode not in GIFT_MODES:
        raise ConfigError("gift_mode は immediate か streak_end のどちらかにしてください。")

    gifts_raw = raw.get("gifts") or []
    if not isinstance(gifts_raw, list):
        raise ConfigError("gifts は「- 」で始まる一覧の形で書いてください。")
    gifts = [_rule(r, f"gifts の{i + 1}番目") for i, r in enumerate(gifts_raw)]
    for rule in gifts:
        if not rule.gifts and rule.min_coins is None and rule.max_coins is None:
            raise ConfigError(
                f"{rule.label}: gift（ギフト名）か min_coins / max_coins（コイン数）のどれかを書いてください。"
            )

    comments_raw = raw.get("comments") or []
    if not isinstance(comments_raw, list):
        raise ConfigError("comments は「- 」で始まる一覧の形で書いてください。")
    comments = [_rule(r, f"comments の{i + 1}番目") for i, r in enumerate(comments_raw)]
    for rule in comments:
        if not rule.keywords:
            raise ConfigError(f"{rule.label}: keywords（反応する言葉）を書いてください。")

    timers_raw = raw.get("timers") or []
    if not isinstance(timers_raw, list):
        raise ConfigError("timers は「- 」で始まる一覧の形で書いてください。")
    timers = [_rule(r, f"timers の{i + 1}番目") for i, r in enumerate(timers_raw)]
    for rule in timers:
        if rule.every_minutes <= 0:
            raise ConfigError(f"{rule.label}: every_minutes（何分ごとか）を書いてください。")

    likes = _optional_rule(raw, "likes")
    if likes and likes.every <= 0:
        raise ConfigError("likes → every（何いいねごとに動かすか）を1以上の数で書いてください。")

    return Config(
        tiktok=tiktok,
        minecraft=minecraft,
        gift_mode=gift_mode,
        gift_announce=_commands(raw.get("gift_announce"), "gift_announce"),
        gifts=gifts,
        unknown_gift=_optional_rule(raw, "unknown_gift"),
        follow=_optional_rule(raw, "follow"),
        share=_optional_rule(raw, "share"),
        likes=likes,
        join=_optional_rule(raw, "join"),
        subscribe=_optional_rule(raw, "subscribe"),
        comments=comments,
        timers=timers,
        log_level=str(raw.get("log_level") or "INFO"),
    )


def _section(raw: dict, name: str) -> dict:
    value = raw.get(name)
    if not isinstance(value, dict):
        raise ConfigError(f"設定ファイルに「{name}:」の項目がありません。")
    return value


def _number(raw: dict, key: str, default: float, where: str, minimum: float = 0) -> float:
    value = raw.get(key, default)
    if value is None:
        value = default
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{where} → {key} には数字を書いてください（今は「{value}」）。") from None
    if number < minimum:
        raise ConfigError(f"{where} → {key} は {minimum:g} 以上にしてください。")
    return number


def _commands(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ConfigError(f"{label} の commands は「- 」で始まる一覧の形で書いてください。")
    commands = []
    for c in value:
        if not isinstance(c, (str, int, float)):
            raise ConfigError(f"{label} の commands に、文字ではないものが入っています: {c!r}")
        text = str(c).strip()
        # Minecraftのチャット欄と同じ感覚で「/」を付けても動くようにする
        if text.startswith("/"):
            text = text[1:]
        if text:
            commands.append(text)
    return commands


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [str(v).strip() for v in value if str(v).strip()]


def _rule(raw: Any, label: str) -> Rule:
    if not isinstance(raw, dict):
        raise ConfigError(f"{label} の書き方が正しくありません。")
    label = str(raw.get("name") or label)
    commands = _commands(raw.get("commands"), label)
    if not commands:
        raise ConfigError(f"{label}: commands（実行するコマンド）を1つ以上書いてください。")

    def optional_int(key: str) -> int | None:
        if raw.get(key) is None:
            return None
        return int(_number(raw, key, 0, label))

    return Rule(
        label=label,
        commands=commands,
        gifts=_str_list(raw.get("gift")),
        min_coins=optional_int("min_coins"),
        max_coins=optional_int("max_coins"),
        repeat=bool(raw.get("repeat", True)),
        times=int(_number(raw, "times", 1, label, minimum=1)),
        keywords=_str_list(raw.get("keywords")),
        cooldown_seconds=_number(raw, "cooldown_seconds", 0, label),
        global_cooldown_seconds=_number(raw, "global_cooldown_seconds", 0, label),
        once_per_user=bool(raw.get("once_per_user", False)),
        every=int(_number(raw, "every", 0, label)),
        every_minutes=_number(raw, "every_minutes", 0, label),
        enabled=bool(raw.get("enabled", True)),
    )


def _optional_rule(raw: dict, key: str) -> Rule | None:
    value = raw.get(key)
    if value is None:
        return None
    rule = _rule(value, key)
    return rule if rule.enabled else None
