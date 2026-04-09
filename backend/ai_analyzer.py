"""v6 DeepSeek AI 分析模組

將 FinMind + 規則引擎結果，透過 DeepSeek API 進行智能分析，
產生市場總覽、今日焦點、個股理由等 AI 判讀內容。

注意：在 ENABLE_AI_ANALYSIS=true 模式下，任何錯誤都會直接 raise，
不會使用 fallback 內容。
"""

import json
import os
from typing import Dict, List, Optional
from backend.config import get_today_str, get_taiwan_now
from backend.yesterday_compare import load_yesterday_report

# DeepSeek API 配置
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# 檢查是否強制 AI 模式（任何失敗都要 raise）
FORCE_AI_MODE = os.environ.get("ENABLE_AI_ANALYSIS", "").lower() in ["true", "1", "yes"]


class AIAnalyzerError(Exception):
    """AI 分析錯誤"""
    pass


class AIAnalyzer:
    """DeepSeek AI 分析器"""
    
    def __init__(self):
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """初始化 DeepSeek client"""
        if not DEEPSEEK_API_KEY:
            raise AIAnalyzerError("DEEPSEEK_API_KEY 未設定")
        
        try:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=DEEPSEEK_API_KEY,
                base_url=DEEPSEEK_BASE_URL
            )
        except ImportError as e:
            raise AIAnalyzerError(f"openai 套件未安裝: {e}")
        except Exception as e:
            raise AIAnalyzerError(f"DeepSeek client 建立失敗: {e}")
    
    def _call_deepseek(self, prompt: str, temperature: float = 0.3) -> str:
        """呼叫 DeepSeek API - 失敗時直接 raise"""
        if not self.client:
            raise AIAnalyzerError("DeepSeek client 未初始化")
        
        try:
            response = self.client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": "你是專業的台股分析師，擅長技術分析與市場解讀。請用繁體中文回答，簡潔有力，不要廢話。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=2000
            )
            content = response.choices[0].message.content
            if not content or not content.strip():
                raise AIAnalyzerError("DeepSeek 回傳空內容（空字串或純空白）")
            return content
        except Exception as e:
            raise AIAnalyzerError(f"DeepSeek API 呼叫失敗: {e}")
    
    def _parse_json_response(self, raw: str, required_fields: List[str]) -> Dict:
        """
        解析 DeepSeek JSON 回應 - 失敗時直接 raise，附 raw 前 500 字供除錯。

        清洗順序：
        1. 確認非空
        2. 剝掉 ```json ... ``` 或 ``` ... ``` code fence
        3. 若前面仍有說明文字，跳到第一個 {
        4. 截斷最後一個 } 之後的多餘內容
        5. json.loads；失敗就 raise（含 raw 前 500 字）
        6. 驗證必要欄位；缺少就 raise
        """
        if not raw or not raw.strip():
            raise AIAnalyzerError(
                "DeepSeek 回傳空字串，無法解析 JSON。"
                f"原始回應前500字：{raw[:500]!r}"
            )

        text = raw.strip()

        # 剝掉 code fence（```json 或 ```）
        if text.startswith("```"):
            first_newline = text.find("\n")
            if first_newline != -1:
                text = text[first_newline + 1:]
            else:
                text = text[3:]  # 只有開頭 ``` 沒有換行
            if text.endswith("```"):
                text = text[: text.rfind("```")]
            text = text.strip()

        # 若仍有前置說明文字，跳到第一個 {
        if not text.startswith("{"):
            brace_idx = text.find("{")
            if brace_idx == -1:
                raise AIAnalyzerError(
                    f"回應中找不到 JSON 物件起始 {{。"
                    f"原始回應前500字：{raw[:500]!r}"
                )
            text = text[brace_idx:]

        # 截斷最後一個 } 之後的多餘內容
        last_brace = text.rfind("}")
        if last_brace != -1:
            text = text[: last_brace + 1]

        try:
            result = json.loads(text)
        except json.JSONDecodeError as e:
            raise AIAnalyzerError(
                f"AI 回應 JSON parse 失敗: {e}。"
                f"原始回應前500字：{raw[:500]!r}"
            )

        # 驗證必要欄位
        missing = [f for f in required_fields if f not in result]
        if missing:
            raise AIAnalyzerError(
                f"AI 回應缺少必要欄位: {missing}。"
                f"原始回應前500字：{raw[:500]!r}"
            )

        return result

    def _parse_json_array_response(self, raw: str, n: int) -> List[Dict]:
        """
        解析 JSON array 回應，預期有 n 個元素。
        失敗時直接 raise，附 raw 前 500 字。
        """
        if not raw or not raw.strip():
            raise AIAnalyzerError(
                f"DeepSeek 回傳空字串。原始回應前500字：{raw[:500]!r}"
            )

        text = raw.strip()

        # 剝掉 code fence
        if text.startswith("```"):
            nl = text.find("\n")
            text = text[nl + 1:] if nl != -1 else text[3:]
            if "```" in text:
                text = text[: text.rfind("```")]
            text = text.strip()

        # 找到第一個 [
        if not text.startswith("["):
            idx = text.find("[")
            if idx == -1:
                raise AIAnalyzerError(
                    f"回應中找不到 array 起始 [。原始回應前500字：{raw[:500]!r}"
                )
            text = text[idx:]

        # 截斷最後 ] 之後
        last = text.rfind("]")
        if last != -1:
            text = text[: last + 1]

        try:
            result = json.loads(text)
        except json.JSONDecodeError as e:
            raise AIAnalyzerError(
                f"AI array parse 失敗: {e}。原始回應前500字：{raw[:500]!r}"
            )

        if not isinstance(result, list):
            raise AIAnalyzerError(
                f"AI 回應不是 array。原始回應前500字：{raw[:500]!r}"
            )

        if len(result) != n:
            raise AIAnalyzerError(
                f"AI 回應個數錯誤：預期 {n}，實際 {len(result)}。"
                f"原始回應前500字：{raw[:500]!r}"
            )

        return result

    def _check_duplicates(self, ai_stocks: List[Dict]) -> None:
        """
        若 why_selected_ai 或 risk_ai 有超過 2 對相似，視為生成失敗，直接 raise。
        相似度以字元集 Jaccard 係數 > 0.7 判定。
        """
        def jaccard(a: str, b: str) -> float:
            if not a or not b:
                return 0.0
            sa = set(a.replace(" ", "").replace("，", "").replace("。", ""))
            sb = set(b.replace(" ", "").replace("，", "").replace("。", ""))
            if not sa or not sb:
                return 0.0
            return len(sa & sb) / len(sa | sb)

        why_texts = [s.get("why_selected_ai", "") for s in ai_stocks]
        risk_texts = [s.get("risk_ai", "") for s in ai_stocks]

        why_dupes = sum(
            1 for i in range(len(why_texts))
            for j in range(i + 1, len(why_texts))
            if jaccard(why_texts[i], why_texts[j]) > 0.70
        )
        risk_dupes = sum(
            1 for i in range(len(risk_texts))
            for j in range(i + 1, len(risk_texts))
            if jaccard(risk_texts[i], risk_texts[j]) > 0.70
        )

        if why_dupes > 1:
            raise AIAnalyzerError(
                f"個股 why_selected_ai 重複過多（{why_dupes} 對相似，閾值 >1），視為生成失敗。"
                f"內容：{why_texts}"
            )
        if risk_dupes > 1:
            raise AIAnalyzerError(
                f"個股 risk_ai 重複過多（{risk_dupes} 對相似，閾值 >1），視為生成失敗。"
                f"內容：{risk_texts}"
            )

    def _build_market_prompt(self, stocks: List[Dict], summary: Dict) -> str:
        """建立市場總覽 prompt"""
        avg_score = sum(s.get("score", 0) for s in stocks) / len(stocks) if stocks else 0
        
        stocks_text = "\n".join([
            f"{s['symbol']} {s['name']}: 分數{s['score']} 建議{s['action_bias']} 趨勢{s['signals']['trend']} 法人{s['signals']['institutional']}"
            for s in stocks[:10]
        ])
        
        prompt = f"""請根據以下今日台股分析數據，產生市場總覽：

【今日統計】
- 分析檔數: {len(stocks)}
- 平均分數: {avg_score:.1f}
- 可留意檔數: {len([s for s in stocks if s['action_bias'] == '可留意'])}
- 觀察檔數: {len([s for s in stocks if s['action_bias'] == '觀察'])}
- 偏保守檔數: {len([s for s in stocks if s['action_bias'] == '偏保守'])}

【前10檔重點】
{stocks_text}

請產生以下內容（JSON 格式）：
{{
  "market_overview_ai": "用30字內總結今日市場氛圍與操作策略",
  "today_focus_ai": ["今日第一個觀察重點", "今日第二個觀察重點", "今日第三個觀察重點"]
}}

注意：
1. 必須是有效 JSON
2. 不要有任何說明文字，直接輸出 JSON
3. 每個重點15字以內
"""
        return prompt
    
    def _build_groups_prompt(self, stocks: List[Dict]) -> str:
        """建立分群分析 prompt"""
        strongest = [s for s in stocks if s['action_bias'] == '可留意'][:5]
        caution = [s for s in stocks if s['action_bias'] == '觀察'][:5]
        avoid = [s for s in stocks if s['action_bias'] in ['偏保守', '暫不考慮']][:5]
        
        def format_stock_list(stock_list):
            return "\n".join([
                f"- {s['symbol']} {s['name']}: 分數{s['score']}, {s['one_line_summary']}"
                for s in stock_list
            ])
        
        prompt = f"""請分析以下三組股票，產生群組總結：

【最值得先看組】（分數高+條件好）
{format_stock_list(strongest)}

【轉強觀察組】（有潛力但需觀察）
{format_stock_list(caution)}

【今日先不要碰組】（條件不佳）
{format_stock_list(avoid)}

請產生 JSON：
{{
  "strongest_group_ai": "這組共同特色與操作建議，30字內",
  "caution_group_ai": "這組需要注意什麼，30字內",
  "avoid_group_ai": "為什麼這組今天不適合，30字內"
}}

直接輸出 JSON，不要說明。
"""
        return prompt
    
    def _build_batch_stocks_prompt(
        self,
        stocks: List[Dict],
        yesterday_map: Dict[str, Dict]
    ) -> str:
        """
        批次分析所有個股的 prompt，強制差異化約束。
        每檔必須使用獨特訊號，禁止空泛套話，重複超標時 raise。
        """
        blocks = []
        for s in stocks:
            yest = yesterday_map.get(s["symbol"])
            indic = s.get("indicators", {})
            sigs = s.get("signals", {})

            if yest:
                score_diff = s["score"] - yest.get("score", s["score"])
                rank_diff = yest.get("rank", s["rank"]) - s["rank"]  # 正數=名次前進
                if score_diff > 0 and rank_diff > 0:
                    change_hint = f"分數從{yest['score']}升至{s['score']}，名次前進"
                elif score_diff > 0:
                    change_hint = f"分數從{yest['score']}升至{s['score']}，名次後退"
                elif score_diff < 0 and rank_diff < 0:
                    change_hint = f"分數從{yest['score']}降至{s['score']}，名次後退"
                elif score_diff < 0:
                    change_hint = f"分數從{yest['score']}降至{s['score']}，名次前進"
                else:
                    change_hint = f"分數持平{s['score']}，名次{'前進' if rank_diff > 0 else '後退' if rank_diff < 0 else '不變'}"
            else:
                change_hint = "首次入榜"

            block = (
                f"\n股票 {s['symbol']} {s['name']}：\n"
                f"  分數={s['score']} 排名={s['rank']} 建議={s['action_bias']}\n"
                f"  趨勢={sigs.get('trend','--')} 量能={sigs.get('volume','--')} "
                f"量比={indic.get('volume_ratio','--')}\n"
                f"  法人={sigs.get('institutional','--')} KD={sigs.get('kd','--')}\n"
                f"  與前次比較：{change_hint}"
            )
            blocks.append(block)

        stocks_text = "\n".join(blocks)

        return f"""請分析以下 {len(stocks)} 檔台股，逐一產生 AI 評語。

【硬性約束 - 違反即失敗】
1. 每檔 why_selected_ai 必須反映「該檔的獨特訊號組合」，不可套同一套話。
2. 每檔 risk_ai 必須選「該檔最 relevant 的風險」，5 檔不可都一樣。
3. 明確禁止單獨使用以下空泛廢話作為整句：
   ✗ 技術面強勢
   ✗ 量價齊揚
   ✗ 法人買盤進場
   ✗ 短線偏多
   （這些詞可作為句子一部分，但整句話必須更具體）
4. change_vs_yesterday_ai 必須精確選以下標籤之一：
   - 首次入榜
   - 留榜，分數提升
   - 留榜，分數下修
   - 留榜，名次前進
   - 留榜，名次後退
   - 留榜，持平
   - 無前次資料

【個股資料】
{stocks_text}

請輸出 JSON array，順序與上方股票完全一致，共 {len(stocks)} 個元素：
[
  {{
    "symbol": "股票代號",
    "why_selected_ai": "依據獨特訊號的選股理由，20字內",
    "risk_ai": "最relevant的專屬風險，20字內",
    "change_vs_yesterday_ai": "上方標籤之一",
    "primary_drivers": ["訊號1（具體）", "訊號2（具體）"],
    "risk_driver": "風險來源一句話",
    "change_type": "標籤"
  }},
  ...
]

直接輸出 JSON array，不要任何說明文字。"""

    def analyze_market(self, stocks: List[Dict], summary: Dict) -> Dict:
        """分析市場總覽 - 失敗時直接 raise"""
        prompt = self._build_market_prompt(stocks, summary)
        response = self._call_deepseek(prompt, temperature=0.4)

        result = self._parse_json_response(response, ["market_overview_ai", "today_focus_ai"])

        if not isinstance(result.get("today_focus_ai"), list):
            raise AIAnalyzerError("today_focus_ai 不是列表格式")

        return {
            "market_overview_ai": result["market_overview_ai"],
            "today_focus_ai": result["today_focus_ai"]
        }

    def analyze_groups(self, stocks: List[Dict]) -> Dict:
        """分析分群 - 失敗時直接 raise"""
        prompt = self._build_groups_prompt(stocks)
        response = self._call_deepseek(prompt, temperature=0.3)

        result = self._parse_json_response(response, [
            "strongest_group_ai", "caution_group_ai", "avoid_group_ai"
        ])

        return {
            "strongest_group_ai": result["strongest_group_ai"],
            "caution_group_ai": result["caution_group_ai"],
            "avoid_group_ai": result["avoid_group_ai"]
        }

    def analyze_all_stocks(
        self,
        stocks: List[Dict],
        yesterday_map: Dict[str, Dict]
    ) -> List[Dict]:
        """
        批次分析所有個股，強制差異化。
        重複超標時直接 raise（fail-fast）。
        """
        required = [
            "symbol", "why_selected_ai", "risk_ai", "change_vs_yesterday_ai",
            "primary_drivers", "risk_driver", "change_type"
        ]

        prompt = self._build_batch_stocks_prompt(stocks, yesterday_map)
        response = self._call_deepseek(prompt, temperature=0.5)
        raw_list = self._parse_json_array_response(response, len(stocks))

        result_list = []
        for i, item in enumerate(raw_list):
            missing = [f for f in required if f not in item]
            if missing:
                raise AIAnalyzerError(
                    f"個股[{i}] 缺少欄位 {missing}。"
                    f"原始回應前500字：{response[:500]!r}"
                )
            if not isinstance(item.get("primary_drivers"), list) or len(item["primary_drivers"]) < 2:
                raise AIAnalyzerError(
                    f"個股[{i}] {item.get('symbol','')} primary_drivers 必須是至少2項的列表"
                )
            result_list.append({
                "symbol": item["symbol"],
                "why_selected_ai": item["why_selected_ai"],
                "risk_ai": item["risk_ai"],
                "change_vs_yesterday_ai": item["change_vs_yesterday_ai"],
                "primary_drivers": item["primary_drivers"],
                "risk_driver": item["risk_driver"],
                "change_type": item["change_type"]
            })

        # 差異化重複檢查
        self._check_duplicates(result_list)

        return result_list

    def generate_ai_report(self, v5_report: Dict) -> Dict:
        """產生完整的 v6 AI 分析報告 - 任何步驟失敗都會 raise"""
        stocks = v5_report.get("stocks", [])
        summary = v5_report.get("summary", {})
        date_str = v5_report.get("date", get_today_str())

        if not stocks:
            raise AIAnalyzerError("v5 報告沒有股票資料")

        print("[AI] 開始分析市場總覽...")
        market_result = self.analyze_market(stocks, summary)

        print("[AI] 開始分析分群...")
        groups_result = self.analyze_groups(stocks)

        # 載入前次報告，建立 symbol -> data 映射
        print("[AI] 載入前次報告進行比較...")
        yesterday_report = load_yesterday_report(date_str)
        yesterday_stocks = yesterday_report.get("stocks") if yesterday_report else None

        yesterday_map: Dict[str, Dict] = {}
        if yesterday_stocks:
            for s in yesterday_stocks:
                yesterday_map[s["symbol"]] = s
            print(f"[AI] 找到前次報告，共 {len(yesterday_stocks)} 檔")
        else:
            print("[AI] 找不到前次報告，跳過比較")

        # 批次差異化分析個股（一次 API 呼叫，含重複檢查）
        print(f"[AI] 批次差異化分析 {len(stocks)} 檔個股...")
        ai_stock_details = self.analyze_all_stocks(stocks, yesterday_map)
        ai_detail_map = {d["symbol"]: d for d in ai_stock_details}

        ai_stocks = []
        for stock in stocks:
            detail = ai_detail_map.get(stock["symbol"])
            if not detail:
                raise AIAnalyzerError(f"AI 分析結果缺少 {stock['symbol']}")
            ai_stocks.append({
                "symbol": stock["symbol"],
                "name": stock["name"],
                "score": stock["score"],
                "rank": stock["rank"],
                "action_bias": stock["action_bias"],
                **detail
            })

        ai_report = {
            "report_version": "v6-ai",
            "date": date_str,
            "generated_at": get_taiwan_now().isoformat(),
            "ai_model": DEEPSEEK_MODEL,
            **market_result,
            **groups_result,
            "stocks": ai_stocks
        }

        print("[AI] 分析完成")
        return ai_report


def save_ai_report(ai_report: Dict, date_str: Optional[str] = None) -> str:
    """儲存 AI 分析報告"""
    from backend.config import get_report_path

    if date_str is None:
        date_str = get_today_str()

    filename = f"{date_str}-ai.json"
    file_path = os.path.join(os.path.dirname(get_report_path()), filename)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(ai_report, f, ensure_ascii=False, indent=2)

    return file_path

