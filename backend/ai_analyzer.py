"""v6 DeepSeek AI 分析模組

將 FinMind + 規則引擎結果，透過 DeepSeek API 進行智能分析，
產生市場總覽、今日焦點、個股理由等 AI 判讀內容。

注意：在 ENABLE_AI_ANALYSIS=true 模式下，任何錯誤都會直接 raise，
不會使用 fallback 內容。
"""

import json
import os
from typing import Any, Dict, List, Optional
from backend.config import get_today_str, get_taiwan_now
from backend.yesterday_compare import load_yesterday_report

# DeepSeek API 配置
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# 檢查是否強制 AI 模式（任何失敗都要 raise）
FORCE_AI_MODE = os.environ.get("ENABLE_AI_ANALYSIS", "").lower() in ["true", "1", "yes"]

AI_DIRECTION_MAP = {
    "暫不考慮": "偏保守",
    "暫不進場": "偏保守",
    "先觀望": "偏向觀察",
    "可留意": "偏多",
    "可偏多觀察": "偏多",
    "強勢續看": "偏多"
}

PROHIBITED_DIRECTIVE_PHRASES = (
    "買進", "買入", "賣出", "進場", "出場", "加碼", "減碼",
    "停損", "停利", "抄底", "布局", "佈局", "建議買", "建議賣",
    "可買", "可賣", "逢低買", "追價買", "進場點"
)


def _to_num(value: Any) -> Optional[float]:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num


def _is_consecutive_institutional_buy(label: Any) -> bool:
    text = str(label or "")
    return "連" in text and "買" in text


def _is_close_to_ma5(close: Optional[float], ma5: Optional[float]) -> bool:
    if close is None or ma5 in [None, 0]:
        return False
    return abs(close - ma5) / abs(ma5) <= 0.01


def _get_ma20_diff(close: Optional[float], ma20: Optional[float]) -> Optional[float]:
    if close is None or ma20 in [None, 0]:
        return None
    return (close - ma20) / ma20


def _downgrade_bullish_summary(summary: Dict[str, str]) -> Dict[str, str]:
    if summary["advice"] == "強勢續看":
        return {
            "advice": "可偏多觀察",
            "reason": "結構仍偏多，但量能或過熱需要再確認",
            "risk": "縮量或高檔過熱時，續攻失敗容易回檔"
        }
    if summary["advice"] == "可偏多觀察":
        return {
            "advice": "先觀望",
            "reason": "偏多條件存在，但量能或過熱需要先消化",
            "risk": "追價後若量縮或高檔反轉，容易回落"
        }
    return summary


def get_v72_decision_summary(stock: Dict[str, Any]) -> Dict[str, str]:
    indicators = stock.get("indicators", {}) or {}
    signals = stock.get("signals", {}) or {}

    score = _to_num(stock.get("score"))
    close = _to_num(indicators.get("close"))
    ma5 = _to_num(indicators.get("ma5"))
    ma20 = _to_num(indicators.get("ma20"))
    k = _to_num(indicators.get("k"))
    volume_ratio = _to_num(indicators.get("volume_ratio"))
    institutional = str(
        signals.get("institutional")
        or stock.get("institutional")
        or stock.get("institution_trend")
        or ""
    ).strip()
    ma20_diff = _get_ma20_diff(close, ma20)
    is_weak_below_ma20 = (
        score is not None and score < 60 and
        close is not None and ma20 is not None and close < ma20
    )
    has_bullish_penalty = (
        (volume_ratio is not None and volume_ratio < 1) or
        (k is not None and k >= 80)
    )

    if score is not None and score < 50:
        return {
            "advice": "暫不考慮",
            "reason": "分數過低且結構偏弱",
            "risk": "下跌延續或反彈失敗"
        }

    matches: List[Dict[str, Any]] = []

    if score is not None and close is not None and ma20 is not None and score >= 80 and close > ma20:
        matches.append({
            "advice": "強勢續看",
            "reason": "評分高且結構偏強",
            "risk": "短線過熱時不宜追價",
            "priority": 5
        })

    if close is not None and ma20 is not None and close > ma20 and _is_consecutive_institutional_buy(institutional):
        matches.append({
            "advice": "可偏多觀察",
            "reason": "價格站上中期結構且法人偏多",
            "risk": "短線若爆量不續攻，容易追高回檔",
            "priority": 4
        })

    if not is_weak_below_ma20 and close is not None and ma20 is not None and k is not None and close < ma20 and k < 30:
        matches.append({
            "advice": "可留意",
            "reason": "低檔區出現反彈訊號",
            "risk": "尚未站回中期結構，反彈可能失敗",
            "priority": 3
        })

    if not is_weak_below_ma20 and (
        (ma20_diff is not None and ma20_diff < 0 and ma20_diff > -0.01) or
        (close is not None and ma5 is not None and volume_ratio is not None and _is_close_to_ma5(close, ma5) and volume_ratio < 1)
    ):
        matches.append({
            "advice": "先觀望",
            "reason": "貼近中期結構，先觀察是否重新站穩"
            if ma20_diff is not None and ma20_diff < 0 and ma20_diff > -0.01
            else "短線位置不差，但量能不足",
            "risk": "若無法站回中期結構，容易再度轉弱"
            if ma20_diff is not None and ma20_diff < 0 and ma20_diff > -0.01
            else "缺乏續航，容易震盪",
            "priority": 2
        })

    if is_weak_below_ma20 or (ma20_diff is not None and ma20_diff <= -0.01):
        matches.append({
            "advice": "暫不進場",
            "reason": "分數偏低且仍在中期壓力下方" if is_weak_below_ma20 else "仍在中期壓力下方",
            "risk": "弱勢延續時，反彈容易失敗" if is_weak_below_ma20 else "容易出現反彈後再回落",
            "priority": 1
        })

    matches.sort(key=lambda item: item["priority"], reverse=True)
    summary = matches[0] if matches else {
        "advice": "先觀望",
        "reason": "條件不足，方向不明",
        "risk": "短線震盪或反覆"
    }

    if has_bullish_penalty and summary["advice"] in ["強勢續看", "可偏多觀察"]:
        summary = _downgrade_bullish_summary(summary)

    return {
        "advice": summary["advice"],
        "reason": summary["reason"],
        "risk": summary["risk"]
    }


def get_expected_ai_direction(advice: str) -> str:
    return AI_DIRECTION_MAP.get(advice, "偏向觀察")


def _contains_prohibited_directive(text: str) -> bool:
    return any(phrase in text for phrase in PROHIBITED_DIRECTIVE_PHRASES)


def build_fallback_v8_judgment(stock: Dict[str, Any], decision_summary: Dict[str, str]) -> Dict[str, Any]:
    indicators = stock.get("indicators", {}) or {}
    signals = stock.get("signals", {}) or {}
    close = _to_num(indicators.get("close"))
    ma5 = _to_num(indicators.get("ma5"))
    ma20 = _to_num(indicators.get("ma20"))
    k = _to_num(indicators.get("k"))
    d = _to_num(indicators.get("d"))
    volume_ratio = _to_num(indicators.get("volume_ratio"))
    institutional = str(signals.get("institutional") or stock.get("institutional") or "").strip()

    structure = "目前資料以既有決策摘要為主，技術結構仍待確認。"
    if close is not None and ma5 is not None and ma20 is not None:
        if close > ma5 > ma20:
            structure = "目前價格位於短中期均線之上，整體技術結構仍偏強。"
        elif close > ma20:
            structure = "目前仍守在 ma20 之上，但短線位置還需要持續觀察。"
        elif close < ma20 and close >= ma5:
            structure = "目前位於短線支撐與中期壓力之間，方向尚未完全明朗。"
        elif close < ma5 and close < ma20:
            structure = "目前價格位於短中期均線下方，整體技術結構仍偏弱。"
    elif decision_summary.get("reason"):
        structure = decision_summary["reason"]

    bullish_factors: List[str] = []
    if signals.get("trend") == "偏多" or (close is not None and ma20 is not None and close > ma20):
        bullish_factors.append("價格仍維持在中期結構附近或之上。")
    if institutional and "買" in institutional:
        bullish_factors.append(f"法人面呈現{institutional}，籌碼尚未明顯轉弱。")
    if volume_ratio is not None and volume_ratio >= 1:
        bullish_factors.append(f"量能維持常態以上（量比{volume_ratio:.2f}）。")
    if k is not None and d is not None and k >= d:
        bullish_factors.append("KD 相對仍偏多，尚未出現明顯轉弱訊號。")
    if close is not None and ma5 is not None and close >= ma5:
        bullish_factors.append("價格仍守在 ma5 附近或之上。")
    if not bullish_factors:
        bullish_factors.append("目前有利條件有限，需觀察既有結構是否能延續。")

    risk_factors: List[str] = []
    if decision_summary.get("risk"):
        risk_factors.append(f"{decision_summary['risk']}。")
    if close is not None and ma20 is not None and close < ma20:
        risk_factors.append("仍在 ma20 附近或下方，容易遇到中期壓力。")
    if volume_ratio is not None and volume_ratio < 1:
        risk_factors.append(f"量能偏弱（量比{volume_ratio:.2f}），續航力仍待確認。")
    if institutional and "賣" in institutional:
        risk_factors.append(f"法人面呈現{institutional}，籌碼仍有調節壓力。")
    if k is not None and k >= 80:
        risk_factors.append("KD 位於高檔，短線震盪風險偏高。")
    if close is not None and ma5 is not None and close < ma5:
        risk_factors.append("短線位置仍未穩定站回 ma5。")
    if not risk_factors:
        risk_factors.append("目前仍需留意訊號延續性與波動風險。")

    direction = get_expected_ai_direction(decision_summary.get("advice", "先觀望"))
    conclusion = "結論偏向觀察，先確認結構是否延續。"
    if direction == "偏多":
        conclusion = "結論偏多，重點觀察強勢結構是否延續。"
    elif direction == "偏保守":
        conclusion = "結論偏保守，先等待壓力消化與結構修復。"

    return {
        "structure": structure,
        "bullish_factors": bullish_factors[:3],
        "risk_factors": risk_factors[:3],
        "conclusion": conclusion
    }


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
        若 why_selected_ai 或 risk_ai 有超過 1 對相似，視為生成失敗，直接 raise。
        相似度以字元集 Jaccard 係數 > 0.75 判定，避免因共享市場條件用語造成誤判。
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
            if jaccard(why_texts[i], why_texts[j]) > 0.75
        )
        risk_dupes = sum(
            1 for i in range(len(risk_texts))
            for j in range(i + 1, len(risk_texts))
            if jaccard(risk_texts[i], risk_texts[j]) > 0.75
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

    def _validate_v8_judgment(
        self,
        judgment: Dict[str, Any],
        expected_direction: str,
        symbol: str
    ) -> Dict[str, Any]:
        required = ["structure", "bullish_factors", "risk_factors", "conclusion"]
        missing = [field for field in required if field not in judgment]
        if missing:
            raise AIAnalyzerError(f"{symbol} judgment_ai 缺少欄位 {missing}")

        structure = str(judgment.get("structure", "")).strip()
        conclusion = str(judgment.get("conclusion", "")).strip()
        bullish = judgment.get("bullish_factors")
        risks = judgment.get("risk_factors")

        if not structure or not conclusion:
            raise AIAnalyzerError(f"{symbol} judgment_ai 文字欄位不可為空")
        if not isinstance(bullish, list) or not isinstance(risks, list):
            raise AIAnalyzerError(f"{symbol} judgment_ai factors 必須是列表")

        bullish = [str(item).strip() for item in bullish if str(item).strip()][:3]
        risks = [str(item).strip() for item in risks if str(item).strip()][:3]

        if not bullish:
            raise AIAnalyzerError(f"{symbol} bullish_factors 至少需要 1 項")
        if not risks:
            raise AIAnalyzerError(f"{symbol} risk_factors 至少需要 1 項")

        all_texts = [structure, conclusion, *bullish, *risks]
        if any(_contains_prohibited_directive(text) for text in all_texts):
            raise AIAnalyzerError(f"{symbol} judgment_ai 出現直接買賣指令")
        if expected_direction not in conclusion:
            raise AIAnalyzerError(
                f"{symbol} judgment_ai 結論方向與 decision_summary 不一致："
                f"預期包含 {expected_direction}，實際為 {conclusion}"
            )

        return {
            "structure": structure,
            "bullish_factors": bullish,
            "risk_factors": risks,
            "conclusion": conclusion
        }

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

    def _build_v8_judgment_prompt(self, stocks: List[Dict]) -> str:
        blocks = []
        for stock in stocks:
            indicators = stock.get("indicators", {}) or {}
            signals = stock.get("signals", {}) or {}
            decision_summary = get_v72_decision_summary(stock)
            expected_direction = get_expected_ai_direction(decision_summary["advice"])

            blocks.append(
                f"\n股票 {stock['symbol']} {stock['name']}：\n"
                f"  symbol={stock['symbol']}\n"
                f"  name={stock['name']}\n"
                f"  score={stock.get('score', '--')}\n"
                f"  trend={signals.get('trend', '--')}\n"
                f"  institutional={signals.get('institutional', '--')}\n"
                f"  indicators.close={indicators.get('close', '--')}\n"
                f"  indicators.ma5={indicators.get('ma5', '--')}\n"
                f"  indicators.ma20={indicators.get('ma20', '--')}\n"
                f"  indicators.k={indicators.get('k', '--')}\n"
                f"  indicators.d={indicators.get('d', '--')}\n"
                f"  indicators.volume_ratio={indicators.get('volume_ratio', '--')}\n"
                f"  decision_summary.advice={decision_summary['advice']}\n"
                f"  decision_summary.reason={decision_summary['reason']}\n"
                f"  decision_summary.risk={decision_summary['risk']}\n"
                f"  結論必須包含：{expected_direction}"
            )

        stocks_text = "\n".join(blocks)
        return f"""請用繁體中文，基於以下數據做技術面解讀：

限制：
- 不得編造資訊
- 不得引用新聞或外部資料
- 不得給出直接買賣指令
- 必須與 decision_summary 保持一致方向

輸出：
1. 結構解讀（目前位置）
2. 有利因素（最多3點）
3. 風險因素（最多3點）
4. 一句結論（偏向觀察/偏多/保守）

請輸出 JSON array，順序與上方股票完全一致，共 {len(stocks)} 個元素：
[
    {{
        "symbol": "股票代號",
        "structure": "目前位置的技術結構解讀",
        "bullish_factors": ["有利因素1", "有利因素2"],
        "risk_factors": ["風險因素1", "風險因素2"],
        "conclusion": "一句結論，必須包含偏向觀察或偏多或偏保守"
    }}
]

【個股資料】
{stocks_text}

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

    def analyze_v8_judgments(self, stocks: List[Dict]) -> List[Dict]:
        try:
            prompt = self._build_v8_judgment_prompt(stocks)
            response = self._call_deepseek(prompt, temperature=0.3)
            raw_list = self._parse_json_array_response(response, len(stocks))
        except Exception as exc:
            print(f"[AI] v8 judgment_ai 批次生成失敗，改用 fallback: {exc}")
            return [
                {
                    "symbol": stock["symbol"],
                    "judgment_ai": build_fallback_v8_judgment(
                        stock,
                        get_v72_decision_summary(stock)
                    )
                }
                for stock in stocks
            ]

        results = []
        for i, item in enumerate(raw_list):
            symbol = str(item.get("symbol", "")).strip()
            decision_summary = get_v72_decision_summary(stocks[i])
            if symbol != stocks[i]["symbol"]:
                print(
                    f"[AI] {stocks[i]['symbol']} judgment_ai symbol 不一致，改用 fallback："
                    f"實際為 {symbol or '--'}"
                )
                validated = build_fallback_v8_judgment(stocks[i], decision_summary)
            else:
                expected_direction = get_expected_ai_direction(decision_summary["advice"])
                try:
                    validated = self._validate_v8_judgment(item, expected_direction, stocks[i]["symbol"])
                except Exception as exc:
                    print(f"[AI] {stocks[i]['symbol']} judgment_ai 驗證失敗，改用 fallback: {exc}")
                    validated = build_fallback_v8_judgment(stocks[i], decision_summary)
            results.append({
                "symbol": stocks[i]["symbol"],
                "judgment_ai": validated
            })

        return results

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

        print(f"[AI] 批次生成 v8 judgment_ai {len(stocks)} 檔...")
        v8_judgments = self.analyze_v8_judgments(stocks)
        v8_map = {item["symbol"]: item["judgment_ai"] for item in v8_judgments}

        ai_stocks = []
        for stock in stocks:
            detail = ai_detail_map.get(stock["symbol"])
            if not detail:
                raise AIAnalyzerError(f"AI 分析結果缺少 {stock['symbol']}")
            judgment_ai = v8_map.get(stock["symbol"])
            if not judgment_ai:
                raise AIAnalyzerError(f"v8 judgment_ai 缺少 {stock['symbol']}")
            ai_stocks.append({
                "symbol": stock["symbol"],
                "name": stock["name"],
                "score": stock["score"],
                "rank": stock["rank"],
                "action_bias": stock["action_bias"],
                "judgment_ai": judgment_ai,
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

