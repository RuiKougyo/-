import pytest
import requests

from ec_monitor.errors import ApiAuthError, ApiRateLimitError, ApiRequestError, ApiTemporaryError
from ec_monitor.sites.rakuten import API_URL, RakutenClient, parse_items
from helpers import FakeResponse, FakeSession, NoWaitLimiter, make_config, rakuten_body, rakuten_item


def make_client(responses, **watch):
    config = make_config(**watch)
    session = FakeSession(responses)
    sleeps = []
    client = RakutenClient(
        config.rakuten, NoWaitLimiter(), session=session, retry_waits=(10, 30), sleep=sleeps.append
    )
    return client, config.watches[0], session, sleeps


def test_検索パラメータとヘッダー():
    client, watch, session, _ = make_client([FakeResponse(200, rakuten_body([rakuten_item("a:1", 3000)]))])
    items = client.search(watch)
    assert len(items) == 1

    method, url, kwargs = session.calls[0]
    assert url == API_URL
    params = kwargs["params"]
    assert params["applicationId"] == "2fc160ec-1111-2222-3333-444455556666"
    assert params["accessKey"] == "pk_testkey"
    assert params["keyword"] == "Switch 本体"
    assert params["NGKeyword"] == "中古"
    assert params["minPrice"] == 1000 and params["maxPrice"] == 50000
    assert params["sort"] == "-updateTimestamp"
    assert params["formatVersion"] == 2
    assert params["availability"] == 1
    # 利用者が登録したWebサイトを Origin / Referer として送る
    assert kwargs["headers"]["Origin"] == "https://myblog.jp"
    assert kwargs["headers"]["Referer"] == "https://myblog.jp/"


def test_商品の読み取り_formatVersion2():
    items = list(parse_items(rakuten_body([rakuten_item("shop:1", 1980, "テスト商品")])))
    item = items[0]
    assert item.code == "shop:1"
    assert item.price == 1980
    assert item.name == "テスト商品"
    assert item.shop_name == "テストショップ"
    assert item.image_url.endswith("_ex=400x400")


def test_商品の読み取り_formatVersion1():
    body = {"Items": [{"Item": {**rakuten_item("shop:2", 500), "mediumImageUrls": [{"imageUrl": "https://x/y.jpg"}]}}]}
    item = list(parse_items(body))[0]
    assert item.code == "shop:2"
    assert item.image_url == "https://x/y.jpg"


def test_必須項目が欠けた商品は読み飛ばす():
    body = rakuten_body([{"itemName": "コードなし", "itemPrice": 100}, rakuten_item("ok:1", 100)])
    assert [i.code for i in parse_items(body)] == ["ok:1"]


def test_複数ページを取得し_最終ページで止まる():
    page1 = rakuten_body([rakuten_item(f"a:{i}", 1000 + i) for i in range(30)], page_count=2)
    page2 = rakuten_body([rakuten_item("b:1", 2000)], page_count=2)
    client, watch, session, _ = make_client([FakeResponse(200, page1), FakeResponse(200, page2)], max_pages=5)
    items = client.search(watch)
    assert len(items) == 31
    assert len(session.calls) == 2
    assert session.calls[1][2]["params"]["page"] == 2


def test_該当なし404は空のリスト():
    body = {"error": "not_found", "error_description": "not found"}
    client, watch, _, _ = make_client([FakeResponse(404, body)])
    assert client.search(watch) == []


def test_許可IPのエラーは日本語で案内する():
    body = {"errors": {"errorCode": 403, "errorMessage": "CLIENT_IP_NOT_ALLOWED"}}
    client, watch, _, _ = make_client([FakeResponse(403, body)])
    with pytest.raises(ApiAuthError, match="許可IPアドレス"):
        client.search(watch)


def test_許可サイトのエラーは日本語で案内する():
    body = {"errors": {"errorMessage": "REQUEST_CONTEXT_BODY_HTTP_REFERRER_MISSING"}}
    client, watch, _, _ = make_client([FakeResponse(403, body)])
    with pytest.raises(ApiAuthError, match="許可されたWebサイト"):
        client.search(watch)


def test_アプリIDの誤りは認証エラー():
    body = {"error": "wrong_parameter", "error_description": "specify valid applicationId"}
    client, watch, _, _ = make_client([FakeResponse(400, body)])
    with pytest.raises(ApiAuthError):
        client.search(watch)


def test_検索条件の誤りはリクエストエラー():
    body = {"error": "wrong_parameter", "error_description": "keyword is not valid"}
    client, watch, _, _ = make_client([FakeResponse(400, body)])
    with pytest.raises(ApiRequestError):
        client.search(watch)


def test_429は待ってから再試行し_成功すればそのまま続く():
    ok = FakeResponse(200, rakuten_body([rakuten_item("a:1", 100)]))
    client, watch, session, sleeps = make_client([FakeResponse(429, {"error": "too_many_requests"}), ok])
    assert len(client.search(watch)) == 1
    assert sleeps == [10]


def test_429が続くと回数上限エラー():
    too_many = FakeResponse(429, {"error": "too_many_requests"}, headers={"Retry-After": "60"})
    client, watch, session, sleeps = make_client([too_many, too_many, too_many])
    with pytest.raises(ApiRateLimitError):
        client.search(watch)
    assert len(session.calls) == 3
    assert sleeps == [60, 60]  # Retry-After の指定に従う


def test_通信エラーが続くと一時エラー():
    error = requests.ConnectionError("down")
    client, watch, _, sleeps = make_client([error, error, error])
    with pytest.raises(ApiTemporaryError, match="インターネット接続"):
        client.search(watch)
    assert sleeps == [10, 30]
