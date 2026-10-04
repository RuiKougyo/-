"""ログ（動作の記録）の設定。

画面とファイルの両方に日本語でログを出します。
ログファイルは1MBごとに切り替え、古いものは5世代まで残して自動で削除します。
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "tiktok_mc"

_LEVEL_JA = {
    "DEBUG": "詳細",
    "INFO": "情報",
    "WARNING": "注意",
    "ERROR": "エラー",
    "CRITICAL": "重大",
}


class _JapaneseLevelFilter(logging.Filter):
    """ログの重要度を日本語にして、書式から参照できるようにする。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.levelname_ja = _LEVEL_JA.get(record.levelname, record.levelname)
        return True


def setup_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    """ログの出力先と書式を設定し、ツール共通のロガーを返す。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname_ja)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler = RotatingFileHandler(
        log_dir / "live.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    console_handler = logging.StreamHandler()
    for handler in (file_handler, console_handler):
        handler.setFormatter(formatter)
        handler.addFilter(_JapaneseLevelFilter())
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(name: str = "") -> logging.Logger:
    """ツール共通ロガー（またはその子ロガー）を返す。"""
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)
