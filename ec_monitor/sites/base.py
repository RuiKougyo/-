"""各サイト（楽天・Yahoo!ショッピング）の検索処理の共通の形。"""

from abc import ABC, abstractmethod
from typing import List

from ..config_loader import Watch
from ..models import Item


class SiteClient(ABC):
    """サイトごとの検索クライアントの共通の形。"""

    #: 設定ファイルでのサイト名（"rakuten" など）
    site_id: str = ""
    #: ログや通知に表示するサイト名
    display_name: str = ""
    #: 利用規約で必須のクレジット表示（Discord通知の一番下に必ず入れる）
    credit_text: str = ""

    @abstractmethod
    def search(self, watch: Watch) -> List[Item]:
        """監視条件で商品を検索し、商品のリストを返す。"""
