"""APIへの通信と、失敗したときの自動再試行。

・通信エラー、HTTP 429（回数上限）、HTTP 5xx（サーバー側の不調）のときは、
  待ち時間を少しずつ延ばしながら自動で再試行します。
・それ以外（成功や 4xx）はそのまま呼び出し元に返し、サイトごとの処理で判断します。
・APIキーが漏れないよう、URLやパラメータはログに出しません。
"""

import time
from typing import Callable, Optional, Sequence

import requests

from .errors import ApiRateLimitError, ApiTemporaryError
from .log_setup import get_logger
from .rate_limiter import RateLimiter

# 1回のリクエストで待つ最大秒数
REQUEST_TIMEOUT = 20
# 再試行の前に待つ秒数（1回目の失敗後, 2回目の失敗後）。合計3回まで試す
DEFAULT_RETRY_WAITS = (10, 30)
# サーバーが「○秒待って」と指定してきたときに従う上限
MAX_RETRY_AFTER = 300

_RETRY_STATUS = {429, 500, 502, 503, 504}


def get_with_retry(
    session: requests.Session,
    url: str,
    *,
    site_label: str,
    limiter: RateLimiter,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    retry_waits: Sequence[float] = DEFAULT_RETRY_WAITS,
    sleep: Callable[[float], None] = time.sleep,
) -> requests.Response:
    """GETリクエストを送り、一時的な失敗なら自動で再試行する。

    再試行しても失敗した場合は ApiTemporaryError（429なら ApiRateLimitError）を出す。
    """
    log = get_logger()
    attempts = len(retry_waits) + 1
    last_error: Optional[Exception] = None

    for attempt in range(1, attempts + 1):
        limiter.wait()  # API上限を守るため、必ず間隔を空ける
        try:
            response = session.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            last_error = ApiTemporaryError(
                f"{site_label}への通信に失敗しました（{_describe_network_error(exc)}）"
            )
            wait = None
        else:
            if response.status_code not in _RETRY_STATUS:
                return response
            if response.status_code == 429:
                last_error = ApiRateLimitError(
                    f"{site_label}のAPIリクエスト回数の上限に達しました（HTTP 429）"
                )
            else:
                last_error = ApiTemporaryError(
                    f"{site_label}のサーバーが一時的にエラーを返しました（HTTP {response.status_code}）"
                )
            wait = _parse_retry_after(response)

        if attempt >= attempts:
            break
        wait = max(wait or 0, retry_waits[attempt - 1])
        log.warning(f"{last_error}。{wait:.0f}秒後に再試行します（{attempt}/{attempts - 1}回目）")
        sleep(wait)

    assert last_error is not None
    raise last_error


def _parse_retry_after(response: requests.Response) -> Optional[float]:
    """Retry-Afterヘッダー（待つべき秒数）があれば読み取る。"""
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return min(float(value), MAX_RETRY_AFTER)
    except ValueError:
        return None


def _describe_network_error(exc: Exception) -> str:
    """通信エラーの内容を、利用者に分かる日本語にする。"""
    if isinstance(exc, requests.Timeout):
        return "応答がありませんでした。インターネット接続を確認してください"
    if isinstance(exc, requests.ConnectionError):
        return "接続できませんでした。インターネット接続を確認してください"
    return type(exc).__name__
