import pytest

from ec_monitor.errors import NotifyError
from ec_monitor.models import Item, Notification
from ec_monitor.notifier import DiscordNotifier, build_embed
from helpers import FakeResponse, FakeSession, NoWaitLimiter

CREDIT = "Supported by Rakuten Developers"


def notification(i, kind="new", old=None):
    it = Item(site="rakuten", code=str(i), name=f"商品{i} @everyone", price=1000, url="https://x/" + str(i),
              image_url="https://img/" + str(i))
    return Notification(kind=kind, watch_name="条件", item=it, old_price=old)


def make_notifier(responses):
    session = FakeSession(responses)
    sleeps = []
    return DiscordNotifier("https://discord.com/api/webhooks/1/x", session=session, sleep=sleeps.append,
                           limiter=NoWaitLimiter()), session, sleeps


def test_埋め込みにクレジットと値下げ前価格が入る():
    embed = build_embed(notification(1, "drop", 1500), "楽天市場", CREDIT)
    assert CREDIT in embed["footer"]["text"]
    assert "~~¥1,500~~" in embed["description"]
    assert "¥1,000" in embed["description"]
    assert embed["url"] == "https://x/1"
    assert embed["thumbnail"]["url"] == "https://img/1"


def test_10件ずつまとめて送り_メンションは無効():
    notifier, session, _ = make_notifier([FakeResponse(204), FakeResponse(204)])
    sent = notifier.send_items([notification(i) for i in range(12)], "楽天市場", CREDIT)
    assert len(sent) == 12
    payloads = [c[2]["json"] for c in session.calls]
    assert [len(p["embeds"]) for p in payloads] == [10, 2]
    assert all(p["allowed_mentions"] == {"parse": []} for p in payloads)


def test_429は指定秒数待って送り直す():
    notifier, session, sleeps = make_notifier([FakeResponse(429, {"retry_after": 2.5}), FakeResponse(204)])
    notifier.send_items([notification(1)], "楽天市場", CREDIT)
    assert sleeps == [2.5]
    assert len(session.calls) == 2


def test_無効なウェブフックはエラーで_送れた分を返す():
    notifier, _, _ = make_notifier([FakeResponse(204), FakeResponse(404, {"message": "Unknown Webhook"})])
    with pytest.raises(NotifyError, match="ウェブフック") as exc:
        notifier.send_items([notification(i) for i in range(15)], "楽天市場", CREDIT)
    assert len(exc.value.sent) == 10
