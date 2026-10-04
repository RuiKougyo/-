# -*- mode: python ; coding: utf-8 -*-
# PyInstaller の設定ファイル（build.bat から使います）
# 1つのexeファイル（ECMonitor.exe）にまとめ、設定サンプルを中に同梱します。

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    # 設定ファイルがないときに、ひな形として書き出すために同梱する
    datas=[("config.sample.yaml", ".")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # 使わない大きなライブラリは入れない（exeを小さくするため）
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
    name="ECMonitor",
    debug=False,
    strip=False,
    upx=False,
    console=True,  # 動作状況が見えるよう、黒い画面（コンソール）を表示する
)
