@echo off
chcp 65001 > nul
cd /d %~dp0
rem Minecraftサーバーにつながるかだけ確認します
TikTokMinecraft.exe --check
pause
