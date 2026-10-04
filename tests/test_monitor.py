"""監視の流れ全体のテスト（偽の楽天APIと偽のDiscordを使う）。"""

from pathlib import Path

from ec_monitor.errors import ApiAuthError, ApiRateLimitError, NotifyError
from ec_monitor.models import Item
from ec_monitor.monitor import BACKOFF_BASE, Monitor
from ec_monitor.sites.base import SiteClient
from ec_monitor.storage import Storage
from helpers import make_config


class FakeClient(SiteClient):
    site_id = "rakuten"
    display_name = "楽天市場"
    credit_text = "Supported by Rakuten Developers"

    def __init__(self):
        self.results = []  # search() のたびに先頭から取り出す（例外なら投げる）

    def search(self, watch):
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeNotifier:
    def __init__(self):
        self.sent = []
        self.texts = []
        self.fail = False

    def send_items(self, notifications, site_name, credit):
        if self.fail:
            err = NotifyError("送信失敗")
            err.sent = []
            raise err
        self.sent.extend(notifications)
        return list(notifications)

    def send_text(self, title, description, footer=""):
        self.texts.append(title)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def item(code, price):
    return Item(site="rakuten", code=code, name=f"商品{code}", price=price, url="https://x/" + code)


def setup(tmp_path: Path, **watch):
    config = make_config(**watch)
    client = FakeClient()
    notifier = FakeNotifier()
    storage = Storage(tmp_path / "state.db")
    clock = Clock()
    monitor = Monitor(config, {"rakuten": client}, storage, notifier, clock=clock, sleep=lambda s: None)
    return monitor, client, notifier, storage, clock


def test_初回は記録のみ_以後は新着と値下げだけ通知(tmp_path):
    monitor, client, notifier, _, _ = setup(tmp_path)
    client.results = [
        [item("a", 3000), item("b", 4000)],                  # 1回目：初回なので通知なし
        [item("a", 3000), item("b", 4000), item("c", 5000)],  # 2回目：c が新着
        [item("a", 2500), item("b", 4000), item("c", 5000)],  # 3回目：a が値下げ
        [item("a", 2500), item("b", 4000), item("c", 5000)],  # 4回目：変化なし
    ]
    monitor.run_once()
    assert notifier.sent == []

    monitor.run_once()
    assert [(n.kind, n.item.code) for n in notifier.sent] == [("new", "c")]

    monitor.run_once()
    assert [(n.kind, n.item.code, n.old_price) for n in notifier.sent[1:]] == [("drop", "a", 3000)]

    monitor.run_once()
    assert len(notifier.sent) == 2  # 重複して通知しない


def test_条件に合わない商品は通知しない(tmp_path):
    monitor, client, notifier, _, _ = setup(tmp_path, max_price=5000)
    client.results = [[], [item("cheap", 3000), item("expensive", 9000)]]
    monitor.run_once()
    monitor.run_once()
    assert [n.item.code for n in notifier.sent] == ["cheap"]


def test_Discordに送れなかった商品は次回また通知する(tmp_path):
    monitor, client, notifier, _, _ = setup(tmp_path)
    client.results = [[], [item("a", 3000)], [item("a", 3000)]]
    monitor.run_once()
    notifier.fail = True
    monitor.run_once()
    notifier.fail = False
    monitor.run_once()
    assert [n.item.code for n in notifier.sent] == ["a"]


def test_検索条件を変えると初回扱いに戻る(tmp_path):
    monitor, client, notifier, storage, _ = setup(tmp_path)
    client.results = [[item("a", 3000)]]
    monitor.run_once()

    config2 = make_config(keyword="別のキーワード")
    client2 = FakeClient()
    client2.results = [[item("z", 3000)]]
    monitor2 = Monitor(config2, {"rakuten": client2}, storage, notifier, sleep=lambda s: None)
    monitor2.run_once()
    assert notifier.sent == []


def test_監視間隔が短すぎると自動で延長(tmp_path):
    monitor, *_ = setup(tmp_path, interval_minutes=1)
    assert monitor.tasks[0].interval_seconds == 5 * 60


def test_一時エラーが続くと待機時間が延びる(tmp_path):
    monitor, client, _, _, clock = setup(tmp_path)
    client.results = [ApiRateLimitError("429"), ApiRateLimitError("429"), [item("a", 3000)]]
    state = monitor.site_states["rakuten"]

    monitor.run_due_tasks()
    assert state.failures == 1
    assert state.paused_until == clock.now + BACKOFF_BASE

    # 待機中は実行しない
    clock.now += 30
    monitor.run_due_tasks()
    assert len(client.results) == 2

    clock.now += BACKOFF_BASE
    monitor.run_due_tasks()
    assert state.failures == 2
    assert state.paused_until == clock.now + BACKOFF_BASE * 2

    clock.now += BACKOFF_BASE * 2
    monitor.run_due_tasks()
    assert state.failures == 0  # 成功したらリセット


def test_認証エラーはDiscordに1回だけ知らせて長く待つ(tmp_path):
    monitor, client, notifier, _, clock = setup(tmp_path)
    client.results = [ApiAuthError("IP"), ApiAuthError("IP")]
    monitor.run_due_tasks()
    assert monitor.site_states["rakuten"].paused_until == clock.now + 30 * 60
    clock.now += 30 * 60 + 1
    monitor.run_due_tasks()
    assert len(notifier.texts) == 1
