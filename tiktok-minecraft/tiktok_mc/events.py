"""TikTokから届く出来事（ギフト・フォロー等）を、ツール内で扱いやすい形にそろえたもの。

TikTokLiveライブラリのイベントは種類ごとに形がバラバラなので、
ここで1つの形（LiveEvent）にそろえてから、ルール判定に渡します。
テストモード（手入力での動作確認）でも同じ形を使います。
"""

from dataclasses import dataclass

GIFT = "gift"
FOLLOW = "follow"
SHARE = "share"
LIKE = "like"
COMMENT = "comment"
JOIN = "join"
SUBSCRIBE = "subscribe"

ALL_KINDS = (GIFT, FOLLOW, SHARE, LIKE, COMMENT, JOIN, SUBSCRIBE)


@dataclass
class LiveEvent:
    kind: str
    user_id: str = ""
    username: str = ""  # @から始まるID（例：tiktok_taro）
    nickname: str = ""  # 表示名（例：たろう）
    gift_name: str = ""
    gift_id: int = 0
    coins: int = 0  # ギフト1個あたりのコイン数
    count: int = 1  # ギフトの個数・いいねの数
    comment: str = ""

    @property
    def display_name(self) -> str:
        return self.nickname or self.username or "だれか"
