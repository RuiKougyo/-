"""楽天市場（楽天ウェブサービス 市場商品検索API）の検索クライアント。

公式API（2026-07-01版）だけを使い、HTMLの解析（スクレイピング）は一切行いません。

利用規約・仕様上の注意：
・1つのアプリケーションIDにつき「1秒に1回」まで。このツールは2秒間隔に制限しています。
・アプリケーションIDとアクセスキーの両方が必要です。
・アプリ登録時に設定した「許可されたWebサイト」と一致する Origin / Referer を送る必要があります。
  （利用者自身が登録したURLを送ります。他人のサイトを名乗ることはしません）
・「許可IPアドレス」に登録したIPアドレス以外からは利用できません。
・取得した情報は「商品の紹介と商品ページへのリンク」の目的でのみ使います。
・クレジット表示（Supported by Rakuten Developers）が必須です。
"""

import re
from typing import Iterable, List, Optional
from urllib.parse import urlparse

import requests

from ..config_loader import RakutenConfig, Watch
from ..errors import ApiAuthError, ApiRequestError, ApiTemporaryError
from ..http_client import get_with_retry
from ..log_setup import get_logger
from ..models import Item
from ..rate_limiter import RateLimiter
from .base import SiteClient

API_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
HITS_PER_PAGE = 30  # 1回のリクエストで取得できる最大件数

# 設定ファイルの並び順 → 楽天APIの sort パラメータ
SORT_PARAMS = {
    "newest": "-updateTimestamp",
    "price_asc": "+itemPrice",
    "standard": "standard",
}


class RakutenClient(SiteClient):
    site_id = "rakuten"
    display_name = "楽天市場"
    credit_text = "Supported by Rakuten Developers"

    def __init__(
        self,
        config: RakutenConfig,
        limiter: RateLimiter,
        session: Optional[requests.Session] = None,
        retry_waits=None,
        sleep=None,
    ):
        self.config = config
        self.limiter = limiter
        self.session = session or requests.Session()
        self._retry_kwargs = {}
        if retry_waits is not None:
            self._retry_kwargs["retry_waits"] = retry_waits
        if sleep is not None:
            self._retry_kwargs["sleep"] = sleep

        parsed = urlparse(config.allowed_website)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        referer = config.allowed_website if config.allowed_website.endswith("/") else config.allowed_website + "/"
        self.headers = {
            "Origin": origin,
            "Referer": referer,
            "Authorization": f"Bearer {config.access_key}",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    def search(self, watch: Watch) -> List[Item]:
        """監視条件で検索し、最大 max_pages ページ分の商品を返す。"""
        log = get_logger()
        items: List[Item] = []
        for page in range(1, watch.max_pages + 1):
            data = self._request(self._build_params(watch, page))
            if data is None:  # 該当商品なし
                break
            page_items = list(parse_items(data))
            items.extend(page_items)
            page_count = _to_int(data.get("pageCount")) or 0
            log.debug(f"楽天：「{watch.name}」{page}ページ目 {len(page_items)}件（全{page_count}ページ）")
            if page >= page_count or not page_items:
                break
        return items

    def _build_params(self, watch: Watch, page: int) -> dict:
        params = {
            "applicationId": self.config.application_id,
            "accessKey": self.config.access_key,
            "format": "json",
            "formatVersion": 2,
            "keyword": watch.keyword,
            "hits": HITS_PER_PAGE,
            "page": page,
            "sort": SORT_PARAMS[watch.sort],
        }
        if watch.exclude_keywords:
            params["NGKeyword"] = " ".join(watch.exclude_keywords)
        if watch.min_price is not None:
            params["minPrice"] = watch.min_price
        if watch.max_price is not None:
            params["maxPrice"] = watch.max_price
        if watch.in_stock_only:
            params["availability"] = 1
        return params

    def _request(self, params: dict) -> Optional[dict]:
        """APIを呼び出し、成功時はJSONを、該当なしのときは None を返す。"""
        response = get_with_retry(
            self.session,
            API_URL,
            site_label=self.display_name,
            limiter=self.limiter,
            params=params,
            headers=self.headers,
            **self._retry_kwargs,
        )
        status = response.status_code
        detail = _error_detail(response)

        if status == 200:
            try:
                return response.json()
            except ValueError as exc:
                raise ApiTemporaryError("楽天APIの応答を読み取れませんでした（JSON形式ではありません）") from exc

        # 楽天APIは「該当する商品がない」ときに 404 not_found を返す
        if status == 404 and "not_found" in detail.lower():
            return None

        if status in (401, 403):
            raise ApiAuthError(_auth_message(status, detail))

        if status == 400:
            lowered = detail.lower()
            if any(k in lowered for k in ("applicationid", "accesskey", "access_key", "application_id")):
                raise ApiAuthError(
                    "楽天APIにアプリケーションIDまたはアクセスキーが受け付けられませんでした。"
                    "config.yaml の rakuten → application_id と access_key を確認してください。"
                    f"（楽天からの応答：{detail}）"
                )
            raise ApiRequestError(
                "楽天APIが検索条件を受け付けませんでした。キーワードや価格の指定を確認してください。"
                f"（楽天からの応答：{detail}）"
            )

        raise ApiTemporaryError(f"楽天APIが想定外の応答を返しました（HTTP {status}：{detail}）")


# ----------------------------------------------------------------------
# 応答の読み取り
# ----------------------------------------------------------------------


def parse_items(data: dict) -> Iterable[Item]:
    """APIの応答（JSON）から商品を取り出す。formatVersion 1・2 のどちらにも対応する。"""
    for entry in data.get("Items") or data.get("items") or []:
        if isinstance(entry, dict) and "Item" in entry and isinstance(entry["Item"], dict):
            entry = entry["Item"]  # formatVersion=1 の形
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("itemCode") or "").strip()
        price = _to_int(entry.get("itemPrice"))
        url = str(entry.get("itemUrl") or "").strip()
        if not code or price is None or not url:
            continue
        yield Item(
            site="rakuten",
            code=code,
            name=str(entry.get("itemName") or "（商品名なし）").strip(),
            price=price,
            url=url,
            image_url=_first_image(entry.get("mediumImageUrls")),
            shop_name=(str(entry.get("shopName")).strip() or None) if entry.get("shopName") else None,
        )


def _first_image(images) -> Optional[str]:
    """商品画像のURLを1つ取り出し、Discordで見やすい大きさのURLにする。"""
    if not images:
        return None
    first = images[0]
    if isinstance(first, dict):
        first = first.get("imageUrl")
    if not first:
        return None
    # 楽天の画像URLは「_ex=128x128」で大きさを指定しているので、少し大きくする
    return re.sub(r"_ex=\d+x\d+", "_ex=400x400", str(first))


def _to_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _error_detail(response: requests.Response) -> str:
    """エラー応答から、原因の手がかりになる文字だけを取り出す（APIキーは含まれない）。"""
    if response.status_code == 200:
        return ""
    try:
        body = response.json()
    except ValueError:
        return (response.text or "").strip()[:200]
    texts: List[str] = []

    def collect(value):
        if isinstance(value, dict):
            for v in value.values():
                collect(v)
        elif isinstance(value, list):
            for v in value:
                collect(v)
        elif value is not None:
            texts.append(str(value))

    collect(body)
    return " / ".join(texts)[:300]


def _auth_message(status: int, detail: str) -> str:
    """認証・権限エラーの原因の候補を、日本語で分かりやすく伝える。"""
    upper = detail.upper()
    if "CLIENT_IP_NOT_ALLOWED" in upper or ("IP" in upper and "ALLOW" in upper):
        return (
            "楽天APIへのアクセスが拒否されました：このパソコンのIPアドレスが「許可IPアドレス」に登録されていません。"
            "インターネット回線のIPアドレスが変わった可能性があります。"
            "楽天ウェブサービスのアプリ管理画面で、現在のIPアドレスを登録し直してください。"
            "（手順はREADMEの「よくあるトラブル」を参照）"
            f"（楽天からの応答：{detail}）"
        )
    if "REFERRER" in upper or "REFERER" in upper or "ORIGIN" in upper:
        return (
            "楽天APIへのアクセスが拒否されました：「許可されたWebサイト」と一致しません。"
            "config.yaml の rakuten → allowed_website に、楽天のアプリ登録画面の「許可されたWebサイト」と"
            "同じURLを入力してください。"
            f"（楽天からの応答：{detail}）"
        )
    return (
        f"楽天APIへのアクセスが拒否されました（HTTP {status}）。"
        "アプリケーションID・アクセスキー・許可されたWebサイト・許可IPアドレスの設定を確認してください。"
        f"（楽天からの応答：{detail}）"
    )
