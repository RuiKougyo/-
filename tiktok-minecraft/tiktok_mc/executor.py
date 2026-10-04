"""Minecraftへ送るコマンドの「順番待ちの列（キュー）」。

ギフトが一度にたくさん届いても、サーバーが重くならないように
1秒あたりの送信数を制限しながら、届いた順に1つずつ送ります。
Minecraftサーバーが落ちていたときは、復旧するまで待ってから続きを送ります。
"""

from __future__ import annotations

import asyncio
import re
from collections import deque
from typing import Protocol

from .log_setup import get_logger
from .rcon import RconAuthError, RconError

log = get_logger("executor")

# 「wait 1.5」のように書くと、次のコマンドまで1.5秒あける
_WAIT_PATTERN = re.compile(r"^wait\s+(\d+(?:\.\d+)?)$", re.IGNORECASE)
# Minecraftがコマンドの間違いを返してきたときの文言
_ERROR_HINTS = ("Unknown or incomplete command", "<--[HERE]", "Incorrect argument", "Unknown command")
MAX_WAIT_SECONDS = 60


class CommandSender(Protocol):
    async def command(self, text: str) -> str: ...

    async def close(self) -> None: ...


class DryRunSender:
    """Minecraftに送らず、画面に表示するだけの送信先（動作確認用）。"""

    async def command(self, text: str) -> str:
        log.info("［送信のふり］/%s", text)
        return ""

    async def close(self) -> None:
        pass


class CommandQueue:
    def __init__(
        self,
        sender: CommandSender,
        commands_per_second: float = 10,
        max_queue: int = 1000,
        retry_delay: float = 5.0,
    ):
        self.sender = sender
        self.interval = 1.0 / commands_per_second
        self.max_queue = max_queue
        self.retry_delay = retry_delay
        self._jobs: deque[tuple[str, list[str]]] = deque()
        self._pending = 0  # 列に並んでいるコマンドの合計数
        self._wakeup = asyncio.Event()
        self._warned_errors: set[str] = set()
        self.sent_count = 0
        self.dropped_count = 0

    @property
    def pending(self) -> int:
        return self._pending

    def submit(self, label: str, commands: list[str]) -> bool:
        """コマンドのまとまりを列の最後に並べる。列があふれていたら捨てて False を返す。"""
        if not commands:
            return True
        if self._pending + len(commands) > self.max_queue:
            self.dropped_count += len(commands)
            log.warning(
                "コマンドの順番待ちが多すぎるため「%s」をスキップしました（待ち %d 件）。",
                label,
                self._pending,
            )
            return False
        self._jobs.append((label, list(commands)))
        self._pending += len(commands)
        self._wakeup.set()
        return True

    async def run(self) -> None:
        """列に並んだコマンドを送り続ける（ツールが終了するまで動き続ける）。"""
        while True:
            if not self._jobs:
                self._wakeup.clear()
                await self._wakeup.wait()
                continue
            label, commands = self._jobs.popleft()
            for command in commands:
                await self._run_one(label, command)
                self._pending -= 1

    async def _run_one(self, label: str, command: str) -> None:
        wait = _WAIT_PATTERN.match(command)
        if wait:
            await asyncio.sleep(min(float(wait.group(1)), MAX_WAIT_SECONDS))
            return
        delay = self.retry_delay
        while True:
            try:
                reply = await self.sender.command(command)
                break
            except RconAuthError as e:
                log.error("%s（60秒後にもう一度試します）", e)
                await asyncio.sleep(60)
            except RconError as e:
                log.warning("%s %d秒後にもう一度試します。", e, int(delay))
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
            except ValueError as e:
                log.error("「%s」のコマンドを送れませんでした: %s", label, e)
                return
        self.sent_count += 1
        log.debug("/%s → %s", command, reply.strip())
        if reply and any(h in reply for h in _ERROR_HINTS):
            # 同じ間違いで何度もログが埋まらないよう、ルールごとに1回だけ知らせる
            key = f"{label}:{command.split(' ', 1)[0]}"
            if key not in self._warned_errors:
                self._warned_errors.add(key)
                log.warning(
                    "「%s」のコマンドがMinecraftでエラーになりました。\n  コマンド: /%s\n  返事: %s",
                    label,
                    command,
                    reply.strip(),
                )
        await asyncio.sleep(self.interval)
