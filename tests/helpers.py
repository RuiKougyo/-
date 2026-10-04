"""テスト用の部品（偽の通信・偽のDiscordなど）。実際のAPIには一切アクセスしない。"""

import json

from ec_monitor.config_loader import parse_config


class FakeResponse:
    def __init__(self, status_code=200, body=None, headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.text = json.dumps(body, ensure_ascii=False) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    """あらかじめ用意した応答を順番に返す偽の通信。送った内容は calls に記録する。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def _next(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url, **kwargs):
        return self._next("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._next("POST", url, **kwargs)


class NoWaitLimiter:
    def wait(self):
        pass


def valid_raw_config(**watch_overrides):
    watch = {
        "name": "テスト条件",
        "site": "rakuten",
        "keyword": "Switch 本体",
        "exclude_keywords": ["中古"],
        "min_price": 1000,
        "max_price": 50000,
        "interval_minutes": 10,
        "max_pages": 1,
    }
    watch.update(watch_overrides)
    return {
        "discord": {"webhook_url": "https://discord.com/api/webhooks/123/abc"},
        "rakuten": {
            "application_id": "2fc160ec-1111-2222-3333-444455556666",
            "access_key": "pk_testkey",
            "allowed_website": "https://myblog.jp",
        },
        "settings": {"first_run_notify": False},
        "watches": [watch],
    }


def make_config(**watch_overrides):
    return parse_config(valid_raw_config(**watch_overrides))


def rakuten_item(code, price, name=None):
    return {
        "itemCode": code,
        "itemName": name or f"商品{code}",
        "itemPrice": price,
        "itemUrl": f"https://item.rakuten.co.jp/shop/{code}/",
        "mediumImageUrls": [f"https://thumbnail.image.rakuten.co.jp/{code}.jpg?_ex=128x128"],
        "shopName": "テストショップ",
    }


def rakuten_body(items, page_count=1):
    return {"count": len(items), "page": 1, "pageCount": page_count, "Items": items}
