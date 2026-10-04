"""監視の本体。登録された監視条件を、それぞれの間隔で繰り返しチェックする。

エラー時の動き：
・通信エラー／API上限エラー（429）／サーバーエラー
    → その場で数回再試行（http_client.py）。それでも失敗が続いたら、
      そのサイトの監視を 1分→2分→4分…（最大60分）と間隔を空けて待機してから再開する。
・認証エラー（アプリID・アクセスキー・許可サイト・許可IPの問題）
    → 設定を直さない限り直らないため、30分待機。Discordにも1回だけお知らせを送る。
・検索条件の誤り
    → その監視条件だけ60分休ませ、他の条件は通常どおり続ける。
"""

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, List

from .config_loader import AppConfig, Watch, minimum_interval_minutes
from .detector import detect_changes
from .errors import ApiAuthError, ApiRequestError, ApiTemporaryError, NotifyError
from .filters import filter_items
from .log_setup import get_logger
from .notifier import DiscordNotifier
from .sites.base import SiteClient
from .storage import Storage

AUTH_ERROR_WAIT = 30 * 60  # 認証エラー時に待つ秒数
REQUEST_ERROR_WAIT = 60 * 60  # 検索条件の誤りのとき、その条件を休ませる秒数
BACKOFF_BASE = 60  # 一時的なエラーが続いたときの最初の待機秒数
BACKOFF_MAX = 60 * 60  # 待機秒数の上限


@dataclass
class Task:
    """「監視条件 × サイト」の1組。次にチェックする時刻を持つ。"""

    watch: Watch
    site: str
    interval_seconds: int
    next_run: float = 0.0


@dataclass
class SiteState:
    """サイトごとのエラー状況。"""

    failures: int = 0  # 連続で失敗した回数
    paused_until: float = 0.0  # この時刻まではこのサイトへのアクセスを控える
    auth_notified: bool = False  # 認証エラーのお知らせをDiscordに送ったか


class Monitor:
    def __init__(
        self,
        config: AppConfig,
        clients: Dict[str, SiteClient],
        storage: Storage,
        notifier: DiscordNotifier,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.clients = clients
        self.storage = storage
        self.notifier = notifier
        self._clock = clock
        self._sleep = sleep
        self.site_states: Dict[str, SiteState] = {site: SiteState() for site in clients}
        self.tasks: List[Task] = self._build_tasks()

    # ------------------------------------------------------------------
    def _build_tasks(self) -> List[Task]:
        """監視条件ごとの間隔を決める。API上限から計算した最小値より短ければ引き上げる。"""
        log = get_logger()
        tasks = []
        minimums = {site: minimum_interval_minutes(self.config.watches, site) for site in self.clients}
        for watch in self.config.watches:
            for site in watch.sites:
                if site not in self.clients:
                    continue
                minutes = watch.interval_minutes
                if minutes < minimums[site]:
                    log.info(
                        f"監視条件「{watch.name}」の監視間隔を {minutes}分 → {minimums[site]}分 に調整しました"
                        "（APIの利用上限を守るための最小値です）"
                    )
                    minutes = minimums[site]
                tasks.append(Task(watch=watch, site=site, interval_seconds=minutes * 60))
        return tasks

    # ------------------------------------------------------------------
    def run_forever(self) -> None:
        """Ctrl+C で止めるまで、監視を続ける。"""
        log = get_logger()
        log.info(f"監視を開始します（監視条件 {len(self.tasks)}件）。止めるときは Ctrl+C を押すか、画面を閉じてください。")
        while True:
            self.run_due_tasks()
            wait = max(0.0, min(t.next_run for t in self.tasks) - self._clock())
            # 長く眠りすぎないよう、最大60秒ずつ待つ
            self._sleep(min(wait, 60.0) if wait > 0 else 0.5)

    def run_once(self) -> None:
        """すべての監視条件を1回ずつチェックして終わる。"""
        for task in self.tasks:
            self._run_task(task)

    def run_due_tasks(self) -> None:
        """チェックする時刻になった監視条件を実行する。"""
        now = self._clock()
        for task in sorted(self.tasks, key=lambda t: t.next_run):
            if task.next_run > now:
                continue
            state = self.site_states[task.site]
            if state.paused_until > self._clock():
                # サイトが待機中なら、待機明けまで先送りする
                task.next_run = state.paused_until
                continue
            self._run_task(task)

    # ------------------------------------------------------------------
    def _run_task(self, task: Task) -> None:
        log = get_logger()
        watch, site = task.watch, task.site
        client = self.clients[site]
        state = self.site_states[site]
        task.next_run = self._clock() + task.interval_seconds

        try:
            items = client.search(watch)
        except ApiAuthError as exc:
            self._pause_site(site, AUTH_ERROR_WAIT, str(exc))
            task.next_run = state.paused_until
            if not state.auth_notified:
                self._notify_problem(f"⚠️ {client.display_name}のAPIでエラーが起きています", str(exc))
                state.auth_notified = True
            return
        except ApiRequestError as exc:
            log.error(f"監視条件「{watch.name}」：{exc} この条件は{REQUEST_ERROR_WAIT // 60}分後に再チェックします。")
            task.next_run = self._clock() + REQUEST_ERROR_WAIT
            return
        except ApiTemporaryError as exc:
            state.failures += 1
            wait = min(BACKOFF_BASE * 2 ** (state.failures - 1), BACKOFF_MAX)
            self._pause_site(site, wait, f"{exc}（{state.failures}回連続で失敗）")
            # 待機が明けたら、間隔を待たずにすぐ再試行する
            task.next_run = state.paused_until
            return
        except Exception:  # 想定外のエラーでも監視全体は止めない
            log.exception(f"監視条件「{watch.name}」のチェック中に想定外のエラーが起きました。次回また試します。")
            return

        # 成功したのでエラー状況をリセット
        if state.failures or state.auth_notified:
            log.info(f"{client.display_name}のAPIへのアクセスが回復しました")
        state.failures = 0
        state.auth_notified = False

        self._process_items(task, client, items)

    def _process_items(self, task: Task, client: SiteClient, items) -> None:
        log = get_logger()
        watch, site = task.watch, task.site
        matched = filter_items(items, watch)
        signature = watch.signature()
        first_run = not self.storage.is_initialized(watch.name, site, signature)
        known = self.storage.get_known(watch.name, site)

        result = detect_changes(
            watch.name, matched, known, first_run=first_run, settings=self.config.settings
        )
        for item, notified_price in result.silent:
            self.storage.record_seen(watch.name, item, notified_price=notified_price)

        sent = []
        if result.notifications:
            try:
                sent = self.notifier.send_items(result.notifications, client.display_name, client.credit_text)
            except NotifyError as exc:
                sent = getattr(exc, "sent", [])
                log.error(f"{exc} 送れなかった商品は、次回のチェックで改めて通知します。")
        # 通知できた商品だけ「通知済み」として記録する（送れなかった分は次回また通知を試みる）
        for n in sent:
            self.storage.record_seen(watch.name, n.item, notified_price=n.item.price)

        if first_run:
            self.storage.mark_initialized(watch.name, site, signature)

        new = sum(1 for n in sent if n.kind == "new")
        drop = sum(1 for n in sent if n.kind == "drop")
        message = (
            f"「{watch.name}」{client.display_name}：取得 {len(items)}件／条件に合う商品 {len(matched)}件"
            f"／通知 新着{new}件・値下げ{drop}件"
        )
        if first_run and not self.config.settings.first_run_notify:
            message += "（初回チェックのため、見つかった商品は記録のみで通知していません）"
        log.info(message)

    # ------------------------------------------------------------------
    def _pause_site(self, site: str, seconds: float, reason: str) -> None:
        log = get_logger()
        state = self.site_states[site]
        state.paused_until = self._clock() + seconds
        resume = datetime.now() + timedelta(seconds=seconds)
        log.error(
            f"{reason}\n    → {self.clients[site].display_name}の監視を {seconds / 60:.0f}分間 休止し、"
            f"{resume:%H:%M}ごろに再開します。"
        )

    def _notify_problem(self, title: str, description: str) -> None:
        """重要なエラーをDiscordでも知らせる（失敗してもログに残すだけ）。"""
        try:
            self.notifier.send_text(title, description + "\n\n詳しくはツールのログ（logsフォルダ）を確認してください。")
        except NotifyError as exc:
            get_logger().error(f"エラーのお知らせをDiscordに送れませんでした：{exc}")


def build_clients(config: AppConfig, session=None) -> Dict[str, SiteClient]:
    """設定に応じて、サイトごとの検索クライアントを用意する。"""
    from .config_loader import REQUEST_SPACING_SECONDS
    from .rate_limiter import RateLimiter
    from .sites.rakuten import RakutenClient

    clients: Dict[str, SiteClient] = {}
    if config.rakuten is not None:
        clients["rakuten"] = RakutenClient(
            config.rakuten, RateLimiter(REQUEST_SPACING_SECONDS["rakuten"]), session=session
        )
    return clients


def describe_watch(watch: Watch) -> str:
    """起動時に表示する、監視条件の説明。"""
    parts = [f"キーワード「{watch.keyword}」"]
    if watch.exclude_keywords:
        parts.append("除外「" + "・".join(watch.exclude_keywords) + "」")
    if watch.min_price is not None or watch.max_price is not None:
        low = f"{watch.min_price:,}円" if watch.min_price is not None else ""
        high = f"{watch.max_price:,}円" if watch.max_price is not None else ""
        parts.append(f"価格 {low}〜{high}")
    return "、".join(parts)

