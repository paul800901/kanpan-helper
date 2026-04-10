# Cloudflare Worker 部署說明

> 看盤助手 v6.1 個股 AI 解讀後端

## 架構說明

```
前端 stock.html
    ↓ POST /api/stock-ai { symbol, date }
Cloudflare Worker (本資料夾)
    ↓ GET  https://paul800901.github.io/kanpan-helper/reports/{date}-universe.json
GitHub Pages (公開靜態資料)
    ↓ 找到股票資料後
DeepSeek API (呼叫 AI)
    ↓ 回傳 JSON
前端渲染 AI 解讀區塊
```

**安全原則：DEEPSEEK_API_KEY 只存在 Worker secrets，永遠不出現在前端程式碼。**

---

## 部署步驟

### 1. 安裝 Wrangler CLI

```bash
npm install -g wrangler
```

### 2. 登入 Cloudflare 帳號

```bash
wrangler login
```

### 3. 切換到 worker 資料夾

```bash
cd worker
```

### 4. 設定 DeepSeek API Key（Worker secret）

```bash
wrangler secret put DEEPSEEK_API_KEY
# 輸入你的 DeepSeek API Key，按 Enter 確認
```

> ⚠️ 這個 key **永遠不要** 寫進 index.js 或 wrangler.toml，只用 secret 機制存放。

### 5. 部署 Worker

```bash
wrangler deploy
```

成功後會顯示：
```
✨ Worker deployed to: https://kanpan-helper-worker.YOUR_SUBDOMAIN.workers.dev
```

### 6. 更新前端設定

複製上面的 Worker URL，填入 `frontend/stock.html`：

```javascript
// 找到這行（約在 <script> 區塊頂端）：
const WORKER_URL = 'https://kanpan-helper-worker.YOUR_SUBDOMAIN.workers.dev';

// 改成你實際的 Worker URL：
const WORKER_URL = 'https://kanpan-helper-worker.paul800901.workers.dev';
```

然後重新部署前端（透過 GitHub Actions）。

---

## 驗證部署是否成功

```bash
curl -X POST https://kanpan-helper-worker.YOUR_SUBDOMAIN.workers.dev/api/stock-ai \
  -H "Content-Type: application/json" \
  -d '{"symbol": "2330", "date": "2026-04-10"}'
```

預期回應：
```json
{
  "ok": true,
  "symbol": "2330",
  "date": "2026-04-10",
  "name": "台積電",
  "ai_summary": "...",
  "trend_view": "...",
  "risk_view": "...",
  "watch_points": ["...", "...", "..."]
}
```

---

## 常見問題

### Q: universe.json 讀取失敗（404）
**A:** 確認 GitHub Actions workflow 已執行完成，`reports/{date}-universe.json` 已 push 到 GitHub Pages。

### Q: AI 分析失敗（500）
**A:** 確認 `wrangler secret put DEEPSEEK_API_KEY` 已設定正確的 key。可用以下指令確認 secret 是否存在：
```bash
wrangler secret list
```

### Q: 想更換 worker name
**A:** 修改 `wrangler.toml` 的 `name` 欄位，re-deploy 後記得同步更新 `stock.html` 的 `WORKER_URL`。

---

## Free Plan 限制（Cloudflare Workers 免費方案）

| 項目 | 限制 |
|------|------|
| 請求次數 | 100,000 / 天 |
| CPU 時間 | 10ms / 請求 |
| 記憶體 | 128MB |
| Workers 數量 | 最多 100 個 |

個股 AI 解讀屬於「按需觸發」，正常使用量遠低於限制。
