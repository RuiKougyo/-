"""取得した商品を、設定した条件でもう一度絞り込む。

APIにも除外キーワードや価格の条件を渡していますが、
表記ゆれ（全角・半角、大文字・小文字）や条件の取りこぼしを防ぐため、
手元でも同じ条件で確認します。
"""

import unicodedata
from typing import Iterable, List

from .config_loader import Watch
from .models import Item


def normalize(text: str) -> str:
    """全角英数字を半角に、大文字を小文字にそろえて比較しやすくする。"""
    return unicodedata.normalize("NFKC", text or "").lower()


def filter_items(items: Iterable[Item], watch: Watch) -> List[Item]:
    """監視条件に合わない商品を取り除く。"""
    excluded = [normalize(k) for k in watch.exclude_keywords]
    result = []
    for item in items:
        if item.price <= 0:
            continue
        if watch.min_price is not None and item.price < watch.min_price:
            continue
        if watch.max_price is not None and item.price > watch.max_price:
            continue
        name = normalize(item.name)
        if any(k and k in name for k in excluded):
            continue
        result.append(item)
    return result
