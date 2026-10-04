# -*- mode: python ; coding: utf-8 -*-
# PyInstaller の設定ファイル（build.bat から使います）
# 1つのexeファイル（TikTokMinecraft.exe）にまとめ、設定サンプルを中に同梱します。
from PyInstaller.utils.hooks import collect_all

datas = [("config.sample.yaml", ".")]
binaries = []
hiddenimports = []
# TikTokLive は通信データの型を実行時に読み込むため、まるごと同梱する
for package in ("TikTokLive", "TikTokLiveProto", "betterproto2", "EulerApiSdk"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "numpy", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TikTokMinecraft",
    debug=False,
    strip=False,
    upx=False,
    console=True,  # 動作状況が見えるよう、黒い画面（コンソール）を表示する
)
