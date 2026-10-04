"""ツールの入口。PyInstallerはこのファイルからexeを作ります。

Pythonで直接動かす場合：  python run.py
"""

import sys

from tiktok_mc.main import main

if __name__ == "__main__":
    sys.exit(main())
