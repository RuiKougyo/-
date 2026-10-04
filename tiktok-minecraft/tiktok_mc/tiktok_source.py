"""TikTokライブへの接続と、届いた出来事の受け取り。

放置で動かせるように、次のことを自動で行います。
- 配信が始まるまで、一定間隔で「配信中か」を確認して待つ
- 配信が始まったら自動で接続する
- 接続が切れたり配信が終わったりしたら、また待ち状態に戻る
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from . import events as ev
from .config import TikTokSettings
from .events import LiveEvent
from .log_setup import get_logger

log = get_logger("tiktok")

EventCallback = Callable[[LiveEvent], None]


class GiftStreakTracker:
    """連打できるギフト（バラなど）の個数を、正しく数えるための仕組み。

    TikTokでは、バラを連打すると「1個」「2個」「3個」…と、合計個数の通知が
    何度も届きます。そのまま使うと 1+2+3 回動いてしまうので、
    前回からの「増えた分」だけを取り出します。
    """

    STALE_SECONDS = 120

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self._last: dict[tuple, tuple[int, float]] = {}

    def delta(self, key: tuple, repeat_count: int, streak_ended: bool) -> int:
        now = self.clock()
        self._purge(now)
        previous, _ = self._last.get(key, (0, now))
        if repeat_count < previous:
            # 新しい連打が始まった（前回の終わりの通知を取りこぼした）
            previous = 0
        if streak_ended:
            self._last.pop(key, None)
        else:
            self._last[key] = (repeat_count, now)
        return max(repeat_count - previous, 0)

    def _purge(self, now: float) -> None:
        for key in [k for k, (_, t) in self._last.items() if now - t > self.STALE_SECONDS]:
            del self._last[key]


def _user_fields(user) -> dict:
    if user is None:
        return {}
    return {
        "user_id": str(getattr(user, "id", "") or ""),
        "username": str(getattr(user, "display_id", "") or getattr(user, "unique_id", "") or ""),
        "nickname": str(getattr(user, "nickname", "") or ""),
    }


class TikTokSource:
    """TikTokライブに接続し続け、出来事を callback に渡す。"""

    def __init__(
        self,
        settings: TikTokSettings,
        callback: EventCallback,
        gift_mode: str = "immediate",
        on_live_start: Callable[[], Awaitable[None] | None] | None = None,
        on_live_end: Callable[[], Awaitable[None] | None] | None = None,
    ):
        self.settings = settings
        self.callback = callback
        self.gift_mode = gift_mode
        self.on_live_start = on_live_start
        self.on_live_end = on_live_end
        self.streaks = GiftStreakTracker()
        self.is_connected = False

    async def run_forever(self) -> None:
        # TikTokLive は読み込みに時間がかかるので、実際に使うときに読み込む
        from TikTokLive.client.web.web_settings import WebDefaults

        if self.settings.sign_api_key:
            WebDefaults.tiktok_sign_api_key = self.settings.sign_api_key

        error_delay = 30.0
        waiting_logged = False
        while True:
            try:
                ended_normally = await self._connect_once(waiting_logged)
                waiting_logged = not ended_normally
                error_delay = 30.0
                if ended_normally:
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001  放置運用のため、何があっても止めずに再試行する
                log.warning("TikTokへの接続でエラーが起きました: %s（%d秒後に再試行）", _describe(e), int(error_delay))
                waiting_logged = False
                await asyncio.sleep(error_delay)
                error_delay = min(error_delay * 2, 600)
                continue
            await asyncio.sleep(self.settings.check_interval_seconds)

    async def _connect_once(self, waiting_logged: bool) -> bool:
        """1回分の「配信中か確認 → 接続 → 終わるまで受信」を行う。

        配信していなかったときは False、配信に接続して終わったときは True を返す。
        """
        from TikTokLive import TikTokLiveClient
        from TikTokLive.client.errors import UserOfflineError

        client = TikTokLiveClient(unique_id=f"@{self.settings.username}")
        self._register(client)
        try:
            try:
                live = await client.is_live()
            except UserOfflineError:
                live = False
            if not live:
                if not waiting_logged:
                    log.info(
                        "@%s は今は配信していません。配信が始まるまで %d 秒ごとに確認して待ちます…",
                        self.settings.username,
                        int(self.settings.check_interval_seconds),
                    )
                return False
            try:
                task = await client.start(fetch_live_check=True, process_connect_events=False)
            except UserOfflineError:
                return False
            await self._mark_connected()
            await task
            return True
        finally:
            if self.is_connected:
                self.is_connected = False
                log.info("TikTokライブとの接続が終わりました。次の配信を待ちます。")
                await _maybe_await(self.on_live_end)
            try:
                await client.disconnect(close_client=False)
                await client.web.close()
            except Exception:  # noqa: BLE001  後片付けの失敗は無視してよい
                pass

    def _register(self, client) -> None:
        from TikTokLive.events import (
            CommentEvent,
            ConnectEvent,
            FollowEvent,
            GiftEvent,
            JoinEvent,
            LikeEvent,
            ShareEvent,
            SubNotifyEvent,
        )

        async def on_connect(event: ConnectEvent) -> None:
            await self._mark_connected()

        async def on_gift(event: GiftEvent) -> None:
            gift = event.gift
            if gift is None:
                return
            streakable = gift.type == 1
            streak_ended = not streakable or bool(event.repeat_end)
            repeat = max(int(event.repeat_count or 1), 1)
            if self.gift_mode == "streak_end":
                if not streak_ended:
                    return
                count = repeat
            else:
                user_id = getattr(event.user, "id", 0) if event.user else 0
                key = (user_id, gift.id, event.group_id)
                count = self.streaks.delta(key, repeat, streak_ended) if streakable else repeat
            if count <= 0:
                return
            self._emit(
                LiveEvent(
                    kind=ev.GIFT,
                    gift_name=gift.name or "",
                    gift_id=int(gift.id or 0),
                    coins=int(gift.diamond_count or 0),
                    count=count,
                    **_user_fields(event.user),
                )
            )

        async def on_follow(event: FollowEvent) -> None:
            self._emit(LiveEvent(kind=ev.FOLLOW, **_user_fields(event.user)))

        async def on_share(event: ShareEvent) -> None:
            self._emit(LiveEvent(kind=ev.SHARE, **_user_fields(event.user)))

        async def on_like(event: LikeEvent) -> None:
            self._emit(LiveEvent(kind=ev.LIKE, count=int(event.count or 0), **_user_fields(event.user)))

        async def on_comment(event: CommentEvent) -> None:
            self._emit(LiveEvent(kind=ev.COMMENT, comment=event.content or "", **_user_fields(event.user)))

        async def on_join(event: JoinEvent) -> None:
            self._emit(LiveEvent(kind=ev.JOIN, **_user_fields(event.user)))

        async def on_subscribe(event: SubNotifyEvent) -> None:
            self._emit(LiveEvent(kind=ev.SUBSCRIBE, **_user_fields(event.user)))

        client.add_listener(ConnectEvent, on_connect)
        client.add_listener(GiftEvent, on_gift)
        client.add_listener(FollowEvent, on_follow)
        client.add_listener(ShareEvent, on_share)
        client.add_listener(LikeEvent, on_like)
        client.add_listener(CommentEvent, on_comment)
        client.add_listener(JoinEvent, on_join)
        client.add_listener(SubNotifyEvent, on_subscribe)

    async def _mark_connected(self) -> None:
        if self.is_connected:
            return
        self.is_connected = True
        log.info("TikTokライブ（@%s）に接続しました！ギフトを待っています。", self.settings.username)
        await _maybe_await(self.on_live_start)

    def _emit(self, event: LiveEvent) -> None:
        try:
            self.callback(event)
        except Exception:  # noqa: BLE001  1件の失敗で受信全体を止めない
            log.exception("出来事の処理中にエラーが起きました")


async def _maybe_await(func) -> None:
    if func is None:
        return
    result = func()
    if asyncio.iscoroutine(result):
        await result


def _describe(error: Exception) -> str:
    name = type(error).__name__
    if name == "UserNotFoundError":
        return "TikTokのユーザーが見つかりません。config.yaml の tiktok → username を確認してください"
    if "RateLimit" in name:
        return "接続の回数制限にかかりました。しばらく待ってから自動で再試行します"
    if name == "AgeRestrictedError":
        return "年齢制限のある配信のため接続できません"
    return f"{name}: {error}"
