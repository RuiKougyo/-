import sys
from pathlib import Path

# tests フォルダから ec_monitor と helpers を読み込めるようにする
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
