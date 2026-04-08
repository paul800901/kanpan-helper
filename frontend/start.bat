@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ============================================
echo  看盤助手 - 本地啟動器
echo ============================================
echo.

REM 檢查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 找不到 Python，請確認已安裝 Python 並加入 PATH
    pause
    exit /b 1
)

echo [1/3] Python 檢查通過
echo.

REM 取得可用埠號
set PORT=8080
:check_port
python -c "import socket; s=socket.socket(); s.bind(('127.0.0.1', %PORT%)); s.close()" >nul 2>&1
if errorlevel 1 (
    set /a PORT+=1
    goto check_port
)

echo [2/3] 使用埠號: %PORT%
echo.

REM 啟動伺服器
echo [3/3] 啟動 HTTP 伺服器...
echo.
echo ----------------------------------------
echo  伺服器已啟動！
echo  網址: http://localhost:%PORT%
echo.
echo  按 Ctrl+C 停止伺服器
echo ----------------------------------------
echo.

REM 嘗試自動開啟瀏覽器
timeout /t 1 >nul
start http://localhost:%PORT%

REM 啟動 Python 伺服器
python -m http.server %PORT%

REM 伺服器停止後
echo.
echo 伺服器已停止
pause
