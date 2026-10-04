"""APIへのリクエスト間隔を守るための仕組み。

サイトごとに1つ用意し、そのサイトへの全リクエストが必ずここを通ります。
監視条件がいくつあっても、前回のリクエストから決まった秒数が経つまで待つので、
API側の回数上限を超えることはありません。
"""

import time
from typing import Callable


class RateLimiter:
    """前回のリクエストから min_interval 秒以上空くまで待つ。"""

    def __init__(
        self,
        min_interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last = None  # 前回リクエストした時刻

    def wait(self) -> None:
        """必要なだけ待ってから、今回のリクエスト時刻を記録する。"""
        if self._last is not None:
            remaining = self.min_interval - (self._clock() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()
