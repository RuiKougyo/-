@echo off
chcp 65001 > nul
rem ============================================================
rem  ECMonitor.exe を作るためのバッチファイル（開発者用）
rem  Python 3.10以上が入ったWindowsで、このファイルをダブルクリックしてください。
rem  完成すると「release」フォルダに exe と設定サンプル、READMEがそろいます。
rem ============================================================
cd /d %~dp0

echo [1/4] 作業用の環境を作成しています...
if not exist .venv (
    python -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error

echo [2/4] 必要なライブラリを入れています...
python -m pip install --upgrade pip > nul
python -m pip install -r requirements-dev.txt || goto :error

echo [3/4] テストを実行しています...
python -m pytest -q || goto :error

echo [4/4] exeを作成しています...
pyinstaller --clean --noconfirm ec_monitor.spec || goto :error

if exist release rmdir /s /q release
mkdir release
copy dist\ECMonitor.exe release\ > nul
copy config.sample.yaml release\ > nul
copy README.md release\ > nul

echo.
echo 完成しました。「release」フォルダの中身を配布してください。
pause
exit /b 0

:error
echo.
echo エラーが起きたため、途中で終了しました。上のメッセージを確認してください。
pause
exit /b 1
