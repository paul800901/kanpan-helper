---
agent: "agent"
description: "以單一層為單位規劃 kanpan-helper 任務，禁止跨層亂動"
---

你正在處理 `kanpan-helper`。

先讀：
- `AGENTS.md`
- `README.md`
- `.github/copilot-instructions.md`
- `KANPAN_TASK_TEMPLATE.md`

然後依下列規則執行：

1. 先把任務歸類到單一層：
   - `Data`
   - `Calculation`
   - `Ranking`
   - `Report`
   - `Frontend`
2. 只允許修改該層檔案。
3. 若需求需要碰到第二層，立即停止，回報需要跨層授權。
4. 不得改 report schema、ranking 欄位、既有欄位命名。
5. 不得順手優化、重構或搬動整條資料管線。

先輸出這份框架，再開始任何修改：

```text
[已讀檔案]

[任務類型]
單層修改 / 跨層修改（需授權）

[本輪層級]
Data / Calculation / Ranking / Report / Frontend

[目標]

[允許修改]

[禁止修改]

[完成定義]
1.
2.
3.

[停止條件]
- 無法判定層級
- 需要跨層
- 需要 schema 變更但未授權
```

完成後必須回報：
- 修改檔案
- 所屬層級
- 是否跨層（有 / 沒有）
- 是否影響 JSON 輸出（有 / 沒有）
- 驗證證據（raw output）
