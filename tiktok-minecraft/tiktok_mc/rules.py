"""届いた出来事（ギフト・フォロー等）を設定のルールと照らし合わせて、
Minecraftで実行するコマンドを組み立てる部分。

コマンドの中の {nickname} や {count} などの「差し込み文字」は、
ここで実際の名前や個数に置き換えます。
"""

from __future__ import annotations

import re
import time
from typing import Callable

from . import events as ev
from .config import Config, Rule
from .events import LiveEvent
from .log_setup import get_logger

log = get_logger("rules")

Job = tuple[str, list[str]]

PLACEHOLDERS = (
    "player", "nickname", "username", "user", "gift", "count", "coins",
    "total_coins", "comment", "likes", "n",
)
_PLACEHOLDER_PATTERN = re.compile(r"\{(" + "|".join(PLACEHOLDERS) + r")\}")
# 改行などの制御文字と、Minecraftの色コード記号（§）
_UNSAFE_CHARS = re.compile(r"[\x00-\x1f\x7f§]")
# 1回のいいね通知でまとめて発動する回数の上限（大量いいねで暴走しないように）
MAX_LIKE_TRIGGERS = 10


def sanitize(text: str, max_length: int = 32) -> str:
    """TikTokの名前やコメントを、コマンドに安全に差し込める形にする。

    「"」や「\\」をそのまま入れると、tellraw などのJSONが壊れたり
    コマンドの意味が変わったりするため、エスケープします。
    """
    text = _UNSAFE_CHARS.sub("", text).strip()[:max_length]
    return text.replace("\\", "\\\\").replace('"', '\\"')


def render(template: str, values: dict[str, str]) -> str:
    """コマンドのひな形の {名前} を実際の値に置き換える。知らない {...} はそのまま残す。"""
    return _PLACEHOLDER_PATTERN.sub(lambda m: values.get(m.group(1), m.group(0)), template)


class RuleEngine:
    def __init__(self, config: Config, clock: Callable[[], float] = time.monotonic):
        self.config = config
        self.clock = clock
        self._last_fired: dict[tuple[str, str], float] = {}
        self._once_fired: set[tuple[str, str]] = set()
        self._like_total = 0
        self._like_fired = 0
        self._unknown_gifts_logged: set[str] = set()

    @property
    def like_total(self) -> int:
        return self._like_total

    def reset_session(self) -> None:
        """配信が新しく始まったときに、いいね数などの集計をリセットする。"""
        self._like_total = 0
        self._like_fired = 0
        self._once_fired.clear()

    # ------------------------------------------------------------------ 入口
    def handle(self, event: LiveEvent) -> list[Job]:
        handler = {
            ev.GIFT: self._gift,
            ev.FOLLOW: lambda e: self._simple(e, self.config.follow),
            ev.SHARE: lambda e: self._simple(e, self.config.share),
            ev.JOIN: lambda e: self._simple(e, self.config.join),
            ev.SUBSCRIBE: lambda e: self._simple(e, self.config.subscribe),
            ev.LIKE: self._like,
            ev.COMMENT: self._comment,
        }.get(event.kind)
        return handler(event) if handler else []

    def timer_job(self, rule: Rule) -> Job:
        return rule.label, [render(c, self._values(LiveEvent(kind="timer"))) for c in rule.commands]

    # ------------------------------------------------------------ 種類ごと
    def _gift(self, event: LiveEvent) -> list[Job]:
        if event.count <= 0:
            return []
        jobs: list[Job] = []
        values = self._values(event)
        if self.config.gift_announce:
            jobs.append(("ギフトのお知らせ", [render(c, values) for c in self.config.gift_announce]))

        rule = next((r for r in self.config.gifts if r.enabled and self._gift_matches(r, event)), None)
        if rule is None:
            rule = self.config.unknown_gift
            key = f"{event.gift_id}:{event.gift_name}"
            if key not in self._unknown_gifts_logged:
                self._unknown_gifts_logged.add(key)
                log.info(
                    "設定にないギフトです: 名前「%s」 ID %d（%dコイン）。"
                    "ギミックを付けたいときは config.yaml の gifts に追加してください。",
                    event.gift_name,
                    event.gift_id,
                    event.coins,
                )
        if rule is not None and self._cooldown_ok(rule, event):
            jobs.append(self._repeated_job(rule, event, values))
        return jobs

    def _like(self, event: LiveEvent) -> list[Job]:
        rule = self.config.likes
        if rule is None:
            return []
        self._like_total += max(event.count, 0)
        reached = self._like_total // rule.every
        times = min(reached - self._like_fired, MAX_LIKE_TRIGGERS)
        self._like_fired = reached
        if times <= 0:
            return []
        values = self._values(event)
        commands = []
        for i in range(times):
            values["likes"] = str((reached - times + i + 1) * rule.every)
            commands += [render(c, values) for c in rule.commands]
        return [(rule.label, commands)]

    def _comment(self, event: LiveEvent) -> list[Job]:
        text = event.comment.lower()
        for rule in self.config.comments:
            if rule.enabled and any(k.lower() in text for k in rule.keywords):
                if self._cooldown_ok(rule, event):
                    return [(rule.label, [render(c, self._values(event)) for c in rule.commands])]
                return []
        return []

    def _simple(self, event: LiveEvent, rule: Rule | None) -> list[Job]:
        if rule is None:
            return []
        if rule.once_per_user:
            key = (rule.label, event.user_id or event.username)
            if key in self._once_fired:
                return []
            self._once_fired.add(key)
        if not self._cooldown_ok(rule, event):
            return []
        return [(rule.label, [render(c, self._values(event)) for c in rule.commands])]

    # ---------------------------------------------------------------- 部品
    @staticmethod
    def _gift_matches(rule: Rule, event: LiveEvent) -> bool:
        if rule.gifts:
            names = {g.lower() for g in rule.gifts}
            if event.gift_name.lower() not in names and str(event.gift_id) not in names:
                return False
        if rule.min_coins is not None and event.coins < rule.min_coins:
            return False
        if rule.max_coins is not None and event.coins > rule.max_coins:
            return False
        return True

    def _repeated_job(self, rule: Rule, event: LiveEvent, values: dict[str, str]) -> Job:
        times = event.count * rule.times if rule.repeat else rule.times
        limit = self.config.minecraft.max_repeat
        if times > limit:
            log.info("「%s」は %d 回分ですが、上限の %d 回に減らして実行します。", rule.label, times, limit)
            times = limit
        commands = []
        for n in range(1, times + 1):
            values["n"] = str(n)
            commands += [render(c, values) for c in rule.commands]
        return rule.label, commands

    def _cooldown_ok(self, rule: Rule, event: LiveEvent) -> bool:
        now = self.clock()
        user_key = (rule.label, event.user_id or event.username)
        global_key = (rule.label, "")
        if rule.cooldown_seconds and now - self._last_fired.get(user_key, -1e9) < rule.cooldown_seconds:
            return False
        if rule.global_cooldown_seconds and now - self._last_fired.get(global_key, -1e9) < rule.global_cooldown_seconds:
            return False
        self._last_fired[user_key] = now
        self._last_fired[global_key] = now
        return True

    def _values(self, event: LiveEvent) -> dict[str, str]:
        nickname = sanitize(event.display_name)
        return {
            "player": self.config.minecraft.player or "@a",
            "nickname": nickname,
            "user": nickname,
            "username": sanitize(event.username or event.display_name),
            "gift": sanitize(event.gift_name),
            "count": str(event.count),
            "coins": str(event.coins),
            "total_coins": str(event.coins * event.count),
            "comment": sanitize(event.comment, max_length=100),
            "likes": str(self._like_total),
            "n": "1",
        }
