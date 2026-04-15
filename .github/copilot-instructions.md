# 看盤助手 IDE 分層執行規則

本專案有固定資料管線：`Data -> Calculation -> Ranking -> Report -> Frontend`。

## 五層定義

### 1. Data Layer
- 檔案：`backend/fetch_data.py`
- 責任：外部資料抓取、來源解析、抓取失敗處理

### 2. Calculation Layer
- 檔案：`backend/calc_indicators.py`
- 責任：技術指標計算，例如 MA、KD、量能比

### 3. Ranking Layer
- 檔案：`backend/ranking.py`
- 責任：評分、排序、排名輸出

### 4. Report Layer
- 檔案：`backend/generate_report.py`
- 責任：報告組裝、報告 JSON 結構、報告輸出

### 5. Frontend Layer
- 檔案：`frontend/context.js`、`frontend/app.js`、`frontend/index.html`
- 責任：卡片顯示、前端投影、畫面互動

## 單層操作原則
- 每次任務只能修改單一層。
- 若需求同時碰到兩層以上，視為跨層修改，必須先取得明確授權。
- 不得因為局部修改而順手重構整條 pipeline。

## 層級隔離
- Data Layer 不得改變 Calculation Layer 依賴的資料結構。
- Calculation Layer 不得改 Ranking Layer 的評分或排序邏輯。
- Ranking Layer 不得改 Report Layer 的 schema 或欄位命名。
- Report Layer 不得改 Frontend Layer 的邏輯、欄位假設或顯示流程。
- Frontend Layer 不得回頭修改 backend、ranking、calc、fetch。

## Schema 保護
- 不得修改 report JSON 結構。
- 不得修改 ranking 輸出欄位。
- 不得新增 report 或 ranking 欄位，除非使用者明確授權。
- 不得重新命名既有欄位。
- 不得因為「看起來更合理」就調整演算法、排序規則或資料流。

## 禁止順手優化
- 不得因為修改單一層而順手調整其他層。
- 不得抽換層級責任。
- 不得搬移邏輯到其他層。
- 不得把單點修正擴大成 pipeline 重寫。

## 修改前必做回報
- 本輪修改層級
- 允許修改檔案
- 預計修改區塊
- 明確不會修改的層

若無法先回答以上四點，停止執行。

## 修改後必做回報
- 實際修改檔案
- 修改層級
- 是否跨層：有 / 沒有
- 是否影響資料輸出：有 / 沒有
- 驗證證據：提供實際檢查或指令 raw output，不可只說已完成

## 停止條件
- 無法判定任務層級
- 需要跨層才能完成，但沒有明確授權
- 涉及 schema 變更，但沒有明確授權
- 任務同時混合 backend 與 frontend 修改，但沒有明確授權

## 跨層修改模式（高風險）
只有在使用者明確授權跨層時才能進入此模式。

執行前必須先列出：
1. 所有受影響層與檔案
2. 資料流變化：修改前與修改後的 `Data -> Calculation -> Ranking -> Report -> Frontend`
3. schema 是否變動；若有，必須列出精確欄位
4. 對前端顯示與既有 JSON 消費端的影響

未完成以上四項，禁止執行跨層修改。
