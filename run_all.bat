@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ============================================
echo  看盤助手 - 完整啟動器
echo ============================================
echo.
echo  此批次檔將：
echo  1. 執行後端分析產生報告
echo  2. 啟動前端伺服器
echo.
pause
cls

REM ====================
REM 步驟 1: 執行分析
REM ====================
echo [步驟 1/3] 執行股票分析...
echo.

cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 找不到 Python
    pause
    exit /b 1
)

echo 正在分析股票，請稍候...
python main.py --test

if errorlevel 1 (
    echo.
    echo [錯誤] 分析程序失敗
    pause
    exit /b 1
)

echo.
echo [步驟 1/3] 分析完成！
echo.
timeout /t 2 >nul
cls

REM ====================
REM 步驟 2: 啟動伺服器（從專案根目錄）
REM ====================
echo [步驟 2/3] 啟動前端伺服器...
echo.
echo 從專案根目錄啟動，可正確存取 /frontend 與 /reports
echo.

REM 取得可用埠號
set PORT=8080
:check_port
python -c "import socket; s=socket.socket(); s.bind(('127.0.0.1', %PORT%)); s.close()" >nul 2>&1
if errorlevel 1 (
    set /a PORT+=1
    goto check_port
)

echo 伺服器埠號: %PORT%
echo.

REM ====================
REM 步驟 3: 開啟瀏覽器
REM ====================
echo [步驟 3/3] 開啟瀏覽器...
echo.
echo ============================================
echo  看盤助手已就緒！
echo.
echo  網址: http://localhost:%PORT%/frontend/
echo.
echo  請在瀏覽器中檢視報告
echo ============================================
echo.

REM 開啟瀏覽器（連到 /frontend 子目錄）
start http://localhost:%PORT%/frontend/

REM 啟動伺服器（從專案根目錄，讓 /frontend 與 /reports 都可存取）
echo 按 Ctrl+C 停止伺服器
echo.
python -m http.server %PORT% --directory .

REM 結束
echo.
echo 伺服器已停止
pause
