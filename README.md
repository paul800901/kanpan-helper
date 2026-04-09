# 看盤助手 (Kanpan Helper) v5

每日台股分析報告系統 - PWA 手機版 + GitHub Pages 部署

## 快速啟動

### 線上版本（GitHub Pages）

**自動部署**：
- 每天 08:00 (台灣時間) 自動生成報告
- 自動部署到 GitHub Pages
- 瀏覽即可查看最新報告

**網址**：`https://paul800901.github.io/kanpan-helper/`

### 本地開發

**方法一：一鍵啟動全部**
```bash
# 雙擊執行
run_all.bat
```
這會自動執行分析並開啟前端頁面。

**方法二：只啟動前端**
```bash
# 雙擊執行
start.bat
```

或手動：
```bash
cd frontend
python -m http.server 8080
# 瀏覽器開啟 http://localhost:8080
```

## 功能特色 (v5)

- **每日自動分析**：抓取台股資料，計算技術指標
- **評分排名**：綜合評分選出 Top 5
- **人話報告**：白話說明理由與風險
- **手機 PWA**：可安裝到手機主畫面
- **歷史查詢**：可切換查看過去報告
- **GitHub Actions 自動化**：每天自動生成報告
- **GitHub Pages 部署**：線上瀏覽，無需本地伺服器
- **安全更新機制**：報告生成失敗時自動恢復索引
- **環境變數支援**：支援 FINMIND_API_TOKEN 環境變數

## 系統架構

```
kanpan-helper/
├── backend/              # 後端分析
│   ├── fetch_data.py     # 資料抓取
│   ├── calc_indicators.py # 指標計算
│   ├── ranking.py        # 評分排名
│   ├── generate_report.py # 報告生成
│   ├── report_index.py   # 索引管理
│   └── config.py         # 設定
├── frontend/             # 前端 PWA
│   ├── index.html        # 主頁面
│   ├── style.css         # 樣式表
│   ├── app.js            # 應用程式
│   ├── manifest.json     # PWA 設定
│   ├── service-worker.js # 快取服務
│   └── start.bat         # 啟動腳本
├── reports/              # 報告輸出
│   ├── index.json        # 報告索引
│   └── YYYY-MM-DD-lite.json
├── main.py               # 主程式
└── run_all.bat           # 一鍵啟動
```

## 使用流程

### GitHub Pages 線上版本

線上版本已自動化，您只需：

1. **瀏覽報告**：開啟 `https://paul800901.github.io/kanpan-helper/`
2. **查看更新時間**：頁面會顯示最後更新時間
3. **切換日期**：從下拉選單選擇歷史報告

### 本地開發

#### 1. 產生報告

```bash
# 測試模式（3檔股票）
python main.py --test

# 完整模式（50檔股票）
python main.py

# 使用快取（不再抓取）
python main.py --use-cache

# 使用特定日期快取
python main.py --use-cache --date 2024-03-15
```

**環境變數設定（選擇性）：**
```bash
# 設定 FinMind API token（若未設定會使用公開 API）
export FINMIND_API_TOKEN=your_token_here
```

#### 2. 查看報告

```bash
# 啟動前端伺服器
cd frontend
python -m http.server 8080

# 或雙擊 start.bat
```

開啟瀏覽器：`http://localhost:8080`

### 3. 安裝 PWA

**Android Chrome：**
1. 開啟網頁
2. 點擊選單「新增至主畫面」
3. 確認安裝

**iOS Safari：**
1. 開啟網頁
2. 點擊分享按鈕
3. 選擇「加入主畫面」

## 報告格式

### v2 精簡版報告欄位

```json
{
  "report_version": "v2-lite",
  "date": "2026-04-08",
  "summary": {
    "market_overview": "本日平均強度普通(58分)...",
    "top_picks": [{"symbol": "2330", "name": "台積電"}]
  },
  "stocks": [{
    "symbol": "2330",
    "name": "台積電",
    "rank": 1,
    "score": 78,
    "score_grade": "A",
    "score_label": "強",
    "action_bias": "可留意",
    "one_line_summary": "短線強勢，法人連買，可留意。",
    "plain_reasons": ["股價站穩均線之上", "法人連續3天買超"],
    "plain_risks": ["技術指標已達高檔"],
    "indicators": {
      "close": 1860.0,
      "volume_ratio": 1.25
    },
    "signals": {
      "trend": "偏多",
      "institutional": "連3買"
    }
  }]
}
```

## 指令參數

### main.py

```bash
python main.py [選項]

選項：
  --test         測試模式（只跑3檔）
  --use-cache    使用快取資料
  --date DATE    指定日期（需搭配 --use-cache）
```

### 前端 URL 參數

```
index.html                    # 自動載入最新報告
index.html?date=2026-04-08    # 載入指定日期
index.html?date=2026-04-08&debug=1  # 除錯模式
```

## 評分規則

| 分數 | 等級 | 標籤 |
|------|------|------|
| 75+ | A | 強 |
| 60-74 | B | 中等 |
| 45-59 | C | 普通 |
| <45 | D | 弱 |

### 行動建議

- **可留意**：分數60+，資料充足，條件良好
- **觀察**：分數尚可但有疑慮，或高分但資料不足
- **偏保守**：分數偏低，或趨勢不明朗
- **暫不考慮**：分數<50，或明顯弱勢

## 注意事項

1. **資料來源**：使用 FinMind 免費 API
2. **更新頻率**：建議每日盤後執行一次
3. **免責聲明**：本系統僅供參考，不構成投資建議
4. **快取**：報告資料會儲存在 `data/` 目錄

## 檔案編碼

所有批次檔使用 UTF-8 編碼，若中文顯示異常請確認終端機編碼設定。

## GitHub Actions 自動化（v5 新增）

### 自動生成報告

```
GitHub Repository → Actions → Daily Report Generation
```

**排程**：每天 08:00 (台灣時間) 自動執行

**手動觸發**：
1. 點選 "Run workflow"
2. 選擇模式：full / test
3. 點選 "Run workflow"

**功能**：
- 自動抓取資料並分析
- 生成完整版和精簡版報告
- 更新 reports/index.json
- 自動 commit 到 main 分支
- **安全機制**：生成失敗時自動恢復索引

### 自動部署 GitHub Pages

```
GitHub Repository → Actions → Deploy to GitHub Pages
```

**觸發條件**：
- 手動觸發
- 或當 frontend/** 或 reports/** 有更新時自動觸發

**功能**：
- 將 frontend/ 複製到網站根目錄
- 將 reports/ 複製到網站根目錄
- 自動部署到 `https://paul800901.github.io/kanpan-helper/`

### 環境變數

**`FINMIND_API_TOKEN`**
- 從 GitHub repository secrets 讀取
- 在 workflow 中自動注入環境變數
- 支援 FinMind 需要授權的 dataset

**`REPORT_BASE_URL`**
- 前端自動偵測是否在 GitHub Pages
- 本地開發：使用相對路徑 `../reports`
- GitHub Pages：使用絕對路徑 `https://paul800901.github.io/kanpan-helper/reports`

## 部署指南

詳細部署步驟請參閱 [DEPLOY.md](DEPLOY.md)

## 版本歷史

- v1：基礎骨架，可產生 JSON 報告
- v2：報告實用化，新增人話欄位
- v3：前端最小可用版，卡片顯示
- v4：PWA 化，支援離線，一鍵啟動
- **v5：GitHub Actions 自動化，GitHub Pages 部署**
