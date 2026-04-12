# Kanpan Helper v5 部署指南

## 架構變更（v5 單一 workflow）

**v5 重要更新**：改用單一 GitHub Actions workflow 完成報告生成、持久化和部署，解決 GITHUB_TOKEN push 不會觸發新 workflow 的 GitHub 限制。

```
kanpan-helper/                      # GitHub repository
├── .github/workflows/
│   └── daily-report.yml           # 單一 workflow：生成→commit→部署
├── frontend/                      # PWA 前端 (部署到 GitHub Pages)
│   ├── index.html
│   ├── app.js
│   └── ...
├── reports/                       # 生成的報告檔案（持久化到 repo）
│   ├── index.json
│   ├── YYYY-MM-DD.json
│   └── YYYY-MM-DD-lite.json
└── backend/                       # Python 分析程式
    └── ...
```

## GitHub 設定

### 1. Repository Secret

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

### 3. Workflow 權限

確保 workflow 有寫入權限：
```
GitHub Repository → Settings → Actions → General

Workflow permissions:
  ✓ Read and write permissions
```

## 運作流程

### Daily Report Generation and Deploy (daily-report.yml)

**觸發條件：**
- 每天 UTC 00:00 (台灣時間 08:00) 自動執行
- 手動觸發 (workflow_dispatch) 可選 full 或 test 模式

**執行步驟（單一 workflow 完成）：**
1. Checkout repository
2. 安裝 Python 依賴
3. 執行 `python main.py` 生成報告（支援 `--test` 模式）
4. 驗證報告格式（檢查 YYYY-MM-DD.json、YYYY-MM-DD-lite.json、index.json）
5. **Commit/Push** reports/ 目錄到 main 分支（持久化）
   - Commit message: `chore: update daily report YYYY-MM-DD`
   - 只添加 reports/，不添加 data/
6. **直接部署** GitHub Pages（在同一 workflow 內完成，不依賴 push 觸發）
   - 複製 frontend/* → _site/
   - 複製 reports/ → _site/
   - 上傳 artifact 並部署到 Pages

**環境變數：**
- `FINMIND_API_TOKEN`: 從 repository secrets 讀取

**安全機制：**
- 報告生成失敗時 workflow 會失敗，不會繼續部署
- index.json 使用原子化更新（原子替換機制，確保失敗時保留舊檔）
- 透過 `permissions` 設定限制 GITHUB_TOKEN 權限

## 本地與遠端同步注意

- GitHub Actions 會在遠端直接生成、commit、push `reports/`，因此 GitHub 遠端或桌面 Git 倉庫的 `reports/` 可能比雲端本體新。
- 開始本地除錯、查資料或修改前，先檢查桌面 Git 倉庫或遠端的 `reports/index.json` 是否較新，避免用舊資料判讀線上問題。
- 如果桌面 Git 倉庫的 `reports/` 較新，先反向同步回雲端本體，再以雲端本體作為主要開發目錄。

### 反向同步 `reports/` 範例

```powershell
Copy-Item "$env:USERPROFILE\Desktop\kanpan_helper_github_sync\kanpan-helper\reports\*.json" "G:\我的雲端硬碟\kanpan-helper\reports\" -Force
```

- 反向同步完成後，再確認雲端本體的 `reports/index.json` 已更新到最新日期。

## 環境變數

### REPORT_BASE_URL (前端自動偵測)

**本地開發：**
```javascript
REPORT_BASE_URL = '../reports'  // 相對路徑
```

**GitHub Pages：**
```javascript
REPORT_BASE_URL = 'https://paul800901.github.io/kanpan-helper/reports'
```

實作方式：前端自動偵測 `window.location.hostname === 'paul800901.github.io'`

### FINMIND_API_TOKEN (後端讀取)

```python
# backend/fetch_data.py
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
# 完整模式（50檔）
python main.py

# 測試模式（3檔）
python main.py --test

# 使用快取
python main.py --use-cache

# 使用特定日期快取
python main.py --use-cache --date 2024-03-15
```

### 啟動前端
```bash
cd frontend
python -m http.server 8000
# 瀏覽 http://localhost:8000
```

### 語法驗證
```bash
# 驗證 JavaScript
node --check frontend/app.js

# 驗證 Python
python -m py_compile backend/*.py main.py
```

## 第一次部署

### 1. 手動觸發報告生成
```
GitHub → Actions → Daily Report Generation and Deploy → Run workflow
選擇: full mode → Run workflow
```

### 2. 監控執行
檢查 Actions log 確認：
- ✓ 成功抓取股票資料
- ✓ 報告檔案已生成
- ✓ index.json 已原子化更新
- ✓ 自動 commit 到 main
- ✓ Pages 部署成功

### 3. 驗證線上版本
- 等待部署完成（約 1-2 分鐘）
- 瀏覽 `https://paul800901.github.io/kanpan-helper/`
- 確認報告正確顯示
- 確認最後更新時間

### 4. 排程自動執行
- 已設定每天 UTC 00:00 自動執行
- 無需額外設定
diff --git a/.github/workflows/daily-report.yml b/.github/workflows/daily-report.yml
index 4d6d49f..2568b8c 100644
--- a/.github/workflows/daily-report.yml
+++ b/.github/workflows/daily-report.yml
@@ -1,4 +1,4 @@
-name: Daily Report Generation
+name: Daily Report Generation and Deploy
 
 on:
   schedule:
@@ -15,18 +15,26 @@ on:
           - full
           - test
 
+# 設定 GITHUB_TOKEN 的權限
+permissions:
+  contents: write  # 需要寫入權限來 commit/push
+  pages: write
+  id-token: write
+
 jobs:
-  generate-report:
+  generate-commit-and-deploy:
     runs-on: ubuntu-latest
     
-    permissions:
-      contents: write
-      pages: write
-      id-token: write
+    environment:
+      name: github-pages
+      url: ${{ steps.deployment.outputs.page_url }}
     
     steps:
       - name: Checkout repository
         uses: actions/checkout@v4
+        with:
+          token: ${{ secrets.GITHUB_TOKEN }}
       
       - name: Set up Python
         uses: actions/setup-python@v4
@@ -39,42 +47,69 @@ jobs:
           python -m pip install --upgrade pip
           pip install -r requirements.txt
       
-      - name: Backup existing index.json
-        run: |
-          if [ -f "reports/index.json" ]; then
-            cp reports/index.json reports/index.json.bak
-            echo "index.json backed up"
-          fi
-      
       - name: Generate daily report
+        id: generate_report
         env:
           FINMIND_API_TOKEN: ${{ secrets.FINMIND_API_TOKEN }}
         run: |
           if [ "${{ github.event.inputs.mode }}" = "test" ]; then
             echo "Running in test mode..."
             python main.py --test
           else
             echo "Running in full mode..."
             python main.py
           fi
+          
+          # 取得今天的日期字串 (台灣時間)
+          TODAY=$(date -d '8 hours' +%Y-%m-%d)
+          echo "today=$TODAY" >> $GITHUB_OUTPUT
+          
+          # 檢查報告是否成功生成
+          if [ ! -f "reports/${TODAY}.json" ]; then
+            echo "Error: 報告生成失敗，找不到 reports/${TODAY}.json"
+            exit 1
+          fi
+          
+          if [ ! -f "reports/${TODAY}-lite.json" ]; then
+            echo "Error: 報告生成失敗，找不到 reports/${TODAY}-lite.json"
+            exit 1
+          fi
+          
+          if [ ! -f "reports/index.json" ]; then
+            echo "Error: 索引更新失敗，找不到 reports/index.json"
+            exit 1
+          fi
+          
+          # 驗證 JSON 格式正確
+          python -m json.tool reports/${TODAY}.json > /dev/null
+          python -m json.tool reports/${TODAY}-lite.json > /dev/null
+          python -m json.tool reports/index.json > /dev/null
+          
+          echo "✓ 報告生成成功並驗證格式正確"
       
       - name: Commit and push reports
+        id: commit_reports
+        env:
+          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
         run: |
+          # 設定 git
           git config --local user.email "github-actions[bot]@users.noreply.github.com"
           git config --local user.name "github-actions[bot]"
           
-          # 只添加報告相關檔案
+          # 只添加 reports/ 目錄（不添加 data/）
           git add reports/
-          git add data/
           
           # 檢查是否有變更
           if git diff --staged --quiet; then
+            echo "no_changes=true" >> $GITHUB_OUTPUT
             echo "No changes to commit"
           else
             git commit -m "chore: update daily report $(date -d '8 hours' +%Y-%m-%d)"
             git push
+            echo "no_changes=false" >> $GITHUB_OUTPUT
+            echo "✓ Committed and pushed new reports"
           fi
       
       - name: Setup Pages
         uses: actions/configure-pages@v4
       
       - name: Prepare site content
         run: |
+          # 建立公開目錄
           mkdir -p _site
           
           # 複製 frontend 檔案
           cp -r frontend/* _site/
           
           # 複製 reports 目錄
           cp -r reports _site/
           
           # 確保 reports 目錄有 .nojekyll (防止 Jekyll 處理)
           touch _site/.nojekyll
           
+          # 建立 _config.yml
+          echo "disable_jekyll: true" > _site/_config.yml
+      
       - name: Upload artifact
         uses: actions/upload-pages-artifact@v3
         with:
           path: '_site'
       
       - name: Deploy to GitHub Pages
+        id: deployment
         uses: actions/deploy-pages@v4
diff --git a/DEPLOY.md b/DEPLOY.md
index 71acc12..1c849b7 100644
--- a/DEPLOY.md
+++ b/DEPLOY.md
@@ -1,60 +1,40 @@
 # Kanpan Helper v5 部署指南
 
-## 架構概述
+## 架構變更（v5 單一 workflow）
+
+**v5 重要更新**：改用單一 GitHub Actions workflow 完成報告生成、持久化和部署，解決 GITHUB_TOKEN push 不會觸發新 workflow 的 GitHub 限制。
 
 ```
 kanpan-helper/                      # GitHub repository
 ├── .github/workflows/
-│   ├── daily-report.yml           # 自動生成每日報告
-│   └── deploy-pages.yml           # 部署到 GitHub Pages
+│   └── daily-report.yml           # 單一 workflow：生成→commit→部署
 ├── frontend/                      # PWA 前端 (部署到 GitHub Pages)
 │   ├── index.html
 │   ├── app.js
 │   └── ...
-├── reports/                       # 生成的報告檔案
+├── reports/                       # 生成的報告檔案（持久化到 repo）
 │   ├── index.json
 │   ├── YYYY-MM-DD.json
 │   └── YYYY-MM-DD-lite.json
 └── backend/                       # Python 分析程式
     └── ...
 ```
 
-## GitHub 設定
+## GitHub 設定
+
+### 1. Repository Secret
+
+必須設定以下 secret：
+- `FINMIND_API_TOKEN`: FinMind API 的授權 token
+
+設定路徑：
+```
+GitHub Repository → Settings → Secrets and variables → Actions → New repository secret
+```
 
-### 1. Repository Secrets
+### 2. GitHub Pages 設定
 
-必須設定以下 secret：
-- `FINMIND_API_TOKEN`: FinMind API 的授權 token
-
-設定路徑：
-```
-GitHub Repository → Settings → Secrets → Actions → New repository secret
-```
-
-### 2. GitHub Pages 設定
-
-設定 GitHub Pages 發布來源：
+設定 GitHub Pages 發布來源：
 ```
 GitHub Repository → Settings → Pages
 
 Build and deployment:
   Source: GitHub Actions
 ```
 
-設定完成後，deploy-pages.yml 會自動部署 frontend 和 reports 目錄。
-
-### 3. Workflow 權限
-
-確保 workflow 有寫入權限：
+### 3. Workflow 權限
+
+確保 workflow 有寫入權限：
 ```
 GitHub Repository → Settings → Actions → General
@@ -62,73 +42,66 @@ Workflow permissions:
   ✓ Read and write permissions
 ```
-
-## 工作流程
-
-### Daily Report Generation (daily-report.yml)
-
-**觸發條件：**
-- 每天 UTC 00:00 (台灣時間 08:00)
-- 手動觸發 (workflow_dispatch)
-
-**執行步驟：**
-1. Checkout repository
-2. 安裝 Python 依賴
-3. **備份**現有的 `reports/index.json`
-4. 執行 `python main.py` 生成報告
-5. **安全更新**: 若報告生成失敗，自動恢復備份的 index.json
-6. Commit 並 push 新的報告檔案
-
-**環境變數：**
-- `FINMIND_API_TOKEN`: 從 repository secrets 讀取
-
-**安全機制：**
-- 失敗時自動恢復 index.json，確保前端不會因單次失敗而無法載入歷史報告
-- 只提交 reports/ 和 data/ 目錄，不影響其他檔案
-
-### Deploy to GitHub Pages (deploy-pages.yml)
-
-**觸發條件：**
-- 手動觸發 (workflow_dispatch)
-- Push 到 main 分支且修改 `frontend/**` 或 `reports/**`
-
-**執行步驟：**
-1. Checkout repository
-2. 設定 Pages
-3. 準備網站內容：
-   - 複製 frontend/* 到網站根目錄
-   - 複製 reports/ 到網站根目錄
-   - 建立 `.nojekyll` 防止 Jekyll 處理
-4. 部署到 GitHub Pages
-
-**公開路徑：**
-- 網站: `https://paul800901.github.io/kanpan-helper/`
-- 報告: `https://paul800901.github.io/kanpan-helper/reports/`
-
-## 環境變數
-
-### REPORT_BASE_URL
-
-前端使用此變數決定報告檔案的基礎路徑：
-
-**本地開發：**
-```javascript
-REPORT_BASE_URL = '../reports'  // 相對路徑
-```
-
-**GitHub Pages：**
-```javascript
-REPORT_BASE_URL = 'https://paul800901.github.io/kanpan-helper/reports'
-```
-
-實作方式：前端自動偵測是否在 GitHub Pages 上執行。
-
-### FINMIND_API_TOKEN
-
-Python 後端從環境變數讀取：
-```python
-import os
-api_token = os.environ.get('FINMIND_API_TOKEN')
-```
-
-在 GitHub Actions 中自動注入：
-```yaml
-env:
-  FINMIND_API_TOKEN: ${{ secrets.FINMIND_API_TOKEN }}
-```
-
-## 本地測試
-
-### 產生報告
-```bash
-# 完整模式
-python main.py
-
-# 測試模式（只跑3檔）
-python main.py --test
-
-# 使用快取
-python main.py --use-cache
-```
-
-### 本地啟動前端
-```bash
-cd frontend
-python -m http.server 8000
-```
-
-然後瀏覽 `http://localhost:8000`
-
-## 第一次部署步驟
-
-### 1. 手動觸發報告生成
-```
-GitHub Repository → Actions → Daily Report Generation → Run workflow
-Select: full mode
-```
-
-### 2. 確認報告生成成功
-檢查 Actions log 確認：
-- 成功抓取股票資料
-- 報告檔案已生成
-- index.json 已更新
-- 自動 commit 到 main
-
-### 3. 手動觸發 Pages 部署
-```
-GitHub Repository → Actions → Deploy to GitHub Pages → Run workflow
-```
-
-### 4. 驗證部署結果
-- 等待部署完成（約 1-2 分鐘）
-- 瀏覽 `https://paul800901.github.io/kanpan-helper/`
-- 確認能載入報告和顯示正確日期
-
-### 5. 設定自動排程
-- daily-report.yml 已設定每天 UTC 00:00 自動執行
-- deploy-pages.yml 會在報告提交後自動觸發（如有修改 frontend 或 reports）
-
-## 故障排除
-
-### 報告生成失敗
-- 檢查 Actions log 中的錯誤訊息
-- 確認 FINMIND_API_TOKEN 是否有效
-- 檢查是否超過 API 速率限制
-
-### GitHub Pages 部署失敗
-- 確認 Pages 設定為 "GitHub Actions"
-- 檢查 deploy-pages.yml log
-- 確認公開網址是否正確
-
-### 前端無法載入報告
-- 開啟瀏覽器開發者工具，檢查 network tab
-- 確認 index.json 路徑是否正確
-- 確認 CORS 問題（GitHub Pages 自動處理）
-
-## 版本資訊
-
-- **v5.0.0**: 最小可用部署版
-  - 支援 GitHub Actions 自動生成報告
-  - 支援 GitHub Pages 部署
-  - 安全更新 index.json 機制
-  - 自動偵測 REPORT_BASE_URL
+## 運作流程
+
+### Daily Report Generation and Deploy (daily-report.yml)
+
+**v5 單一 workflow 設計：在一次執行內完成報告生成、持久化和部署**
+
+**觸發條件：**
+- 每天 UTC 00:00 (台灣時間 08:00) 自動執行
+- 手動觸發 (workflow_dispatch)，可選 mode: full / test
+
+**執行步驟：**
+1. Checkout repository
+2. 安裝 Python 依賴
+3. 執行 `python main.py` 生成報告（支援 `--test` 模式）
+4. **驗證**報告格式（檢查 YYYY-MM-DD.json、YYYY-MM-DD-lite.json、index.json）
+5. **Commit/Push** reports/ 到 main 分支（持久化）
+   - Commit message: `chore: update daily report YYYY-MM-DD`
+   - 只添加 reports/，不添加 data/
+6. **直接部署** GitHub Pages（在同一 workflow 內完成，不依賴 push 觸發）
+   - 複製 frontend/* → _site/
+   - 複製 reports/ → _site/
+   - 上傳 artifact 並部署到 Pages
+
+**環境變數：**
+- `FINMIND_API_TOKEN`: 從 repository secrets 讀取
+
+**安全機制：**
+- 報告生成失敗時 workflow 會失敗，不會繼續部署
+- index.json 使用原子化更新（原子替換機制，確保失敗時保留舊檔）
+- 透過 `permissions` 設定限制 GITHUB_TOKEN 權限
+
+**公開路徑：**
+- 網站: `https://paul800901.github.io/kanpan-helper/`
+- 報告: `https://paul800901.github.io/kanpan-helper/reports/`
+
+## 環境變數
+
+### REPORT_BASE_URL (前端自動偵測)
+
+**本地開發：**
+```javascript
+REPORT_BASE_URL = '../reports'  // 相對路徑
+```
+
+**GitHub Pages：**
+```javascript
+REPORT_BASE_URL = 'https://paul800901.github.io/kanpan-helper/reports'
+```
+
+實作方式：前端自動偵測 `window.location.hostname === 'paul800901.github.io'`
+
+### FINMIND_API_TOKEN (後端讀取)
+
+```python
+# backend/fetch_data.py
+import os
+api_token = os.environ.get('FINMIND_API_TOKEN')
+```
+
+在 GitHub Actions 中自動注入：
+```yaml
+env:
+  FINMIND_API_TOKEN: ${{ secrets.FINMIND_API_TOKEN }}
+```
+
+## 本地測試
+
+### 產生報告
+```bash
+# 完整模式（50檔）
+python main.py
+
+# 測試模式（3檔）
+python main.py --test
+
+# 使用快取
+python main.py --use-cache
+
+# 使用特定日期快取
+python main.py --use-cache --date 2024-03-15
+```
+
+### 驗證語法
+```bash
+# 驗證 JavaScript
+node --check frontend/app.js
+
+# 驗證 Python
+python -m py_compile backend/*.py main.py
+```
+
+### 啟動前端
+```bash
+cd frontend
+python -m http.server 8000
+# 瀏覽 http://localhost:8000
+```
+
+## 第一次部署
+
+### 1. 手動觸發報告生成
+```
+GitHub → Actions → Daily Report Generation and Deploy → Run workflow
+選擇: full mode → Run workflow
+```
+
+### 2. 監控執行
+檢查 Actions log 確認：
+- ✓ 成功抓取股票資料
+- ✓ 報告檔案已生成
+- ✓ index.json 已原子化更新
+- ✓ 自動 commit 到 main
+- ✓ Pages 部署成功
+
+### 3. 驗證線上版本
+- 等待部署完成（約 1-2 分鐘）
+- 瀏覽 `https://paul800901.github.io/kanpan-helper/`
+- 確認報告正確顯示
+- 確認最後更新時間
+
+### 4. 排程自動執行
+- 已設定每天 UTC 00:00 自動執行
+- 無需額外設定
+
+## 故障排除
+
+### 報告生成失敗
+- 檢查 Actions log 中的錯誤訊息
+- 確認 FINMIND_API_TOKEN 是否有效
+- 檢查是否超過 API 速率限制
+
+### GitHub Pages 部署失敗
+- 確認 Pages 設定為 "GitHub Actions"
+- 檢查 daily-report.yml log
+- 確認公開網址是否正確
+
+### 前端無法載入報告
+- 開啟瀏覽器開發者工具，檢查 network tab
+- 確認 index.json 路徑是否正確
+- 確認 CORS 問題（GitHub Pages 自動處理）
+
+## 版本資訊
+
+- **v5.0.0**: 單一 workflow 部署版
+  - 單一 GitHub Actions workflow 完成生成→持久化→部署
+  - 解決 GITHUB_TOKEN push 不觸發 workflow 限制
+  - 原子化安全更新 index.json
+  - 自動偵測 REPORT_BASE_URL
+  - 支援手動和排程觸發
