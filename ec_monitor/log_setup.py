"""ログ（動作の記録）の設定。

画面とファイルの両方に日本語でログを出します。
ログファイルは1MBごとに切り替え、古いものは5世代まで残して自動で削除します。
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "ec_monitor"


def setup_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    """ログの出力先と書式を設定し、ツール共通のロガーを返す。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    # 2回呼ばれても二重に出力されないよう、既存の出力先は外す
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname_ja)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        log_dir / "monitor.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_JapaneseLevelFilter())
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(_JapaneseLevelFilter())
    logger.addHandler(console_handler)

    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    """ツール共通のロガーを取得する。"""
    return logging.getLogger(LOGGER_NAME)


class _JapaneseLevelFilter(logging.Filter):
    """ログの重要度（INFO/WARNINGなど）を日本語の表記に置き換える。"""

    _NAMES = {
        "DEBUG": "詳細",
        "INFO": "情報",
        "WARNING": "注意",
        "ERROR": "エラー",
        "CRITICAL": "重大",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        record.levelname_ja = self._NAMES.get(record.levelname, record.levelname)
        return True
