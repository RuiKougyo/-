@echo off
chcp 65001 > nul
cd /d %~dp0
rem キーボードで「ギフトが来たふり」をして、Minecraftで動作確認します
TikTokMinecraft.exe --test
pause
