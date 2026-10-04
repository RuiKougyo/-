"""ファイルの置き場所を決めるモジュール。

exe化したときは「exeが置いてあるフォルダ」、
Pythonで直接動かしたときは「プロジェクトのフォルダ」を基準にします。
"""

import sys
from pathlib import Path


def base_dir() -> Path:
    """設定ファイル・ログ・記録データを置く基準フォルダを返す。"""
    if getattr(sys, "frozen", False):
        # PyInstallerでexe化されている場合は、exeのあるフォルダ
        return Path(sys.executable).resolve().parent
    # 通常のPython実行時は、このパッケージの1つ上（プロジェクトのフォルダ）
    return Path(__file__).resolve().parent.parent


def bundled_file(name: str) -> Path:
    """exeの中に同梱したファイル（設定サンプルなど）の場所を返す。"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / name
    return base_dir() / name
