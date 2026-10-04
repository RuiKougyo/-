import pytest

from tiktok_mc import events as ev
from tiktok_mc.config import parse_config
from tiktok_mc.events import LiveEvent
from tiktok_mc.rules import RuleEngine, render, sanitize


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_engine(extra: dict | None = None, clock=None) -> RuleEngine:
    raw = {
        "tiktok": {"username": "me"},
        "minecraft": {"password": "pw", "player": "Steve", "max_repeat": 10},
        "gift_announce": ["say thanks {nickname} {gift}x{count}"],
        "gifts": [
            {"name": "rose", "gift": ["Rose", 5655], "commands": ["summon zombie #{n}"]},
            {"name": "big", "min_coins": 100, "repeat": False, "commands": ["summon lightning_bolt"]},
            {"name": "mid", "min_coins": 10, "max_coins": 99, "times": 2, "commands": ["summon tnt"]},
        ],
        "unknown_gift": {"commands": ["summon chicken"]},
        "follow": {"once_per_user": True, "commands": ["say follow {nickname}"]},
        "share": {"cooldown_seconds": 30, "commands": ["say share"]},
        "likes": {"every": 100, "commands": ["say likes {likes}"]},
        "comments": [{"keywords": ["ジャンプ"], "cooldown_seconds": 10, "commands": ["effect give {player} jump_boost"]}],
    }
    raw.update(extra or {})
    return RuleEngine(parse_config(raw), clock=clock or FakeClock())


def gift(name="Rose", count=1, coins=1, gift_id=0, user="u1", nickname="たろう"):
    return LiveEvent(kind=ev.GIFT, gift_name=name, gift_id=gift_id, coins=coins, count=count,
                     user_id=user, nickname=nickname)


def test_gift_by_name_repeats_per_count():
    jobs = make_engine().handle(gift("rose", count=3))
    assert jobs[0] == ("ギフトのお知らせ", ["say thanks たろう rosex3"])
    assert jobs[1] == ("rose", ["summon zombie #1", "summon zombie #2", "summon zombie #3"])


def test_gift_by_id():
    jobs = make_engine().handle(gift("ローズ", gift_id=5655))
    assert jobs[1][0] == "rose"


def test_gift_by_coins_and_times():
    engine = make_engine()
    assert engine.handle(gift("Lion", coins=29999, count=2))[1] == ("big", ["summon lightning_bolt"])
    assert engine.handle(gift("Perfume", coins=20, count=2))[1] == ("mid", ["summon tnt"] * 4)


def test_repeat_is_capped():
    jobs = make_engine().handle(gift("Rose", count=999))
    assert len(jobs[1][1]) == 10


def test_unknown_gift_falls_back():
    jobs = make_engine().handle(gift("GG", coins=1))
    assert jobs[1] == ("unknown_gift", ["summon chicken"])


def test_nickname_cannot_break_commands():
    nasty = 'a"}]\nop @a §k\\'
    jobs = make_engine().handle(gift("Rose", nickname=nasty))
    command = jobs[0][1][0]
    assert "\n" not in command and "§" not in command
    assert '\\"' in command  # 「"」はエスケープされる
    assert sanitize('x"y') == 'x\\"y'


def test_render_keeps_nbt_braces():
    assert render("summon tnt ~ ~ ~ {fuse:60} {player}", {"player": "Steve"}) == "summon tnt ~ ~ ~ {fuse:60} Steve"


def test_follow_once_per_user():
    engine = make_engine()
    follow = LiveEvent(kind=ev.FOLLOW, user_id="u1", nickname="a")
    assert engine.handle(follow)
    assert engine.handle(follow) == []
    engine.reset_session()
    assert engine.handle(follow)


def test_share_cooldown():
    clock = FakeClock()
    engine = make_engine(clock=clock)
    share = LiveEvent(kind=ev.SHARE, user_id="u1")
    assert engine.handle(share)
    clock.now += 10
    assert engine.handle(share) == []
    assert engine.handle(LiveEvent(kind=ev.SHARE, user_id="u2"))  # 別の人はOK
    clock.now += 25
    assert engine.handle(share)


def test_likes_every_threshold():
    engine = make_engine()
    assert engine.handle(LiveEvent(kind=ev.LIKE, count=60)) == []
    assert engine.handle(LiveEvent(kind=ev.LIKE, count=60)) == [("likes", ["say likes 100"])]
    # 一度に大量のいいね → 超えた回数分まとめて
    assert engine.handle(LiveEvent(kind=ev.LIKE, count=200)) == [("likes", ["say likes 200", "say likes 300"])]


def test_comment_keyword():
    engine = make_engine()
    jobs = engine.handle(LiveEvent(kind=ev.COMMENT, user_id="u1", comment="ジャンプして！"))
    assert jobs == [("comments の1番目", ["effect give Steve jump_boost"])]
    assert engine.handle(LiveEvent(kind=ev.COMMENT, user_id="u1", comment="ジャンプ")) == []
    assert engine.handle(LiveEvent(kind=ev.COMMENT, user_id="u2", comment="こんにちは")) == []


def test_player_defaults_to_everyone():
    engine = make_engine({"minecraft": {"password": "pw"}})
    jobs = engine.handle(LiveEvent(kind=ev.COMMENT, user_id="u1", comment="ジャンプ"))
    assert jobs[0][1] == ["effect give @a jump_boost"]


@pytest.mark.parametrize("count", [0, -1])
def test_zero_count_gift_ignored(count):
    assert make_engine().handle(gift(count=count)) == []


def test_once_per_user_is_per_rule():
    engine = make_engine({"share": {"once_per_user": True, "commands": ["say share"]}})
    assert engine.handle(LiveEvent(kind=ev.FOLLOW, user_id="u1"))
    assert engine.handle(LiveEvent(kind=ev.SHARE, user_id="u1"))  # フォロー済みでもシェアは別
    assert engine.handle(LiveEvent(kind=ev.SHARE, user_id="u1")) == []
