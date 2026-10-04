"""ツール内でやり取りするデータの形。"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Item:
    """APIから取得した1つの商品。サイトの違いはここで吸収する。"""

    site: str  # "rakuten" / "yahoo"
    code: str  # サイト内で商品を一意に識別するコード
    name: str
    price: int
    url: str
    image_url: Optional[str] = None
    shop_name: Optional[str] = None


@dataclass
class Notification:
    """Discordへ送る1件分の通知内容。"""

    kind: str  # "new"（新着） / "drop"（値下げ）
    watch_name: str
    item: Item
    old_price: Optional[int] = None  # 値下げ前の価格（新着のときはNone）
