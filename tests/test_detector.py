from ec_monitor.config_loader import Settings
from ec_monitor.detector import detect_changes, is_price_drop
from ec_monitor.filters import filter_items
from ec_monitor.models import Item
from helpers import make_config


def item(code, price, name="商品"):
    return Item(site="rakuten", code=code, name=name, price=price, url="https://example.jp/" + code)


def row(last_price, notified_price):
    return {"last_price": last_price, "notified_price": notified_price}


def test_初回は通知せず記録だけ():
    result = detect_changes("w", [item("a", 100)], {}, first_run=True, settings=Settings())
    assert result.notifications == []
    assert result.silent == [(item("a", 100), 100)]


def test_初回でも設定次第で通知する():
    result = detect_changes("w", [item("a", 100)], {}, first_run=True, settings=Settings(first_run_notify=True))
    assert [n.kind for n in result.notifications] == ["new"]


def test_2回目以降の未知の商品は新着():
    result = detect_changes("w", [item("a", 100), item("b", 200)], {"a": row(100, 100)}, first_run=False, settings=Settings())
    assert [(n.kind, n.item.code) for n in result.notifications] == [("new", "b")]


def test_値下げを検知し_前の価格を持つ():
    result = detect_changes("w", [item("a", 800)], {"a": row(1000, 1000)}, first_run=False, settings=Settings())
    n = result.notifications[0]
    assert n.kind == "drop" and n.old_price == 1000 and n.item.price == 800


def test_値上がりや同じ価格は通知しない():
    known = {"a": row(1000, 1000)}
    for price in (1000, 1200):
        result = detect_changes("w", [item("a", price)], known, first_run=False, settings=Settings())
        assert result.notifications == []


def test_価格が行き来しても同じ値下げを繰り返し通知しない():
    # 1000円で通知済み → 900円で通知済み（notified=900）→ 1000円に戻った → また900円
    known = {"a": row(1000, 900)}
    result = detect_changes("w", [item("a", 900)], known, first_run=False, settings=Settings())
    assert result.notifications == []


def test_同じ商品が複数ページに出ても1回だけ():
    result = detect_changes("w", [item("a", 100), item("a", 100)], {}, first_run=False, settings=Settings())
    assert len(result.notifications) == 1


def test_値下げの金額と割合のしきい値():
    assert is_price_drop(1000, 999, Settings(min_drop_yen=1))
    assert not is_price_drop(1000, 999, Settings(min_drop_yen=100))
    assert is_price_drop(1000, 900, Settings(min_drop_yen=100, min_drop_percent=10))
    assert not is_price_drop(1000, 950, Settings(min_drop_percent=10))


def test_除外キーワードと価格で絞り込む():
    watch = make_config(exclude_keywords=["中古", "ｼﾞｬﾝｸ"], min_price=1000, max_price=5000).watches[0]
    items = [
        item("ok", 3000, "新品 Switch"),
        item("used", 3000, "【中古】Switch"),
        item("junk", 3000, "ジャンク品 Switch"),  # 半角カナの除外語でも全角の商品名に一致
        item("cheap", 500, "Switch"),
        item("expensive", 9000, "Switch"),
    ]
    assert [i.code for i in filter_items(items, watch)] == ["ok"]
