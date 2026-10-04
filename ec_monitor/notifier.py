"""Discordのウェブフックで通知を送る。

・1回の送信に商品を最大10件までまとめます（Discordの上限）。
・Discordから「送りすぎ（HTTP 429）」と言われたら、指定された秒数だけ待って送り直します。
・商品名に「@everyone」などが含まれていても、勝手にメンションが飛ばないようにしています。
・各サイトの規約で必須のクレジット表示を、通知の一番下に必ず入れます。
"""

import time
from datetime import datetime, timezone
from typing import Callable, List, Optional, Sequence

import requests

from . import APP_NAME
from .errors import NotifyError
from .log_setup import get_logger
from .models import Notification
from .rate_limiter import RateLimiter

EMBEDS_PER_MESSAGE = 10
MAX_ATTEMPTS = 5
COLOR_NEW = 0x2ECC71  # 緑
COLOR_DROP = 0xE74C3C  # 赤
COLOR_INFO = 0x3498DB  # 青


class DiscordNotifier:
    def __init__(
        self,
        webhook_url: str,
        session: Optional[requests.Session] = None,
        sleep: Callable[[float], None] = time.sleep,
        limiter: Optional[RateLimiter] = None,
    ):
        self.webhook_url = webhook_url
        self.session = session or requests.Session()
        self._sleep = sleep
        # Discordのウェブフックは短時間に送りすぎると制限されるため、1秒以上空ける
        self.limiter = limiter or RateLimiter(1.0, sleep=sleep)

    # ------------------------------------------------------------------
    def send_items(
        self, notifications: Sequence[Notification], site_name: str, credit: str
    ) -> List[Notification]:
        """商品の通知を送り、送信に成功した通知のリストを返す。

        途中で失敗した場合は、それまでに送れた分を返したうえで NotifyError を出す。
        （送れなかった分は記録しないので、次回のチェックで改めて通知される）
        """
        sent: List[Notification] = []
        for start in range(0, len(notifications), EMBEDS_PER_MESSAGE):
            batch = list(notifications[start : start + EMBEDS_PER_MESSAGE])
            payload = {
                "username": APP_NAME,
                "content": _summary_line(batch, site_name),
                "embeds": [build_embed(n, site_name, credit) for n in batch],
                "allowed_mentions": {"parse": []},
            }
            try:
                self._post(payload)
            except NotifyError as exc:
                exc.sent = sent  # type: ignore[attr-defined]
                raise
            sent.extend(batch)
        return sent

    def send_text(self, title: str, description: str, footer: str = "") -> None:
        """お知らせ（テスト通知や重要なエラー）を送る。"""
        embed = {"title": title[:256], "description": description[:4000], "color": COLOR_INFO}
        if footer:
            embed["footer"] = {"text": footer[:2000]}
        self._post({"username": APP_NAME, "embeds": [embed], "allowed_mentions": {"parse": []}})

    # ------------------------------------------------------------------
    def _post(self, payload: dict) -> None:
        log = get_logger()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.limiter.wait()
            try:
                response = self.session.post(self.webhook_url, json=payload, params={"wait": "true"}, timeout=20)
            except requests.RequestException:
                self._wait_before_retry(attempt, "Discordへの通知で通信エラーが起きました")
                continue

            status = response.status_code
            if status in (200, 204):
                return
            if status == 429:
                wait = _discord_retry_after(response)
                log.warning(f"Discordの送信回数の制限にかかりました。{wait:.1f}秒待って送り直します")
                self._sleep(wait)
                continue
            if status in (401, 403, 404):
                raise NotifyError(
                    "DiscordのウェブフックURLが無効です（削除された・URLが間違っている可能性があります）。"
                    "Discordでウェブフックを作り直し、config.yaml の webhook_url を更新してください。"
                )
            if status >= 500:
                self._wait_before_retry(attempt, f"Discord側が一時的にエラーを返しました（HTTP {status}）")
                continue
            raise NotifyError(f"Discordが通知を受け付けませんでした（HTTP {status}：{response.text[:200]}）")

        raise NotifyError(f"Discordへの通知に{MAX_ATTEMPTS}回続けて失敗しました。インターネット接続を確認してください。")

    def _wait_before_retry(self, attempt: int, reason: str) -> None:
        """最後の試行でなければ、少しずつ長く待ってから再試行する。"""
        if attempt >= MAX_ATTEMPTS:
            get_logger().warning(f"{reason}。")
            return
        wait = 5 * attempt
        get_logger().warning(f"{reason}。{wait}秒後に再試行します（{attempt}/{MAX_ATTEMPTS - 1}回目）")
        self._sleep(wait)


# ----------------------------------------------------------------------
# 表示内容の組み立て
# ----------------------------------------------------------------------


def yen(value: int) -> str:
    return f"¥{value:,}"


def build_embed(n: Notification, site_name: str, credit: str) -> dict:
    """1件の商品を、Discordの「埋め込み」形式（カード表示）にする。"""
    item = n.item
    lines = []
    if n.kind == "drop" and n.old_price is not None:
        diff = n.old_price - item.price
        percent = diff / n.old_price * 100 if n.old_price else 0
        lines.append(f"**価格：{yen(item.price)}**　（{percent:.0f}%OFF）")
        lines.append(f"値下げ前：~~{yen(n.old_price)}~~　→　{diff:,}円 値下がり")
    else:
        lines.append(f"**価格：{yen(item.price)}**")
    if item.shop_name:
        lines.append(f"ショップ：{item.shop_name}")

    label = "💸 値下げ" if n.kind == "drop" else "🆕 新着"
    embed = {
        "title": _truncate(f"{label}｜{item.name}", 256),
        "url": item.url,
        "description": "\n".join(lines),
        "color": COLOR_DROP if n.kind == "drop" else COLOR_NEW,
        # クレジット表示（各サイトの利用規約で必須）
        "footer": {"text": _truncate(f"{site_name}｜監視条件「{n.watch_name}」｜{credit}", 2048)},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if item.image_url:
        embed["thumbnail"] = {"url": item.image_url}
    return embed


def _summary_line(batch: Sequence[Notification], site_name: str) -> str:
    new = sum(1 for n in batch if n.kind == "new")
    drop = sum(1 for n in batch if n.kind == "drop")
    parts = []
    if new:
        parts.append(f"新着 {new}件")
    if drop:
        parts.append(f"値下げ {drop}件")
    watch = batch[0].watch_name if batch else ""
    return f"【{site_name}】「{watch}」で " + "・".join(parts) + " 見つかりました"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _discord_retry_after(response: requests.Response) -> float:
    try:
        value = float(response.json().get("retry_after", 0))
    except (ValueError, AttributeError):
        value = 0.0
    if value <= 0:
        try:
            value = float(response.headers.get("Retry-After", 5))
        except ValueError:
            value = 5.0
    return min(max(value, 0.5), 120.0)
