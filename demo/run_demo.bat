@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

set PY=
where python >nul 2>nul && set PY=python
if "%PY%"=="" (where py >nul 2>nul && set PY=py -3)
if "%PY%"=="" (
  echo [!] 没找到 Python。请先安装 Python 3.10+（脚本只用标准库，无第三方依赖）。
  pause
  exit /b 1
)

echo ============================================================
echo  看山 · 本地演示（离线，不联网，不需要任何账号授权）
echo  ============================================================
%PY% demo\server.py
if errorlevel 1 pause
endlocal
