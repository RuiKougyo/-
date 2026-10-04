from tiktok_mc.tiktok_source import GiftStreakTracker


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def test_streak_counts_only_new_gifts():
    t = GiftStreakTracker()
    key = ("u1", 5655, 1)
    assert t.delta(key, 1, False) == 1
    assert t.delta(key, 2, False) == 1
    assert t.delta(key, 5, False) == 3
    assert t.delta(key, 5, True) == 0  # 連打終了の通知（個数は増えていない）
    # 次の連打は1から数え直し
    assert t.delta(key, 1, False) == 1


def test_lost_end_event_restarts_count():
    t = GiftStreakTracker()
    key = ("u1", 5655, 1)
    t.delta(key, 10, False)
    assert t.delta(key, 2, False) == 2


def test_end_only_event_counts_all():
    t = GiftStreakTracker()
    assert t.delta(("u1", 1, 1), 4, True) == 4


def test_stale_entries_are_forgotten():
    clock = Clock()
    t = GiftStreakTracker(clock=clock)
    t.delta(("u1", 1, 1), 3, False)
    clock.now += 1000
    assert t.delta(("u1", 1, 1), 3, False) == 3
