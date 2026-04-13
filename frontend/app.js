/**
 * 看盤助手 v31 - 首頁
 * 讀取 YYYY-MM-DD-lite.json + YYYY-MM-DD-ai.json + YYYY-MM-DD-universe.json + strategy_activation.json。
 */

// === State ===
let liteData = null;
let aiData = null;
let fullData = null;
let universeData = null;
let activationData = null;
let indexData = null;
let currentDate = null;

let requestVersion = createRequestVersion();

function createRequestVersion() {
    return String(Date.now());
}

function buildFreshUrl(url, version = requestVersion) {
    const target = new URL(url, window.location.href);
    target.searchParams.set('_ts', version);
    return target.toString();
}
// === Config ===
const IS_GITHUB = window.location.hostname === 'paul800901.github.io';
const BASE = IS_GITHUB
    ? 'https://paul800901.github.io/kanpan-helper/reports'
    : '../reports';

const MINI_CHART_COLORS = Object.freeze({
    up: '#d14b4b',
    down: '#1d8a63',
    ma5: '#f59e0b',
    ma20: '#2563eb',
    grid: 'rgba(26,58,92,0.10)',
    frame: '#d7e3ef',
    text: '#627d98'
});

// === Utils ===
function esc(text) {
    if (text == null) return '';
    const d = document.createElement('div');
    d.textContent = String(text);
    return d.innerHTML;
}
function fmt(n) {
    if (n == null) return '--';
    return Number(n).toLocaleString('zh-TW');
}
function fmtPct(r) {
    if (r == null) return '--';
    return Math.round(r * 100) + '%';
}

function toNum(value) {
    if (value == null || value === '') return null;
    const num = Number(value);
    return Number.isFinite(num) ? num : null;
}

function fmtZonePrice(value) {
    if (value == null) return '--';
    return Number(value).toLocaleString('zh-TW', {
        minimumFractionDigits: 0,
        maximumFractionDigits: 2
    });
}

function shortDateLabel(dateText) {
    if (!dateText) return '--';
    const [year, month, day] = String(dateText).split('-');
    if (!month || !day) return String(dateText);
    return `${month}/${day}`;
}

function isConsecutiveInstitutionalBuy(label) {
    if (!label) return false;
    const text = String(label);
    return text.includes('連') && text.includes('買');
}

function isCloseToMa5(close, ma5) {
    if (close == null || ma5 == null || ma5 === 0) return false;
    return Math.abs(close - ma5) / Math.abs(ma5) <= 0.01;
}

function getMa20Diff(close, ma20) {
    if (close == null || ma20 == null || ma20 === 0) return null;
    return (close - ma20) / ma20;
}

function downgradeBullishSummary(summary) {
    if (summary.advice === '強勢續看') {
        return {
            advice: '可偏多觀察',
            reason: '結構仍偏多，但量能或過熱需要再確認',
            risk: '縮量或高檔過熱時，續攻失敗容易回檔'
        };
    }
    if (summary.advice === '可偏多觀察') {
        return {
            advice: '先觀望',
            reason: '偏多條件存在，但量能或過熱需要先消化',
            risk: '追價後若量縮或高檔反轉，容易回落'
        };
    }
    return summary;
}

const FINAL_ADVICE_PRIORITY = Object.freeze({
    '暫不考慮': 1,
    '暫不進場': 2,
    '先觀望': 3,
    '可留意': 4,
    '可偏多觀察': 5,
    '強勢續看': 6
});

function getAdvicePriority(advice) {
    return FINAL_ADVICE_PRIORITY[advice] || 0;
}

function isAvoidAdvice(advice) {
    return advice === '暫不考慮' || advice === '暫不進場';
}

function isWatchAdvice(advice) {
    return advice === '先觀望';
}

function getAdviceBucket(advice) {
    if (isAvoidAdvice(advice)) return 'avoid';
    if (isWatchAdvice(advice)) return 'watch';
    return 'strong';
}

function getAIConclusionDirection(advice) {
    if (isAvoidAdvice(advice)) return '偏保守';
    if (isWatchAdvice(advice)) return '偏向觀察';
    return '偏多';
}

function hasProhibitedAIInstruction(text) {
    return /買進|買入|賣出|進場|出場|加碼|減碼|停損|停利|抄底|布局|佈局|建議買|建議賣|可買|可賣|逢低買|追價買|進場點/.test(text);
}

function normalizeAITextList(items) {
    if (!Array.isArray(items)) return [];
    return items
        .map(item => String(item ?? '').trim())
        .filter(Boolean)
        .slice(0, 3);
}

function buildFallbackAIJudgment(stock, summary) {
    const indicators = stock?.indicators || {};
    const signals = stock?.signals || {};
    const close = toNum(indicators.close);
    const ma5 = toNum(indicators.ma5);
    const ma20 = toNum(indicators.ma20);
    const k = toNum(indicators.k);
    const d = toNum(indicators.d);
    const volumeRatio = toNum(indicators.volume_ratio);
    const institutional = String(signals.institutional ?? stock?.institutional ?? '').trim();

    let structure = '目前資料以決策摘要為主，結構仍待進一步確認。';
    if (close != null && ma5 != null && ma20 != null) {
        if (close > ma5 && ma5 > ma20) {
            structure = '目前股價站在短中期均線之上，整體結構仍偏強。';
        } else if (close > ma20) {
            structure = '目前仍守在 ma20 之上，但短線位置需要再確認。';
        } else if (close < ma20 && close >= ma5) {
            structure = '目前位於短線支撐與中期壓力之間，方向尚未完全明確。';
        } else if (close < ma5 && close < ma20) {
            structure = '目前位於短中期均線下方，整體結構仍偏弱。';
        }
    } else if (summary?.reason) {
        structure = summary.reason;
    }

    const bullishFactors = [];
    if (signals.trend === '偏多' || (close != null && ma20 != null && close > ma20)) {
        bullishFactors.push('價格仍維持在中期結構附近或之上。');
    }
    if (institutional.includes('買')) {
        bullishFactors.push(`法人面維持${institutional}，籌碼未明顯轉弱。`);
    }
    if (volumeRatio != null && volumeRatio >= 1) {
        bullishFactors.push(`量能維持常態以上（量比${volumeRatio.toFixed(2)}）。`);
    }
    if (k != null && d != null && k >= d) {
        bullishFactors.push('KD 相對仍偏多，尚未出現明顯轉弱訊號。');
    }
    if (close != null && ma5 != null && close >= ma5) {
        bullishFactors.push('股價仍守在 ma5 附近或之上。');
    }

    const riskFactors = [];
    if (summary?.risk) {
        riskFactors.push(`${summary.risk}。`);
    }
    if (close != null && ma20 != null && close < ma20) {
        riskFactors.push('仍在 ma20 附近或下方，容易遇到中期壓力。');
    }
    if (volumeRatio != null && volumeRatio < 1) {
        riskFactors.push(`量能偏弱（量比${volumeRatio.toFixed(2)}），續航力仍待確認。`);
    }
    if (institutional.includes('賣')) {
        riskFactors.push(`法人面呈現${institutional}，籌碼仍有調節壓力。`);
    }
    if (k != null && k >= 80) {
        riskFactors.push('KD 位於高檔，短線震盪風險偏高。');
    }
    if (close != null && ma5 != null && close < ma5) {
        riskFactors.push('短線位置仍未穩定站回 ma5。');
    }

    while (bullishFactors.length < 1) {
        bullishFactors.push('目前有利條件有限，需以既有結構是否延續為主。');
    }
    while (riskFactors.length < 1) {
        riskFactors.push('目前仍需留意訊號延續性與波動風險。');
    }

    const direction = getAIConclusionDirection(summary?.advice || '先觀望');
    let conclusion = '結論偏向觀察，先確認結構是否延續。';
    if (direction === '偏多') {
        conclusion = '結論偏多，重點觀察強勢結構是否延續。';
    } else if (direction === '偏保守') {
        conclusion = '結論偏保守，先等待壓力消化與結構修復。';
    }

    return {
        structure,
        bullishFactors: bullishFactors.slice(0, 3),
        riskFactors: riskFactors.slice(0, 3),
        conclusion,
        isFallback: true
    };
}

function getAIJudgment(stock, ai, summary) {
    const candidate = ai?.judgment_ai;
    const expectedDirection = getAIConclusionDirection(summary?.advice || '先觀望');

    if (!candidate || typeof candidate !== 'object') {
        return buildFallbackAIJudgment(stock, summary);
    }

    const structure = String(candidate.structure ?? '').trim();
    const bullishFactors = normalizeAITextList(candidate.bullish_factors);
    const riskFactors = normalizeAITextList(candidate.risk_factors);
    const conclusion = String(candidate.conclusion ?? '').trim();
    const allTexts = [structure, conclusion, ...bullishFactors, ...riskFactors];

    if (
        !structure ||
        !bullishFactors.length ||
        !riskFactors.length ||
        !conclusion ||
        !conclusion.includes(expectedDirection) ||
        allTexts.some(hasProhibitedAIInstruction)
    ) {
        return buildFallbackAIJudgment(stock, summary);
    }

    return {
        structure,
        bullishFactors,
        riskFactors,
        conclusion,
        isFallback: false
    };
}

function renderAIJudgment(aiJudgment) {
    const bullishItems = aiJudgment.bullishFactors
        .map(item => `<li class="ai-judgment-item">${esc(item)}</li>`)
        .join('');
    const riskItems = aiJudgment.riskFactors
        .map(item => `<li class="ai-judgment-item">${esc(item)}</li>`)
        .join('');
    const fallbackNote = aiJudgment.isFallback
        ? '<div class="ai-judgment-note">AI 資料暫缺，改用系統整理</div>'
        : '';

    return `
        <div class="ai-judgment">
            <div class="ai-judgment-title">AI 判斷</div>
            ${fallbackNote}
            <div class="ai-judgment-row">
                <div class="ai-judgment-label">結構</div>
                <div class="ai-judgment-text">${esc(aiJudgment.structure)}</div>
            </div>
            <div class="ai-judgment-row">
                <div class="ai-judgment-label">有利</div>
                <div class="ai-judgment-text"><ul class="ai-judgment-list">${bullishItems}</ul></div>
            </div>
            <div class="ai-judgment-row">
                <div class="ai-judgment-label">風險</div>
                <div class="ai-judgment-text"><ul class="ai-judgment-list">${riskItems}</ul></div>
            </div>
            <div class="ai-judgment-row">
                <div class="ai-judgment-label">結論</div>
                <div class="ai-judgment-text">${esc(aiJudgment.conclusion)}</div>
            </div>
        </div>`;
}

function getDecisionSummary(stock) {
    const indicators = stock?.indicators || {};
    const signals = stock?.signals || {};

    const score = toNum(stock?.score);
    const close = toNum(indicators.close);
    const ma5 = toNum(indicators.ma5);
    const ma20 = toNum(indicators.ma20);
    const k = toNum(indicators.k);
    const volumeRatio = toNum(indicators.volume_ratio);
    const institutional = String(
        signals.institutional ?? stock?.institutional ?? stock?.institution_trend ?? ''
    ).trim();
    const ma20Diff = getMa20Diff(close, ma20);
    const isWeakBelowMa20 = score != null && score < 60 && close != null && ma20 != null && close < ma20;
    const hasBullishPenalty = (volumeRatio != null && volumeRatio < 1) || (k != null && k >= 80);

    if (score != null && score < 50) {
        return {
            advice: '暫不考慮',
            reason: '分數過低且結構偏弱',
            risk: '下跌延續或反彈失敗'
        };
    }

    const matches = [];

    if (score != null && close != null && ma20 != null && score >= 80 && close > ma20) {
        matches.push({
            advice: '強勢續看',
            reason: '評分高且結構偏強',
            risk: '短線過熱時不宜追價',
            priority: 5
        });
    }

    if (close != null && ma20 != null && close > ma20 && isConsecutiveInstitutionalBuy(institutional)) {
        matches.push({
            advice: '可偏多觀察',
            reason: '價格站上中期結構且法人偏多',
            risk: '短線若爆量不續攻，容易追高回檔',
            priority: 4
        });
    }

    if (!isWeakBelowMa20 && close != null && ma20 != null && k != null && close < ma20 && k < 30) {
        matches.push({
            advice: '可留意',
            reason: '低檔區出現反彈訊號',
            risk: '尚未站回中期結構，反彈可能失敗',
            priority: 3
        });
    }

    if (
        !isWeakBelowMa20 && (
            (ma20Diff != null && ma20Diff < 0 && ma20Diff > -0.01) ||
            (close != null && ma5 != null && volumeRatio != null && isCloseToMa5(close, ma5) && volumeRatio < 1)
        )
    ) {
        matches.push({
            advice: '先觀望',
            reason: ma20Diff != null && ma20Diff < 0 && ma20Diff > -0.01
                ? '貼近中期結構，先觀察是否重新站穩'
                : '短線位置不差，但量能不足',
            risk: ma20Diff != null && ma20Diff < 0 && ma20Diff > -0.01
                ? '若無法站回中期結構，容易再度轉弱'
                : '缺乏續航，容易震盪',
            priority: 2
        });
    }

    if (isWeakBelowMa20 || (ma20Diff != null && ma20Diff <= -0.01)) {
        matches.push({
            advice: '暫不進場',
            reason: isWeakBelowMa20 ? '分數偏低且仍在中期壓力下方' : '仍在中期壓力下方',
            risk: isWeakBelowMa20 ? '弱勢延續時，反彈容易失敗' : '容易出現反彈後再回落',
            priority: 1
        });
    }

    matches.sort((left, right) => right.priority - left.priority);

    let summary = matches[0] || {
        advice: '先觀望',
        reason: '條件不足，方向不明',
        risk: '短線震盪或反覆'
    };

    if (
        hasBullishPenalty &&
        (summary.advice === '強勢續看' || summary.advice === '可偏多觀察')
    ) {
        summary = downgradeBullishSummary(summary);
    }

    return summary;
}

function getEntryZones(stock, summary = getDecisionSummary(stock)) {
    const indicators = stock?.indicators || {};
    const score = toNum(stock?.score);
    const close = toNum(indicators.close);
    const ma5 = toNum(indicators.ma5);
    const ma20 = toNum(indicators.ma20);
    const advice = summary?.advice || '先觀望';
    const isWeakBelowMa20 = score != null && score < 60 && close != null && ma20 != null && close < ma20;
    const pilotLowValue = ma5 != null ? ma5 * 0.98 : null;
    const pilotHighValue = ma5 != null ? ma5 * 1.02 : null;
    const isPilotInside = close != null && pilotLowValue != null && pilotHighValue != null && close >= pilotLowValue && close <= pilotHighValue;
    const isPilotExpired = close != null && pilotHighValue != null && close > pilotHighValue;

    let observe = '--';
    let observeAnchor = null;
    if (close != null) {
        if (ma5 != null && close < ma5) {
            observe = `${fmtZonePrice(ma5)}附近`;
            observeAnchor = ma5;
        } else {
            observe = `${fmtZonePrice(close * 1.01)}以上`;
            observeAnchor = close * 1.01;
        }
    }

    let pilot = '--';
    if (ma5 != null) {
        const pilotLow = fmtZonePrice(ma5 * 0.98);
        const pilotHigh = fmtZonePrice(ma5 * 1.02);
        const pilotBase = `${pilotLow} ~ ${pilotHigh}`;

        if (isAvoidAdvice(advice)) {
            pilot = '不建議使用（目前不在可進場狀態）';
            if (isPilotInside) {
                pilot += '（即使落在區間內，仍不建議進場）';
            }
        } else if (isWatchAdvice(advice)) {
            if (isPilotExpired) {
                pilot = `${pilotBase}（已離開試單區，僅供觀察，不建議進場）`;
            } else if (isPilotInside) {
                pilot = `${pilotBase}（現價位於試單區內，僅供觀察，不建議進場）`;
            } else {
                pilot = `${pilotBase}（僅供觀察，不建議進場）`;
            }
        } else if (isPilotExpired) {
            pilot = `${pilotBase}（已離開試單區）`;
        } else if (isPilotInside) {
            pilot = `${pilotBase}（現價位於試單區內）`;
        } else {
            pilot = pilotBase;
        }
    }

    let lowRisk = '--';
    let lowRiskAnchor = null;
    if (isAvoidAdvice(advice)) {
        observe = '暫不提供（等待結構重新轉強）';
        lowRisk = isWeakBelowMa20
            ? '暫不提供（仍在中期壓力下）'
            : '暫不提供（目前不在可進場狀態）';
    } else if (isWeakBelowMa20) {
        lowRisk = '暫不提供（仍在中期壓力下）';
    } else if (ma20 != null) {
        lowRisk = `${fmtZonePrice(ma20)}附近`;
        lowRiskAnchor = ma20;
        if (close != null && ma20 > close && score != null && score < 70) {
            lowRisk += '（壓力未完全消化）';
        }
    }

    if (
        !isAvoidAdvice(advice) &&
        observeAnchor != null &&
        lowRiskAnchor != null &&
        lowRiskAnchor !== 0 &&
        Math.abs(observeAnchor - lowRiskAnchor) / Math.abs(lowRiskAnchor) < 0.01
    ) {
        observe = `區間集中：${fmtZonePrice((observeAnchor + lowRiskAnchor) / 2)}附近（需等待明確方向）`;
        lowRisk = '已併入觀察區';
    }

    return {
        observe,
        pilot,
        lowRisk
    };
}

function renderEntryZones(entryZones) {
    return `
        <div class="entry-zones">
            <div class="entry-zones-title">進場區間</div>
            <div class="entry-zone-row">
                <div class="entry-zone-label">觀察區</div>
                <div class="entry-zone-text">${esc(entryZones.observe)}</div>
            </div>
            <div class="entry-zone-row">
                <div class="entry-zone-label">試單區</div>
                <div class="entry-zone-text">${esc(entryZones.pilot)}</div>
            </div>
            <div class="entry-zone-row">
                <div class="entry-zone-label">低風險區</div>
                <div class="entry-zone-text">${esc(entryZones.lowRisk)}</div>
            </div>
        </div>`;
}

function renderDecisionSummary(summary, stock) {
    const entryZones = getEntryZones(stock, summary);
    return `
        <div class="decision-summary">
            <div class="decision-summary-title">決策摘要</div>
            <div class="decision-summary-row">
                <div class="decision-summary-label">建議</div>
                <div class="decision-summary-text">${esc(summary.advice)}</div>
            </div>
            <div class="decision-summary-row">
                <div class="decision-summary-label">理由</div>
                <div class="decision-summary-text">${esc(summary.reason)}</div>
            </div>
            <div class="decision-summary-row">
                <div class="decision-summary-label">風險</div>
                <div class="decision-summary-text">${esc(summary.risk)}</div>
            </div>
            ${renderEntryZones(entryZones)}
        </div>`;
}

// === Data Fetch ===
async function fetchJSON(url, version = requestVersion) {
    const res = await fetch(buildFreshUrl(url, version), { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${url}`);
    return res.json();
}

async function loadIndex() {
    try { return await fetchJSON(`${BASE}/index.json`); }
    catch (e) { console.warn('index.json 載入失敗:', e.message); return null; }
}

async function loadReports(date) {
    const [lite, ai, full, activation, universe] = await Promise.allSettled([
        fetchJSON(`${BASE}/${date}-lite.json`),
        fetchJSON(`${BASE}/${date}-ai.json`),
        fetchJSON(`${BASE}/${date}.json`),
        fetchJSON(`${BASE}/strategy_activation.json`),
        fetchJSON(`${BASE}/${date}-universe.json`)
    ]);
    if (lite.status === 'rejected') {
        throw new Error(`lite 報告載入失敗: ${lite.reason.message}`);
    }
    if (full.status === 'rejected') {
        console.warn(`${date}.json 不存在，首頁決策摘要將使用保底訊息`);
    }
    if (activation.status === 'rejected') {
        console.warn(`strategy_activation.json 不存在，首頁將隱藏 steady_v5 啟用判斷: ${activation.reason.message}`);
    }
    if (universe.status === 'rejected') {
        console.warn(`${date}-universe.json 不存在，首頁將隱藏焦點圖表區: ${universe.reason.message}`);
    }
    return {
        lite: lite.value,
        ai: ai.status === 'fulfilled' ? ai.value : null,
        full: full.status === 'fulfilled' ? full.value : null,
        activation: activation.status === 'fulfilled' ? activation.value : null,
        universe: universe.status === 'fulfilled' ? universe.value : null
    };
}

// === Date Dropdown ===
function buildDateDropdown() {
    const sel = document.getElementById('dateDropdown');
    if (!indexData || !indexData.reports || indexData.reports.length === 0) {
        sel.innerHTML = '<option value="">無可用報告</option>';
        return;
    }
    sel.innerHTML = indexData.reports
        .filter(r => r.has_lite)
        .map(r => {
            const isSelected = r.date === currentDate ? ' selected' : '';
            const tag = r.date === indexData.latest_date ? ' (最新)' : '';
            return `<option value="${r.date}"${isSelected}>${r.date}${tag}</option>`;
        })
        .join('');
}

function updateDateBadge() {
    const el = document.getElementById('dateBadge');
    if (!currentDate || !indexData) { el.textContent = ''; el.className = 'date-badge'; return; }
    const isLatest = currentDate === indexData.latest_date;
    el.textContent = isLatest ? '最新' : '歷史';
    el.className = `date-badge ${isLatest ? 'latest' : 'history'}`;
}

// === UI States ===
function showLoading() {
    document.getElementById('loadingState').style.display = 'flex';
    document.getElementById('aiOverview').style.display = 'none';
    document.getElementById('activationSection').style.display = 'none';
    document.getElementById('focusChartSection').style.display = 'none';
    document.getElementById('groupSection').style.display = 'none';
    document.getElementById('stockSection').style.display = 'none';
    document.getElementById('footerBar').style.display = 'none';
}

function showContent() {
    document.getElementById('loadingState').style.display = 'none';
    document.getElementById('aiOverview').style.display = 'block';
    document.getElementById('groupSection').style.display = 'flex';
    document.getElementById('stockSection').style.display = 'block';
    document.getElementById('footerBar').style.display = 'flex';
}

function showError(title, msg) {
    document.getElementById('errorTitle').textContent = title;
    document.getElementById('errorMsg').innerHTML = msg;
    document.getElementById('errorModal').style.display = 'flex';
}

// === Render: AI Overview ===
function renderAIOverview() {
    const overviewEl = document.getElementById('marketOverviewAI');
    const focusEl = document.getElementById('focusList');

    if (aiData) {
        overviewEl.textContent = aiData.market_overview_ai || '今日 AI 市場分析完成';
        const focuses = aiData.today_focus_ai || [];
        focusEl.innerHTML = focuses
            .map((f, i) => `<div class="focus-item" data-num="${i + 1}">${esc(f)}</div>`)
            .join('');
    } else {
        overviewEl.textContent = liteData?.summary?.market_overview || '今日市場資料已載入';
        focusEl.innerHTML = '';
    }
}

function getActivationTone(action) {
    if (action === '啟用') return 'enabled';
    if (action === '降權') return 'downweight';
    return 'disabled';
}

function renderStrategyActivation() {
    const section = document.getElementById('activationSection');
    const card = document.getElementById('activationCard');
    const titleEl = document.getElementById('activationTitle');
    const statusEl = document.getElementById('activationStatus');
    const summaryEl = document.getElementById('activationSummary');
    const noteEl = document.getElementById('activationNote');
    const metaEl = document.getElementById('activationMeta');
    const gatesEl = document.getElementById('activationGates');

    if (!activationData) {
        section.style.display = 'none';
        return;
    }

    const action = activationData?.decision?.action || '--';
    const weightMultiplier = activationData?.decision?.weight_multiplier;
    const currentMarket = activationData?.current_market_snapshot || {};
    const gateChecks = activationData?.gate_checks || {};
    const isAlignedToSelectedDate = activationData?.as_of_date === currentDate;
    const tone = getActivationTone(action);

    card.className = `activation-card ${tone}`;
    titleEl.textContent = isAlignedToSelectedDate
        ? '今日策略過濾'
        : `最新策略過濾（${activationData?.as_of_date || '--'}）`;
    statusEl.textContent = weightMultiplier != null ? `${action} ${weightMultiplier}x` : action;
    statusEl.className = `activation-status ${tone}`;
    summaryEl.textContent = activationData?.summary || '目前沒有 steady_v5 啟用判斷。';

    if (isAlignedToSelectedDate) {
        noteEl.style.display = 'none';
        noteEl.textContent = '';
    } else {
        noteEl.style.display = 'block';
        noteEl.textContent = `你正在查看 ${currentDate}，這張卡顯示的是最新日期 ${activationData?.as_of_date || '--'} 的 steady_v5 啟用判斷。`;
    }

    const trendLabel = currentMarket?.market_trend?.market_trend || '--';
    const concentrationLabel = currentMarket?.capital_concentration?.label || '--';
    const volumeLabel = currentMarket?.volume?.label || '--';
    metaEl.innerHTML = `
        <span class="activation-meta-item">大盤趨勢 <b>${esc(trendLabel)}</b></span>
        <span class="activation-meta-item">資金集中度 <b>${esc(concentrationLabel)}</b></span>
        <span class="activation-meta-item">量能 <b>${esc(volumeLabel)}</b></span>
    `;

    gatesEl.innerHTML = Object.values(gateChecks).map(check => `
        <div class="activation-gate ${check.passed ? 'passed' : 'failed'}">
            <div class="activation-gate-label">${esc(check.label)}</div>
            <div class="activation-gate-value">${esc(check.actual || '--')}</div>
            <div class="activation-gate-rule">需求 ${esc(check.required || '--')}</div>
        </div>
    `).join('');

    section.style.display = 'block';
}

function setSvgMarkup(svg, width, height, markup) {
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('width', String(width));
    svg.setAttribute('height', String(height));
    svg.innerHTML = markup;
}

function renderMiniChartPlaceholder(svg, message) {
    const width = 320;
    const height = 148;
    setSvgMarkup(svg, width, height, `
        <rect x="0" y="0" width="${width}" height="${height}" rx="14" fill="#f8fbff" stroke="${MINI_CHART_COLORS.frame}" stroke-dasharray="5 5"></rect>
        <text x="${width / 2}" y="${height / 2}" fill="${MINI_CHART_COLORS.text}" font-size="13" text-anchor="middle" dominant-baseline="middle">${esc(message)}</text>
    `);
}

function getChartRange(values, paddingRatio = 0.06) {
    const numericValues = values.filter(value => Number.isFinite(value));
    if (!numericValues.length) return null;

    const minValue = Math.min(...numericValues);
    const maxValue = Math.max(...numericValues);

    if (minValue === maxValue) {
        const padding = Math.abs(minValue || 1) * 0.04 || 1;
        return { min: minValue - padding, max: maxValue + padding };
    }

    const padding = (maxValue - minValue) * paddingRatio;
    return {
        min: minValue - padding,
        max: maxValue + padding
    };
}

function scaleToY(value, range, top, height) {
    return top + ((range.max - value) / (range.max - range.min)) * height;
}

function buildLinePath(points) {
    let path = '';
    let started = false;

    points.forEach(point => {
        if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) {
            started = false;
            return;
        }

        if (!started) {
            path += `M ${point.x.toFixed(2)} ${point.y.toFixed(2)}`;
            started = true;
        } else {
            path += ` L ${point.x.toFixed(2)} ${point.y.toFixed(2)}`;
        }
    });

    return path;
}

function compareFocusCandidate(left, right) {
    const adviceDiff = getAdvicePriority(right.summary.advice) - getAdvicePriority(left.summary.advice);
    if (adviceDiff) return adviceDiff;

    const rightScore = right.score ?? -Infinity;
    const leftScore = left.score ?? -Infinity;
    if (rightScore !== leftScore) return rightScore - leftScore;

    const leftRank = left.rank ?? Infinity;
    const rightRank = right.rank ?? Infinity;
    if (leftRank !== rightRank) return leftRank - rightRank;

    return String(left.stock.symbol).localeCompare(String(right.stock.symbol), 'zh-Hant');
}

function buildStockDetailLink(symbol) {
    return `stock.html?symbol=${encodeURIComponent(symbol)}&date=${encodeURIComponent(currentDate || '')}`;
}

function getFocusChartCandidates() {
    const stocks = liteData?.stocks || [];
    const fullMap = {};
    const universeMap = {};

    if (fullData?.stocks) {
        fullData.stocks.forEach(stock => {
            fullMap[stock.symbol] = stock;
        });
    }
    if (universeData?.stocks) {
        universeData.stocks.forEach(stock => {
            universeMap[stock.symbol] = stock;
        });
    }

    const actionable = [];
    const watchlist = [];

    stocks.forEach(stock => {
        const universeStock = universeMap[stock.symbol];
        const chartData = universeStock?.chart_data;
        const candles = Array.isArray(chartData?.candles) ? chartData.candles : [];
        if (!chartData?.available || candles.length < 6) {
            return;
        }

        const baseStock = fullMap[stock.symbol] || stock;
        const summary = getDecisionSummary(baseStock);
        const lastCandle = candles[candles.length - 1] || {};
        const candidate = {
            stock,
            universeStock,
            summary,
            candles,
            rank: toNum(stock.rank ?? universeStock?.rank),
            score: toNum(baseStock.score ?? stock.score ?? universeStock?.score),
            close: toNum(stock?.indicators?.close) ?? toNum(lastCandle.close),
            ma5: toNum(stock?.indicators?.ma5) ?? toNum(lastCandle.ma5),
            volumeRatio: toNum(stock?.indicators?.volume_ratio) ?? toNum(universeStock?.volume_ratio),
            trend: String(stock?.signals?.trend ?? universeStock?.trend ?? '--').trim() || '--',
            institutional: String(stock?.signals?.institutional ?? universeStock?.institutional ?? '--').trim() || '--'
        };

        if (getAdvicePriority(summary.advice) >= getAdvicePriority('可留意')) {
            actionable.push(candidate);
            return;
        }

        if (!isAvoidAdvice(summary.advice)) {
            watchlist.push(candidate);
        }
    });

    actionable.sort(compareFocusCandidate);
    watchlist.sort(compareFocusCandidate);

    const picked = actionable.slice(0, 3);
    watchlist.forEach(candidate => {
        if (picked.length >= 3) return;
        if (picked.some(item => item.stock.symbol === candidate.stock.symbol)) return;
        picked.push(candidate);
    });

    return picked;
}

function buildFocusChartCard(candidate) {
    const summaryBucket = getAdviceBucket(candidate.summary.advice);
    const previewCandles = candidate.candles.slice(-24);
    const firstCandle = previewCandles[0];
    const lastCandle = previewCandles[previewCandles.length - 1];
    const footerRight = candidate.institutional !== '--'
        ? `${candidate.trend} / ${candidate.institutional}`
        : candidate.trend;

    return `
        <a class="focus-chart-card" href="${buildStockDetailLink(candidate.stock.symbol)}" aria-label="查看 ${esc(candidate.stock.symbol)} ${esc(candidate.stock.name)} 完整個股頁">
            <div class="focus-chart-top">
                <div class="focus-chart-top-main">
                    <div class="focus-chart-symbol-line">
                        <span class="focus-chart-symbol">${esc(candidate.stock.symbol)}</span>
                        <span class="focus-chart-name">${esc(candidate.stock.name)}</span>
                    </div>
                    <div class="focus-chart-reason">${esc(candidate.summary.reason)}</div>
                </div>
                <div class="focus-chart-rank">#${candidate.rank ?? '--'}</div>
            </div>
            <div class="focus-chart-pills">
                <span class="focus-chart-pill advice ${summaryBucket}">${esc(candidate.summary.advice)}</span>
                <span class="focus-chart-pill score">${fmt(candidate.score)} 分</span>
            </div>
            <div class="focus-chart-stats">
                <div class="focus-chart-stat">
                    <span>收盤</span>
                    <strong>${fmtZonePrice(candidate.close)}</strong>
                </div>
                <div class="focus-chart-stat">
                    <span>MA5</span>
                    <strong>${fmtZonePrice(candidate.ma5)}</strong>
                </div>
                <div class="focus-chart-stat">
                    <span>量比</span>
                    <strong>${fmtPct(candidate.volumeRatio)}</strong>
                </div>
            </div>
            <div class="focus-chart-canvas">
                <svg class="focus-chart-svg" aria-hidden="true"></svg>
            </div>
            <div class="focus-chart-footer">
                <span>${esc(shortDateLabel(firstCandle?.date))} - ${esc(shortDateLabel(lastCandle?.date))}</span>
                <span>${esc(footerRight)}</span>
            </div>
        </a>`;
}

function renderMiniFocusChart(svg, candles) {
    if (!svg) return;

    const usableCandles = Array.isArray(candles) ? candles.slice(-24) : [];
    if (usableCandles.length < 2) {
        renderMiniChartPlaceholder(svg, '圖表資料不足');
        return;
    }

    const width = 320;
    const height = 148;
    const left = 10;
    const right = 10;
    const top = 10;
    const bottom = 24;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const step = plotWidth / usableCandles.length;
    const bodyWidth = Math.max(4, Math.min(8, step * 0.58));

    const priceValues = [];
    usableCandles.forEach(candle => {
        priceValues.push(toNum(candle.low), toNum(candle.high), toNum(candle.ma5), toNum(candle.ma20));
    });
    const range = getChartRange(priceValues, 0.05);
    if (!range) {
        renderMiniChartPlaceholder(svg, '圖表資料不足');
        return;
    }

    const guideMarkup = [0.15, 0.5, 0.85].map(ratio => {
        const y = top + plotHeight * ratio;
        return `<line x1="${left}" y1="${y.toFixed(2)}" x2="${(left + plotWidth).toFixed(2)}" y2="${y.toFixed(2)}" stroke="${MINI_CHART_COLORS.grid}" stroke-width="1"></line>`;
    }).join('');

    let wickMarkup = '';
    let bodyMarkup = '';
    const ma5Points = [];
    const ma20Points = [];

    usableCandles.forEach((candle, index) => {
        const open = toNum(candle.open);
        const high = toNum(candle.high);
        const low = toNum(candle.low);
        const close = toNum(candle.close);
        const x = left + step * index + step / 2;

        if (open == null || high == null || low == null || close == null) {
            ma5Points.push(null);
            ma20Points.push(null);
            return;
        }

        const tone = close >= open ? MINI_CHART_COLORS.up : MINI_CHART_COLORS.down;
        const highY = scaleToY(high, range, top, plotHeight);
        const lowY = scaleToY(low, range, top, plotHeight);
        const openY = scaleToY(open, range, top, plotHeight);
        const closeY = scaleToY(close, range, top, plotHeight);
        const bodyTop = Math.min(openY, closeY);
        const bodyHeight = Math.max(2, Math.abs(openY - closeY));

        wickMarkup += `<line x1="${x.toFixed(2)}" y1="${highY.toFixed(2)}" x2="${x.toFixed(2)}" y2="${lowY.toFixed(2)}" stroke="${tone}" stroke-width="1.3"></line>`;
        bodyMarkup += `<rect x="${(x - bodyWidth / 2).toFixed(2)}" y="${bodyTop.toFixed(2)}" width="${bodyWidth.toFixed(2)}" height="${bodyHeight.toFixed(2)}" rx="1.2" fill="${tone}"></rect>`;

        const ma5 = toNum(candle.ma5);
        const ma20 = toNum(candle.ma20);
        ma5Points.push(ma5 == null ? null : { x, y: scaleToY(ma5, range, top, plotHeight) });
        ma20Points.push(ma20 == null ? null : { x, y: scaleToY(ma20, range, top, plotHeight) });
    });

    const ma5Path = buildLinePath(ma5Points);
    const ma20Path = buildLinePath(ma20Points);
    const startLabel = shortDateLabel(usableCandles[0]?.date);
    const endLabel = shortDateLabel(usableCandles[usableCandles.length - 1]?.date);

    setSvgMarkup(svg, width, height, `
        <rect x="0" y="0" width="${width}" height="${height}" rx="14" fill="#f8fbff" stroke="${MINI_CHART_COLORS.frame}"></rect>
        ${guideMarkup}
        ${wickMarkup}
        ${bodyMarkup}
        ${ma5Path ? `<path d="${ma5Path}" fill="none" stroke="${MINI_CHART_COLORS.ma5}" stroke-width="2"></path>` : ''}
        ${ma20Path ? `<path d="${ma20Path}" fill="none" stroke="${MINI_CHART_COLORS.ma20}" stroke-width="2"></path>` : ''}
        <text x="${left}" y="${height - 7}" fill="${MINI_CHART_COLORS.text}" font-size="11">${esc(startLabel)}</text>
        <text x="${width - right}" y="${height - 7}" fill="${MINI_CHART_COLORS.text}" font-size="11" text-anchor="end">${esc(endLabel)}</text>
    `);
}

function renderFocusCharts() {
    const section = document.getElementById('focusChartSection');
    const list = document.getElementById('focusChartList');
    if (!section || !list) return;

    const candidates = getFocusChartCandidates();
    if (!candidates.length) {
        list.innerHTML = '';
        section.style.display = 'none';
        return;
    }

    list.innerHTML = candidates.map(buildFocusChartCard).join('');
    const svgs = list.querySelectorAll('.focus-chart-svg');
    candidates.forEach((candidate, index) => {
        renderMiniFocusChart(svgs[index], candidate.candles);
    });
    section.style.display = 'block';
}

// === Render: Groups ===
function renderGroups() {
    const stocks = liteData?.stocks || [];
    const fullMap = {};
    if (fullData?.stocks) {
        fullData.stocks.forEach(s => { fullMap[s.symbol] = s; });
    }

    const decisions = stocks.map(stock => ({
        stock,
        summary: getDecisionSummary(fullMap[stock.symbol] || stock)
    }));
    const strong = decisions.filter(item => getAdviceBucket(item.summary.advice) === 'strong');
    const watch  = decisions.filter(item => getAdviceBucket(item.summary.advice) === 'watch');
    const avoid  = decisions.filter(item => getAdviceBucket(item.summary.advice) === 'avoid');

    const makeTag = item =>
        `<span class="group-tag" onclick="scrollToCard('${item.stock.symbol}')">${esc(item.stock.symbol)} ${esc(item.stock.name)}</span>`;
    const makeGroupText = items =>
        items.length
            ? items.map(item => `${item.stock.name}（${item.summary.advice}）`).join('、')
            : '--';

    document.getElementById('strongestGroupAI').textContent =
        makeGroupText(strong);
    document.getElementById('cautionGroupAI').textContent =
        makeGroupText(watch);
    document.getElementById('avoidGroupAI').textContent =
        makeGroupText(avoid);

    document.getElementById('strongestTags').innerHTML = strong.map(item => makeTag(item)).join('');
    document.getElementById('cautionTags').innerHTML   = watch.map(item => makeTag(item)).join('');
    document.getElementById('avoidTags').innerHTML     = avoid.map(item => makeTag(item)).join('');
}

function scrollToCard(symbol) {
    const el = document.querySelector(`.stock-card[data-symbol="${symbol}"]`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// === Render: Stock Cards ===
function renderStockCards() {
    const stocks = liteData?.stocks || [];
    const aiMap = {};
    const fullMap = {};
    if (aiData?.stocks) {
        aiData.stocks.forEach(s => { aiMap[s.symbol] = s; });
    }
    if (fullData?.stocks) {
        fullData.stocks.forEach(s => { fullMap[s.symbol] = s; });
    }

    const html = stocks.map(s => buildStockCard(s, aiMap[s.symbol], fullMap[s.symbol])).join('');
    document.getElementById('stockList').innerHTML =
        html || '<p style="text-align:center;color:#888;padding:40px">無個股資料</p>';

    document.querySelectorAll('.stock-card-header').forEach(h => {
        h.addEventListener('click', () => {
            const details = h.nextElementSibling;
            if (details) details.classList.toggle('open');
        });
    });
}

function buildStockCard(stock, ai, fullStock) {
    const grade = stock.score_grade || 'C';
    const indic = stock.indicators || {};
    const sigs  = stock.signals || {};
    const decisionSummary = getDecisionSummary(fullStock || stock);
    const bias = decisionSummary.advice;
    const aiJudgment = getAIJudgment(fullStock || stock, ai, decisionSummary);

    const whyText = decisionSummary.reason || '暫無摘要';

    const driversHTML = ai?.primary_drivers?.length
        ? `<div class="drivers-list">${ai.primary_drivers.map(d => `<span class="driver-tag">${esc(d)}</span>`).join('')}</div>`
        : '';

    const aiSection = ai ? `
        <div class="detail-block">
            <div class="detail-label">風險提醒</div>
            <div class="detail-value risk">${esc(ai.risk_ai)}</div>
        </div>
        <div class="detail-block">
            <div class="detail-label">與昨日比較</div>
            <div class="detail-value change">${esc(ai.change_vs_yesterday_ai)}</div>
        </div>
        ${driversHTML ? `<div class="detail-block"><div class="detail-label">主要驅動因子</div>${driversHTML}</div>` : ''}
    ` : '';

    return `
<div class="stock-card" data-symbol="${esc(stock.symbol)}">
    <div class="stock-card-header">
        <div class="stock-top-row">
            <div class="stock-identity">
                <div class="stock-symbol">${esc(stock.symbol)}</div>
                <div class="stock-name">${esc(stock.name)}</div>
            </div>
            <div class="stock-rank-box">
                <div class="rank-num">${stock.rank ?? '--'}</div>
                <div class="rank-lbl">名次</div>
            </div>
            <div class="stock-score-box">
                <div class="score-num">${stock.score ?? 0}</div>
                <div class="score-badge grade-${esc(grade)}">${esc(grade)} ${esc(stock.score_label ?? '')}</div>
            </div>
        </div>
        <div class="bias-tag bias-${esc(bias)}">${esc(bias)}</div>
        <div class="why-text">${esc(whyText)}</div>
        ${renderDecisionSummary(decisionSummary, fullStock || stock)}
        ${renderAIJudgment(aiJudgment)}
        <div class="expand-hint">▼ 展開完整分析</div>
    </div>
    <div class="stock-details">
        ${aiSection}
        <div class="detail-block">
            <div class="detail-label">技術數據</div>
            <div class="indicators-row">
                <div class="indicator-box">
                    <div class="ind-label">收盤價</div>
                    <div class="ind-value">${fmt(indic.close)}</div>
                </div>
                <div class="indicator-box">
                    <div class="ind-label">量比</div>
                    <div class="ind-value">${fmtPct(indic.volume_ratio)}</div>
                </div>
                <div class="indicator-box">
                    <div class="ind-label">趨勢</div>
                    <div class="ind-value">${esc(sigs.trend ?? '--')}</div>
                </div>
                <div class="indicator-box">
                    <div class="ind-label">法人</div>
                    <div class="ind-value">${esc(sigs.institutional ?? '--')}</div>
                </div>
            </div>
        </div>
    </div>
</div>`;
}

// === Render: Footer ===
function renderFooter() {
    const stocks = liteData?.stocks || [];
    const fullMap = {};
    if (fullData?.stocks) {
        fullData.stocks.forEach(s => { fullMap[s.symbol] = s; });
    }
    document.getElementById('footerDate').textContent = currentDate || '--';
    document.getElementById('totalCount').textContent = stocks.length;
    document.getElementById('goodCount').textContent = stocks.filter(stock => {
        const advice = getDecisionSummary(fullMap[stock.symbol] || stock).advice;
        return getAdvicePriority(advice) >= getAdvicePriority('可留意');
    }).length;
}

// === Main Flow ===
async function loadAndRender(date) {
    showLoading();
    currentDate = date;
    updateDateBadge();

    try {
        const result = await loadReports(date);
        liteData = result.lite;
        aiData   = result.ai;
        fullData = result.full;
        universeData = result.universe;
        activationData = result.activation;

        if (!aiData) {
            console.warn(`${date}-ai.json 不存在，以基礎資料顯示`);
        }

        renderAIOverview();
        renderStrategyActivation();
        renderFocusCharts();
        renderGroups();
        renderStockCards();
        renderFooter();
        showContent();

    } catch (err) {
        document.getElementById('loadingState').style.display = 'none';
        showError('載入失敗', esc(err.message));
    }
}

async function reloadLatest() {
    requestVersion = createRequestVersion();
    indexData = await loadIndex();
    if (!indexData?.latest_date) {
        showError('無報告', '找不到任何可用報告');
        return;
    }
    currentDate = indexData.latest_date;
    buildDateDropdown();
    updateDateBadge();
    history.replaceState({}, '', window.location.pathname);
    await loadAndRender(currentDate);
}

// === Init ===
async function init() {
    document.getElementById('reloadBtn').addEventListener('click', reloadLatest);

    document.getElementById('dateDropdown').addEventListener('change', async function () {
        if (!this.value) return;
        requestVersion = createRequestVersion();
        currentDate = this.value;
        const url = new URL(location.href);
        url.searchParams.set('date', currentDate);
        history.pushState({}, '', url);
        await loadAndRender(currentDate);
        buildDateDropdown();
        updateDateBadge();
    });

    window.addEventListener('popstate', async () => {
        const d = new URLSearchParams(location.search).get('date');
        if (d && d !== currentDate) {
            requestVersion = createRequestVersion();
            currentDate = d;
            buildDateDropdown();
            await loadAndRender(d);
        }
    });

    requestVersion = createRequestVersion();
    indexData = await loadIndex();
    const urlDate = new URLSearchParams(location.search).get('date');

    if (urlDate) {
        currentDate = urlDate;
    } else if (indexData?.latest_date) {
        currentDate = indexData.latest_date;
    } else {
        showError('無報告', '尚未產生任何報告');
        return;
    }

    buildDateDropdown();
    await loadAndRender(currentDate);
}

window.reloadLatest  = reloadLatest;
window.scrollToCard  = scrollToCard;

document.addEventListener('DOMContentLoaded', init);