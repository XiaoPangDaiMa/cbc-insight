@echo off
rem 双击这个文件即可启动（Windows）。参数会原样传给 start.ps1，例如：
rem   start.bat -NoBrowser
chcp 65001 >nul
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 (
    echo.
    echo 启动过程中出错，请把上面的红字发给开发者。
    pause
) else (
    timeout /t 3 >nul
)
endlocal
