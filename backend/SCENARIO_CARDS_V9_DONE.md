# SCENARIO_CARDS_V9 Done Definition

## 已完成

- 正式 contract：scenario_cards_v9
- schema version：scenario-cards-v9
- 核心欄位包含 source_types、priority_score、priority_rank
- validator 已固定在第三頁正式 contract 路徑
- public API 白名單已固定在 backend/context_cards.py 的 __all__
- public/internal boundary guard 已存在
- dependency guard 已存在
- normal golden regression 已存在
- fallback golden regression 已存在

## 單一真相源

- 第三頁正式真相源只有 scenario_cards_v9
- 第三頁 render、回歸保護與後續維護都應以 scenario_cards_v9 為唯一正式輸出

## 不得回退

- 不得回退為以 legacy cards 作為第三頁正式主來源
- 不得回退為以 trace_catalog 作為第三頁正式主來源
- 不得回退為以 stock_mapping_catalog 作為第三頁正式主來源
- 不得在 frontend 重算第三頁排序、priority_score、priority_rank 或核心推理
- 不得讓 app/script 直連 backend/context_cards.py 內層 helper
- 不得繞過既有 public API 白名單、boundary guard、dependency guard、normal golden、fallback golden

## 允許維護

- 小範圍 bug fix
- 測試補強
- 註解與文件更新
- 不改 contract 的內部實作優化
