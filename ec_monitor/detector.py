"""「新着」「値下げ」の判定。

・新着：その監視条件で、これまで一度も見つけていない商品
・値下げ：前回通知したときの価格より、設定した金額・割合以上安くなった商品
  （価格が上下を繰り返しても、同じ値下げを何度も通知しないため「前回通知した価格」と比べる）
・初回チェック：設定（first_run_notify: false）では、通知せずに記録だけ行う
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .config_loader import Settings
from .models import Item, Notification


@dataclass
class DetectResult:
    #: 通知する商品
    notifications: List[Notification] = field(default_factory=list)
    #: 通知せずに記録だけする商品（商品, 通知済み価格として記録する値 または None）
    silent: List[Tuple[Item, Optional[int]]] = field(default_factory=list)


def detect_changes(
    watch_name: str,
    items: List[Item],
    known: Dict[str, "object"],
    *,
    first_run: bool,
    settings: Settings,
) -> DetectResult:
    result = DetectResult()
    seen_codes = set()

    for item in items:
        # 複数ページで同じ商品が出てきた場合は1回だけ扱う
        if item.code in seen_codes:
            continue
        seen_codes.add(item.code)

        row = known.get(item.code)
        if row is None:
            if first_run and not settings.first_run_notify:
                # 初回は記録だけ。今の価格を「通知済み価格」として、以後の値下げ判定の基準にする
                result.silent.append((item, item.price))
            else:
                result.notifications.append(Notification(kind="new", watch_name=watch_name, item=item))
            continue

        reference = row["notified_price"] if row["notified_price"] is not None else row["last_price"]
        if reference is not None and is_price_drop(reference, item.price, settings):
            result.notifications.append(
                Notification(kind="drop", watch_name=watch_name, item=item, old_price=reference)
            )
        else:
            result.silent.append((item, None))

    return result


def is_price_drop(old_price: int, new_price: int, settings: Settings) -> bool:
    """設定した条件（金額・割合）を満たす値下げかどうか。"""
    if new_price >= old_price or old_price <= 0:
        return False
    diff = old_price - new_price
    if diff < settings.min_drop_yen:
        return False
    if diff / old_price * 100 < settings.min_drop_percent:
        return False
    return True
