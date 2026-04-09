@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ============================================
echo  看盤助手 - 前端啟動器
echo ============================================
echo.

REM 檢查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 找不到 Python，請確認已安裝 Python 並加入 PATH
    pause
    exit /b 1
)

echo [1/2] Python 檢查通過
echo.

REM 保持在專案根目錄
cd /d "%~dp0" 2>nul
if errorlevel 1 (
    echo [錯誤] 無法進入專案目錄
    pause
    exit /b 1
)

echo [2/2] 使用專案根目錄
echo.

REM 取得可用埠號
set PORT=8080
:check_port
python -c "import socket; s=socket.socket(); s.bind(('127.0.0.1', %PORT%)); s.close()" >nul 2>&1
if errorlevel 1 (
    set /a PORT+=1
    goto check_port
)

echo 使用埠號: %PORT%
echo.
echo ----------------------------------------
echo  看盤助手已啟動！
echo.
echo  請在瀏覽器開啟:
echo  http://localhost:%PORT%/frontend/
echo.
echo  或等待自動開啟...
echo ----------------------------------------
echo.

REM 嘗試自動開啟瀏覽器
timeout /t 2 >nul
start http://localhost:%PORT%/frontend/

REM 啟動 Python 伺服器（從專案根目錄啟動）
echo 按 Ctrl+C 停止伺服器
echo.
python -m http.server %PORT% --directory .

REM 伺服器停止後
echo.
echo 伺服器已停止
pause

REM 伺服器停止後
echo.
echo 伺服器已停止
pause
