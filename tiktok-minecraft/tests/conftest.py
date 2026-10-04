import sys
from pathlib import Path

# テストから tiktok_mc パッケージを読み込めるようにする
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
