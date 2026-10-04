@echo off
chcp 65001 > nul
cd /d %~dp0
rem 配信を待って自動で接続し、ギフトでギミックを動かします（本番）
TikTokMinecraft.exe
pause
