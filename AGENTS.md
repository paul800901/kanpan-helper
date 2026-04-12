# 看盤助手 AI 作業守則

## ⚠️ 文件污染處理（關鍵教訓）

### 問題模式
文件出現雜散字元（stray 'n', '\n'）時，局部替換經常失敗。

### 解決方案
| 嘗試次數 | 正確做法 |
|---------|----------|
| 第1次 | 嘗試 `StrReplaceFile` |
| **第2次失敗後** | **立即改用 `WriteFile` 完整重寫** |

**絕對禁止**：連續使用 StrReplaceFile 超過 2 次。

### 實際驗證要求
- JavaScript: `node --check file.js`（必須顯示 raw output）
- Python: `python -m py_compile file.py`
- YAML: `python -c "import yaml; yaml.safe_load(open('file.yml'))"`

---

## 🔁 開發部署工作流（v5 標準流程）

### 目錄結構
```
雲端本體（G:\我的雲端硬碟\kanpan-helper）  ← 日常開發修改
         ↓ 複製
桌面 Git（C:\Users\...\kanpan_helper_github_sync\kanpan-helper）
         ↓ git push
GitHub（paul800901/kanpan-helper）
         ↓ 手動觸發 workflow
GitHub Pages 部署
```

### 標準步驟
1. **在雲端本體修改程式碼**（你的主要工作目錄）
2. **本地測試**確認功能正常
3. **複製到桌面 Git**：
   ```powershell
   robocopy "G:\我的雲端硬碟\kanpan-helper" "$env:USERPROFILE\Desktop\kanpan_helper_github_sync\kanpan-helper" /MIR /XD .git __pycache__
   ```
4. **提交並推送**：
   ```bash
   git add .
   git commit -m "描述修改內容"
   git push origin main
   ```
5. **手動觸發部署**：
   - 到 GitHub Actions → "Daily Report Generation and Deploy"
   - 點擊 "Run workflow" → 選 test 或 full 模式
   - **注意**：修改 `reports/` 下的舊報告數據不會自動觸發部署！

### 關鍵提醒
- **只有定時或手動觸發** workflow 才會部署
- **修改現有報告 JSON** 後必須手動 Run workflow 才會生效
- **`.github/workflows/` 修改** 也需要手動觸發
- **AI 修改完成後，若使用者未明示禁止，預設要同步到桌面 Git 倉庫並執行 `git add`、`git commit`、`git push origin main`**
- **若 push 被拒絕且遠端有新提交，先 `git pull --rebase origin main`，確認無衝突後再重推，不要直接放棄**
- **同步與提交時不要順手帶入無關產物，例如 `worker/.wrangler/`**

---

## 專案結構

```
kanpan-helper/
├── backend/           # Python 報告生成
│   ├── report_index.py    # 原子索引更新
│   └── generate_report.py # 報告產生邏輯
├── frontend/          # PWA 前端
│   └── app.js             # 主要應用程式
├── reports/           # 輸出報告 (Git追蹤)
├── .github/workflows/ # GitHub Actions
│   └── daily-report.yml   # 單一workflow部署
└── main.py            # 入口點
```

---

## 關鍵配置

- **部署**: GitHub Pages (GitHub Actions)
- **Python**: 3.10
- **Node**: v18+
- **API Token**: FINMIND_API_TOKEN (Repository Secret)

---

## 常見操作

### 本地測試
```bash
cd frontend
python -m http.server 8080
```

### 語法檢查
```bash
node --check frontend/app.js
python -m py_compile backend/*.py main.py
```

---

## 使用者偏好

- **語言**: 中文回覆
- **風格**: 直接、簡潔、不要過度工程化
- **驗證**: 必須提供 raw terminal output，不只是「return code: 0」
- **失敗處理**: 第2次嘗試失敗立即換策略，不要固執
