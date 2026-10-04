"""設定ファイル（config.yaml）の読み込みと内容チェック。

間違いがあれば、どこをどう直せばよいかを日本語でまとめて表示します。
"""

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import yaml

from .errors import ConfigError

# 対応しているサイト（Yahoo!ショッピングは次の段階で追加予定）
SUPPORTED_SITES = ("rakuten",)
PLANNED_SITES = ("yahoo",)

# 並び順の指定（設定ファイルでの書き方 → 説明）
SORT_CHOICES = {
    "newest": "更新日時が新しい順",
    "price_asc": "価格が安い順",
    "standard": "楽天の標準の並び順",
}

# 監視間隔の下限（分）。API上限から計算した値がこれより大きければそちらを使う
MIN_INTERVAL_MINUTES = 5
MAX_PAGES_LIMIT = 10

# サイトごとの「リクエストとリクエストの間に空ける秒数」
# 楽天：規約は1秒に1回まで。新APIでは1.5秒未満で429になる報告があるため2秒にする
REQUEST_SPACING_SECONDS = {"rakuten": 2.0}


@dataclass
class DiscordConfig:
    webhook_url: str


@dataclass
class RakutenConfig:
    application_id: str
    access_key: str
    allowed_website: str


@dataclass
class Settings:
    first_run_notify: bool = False
    min_drop_yen: int = 1
    min_drop_percent: float = 0.0
    log_level: str = "INFO"


@dataclass
class Watch:
    name: str
    sites: List[str]
    keyword: str
    exclude_keywords: List[str] = field(default_factory=list)
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    interval_minutes: int = 10
    max_pages: int = 1
    sort: str = "newest"
    in_stock_only: bool = True

    def signature(self) -> str:
        """検索条件の「指紋」。条件が変わったかどうかの判定に使う（名前と間隔は含めない）。"""
        parts = [
            ",".join(sorted(self.sites)),
            self.keyword,
            ",".join(sorted(self.exclude_keywords)),
            str(self.min_price),
            str(self.max_price),
            str(self.max_pages),
            self.sort,
            str(self.in_stock_only),
        ]
        return "|".join(parts)


@dataclass
class AppConfig:
    discord: DiscordConfig
    rakuten: Optional[RakutenConfig]
    settings: Settings
    watches: List[Watch]


def load_config(path: Path) -> AppConfig:
    """設定ファイルを読み込み、内容をチェックして返す。問題があれば ConfigError を出す。"""
    if not path.exists():
        raise ConfigError(f"設定ファイルが見つかりません：{path}")
    try:
        with open(path, encoding="utf-8-sig") as f:  # メモ帳で保存したBOM付きにも対応
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        line = getattr(getattr(exc, "problem_mark", None), "line", None)
        where = f"（{line + 1}行目付近）" if line is not None else ""
        raise ConfigError(
            f"設定ファイルの書き方に誤りがあります{where}。"
            "字下げ（先頭の空白）や「:」の後の空白、全角スペースが混ざっていないか確認してください。"
        ) from exc
    except UnicodeDecodeError as exc:
        raise ConfigError("設定ファイルは「UTF-8」形式で保存してください。") from exc

    return parse_config(raw)


def parse_config(raw) -> AppConfig:
    """読み込んだ内容（辞書）をチェックして AppConfig にする。"""
    errors: List[str] = []
    if not isinstance(raw, dict):
        raise ConfigError("設定ファイルが空か、形式が正しくありません。サンプルをコピーして作り直してください。")

    discord = _parse_discord(raw.get("discord"), errors)
    settings = _parse_settings(raw.get("settings") or {}, errors)
    watches = _parse_watches(raw.get("watches"), errors)

    rakuten = None
    if any("rakuten" in w.sites for w in watches):
        rakuten = _parse_rakuten(raw.get("rakuten"), errors)

    if errors:
        raise ConfigError("設定ファイルに次の問題があります：\n" + "\n".join(f"  ・{e}" for e in errors))

    return AppConfig(discord=discord, rakuten=rakuten, settings=settings, watches=watches)


def minimum_interval_minutes(watches: List[Watch], site: str) -> int:
    """そのサイトの全監視条件を1周したときのリクエスト数から、監視間隔の最小値を計算する。

    1周にかかる時間の2倍以上は空けるようにして、API上限に対して余裕を持たせる。
    """
    total_requests = sum(w.max_pages for w in watches if site in w.sites)
    spacing = REQUEST_SPACING_SECONDS.get(site, 2.0)
    by_limit = math.ceil(total_requests * spacing * 2 / 60)
    return max(MIN_INTERVAL_MINUTES, by_limit)


# ---------------------------------------------------------------------------
# 以下、各項目のチェック
# ---------------------------------------------------------------------------


def _is_placeholder(value: str) -> bool:
    """サンプルのままの値（「ここに～」など）が残っていないか。"""
    return not value or "ここに" in value or "xxxx" in value.lower()


def _parse_discord(raw, errors: List[str]) -> DiscordConfig:
    raw = raw or {}
    url = str(raw.get("webhook_url") or "").strip()
    if _is_placeholder(url):
        errors.append("discord → webhook_url に、DiscordのウェブフックURLを入力してください。")
    elif not (
        url.startswith("https://discord.com/api/webhooks/")
        or url.startswith("https://discordapp.com/api/webhooks/")
        or url.startswith("https://canary.discord.com/api/webhooks/")
        or url.startswith("https://ptb.discord.com/api/webhooks/")
    ):
        errors.append(
            "discord → webhook_url の形式が正しくありません。"
            "「https://discord.com/api/webhooks/」で始まるURLをそのまま貼り付けてください。"
        )
    return DiscordConfig(webhook_url=url)


def _parse_rakuten(raw, errors: List[str]) -> Optional[RakutenConfig]:
    raw = raw or {}
    app_id = str(raw.get("application_id") or "").strip()
    access_key = str(raw.get("access_key") or "").strip()
    website = str(raw.get("allowed_website") or "").strip()

    if _is_placeholder(app_id):
        errors.append("rakuten → application_id に、楽天のアプリケーションIDを入力してください。")
    if _is_placeholder(access_key):
        errors.append("rakuten → access_key に、楽天のアクセスキー（pk_で始まる文字）を入力してください。")
    elif not access_key.startswith("pk_"):
        errors.append(
            "rakuten → access_key は「pk_」で始まる文字です。"
            "アプリケーションIDやアフィリエイトIDと取り違えていないか確認してください。"
        )

    parsed = urlparse(website)
    if _is_placeholder(website) or parsed.netloc.endswith("example.com"):
        errors.append(
            "rakuten → allowed_website に、楽天のアプリ登録で「許可されたWebサイト」に入力したURLを入力してください。"
        )
    elif parsed.scheme not in ("http", "https") or not parsed.netloc:
        errors.append(
            "rakuten → allowed_website は「https://」から始まるURLで入力してください（例：https://myblog.jp）。"
        )
    return RakutenConfig(application_id=app_id, access_key=access_key, allowed_website=website)


def _parse_settings(raw, errors: List[str]) -> Settings:
    if not isinstance(raw, dict):
        errors.append("settings の書き方が正しくありません。")
        return Settings()
    s = Settings()
    s.first_run_notify = _to_bool(raw.get("first_run_notify", s.first_run_notify), "settings → first_run_notify", errors)
    s.min_drop_yen = _to_int(raw.get("min_drop_yen", s.min_drop_yen), "settings → min_drop_yen", errors, minimum=1)
    s.min_drop_percent = _to_float(
        raw.get("min_drop_percent", s.min_drop_percent), "settings → min_drop_percent", errors, minimum=0, maximum=99
    )
    level = str(raw.get("log_level", s.log_level)).upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        errors.append("settings → log_level は INFO / DEBUG / WARNING / ERROR のどれかにしてください。")
        level = "INFO"
    s.log_level = level
    return s


def _parse_watches(raw, errors: List[str]) -> List[Watch]:
    if not isinstance(raw, list) or not raw:
        errors.append("watches に、監視条件を1つ以上登録してください。")
        return []

    watches: List[Watch] = []
    seen_names = set()
    for index, entry in enumerate(raw, start=1):
        label = f"watches の{index}番目"
        if not isinstance(entry, dict):
            errors.append(f"{label} の書き方が正しくありません（先頭に「- 」が必要です）。")
            continue

        name = str(entry.get("name") or "").strip()
        if not name:
            errors.append(f"{label}：name（監視条件の名前）を入力してください。")
            name = f"条件{index}"
        elif name in seen_names:
            errors.append(f"{label}：name「{name}」が他の条件と重複しています。別の名前にしてください。")
        seen_names.add(name)
        label = f"監視条件「{name}」"

        sites = _parse_sites(entry.get("site", "rakuten"), label, errors)

        keyword = str(entry.get("keyword") or "").strip()
        if not keyword:
            errors.append(f"{label}：keyword（検索キーワード）を入力してください。")

        exclude = entry.get("exclude_keywords") or []
        if isinstance(exclude, str):
            exclude = [exclude]
        if not isinstance(exclude, list):
            errors.append(f"{label}：exclude_keywords は [\"中古\", \"ジャンク\"] のように並べて書いてください。")
            exclude = []
        exclude = [str(x).strip() for x in exclude if str(x).strip()]

        min_price = _to_optional_int(entry.get("min_price"), f"{label}：min_price", errors)
        max_price = _to_optional_int(entry.get("max_price"), f"{label}：max_price", errors)
        if min_price is not None and max_price is not None and min_price > max_price:
            errors.append(f"{label}：min_price（下限）が max_price（上限）より大きくなっています。")

        interval = _to_int(entry.get("interval_minutes", 10), f"{label}：interval_minutes", errors, minimum=1)
        max_pages = _to_int(
            entry.get("max_pages", 1), f"{label}：max_pages", errors, minimum=1, maximum=MAX_PAGES_LIMIT
        )

        sort = str(entry.get("sort", "newest")).strip()
        if sort not in SORT_CHOICES:
            choices = " / ".join(f"{k}（{v}）" for k, v in SORT_CHOICES.items())
            errors.append(f"{label}：sort は次のどれかにしてください：{choices}")
            sort = "newest"

        in_stock = _to_bool(entry.get("in_stock_only", True), f"{label}：in_stock_only", errors)

        watches.append(
            Watch(
                name=name,
                sites=sites,
                keyword=keyword,
                exclude_keywords=exclude,
                min_price=min_price,
                max_price=max_price,
                interval_minutes=interval,
                max_pages=max_pages,
                sort=sort,
                in_stock_only=in_stock,
            )
        )
    return watches


def _parse_sites(value, label: str, errors: List[str]) -> List[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value:
        errors.append(f"{label}：site には rakuten を指定してください。")
        return ["rakuten"]
    sites = []
    for v in value:
        v = str(v).strip().lower()
        if v in SUPPORTED_SITES:
            if v not in sites:
                sites.append(v)
        elif v in PLANNED_SITES:
            errors.append(f"{label}：Yahoo!ショッピング（yahoo）はこのバージョンではまだ使えません。rakuten を指定してください。")
        else:
            errors.append(f"{label}：site「{v}」は対応していません。rakuten を指定してください。")
    return sites or ["rakuten"]


def _to_bool(value, label: str, errors: List[str]) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "yes", "on", "1", "はい"):
        return True
    if text in ("false", "no", "off", "0", "いいえ"):
        return False
    errors.append(f"{label} は true か false で指定してください。")
    return False


def _to_int(value, label: str, errors: List[str], minimum=None, maximum=None) -> int:
    try:
        number = int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        errors.append(f"{label} は半角の数字で入力してください（入力値：{value}）。")
        return minimum or 0
    if minimum is not None and number < minimum:
        errors.append(f"{label} は {minimum} 以上にしてください。")
    if maximum is not None and number > maximum:
        errors.append(f"{label} は {maximum} 以下にしてください。")
    return number


def _to_optional_int(value, label: str, errors: List[str]) -> Optional[int]:
    if value is None or str(value).strip() == "":
        return None
    return _to_int(value, label, errors, minimum=0)


def _to_float(value, label: str, errors: List[str], minimum=None, maximum=None) -> float:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        errors.append(f"{label} は半角の数字で入力してください（入力値：{value}）。")
        return 0.0
    if minimum is not None and number < minimum:
        errors.append(f"{label} は {minimum} 以上にしてください。")
    if maximum is not None and number > maximum:
        errors.append(f"{label} は {maximum} 以下にしてください。")
    return number
