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
            if not content:
                raise AIAnalyzerError("DeepSeek 回傳空內容")
            return content
        except Exception as e:
            raise AIAnalyzerError(f"DeepSeek API 呼叫失敗: {e}")
    
    def _parse_json_response(self, response: str, required_fields: List[str]) -> Dict:
        """解析 JSON 回應 - 失敗時直接 raise"""
        try:
            result = json.loads(response.strip())
        except json.JSONDecodeError as e:
            raise AIAnalyzerError(f"AI 回應不是有效 JSON: {e}")
        
        # 檢查必要欄位
        missing = [f for f in required_fields if f not in result]
        if missing:
            raise AIAnalyzerError(f"AI 回應缺少必要欄位: {missing}")
        
        return result
    
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
    
    def _build_stock_detail_prompt(self, stock: Dict, yesterday_data: Optional[Dict]) -> str:
        """建立個股詳情 prompt"""
        change_info = ""
        if yesterday_data:
            change_info = f"""
【與前次報告比較】
- 前次分數: {yesterday_data.get('score', 'N/A')}
- 今日分數: {stock['score']}
- 排名變化: {yesterday_data.get('rank', 'N/A')} → {stock['rank']}
"""
        
        prompt = f"""分析個股 {stock['symbol']} {stock['name']}：

【基本資料】
- 分數: {stock['score']} (等級{stock['score_grade']})
- 排名: 第{stock['rank']}名
- 建議: {stock['action_bias']}

【技術訊號】
- 趨勢: {stock['signals']['trend']}
- 量能: {stock['signals']['volume']}
- 法人: {stock['signals']['institutional']}
- KD: {stock['signals']['kd']}

【選股理由】
{chr(10).join(['- ' + r for r in stock.get('plain_reasons', [])])}

【風險提醒】
{chr(10).join(['- ' + r for r in stock.get('plain_risks', [])])}

{change_info}

請產生 JSON：
{{
  "why_selected_ai": "為什麼選這檔，20字內人話說明",
  "risk_ai": "最需要注意的風險，20字內",
  "change_vs_yesterday_ai": "與前次報告相比的關鍵變化，20字內（無前次資料則填'首次入榜'）"
}}

直接輸出 JSON。
"""
        return prompt
    
    def analyze_market(self, stocks: List[Dict], summary: Dict) -> Dict:
        """分析市場總覽 - 失敗時直接 raise"""
        prompt = self._build_market_prompt(stocks, summary)
        response = self._call_deepseek(prompt, temperature=0.4)
        
        result = self._parse_json_response(response, ["market_overview_ai", "today_focus_ai"])
        
        # 驗證 today_focus_ai 是列表
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
    
    def analyze_stock(self, stock: Dict, yesterday_stocks: Optional[List[Dict]]) -> Dict:
        """分析單一個股 - 失敗時直接 raise"""
        # 查找前次報告數據
        yesterday_data = None
        if yesterday_stocks:
            yesterday_data = next(
                (s for s in yesterday_stocks if s['symbol'] == stock['symbol']), 
                None
            )
        
        prompt = self._build_stock_detail_prompt(stock, yesterday_data)
        response = self._call_deepseek(prompt, temperature=0.3)
        
        result = self._parse_json_response(response, [
            "why_selected_ai", "risk_ai", "change_vs_yesterday_ai"
        ])
        
        return {
            "why_selected_ai": result["why_selected_ai"],
            "risk_ai": result["risk_ai"],
            "change_vs_yesterday_ai": result["change_vs_yesterday_ai"]
        }
    
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
        
        # 載入前次報告
        print("[AI] 載入前次報告進行比較...")
        yesterday_report = load_yesterday_report(date_str)
        yesterday_stocks = yesterday_report.get("stocks") if yesterday_report else None
        
        if yesterday_stocks:
            print(f"[AI] 找到前次報告，共 {len(yesterday_stocks)} 檔")
        else:
            print("[AI] 找不到前次報告，跳過比較")
        
        # 分析每檔個股
        print(f"[AI] 開始分析 {len(stocks)} 檔個股...")
        ai_stocks = []
        for i, stock in enumerate(stocks):
            print(f"[AI] 分析 {i+1}/{len(stocks)}: {stock['symbol']}...")
            ai_detail = self.analyze_stock(stock, yesterday_stocks)
            ai_stocks.append({
                "symbol": stock["symbol"],
                "name": stock["name"],
                "score": stock["score"],
                "rank": stock["rank"],
                "action_bias": stock["action_bias"],
                **ai_detail
            })
        
        # 組合最終報告 - 使用台灣時區
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
