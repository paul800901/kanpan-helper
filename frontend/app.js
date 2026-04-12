/**
 * 看盤助手 v6 - 正式版
 * 讀取 YYYY-MM-DD-lite.json + YYYY-MM-DD-ai.json，純 v6 AI 顯示。
 */

// === State ===
let liteData = null;
let aiData = null;
let fullData = null;
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
    const num = Number(value);
    return Number.isFinite(num) ? num : null;
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

    if (close != null && ma20 != null && k != null && close < ma20 && k < 30) {
        matches.push({
            advice: '可留意',
            reason: '低檔區出現反彈訊號',
            risk: '尚未站回中期結構，反彈可能失敗',
            priority: 3
        });
    }

    if (close != null && ma5 != null && volumeRatio != null && isCloseToMa5(close, ma5) && volumeRatio < 1) {
        matches.push({
            advice: '先觀望',
            reason: '短線位置不差，但量能不足',
            risk: '缺乏續航，容易震盪',
            priority: 2
        });
    }

    if (close != null && ma20 != null && k != null && close < ma20 && k >= 30) {
        matches.push({
            advice: '暫不進場',
            reason: '仍在中期壓力下方',
            risk: '容易出現反彈後再回落',
            priority: 1
        });
    }

    if (matches.length === 0) {
        return {
            advice: '無明確訊號',
            reason: '未命中 v6.5 固定規則',
            risk: '條件不足時，短線方向可能反覆'
        };
    }

    matches.sort((left, right) => right.priority - left.priority);
    return matches[0];
}

function renderDecisionSummary(summary) {
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
    const [lite, ai, full] = await Promise.allSettled([
        fetchJSON(`${BASE}/${date}-lite.json`),
        fetchJSON(`${BASE}/${date}-ai.json`),
        fetchJSON(`${BASE}/${date}.json`)
    ]);
    if (lite.status === 'rejected') {
        throw new Error(`lite 報告載入失敗: ${lite.reason.message}`);
    }
    if (full.status === 'rejected') {
        console.warn(`${date}.json 不存在，首頁決策摘要將使用保底訊息`);
    }
    return {
        lite: lite.value,
        ai: ai.status === 'fulfilled' ? ai.value : null,
        full: full.status === 'fulfilled' ? full.value : null
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

// === Render: Groups ===
function renderGroups() {
    const stocks = liteData?.stocks || [];
    const aiStocksMap = {};
    if (aiData?.stocks) {
        aiData.stocks.forEach(s => { aiStocksMap[s.symbol] = s; });
    }

    const strong = stocks.filter(s => s.action_bias === '可留意');
    const watch  = stocks.filter(s => s.action_bias === '觀察');
    const avoid  = stocks.filter(s => ['偏保守', '暫不考慮'].includes(s.action_bias));

    const makeTag = (s, cls) =>
        `<span class="group-tag" onclick="scrollToCard('${s.symbol}')">${esc(s.symbol)} ${esc(s.name)}</span>`;

    document.getElementById('strongestGroupAI').textContent =
        aiData?.strongest_group_ai || strong.map(s => s.name).join('、') || '--';
    document.getElementById('cautionGroupAI').textContent =
        aiData?.caution_group_ai || watch.map(s => s.name).join('、') || '--';
    document.getElementById('avoidGroupAI').textContent =
        aiData?.avoid_group_ai || avoid.map(s => s.name).join('、') || '--';

    document.getElementById('strongestTags').innerHTML = strong.map(s => makeTag(s, 'group-strong')).join('');
    document.getElementById('cautionTags').innerHTML   = watch.map(s => makeTag(s, 'group-watch')).join('');
    document.getElementById('avoidTags').innerHTML     = avoid.map(s => makeTag(s, 'group-avoid')).join('');
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
    const bias  = stock.action_bias || '暫不考慮';
    const indic = stock.indicators || {};
    const sigs  = stock.signals || {};
    const decisionSummary = getDecisionSummary(fullStock || stock);

    const whyText = ai?.why_selected_ai || stock.one_line_summary || '暫無摘要';

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
        ${renderDecisionSummary(decisionSummary)}
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
    document.getElementById('footerDate').textContent = currentDate || '--';
    document.getElementById('totalCount').textContent = stocks.length;
    document.getElementById('goodCount').textContent = stocks.filter(s => s.action_bias === '可留意').length;
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

        if (!aiData) {
            console.warn(`${date}-ai.json 不存在，以基礎資料顯示`);
        }

        renderAIOverview();
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