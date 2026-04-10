/**
 * 看盤助手 v6.1 - Cloudflare Worker
 *
 * 提供給前端呼叫的 AI 分析 API：
 *   POST /api/stock-ai  ← 輸入 symbol + date，回傳 AI 解讀
 *
 * 安全原則：
 *   - DEEPSEEK_API_KEY 只存在 Worker secrets，前端絕對看不到
 *   - universe.json 從 GitHub Pages 公開網址讀取（不需要鑑權）
 *
 * 部署完成後，將回傳的 Worker URL 填入 frontend/stock.html 的 WORKER_URL 常數。
 */

// GitHub Pages 上的 reports 根目錄（公開網址）
const GITHUB_PAGES_BASE = 'https://paul800901.github.io/kanpan-helper/reports';

// DeepSeek API 端點
const DEEPSEEK_API_URL = 'https://api.deepseek.com/chat/completions';

// ────────────────────────────────────────
// 主入口
// ────────────────────────────────────────
export default {
    async fetch(request, env) {
        const url = new URL(request.url);

        // CORS preflight
        if (request.method === 'OPTIONS') {
            return new Response(null, {
                status: 204,
                headers: corsHeaders(request),
            });
        }

        if (url.pathname === '/api/stock-ai' && request.method === 'POST') {
            return handleStockAI(request, env);
        }

        return new Response(JSON.stringify({ ok: false, error: 'Not Found' }), {
            status: 404,
            headers: { 'Content-Type': 'application/json' },
        });
    },
};

// ────────────────────────────────────────
// 主 Handler
// ────────────────────────────────────────
async function handleStockAI(request, env) {
    // 1. 解析輸入
    let body;
    try {
        body = await request.json();
    } catch {
        return jsonError(request, 400, '無效的 JSON 格式');
    }

    const { symbol, date } = body || {};

    // 2. 驗證
    if (!symbol || !/^\d{4}$/.test(symbol)) {
        return jsonError(request, 400, 'symbol 格式無效，須為 4 位數字（例如：2330）');
    }
    if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
        return jsonError(request, 400, 'date 格式無效，須為 YYYY-MM-DD');
    }

    // 3. 從 GitHub Pages 讀取 universe.json
    let universeData;
    try {
        const universeUrl = `${GITHUB_PAGES_BASE}/${date}-universe.json`;
        const res = await fetch(universeUrl, {
            cf: { cacheTtl: 300, cacheEverything: true },
        });
        if (!res.ok) {
            throw new Error(`universe.json 不存在（HTTP ${res.status}）。請確認 ${date} 的 workflow 已執行完成。`);
        }
        universeData = await res.json();
    } catch (e) {
        return jsonError(request, 404, String(e.message));
    }

    // 4. 找到指定股票
    const stock = (universeData.stocks || []).find(s => s.symbol === symbol);
    if (!stock) {
        return jsonError(request, 404, `${date} 的資料中找不到股票 ${symbol}`);
    }

    // 5. 組 prompt 並呼叫 DeepSeek
    const DEEPSEEK_API_KEY = env.DEEPSEEK_API_KEY;
    if (!DEEPSEEK_API_KEY) {
        return jsonError(request, 500, '伺服器未設定 DEEPSEEK_API_KEY，請至 Cloudflare 設定 secret');
    }

    let aiResult;
    try {
        const prompt = buildPrompt(stock, date);
        aiResult = await callDeepSeek(prompt, DEEPSEEK_API_KEY);
    } catch (e) {
        return jsonError(request, 500, `AI 分析失敗：${e.message}`);
    }

    // 6. 回傳結果
    return jsonResponse(request, {
        ok: true,
        symbol,
        date,
        name: stock.name,
        ...aiResult,
    });
}

// ────────────────────────────────────────
// 組合 prompt
// ────────────────────────────────────────
function buildPrompt(stock, date) {
    const volPct = stock.volume_ratio != null
        ? Math.round(stock.volume_ratio * 100) + '%'
        : '--';
    const reasons = (stock.plain_reasons || []).join('；');
    const risks   = (stock.plain_risks   || []).join('；');

    return `你是一位台股市場分析師，擅長用白話文解讀技術數據。請用繁體中文分析以下個股，語氣親切、適合一般投資人閱讀。

股票：${stock.name}（${stock.symbol}）　日期：${date}
評分：${stock.score} 分（${stock.score_grade} 級 / ${stock.score_label}）
建議傾向：${stock.action_bias}
趨勢：${stock.trend}　量能：${stock.volume}（量比：${volPct}）
法人：${stock.institutional}　KD 狀態：${stock.kd_state}
一句摘要：${stock.one_line_summary}
技術觀察：${reasons}
風險提示：${risks}

請以 JSON 格式回覆，不要加任何說明文字或 markdown 區塊，直接輸出：
{
  "ai_summary": "50字內整體分析摘要",
  "trend_view": "30字內趨勢觀點",
  "risk_view": "30字內主要風險",
  "watch_points": ["觀察點1（20字內）", "觀察點2（20字內）", "觀察點3（20字內）"]
}`;
}

// ────────────────────────────────────────
// 呼叫 DeepSeek API
// ────────────────────────────────────────
async function callDeepSeek(prompt, apiKey) {
    const response = await fetch(DEEPSEEK_API_URL, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
            model: 'deepseek-chat',
            messages: [{ role: 'user', content: prompt }],
            max_tokens: 500,
            temperature: 0.3,
            response_format: { type: 'json_object' },
        }),
    });

    if (!response.ok) {
        const errText = await response.text().catch(() => '');
        throw new Error(`DeepSeek API 錯誤 (${response.status}): ${errText.slice(0, 200)}`);
    }

    const data = await response.json();
    const content = data.choices?.[0]?.message?.content || '';

    // 嘗試解析 JSON
    let parsed;
    try {
        // DeepSeek 有時會在 JSON 外加 markdown，提取花括號內容
        const match = content.match(/\{[\s\S]*\}/);
        parsed = JSON.parse(match ? match[0] : content);
    } catch {
        throw new Error(`AI 回應格式無效，無法解析 JSON：${content.slice(0, 100)}`);
    }

    return {
        ai_summary:   String(parsed.ai_summary   || ''),
        trend_view:   String(parsed.trend_view   || ''),
        risk_view:    String(parsed.risk_view    || ''),
        watch_points: Array.isArray(parsed.watch_points) ? parsed.watch_points.map(String) : [],
    };
}

// ────────────────────────────────────────
// CORS Helpers
// ────────────────────────────────────────
function corsHeaders(request) {
    const origin = request.headers.get('Origin') || '';
    // 允許 GitHub Pages + 本地開發
    const allowedOrigins = [
        'https://paul800901.github.io',
        'http://localhost',
        'http://127.0.0.1',
    ];
    const match = allowedOrigins.find(o => origin.startsWith(o));
    return {
        'Access-Control-Allow-Origin': match ? origin : 'https://paul800901.github.io',
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Max-Age': '86400',
    };
}

function jsonResponse(request, data, status = 200) {
    return new Response(JSON.stringify(data, null, 2), {
        status,
        headers: {
            ...corsHeaders(request),
            'Content-Type': 'application/json; charset=utf-8',
        },
    });
}

function jsonError(request, status, message) {
    return jsonResponse(request, { ok: false, error: message }, status);
}
