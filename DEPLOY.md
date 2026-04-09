# Kanpan Helper v5 部署指南

## 架構概述

```
kanpan-helper/                      # GitHub repository
├── .github/workflows/
│   ├── daily-report.yml           # 自動生成每日報告
│   └── deploy-pages.yml           # 部署到 GitHub Pages
├── frontend/                      # PWA 前端 (部署到 GitHub Pages)
│   ├── index.html
│   ├── app.js
│   └── ...
├── reports/                       # 生成的報告檔案
│   ├── index.json
│   ├── YYYY-MM-DD.json
│   └── YYYY-MM-DD-lite.json
└── backend/                       # Python 分析程式
    └── ...
```

## GitHub 設定

### 1. Repository Secrets

必須設定以下 secret：
- `FINMIND_API_TOKEN`: FinMind API 的授權 token

設定路徑：
```
GitHub Repository → Settings → Secrets and variables → Actions → New repository secret
```

### 2. GitHub Pages 設定

設定 GitHub Pages 發布來源：
```
GitHub Repository → Settings → Pages

Build and deployment:
  Source: GitHub Actions
```

設定完成後，deploy-pages.yml 會自動部署 frontend 和 reports 目錄。

### 3. Workflow 權限

確保 workflow 有寫入權限：
```
GitHub Repository → Settings → Actions → General

Workflow permissions:
  ✓ Read and write permissions
```

## 工作流程

### Daily Report Generation (daily-report.yml)

**觸發條件：**
- 每天 UTC 00:00 (台灣時間 08:00)
- 手動觸發 (workflow_dispatch)

**執行步驟：**
1. Checkout repository
2. 安裝 Python 依賴
3. **備份**現有的 `reports/index.json`
4. 執行 `python main.py` 生成報告
5. **安全更新**: 若報告生成失敗，自動恢復備份的 index.json
6. Commit 並 push 新的報告檔案

**環境變數：**
- `FINMIND_API_TOKEN`: 從 repository secrets 讀取

**安全機制：**
- 失敗時自動恢復 index.json，確保前端不會因單次失敗而無法載入歷史報告
- 只提交 reports/ 和 data/ 目錄，不影響其他檔案

### Deploy to GitHub Pages (deploy-pages.yml)

**觸發條件：**
- 手動觸發 (workflow_dispatch)
- Push 到 main 分支且修改 `frontend/**` 或 `reports/**`

**執行步驟：**
1. Checkout repository
2. 設定 Pages
3. 準備網站內容：
   - 複製 frontend/* 到網站根目錄
   - 複製 reports/ 到網站根目錄
   - 建立 `.nojekyll` 防止 Jekyll 處理
4. 部署到 GitHub Pages

**公開路徑：**
- 網站: `https://paul800901.github.io/kanpan-helper/`
- 報告: `https://paul800901.github.io/kanpan-helper/reports/`

## 環境變數

### REPORT_BASE_URL

前端使用此變數決定報告檔案的基礎路徑：

**本地開發：**
```javascript
REPORT_BASE_URL = '../reports'  // 相對路徑
```

**GitHub Pages：**
```javascript
REPORT_BASE_URL = 'https://paul800901.github.io/kanpan-helper/reports'
```

實作方式：前端自動偵測是否在 GitHub Pages 上執行。

### FINMIND_API_TOKEN

Python 後端從環境變數讀取：
```python
import os
api_token = os.environ.get('FINMIND_API_TOKEN')
```

在 GitHub Actions 中自動注入：
```yaml
env:
  FINMIND_API_TOKEN: ${{ secrets.FINMIND_API_TOKEN }}
```

## 本地測試

### 產生報告
```bash
# 完整模式
python main.py

# 測試模式（只跑3檔）
python main.py --test

# 使用快取
python main.py --use-cache
```

### 本地啟動前端
```bash
cd frontend
python -m http.server 8000
```

然後瀏覽 `http://localhost:8000`

## 第一次部署步驟

### 1. 手動觸發報告生成
```
GitHub Repository → Actions → Daily Report Generation → Run workflow
Select: full mode
```

### 2. 確認報告生成成功
檢查 Actions log 確認：
- 成功抓取股票資料
- 報告檔案已生成
- index.json 已更新
- 自動 commit 到 main

### 3. 手動觸發 Pages 部署
```
GitHub Repository → Actions → Deploy to GitHub Pages → Run workflow
```

### 4. 驗證部署結果
- 等待部署完成（約 1-2 分鐘）
- 瀏覽 `https://paul800901.github.io/kanpan-helper/`
- 確認能載入報告和顯示正確日期

### 5. 設定自動排程
- daily-report.yml 已設定每天 UTC 00:00 自動執行
- deploy-pages.yml 會在報告提交後自動觸發（如有修改 frontend 或 reports）

## 故障排除

### 報告生成失敗
- 檢查 Actions log 中的錯誤訊息
- 確認 FINMIND_API_TOKEN 是否有效
- 檢查是否超過 API 速率限制

### GitHub Pages 部署失敗
- 確認 Pages 設定為 "GitHub Actions"
- 檢查 deploy-pages.yml log
- 確認公開網址是否正確

### 前端無法載入報告
- 開啟瀏覽器開發者工具，檢查 network tab
- 確認 index.json 路徑是否正確
- 確認 CORS 問題（GitHub Pages 自動處理）

## 版本資訊

- **v5.0.0**: 最小可用部署版
  - 支援 GitHub Actions 自動生成報告
  - 支援 GitHub Pages 部署
  - 安全更新 index.json 機制
  - 自動偵測 REPORT_BASE_URL
