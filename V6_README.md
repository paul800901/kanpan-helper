# 看盤助手 v6 - DeepSeek AI 分析版

## 版本定位

| 版本 | 功能 | 狀態 |
|------|------|------|
| v5 | FinMind + 規則引擎 + GitHub Actions 部署 | ✅ 穩定運行 |
| v6 | v5 基礎 + DeepSeek AI 分析 | 🆕 新增 |

## 核心變更

### 後端新增

| 檔案 | 功能 |
|------|------|
| `backend/ai_analyzer.py` | DeepSeek API 客戶端，產生 AI 分析 |
| `backend/yesterday_compare.py` | 載入昨日報告，比較變化 |

### 後端修改

| 檔案 | 變更 |
|------|------|
| `backend/generate_report.py` | 新增 `generate_ai_report_if_enabled()` 函數 |
| `main.py` | Step 5 新增 AI 報告生成 |
| `requirements.txt` | 新增 `openai>=1.0.0` |

### 前端修改

| 檔案 | 變更 |
|------|------|
| `frontend/index.html` | 新增 v6 AI 區塊（總結、焦點、分群） |
| `frontend/style.css` | 新增 v6 樣式（AI 區塊、分群標籤） |
| `frontend/app.js` | 雙模式渲染（v6 AI 模式 / v5 兼容模式） |

## 啟用 AI 分析

設定環境變數：

```bash
# Windows PowerShell
$env:DEEPSEEK_API_KEY="your-api-key"
$env:ENABLE_AI_ANALYSIS="true"

# 或 Windows CMD
set DEEPSEEK_API_KEY=your-api-key
set ENABLE_AI_ANALYSIS=true
```

## 輸出檔案

執行 `main.py` 後產生：

```
reports/
├── 2026-04-09.json           # v5 完整報告
├── 2026-04-09-lite.json      # v5 精簡報告
└── 2026-04-09-ai.json        # v6 AI 分析報告（新）
```

## AI 輸出欄位

```json
{
  "report_version": "v6-ai",
  "date": "2026-04-09",
  "generated_at": "ISO時間",
  "ai_model": "deepseek-chat",
  "market_overview_ai": "今日市場一句話總結",
  "today_focus_ai": ["焦點1", "焦點2", "焦點3"],
  "strongest_group_ai": "最值得先看組的特色",
  "caution_group_ai": "轉強觀察組的注意事項",
  "avoid_group_ai": "今日先不要碰的原因",
  "stocks": [
    {
      "symbol": "2330",
      "name": "台積電",
      "score": 88,
      "rank": 1,
      "action_bias": "可留意",
      "why_selected_ai": "AI分析的入選理由",
      "risk_ai": "AI判讀的主要風險",
      "change_vs_yesterday_ai": "與昨日比較的變化"
    }
  ]
}
```

## 前端顯示邏輯

- **有 AI 報告** → 顯示 v6 介面（AI 總結、分群、AI 分析卡片）
- **無 AI 報告** → 顯示 v5 介面（傳統摘要、篩選列、規則卡片）

自動向下兼容，不會破壞既有功能。

## 部署注意

1. **GitHub Secrets** 需新增：
   - `DEEPSEEK_API_KEY`（選用，無則自動跳過 AI 步驟）
   - `ENABLE_AI_ANALYSIS` 設為 `true` 才會啟用

2. **Workflow** 不需修改，已整合在現有流程中

3. **GitHub Pages** 會自動部署新的前端檔案

## 測試方式

```bash
# 本地測試（無 AI）
python main.py --test

# 本地測試（有 AI，需設定 API KEY）
$env:ENABLE_AI_ANALYSIS="true"
python main.py --test

# 使用快取測試
python main.py --use-cache
```

## 檔案清單總覽

### 新增檔案
- `backend/ai_analyzer.py` (12KB)
- `backend/yesterday_compare.py` (4KB)
- `V6_README.md` (本檔案)

### 修改檔案
- `backend/generate_report.py` - 新增 AI 生成函數
- `main.py` - Step 5 AI 分析
- `frontend/index.html` - v6 UI 結構
- `frontend/style.css` - v6 樣式
- `frontend/app.js` - 雙模式渲染
- `requirements.txt` - 新增 openai 套件
