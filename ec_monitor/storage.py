"""見つけた商品と価格の記録（SQLiteデータベース）。

一度通知した商品を重複して通知しないため、次の情報だけを保存します。
  ・どの監視条件で見つけたか、商品コード、商品名、最新の価格、最後に通知した価格、日時
商品の説明文や画像などは保存しません（規約上、必要最小限の保存にとどめるため）。
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from .models import Item


class Storage:
    def __init__(self, db_path: Path):
        if str(db_path) != ":memory:":
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    watch_name     TEXT NOT NULL,
                    site           TEXT NOT NULL,
                    item_code      TEXT NOT NULL,
                    item_name      TEXT,
                    last_price     INTEGER,
                    notified_price INTEGER,
                    first_seen     TEXT,
                    last_seen      TEXT,
                    last_notified  TEXT,
                    PRIMARY KEY (watch_name, site, item_code)
                )
                """
            )
            # 監視条件ごとの状態（初回チェックが済んだか、検索条件の指紋）
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watch_state (
                    watch_name  TEXT NOT NULL,
                    site        TEXT NOT NULL,
                    signature   TEXT NOT NULL,
                    initialized TEXT NOT NULL,
                    PRIMARY KEY (watch_name, site)
                )
                """
            )

    # ------------------------------------------------------------------
    # 監視条件の状態
    # ------------------------------------------------------------------
    def is_initialized(self, watch_name: str, site: str, signature: str) -> bool:
        """この監視条件（同じ検索条件）で、初回チェックが済んでいるか。

        検索条件を変更した場合は「初回」扱いに戻し、大量の通知が来ないようにする。
        """
        row = self.conn.execute(
            "SELECT signature FROM watch_state WHERE watch_name=? AND site=?", (watch_name, site)
        ).fetchone()
        return row is not None and row["signature"] == signature

    def mark_initialized(self, watch_name: str, site: str, signature: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO watch_state (watch_name, site, signature, initialized) VALUES (?, ?, ?, ?)",
                (watch_name, site, signature, _now()),
            )

    # ------------------------------------------------------------------
    # 商品の記録
    # ------------------------------------------------------------------
    def get_known(self, watch_name: str, site: str) -> Dict[str, sqlite3.Row]:
        """この監視条件で記録済みの商品を {商品コード: 記録} で返す。"""
        rows = self.conn.execute(
            "SELECT * FROM items WHERE watch_name=? AND site=?", (watch_name, site)
        ).fetchall()
        return {row["item_code"]: row for row in rows}

    def record_seen(self, watch_name: str, item: Item, notified_price: Optional[int] = None) -> None:
        """商品を見かけたことを記録する。notified_price を渡したときは「通知済み価格」も更新する。"""
        now = _now()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO items (watch_name, site, item_code, item_name, last_price,
                                   notified_price, first_seen, last_seen, last_notified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (watch_name, site, item_code) DO UPDATE SET
                    item_name = excluded.item_name,
                    last_price = excluded.last_price,
                    last_seen = excluded.last_seen,
                    notified_price = COALESCE(excluded.notified_price, items.notified_price),
                    last_notified = COALESCE(excluded.last_notified, items.last_notified)
                """,
                (
                    watch_name,
                    item.site,
                    item.code,
                    item.name,
                    item.price,
                    notified_price,
                    now,
                    now,
                    now if notified_price is not None else None,
                ),
            )

    def close(self) -> None:
        self.conn.close()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
