/**
 * 看盤助手 v6 - PWA 版應用程式
 * 支援 v5 規則引擎 + v6 DeepSeek AI 分析
 */

// 全域狀態
let reportData = null;      // v5 報告資料
let aiReportData = null;    // v6 AI 分析資料
let indexData = null;
let currentFilter = 'all';
let currentDate = null;

// 設定 - 自動偵測是否在 GitHub Pages 上執行
const IS_GITHUB_PAGES = window.location.hostname === 'paul800901.github.io';
const REPORT_BASE_URL = IS_GITHUB_PAGES 
    ? 'https://paul800901.github.io/kanpan-helper/reports'
    : '../reports';

const CONFIG = {
    INDEX_PATH: `${REPORT_BASE_URL}/index.json`,
    REPORTS_PATH: REPORT_BASE_URL,
    SAMPLE_PATH: './sample',
    IS_GITHUB_PAGES: IS_GITHUB_PAGES
};

// ============================================
// 輔助函式
// ============================================

function getUrlParam(name) {
    const params = new URLSearchParams(window.location.search);
    return params.get(name);
}

function getTodayString() {
    const now = new Date();
    const taiwanTime = new Date(now.getTime() + (now.getTimezoneOffset() + 480) * 60000);
    return taiwanTime.toISOString().split('T')[0];
}

function formatNumber(num) {
    if (num === null || num === undefined) return '--';
    return num.toLocaleString('zh-TW');
}

function formatPercent(ratio) {
    if (ratio === null || ratio === undefined) return '--';
    return Math.round(ratio * 100) + '%';
}

function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ============================================
// 資料載入
// ============================================

async function loadIndex() {
    try {
        const response = await fetch(CONFIG.INDEX_PATH);
        if (!response.ok) {
            if (response.status === 404) {
                return null;
            }
            throw new Error(`無法載入索引 (${response.status})`);
        }
        return await response.json();
    } catch (error) {
        console.log('索引載入失敗:', error.message);
        return null;
    }
}

async function loadReportByDate(dateStr) {
    // 載入 v5 報告（精簡版）
    const reportPath = `${CONFIG.REPORTS_PATH}/${dateStr}-lite.json`;
    
    try {
        const response = await fetch(reportPath);
        if (!response.ok) {
            if (response.status === 404) {
                throw new Error(`找不到 ${dateStr} 的報告檔案`);
            }
            throw new Error(`無法載入報告 (${response.status})`);
        }
        
        const data = await response.json();
        
        if (!data.stocks || !Array.isArray(data.stocks)) {
            throw new Error('報告格式錯誤：缺少股票資料');
        }
        
        return data;
    } catch (error) {
        throw error;
    }
}

async function loadAIReport(dateStr) {
    // 嘗試載入 v6 AI 分析報告
    const aiPath = `${CONFIG.REPORTS_PATH}/${dateStr}-ai.json`;
    
    try {
        const response = await fetch(aiPath);
        if (!response.ok) {
            return null; // AI 報告不存在是正常的
        }
        return await response.json();
    } catch (error) {
        console.log('AI 報告載入失敗:', error.message);
        return null;
    }
}

async function loadSampleData() {
    try {
        const response = await fetch(`${CONFIG.SAMPLE_PATH}/2026-04-08-lite.json`);
        if (!response.ok) {
            throw new Error('測試資料載入失敗');
        }
        return await response.json();
    } catch (error) {
        throw new Error('無法載入測試資料');
    }
}

// ============================================
// 錯誤處理
// ============================================

function showError(title, message, showRetry = true) {
    document.getElementById('errorTitle').textContent = title;
    document.getElementById('errorMessage').innerHTML = message;
    document.getElementById('errorModal').style.display = 'flex';
    
    const retryBtn = document.getElementById('errorRetryBtn');
    retryBtn.style.display = showRetry ? 'block' : 'none';
}

function hideError() {
    document.getElementById('errorModal').style.display = 'none';
}

function showEmptyState() {
    document.getElementById('emptyModal').style.display = 'flex';
}

function hideEmptyState() {
    document.getElementById('emptyModal').style.display = 'none';
}

// ============================================
// 日期選擇器
// ============================================

function initDateDropdown() {
    const dropdown = document.getElementById('dateDropdown');
    
    dropdown.addEventListener('change', async function() {
        const selectedDate = this.value;
        if (!selectedDate) return;
        
        currentDate = selectedDate;
        
        const url = new URL(window.location);
        url.searchParams.set('date', selectedDate);
        window.history.pushState({}, '', url);
        
        await loadAndRenderReport(selectedDate);
    });
}

function populateDateDropdown() {
    const dropdown = document.getElementById('dateDropdown');
    dropdown.innerHTML = '';
    
    if (!indexData || !indexData.reports || indexData.reports.length === 0) {
        dropdown.innerHTML = '<option value="">無可用報告</option>';
        return;
    }
    
    const availableReports = indexData.reports.filter(r => r.has_lite);
    
    availableReports.forEach(report => {
        const option = document.createElement('option');
        option.value = report.date;
        
        const isLatest = report.date === indexData.latest_date;
        option.textContent = `${report.date}${isLatest ? ' (最新)' : ''}`;
        
        if (report.date === currentDate) {
            option.selected = true;
        }
        
        dropdown.appendChild(option);
    });
}

function updateDateBadge() {
    const badge = document.getElementById('dateBadge');
    
    if (!currentDate || !indexData) {
        badge.textContent = '';
        badge.className = 'date-badge';
        return;
    }
    
    const isLatest = currentDate === indexData.latest_date;
    badge.textContent = isLatest ? '最新' : '歷史';
    badge.className = `date-badge ${isLatest ? 'latest' : 'history'}`;
}

// ============================================
// 主要載入流程
// ============================================

async function initialize() {
    indexData = await loadIndex();
    
    const urlDate = getUrlParam('date');
    
    if (urlDate) {
        currentDate = urlDate;
    } else if (indexData && indexData.latest_date) {
        currentDate = indexData.latest_date;
    } else {
        showEmptyState();
        document.getElementById('stockList').innerHTML = '';
        return;
    }
    
    populateDateDropdown();
    initDateDropdown();
    
    await loadAndRenderReport(currentDate);
}

async function loadAndRenderReport(dateStr) {
    const listContainer = document.getElementById('stockList');
    listContainer.innerHTML = '<div class="loading">載入報告中...</div>';
    
    try {
        // 並行載入 v5 報告和 v6 AI 報告
        const [v5Data, aiData] = await Promise.all([
            loadReportByDate(dateStr),
            loadAIReport(dateStr)
        ]);
        
        reportData = v5Data;
        aiReportData = aiData;
        currentDate = dateStr;
        
        updateDateBadge();
        renderPage();
        hideError();
        
    } catch (error) {
        console.error('載入報告失敗:', error);
        
        if (indexData && dateStr !== indexData.latest_date) {
            showError(
                '報告遺失',
                `找不到 ${dateStr} 的報告檔案。<br>該日期可能已被刪除或從未產生。`,
                true
            );
        } else {
            showError('載入失敗', error.message, true);
        }
        
        listContainer.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📄</div>
                <div class="empty-state-text">無法載入報告</div>
            </div>
        `;
    }
}

async function reloadLatest() {
    indexData = await loadIndex();
    
    if (!indexData || !indexData.latest_date) {
        showEmptyState();
        return;
    }
    
    const url = new URL(window.location);
    url.searchParams.delete('date');
    window.history.pushState({}, '', url);
    
    populateDateDropdown();
    
    currentDate = indexData.latest_date;
    await loadAndRenderReport(currentDate);
}

// ============================================
// 渲染函式 - 主要分派
// ============================================

function renderPage() {
    if (!reportData) return;
    
    // 判斷使用 v6 還是 v5 渲染
    const hasAIReport = aiReportData && aiReportData.report_version === 'v6-ai';
    
    if (hasAIReport) {
        renderV6Page();
    } else {
        renderV5Page();
    }
    
    renderFooter();
    renderLastUpdated();
}

// ============================================
// v6 渲染（有 AI 分析）
// ============================================

function renderV6Page() {
    // 隱藏 v5 摘要區，顯示 v6 AI 區
    document.getElementById('summarySection').style.display = 'none';
    document.getElementById('filterBar').style.display = 'none';
    
    document.getElementById('aiSummarySection').style.display = 'block';
    document.getElementById('aiGroupsSection').style.display = 'block';
    
    // 隱藏傳統市場總覽
    document.getElementById('marketSummary').style.display = 'none';
    
    renderV6AISummary();
    renderV6Groups();
    renderV6StockList();
}

function renderV6AISummary() {
    // AI 一句話總結
    const oneLiner = aiReportData.market_overview_ai || '今日市場分析完成';
    document.getElementById('aiOneLiner').textContent = oneLiner;
    
    // 今日三個焦點
    const focusList = aiReportData.today_focus_ai || [];
    const focusContainer = document.getElementById('aiFocusList');
    focusContainer.innerHTML = focusList
        .map(focus => `<span class="ai-focus-item">${escapeHtml(focus)}</span>`)
        .join('');
}

function renderV6Groups() {
    const stocks = reportData.stocks || [];
    const aiStocks = aiReportData.stocks || [];
    
    // 分類股票
    const strongest = stocks.filter(s => s.action_bias === '可留意').slice(0, 5);
    const caution = stocks.filter(s => s.action_bias === '觀察').slice(0, 5);
    const risky = stocks.filter(s => s.action_bias === '偏保守').slice(0, 5);
    const avoid = stocks.filter(s => s.action_bias === '暫不考慮').slice(0, 5);
    
    // 最值得先看
    document.getElementById('strongestDesc').textContent = 
        aiReportData.strongest_group_ai || '分數高且條件佳';
    document.getElementById('strongestStocks').innerHTML = 
        strongest.map(s => createGroupStockTag(s, aiStocks.find(ais => ais.symbol === s.symbol))).join('');
    
    // 轉強觀察
    document.getElementById('cautionDesc').textContent = 
        aiReportData.caution_group_ai || '有潛力但需觀察';
    document.getElementById('cautionStocks').innerHTML = 
        caution.map(s => createGroupStockTag(s, aiStocks.find(ais => ais.symbol === s.symbol))).join('');
    
    // 高分但有風險
    document.getElementById('riskyStocks').innerHTML = 
        risky.map(s => createGroupStockTag(s, aiStocks.find(ais => ais.symbol === s.symbol))).join('');
    
    // 今日先不要碰
    document.getElementById('avoidDesc').textContent = 
        aiReportData.avoid_group_ai || '條件不佳，暫不考慮';
    document.getElementById('avoidStocks').innerHTML = 
        avoid.map(s => createGroupStockTag(s, aiStocks.find(ais => ais.symbol === s.symbol))).join('');
}

function createGroupStockTag(stock, aiData) {
    const aiWhy = aiData ? aiData.why_selected_ai : stock.one_line_summary;
    return `
        <div class="group-stock-tag" onclick="showStockDetail('${stock.symbol}')" title="${escapeHtml(aiWhy || '')}">
            <span class="symbol">${escapeHtml(stock.symbol)}</span>
            <span class="name">${escapeHtml(stock.name)}</span>
        </div>
    `;
}

function renderV6StockList() {
    const container = document.getElementById('stockList');
    const stocks = reportData.stocks || [];
    const aiStocks = aiReportData.stocks || [];
    
    if (stocks.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">🔍</div>
                <div class="empty-state-text">沒有符合條件的股票</div>
            </div>
        `;
        return;
    }
    
    container.innerHTML = stocks.map(stock => {
        const aiData = aiStocks.find(ais => ais.symbol === stock.symbol);
        return createV6StockCard(stock, aiData);
    }).join('');
    
    // 綁定點擊事件
    document.querySelectorAll('.stock-header').forEach(header => {
        header.addEventListener('click', function() {
            const details = this.closest('.stock-card').querySelector('.stock-details');
            details.classList.toggle('expanded');
        });
    });
}

function createV6StockCard(stock, aiData) {
    const gradeClass = `grade-${stock.score_grade || 'C'}`;
    const biasClass = `bias-${stock.action_bias}`;
    
    // 使用 AI 分析或 fallback 到規則版
    const whySelected = aiData ? aiData.why_selected_ai : stock.one_line_summary;
    const riskText = aiData ? aiData.risk_ai : (stock.plain_risks || [''])[0];
    const changeText = aiData ? aiData.change_vs_yesterday_ai : '與昨日持平';
    
    const indicators = stock.indicators || {};
    const signals = stock.signals || {};
    
    return `
        <div class="stock-card" data-bias="${escapeHtml(stock.action_bias)}">
            <div class="stock-header">
                <div class="stock-main">
                    <div class="stock-info">
                        <div class="stock-symbol">${escapeHtml(stock.symbol)}</div>
                        <div class="stock-name">${escapeHtml(stock.name)}</div>
                    </div>
                    <div class="stock-rank">
                        <div class="rank-number">${stock.rank || '--'}</div>
                        <div class="rank-label">名次</div>
                    </div>
                    <div class="stock-score">
                        <div class="score-value">${stock.score || 0}</div>
                        <span class="score-grade ${gradeClass}">
                            ${stock.score_grade || '?'} ${stock.score_label || ''}
                        </span>
                    </div>
                </div>
                
                <div class="action-bias ${biasClass}">${escapeHtml(stock.action_bias)}</div>
                
                <div class="one-line-summary">
                    ${escapeHtml(whySelected || '暫無摘要')}
                </div>
                
                <div class="expand-hint">
                    點擊展開詳情 <span class="expand-icon">▼</span>
                </div>
            </div>
            
            <div class="stock-details">
                <!-- AI 分析區塊（v6） -->
                ${aiData ? `
                <div class="ai-analysis-section">
                    <div class="ai-section-title">為什麼選這檔</div>
                    <div class="ai-section-content">${escapeHtml(aiData.why_selected_ai || '')}</div>
                </div>
                <div class="ai-analysis-section">
                    <div class="ai-section-title ai-risk">風險提醒</div>
                    <div class="ai-section-content ai-risk">${escapeHtml(aiData.risk_ai || '')}</div>
                </div>
                <div class="ai-analysis-section">
                    <div class="ai-section-title ai-change">與昨日比較</div>
                    <div class="ai-section-content ai-change">${escapeHtml(aiData.change_vs_yesterday_ai || '')}</div>
                </div>
                ` : ''}
                
                <!-- 傳統技術數據 -->
                <div class="details-section">
                    <div class="details-title">技術數據</div>
                    <div class="indicators-grid">
                        <div class="indicator-item">
                            <div class="indicator-label">收盤價</div>
                            <div class="indicator-value">${formatNumber(indicators.close)}</div>
                        </div>
                        <div class="indicator-item">
                            <div class="indicator-label">成交量比</div>
                            <div class="indicator-value">${formatPercent(indicators.volume_ratio)}</div>
                        </div>
                        <div class="indicator-item">
                            <div class="indicator-label">趨勢</div>
                            <div class="indicator-value">${escapeHtml(signals.trend || '--')}</div>
                        </div>
                        <div class="indicator-item">
                            <div class="indicator-label">法人動向</div>
                            <div class="indicator-value">${escapeHtml(signals.institutional || '--')}</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

// ============================================
// v5 渲染（無 AI 分析，向後兼容）
// ============================================

function renderV5Page() {
    // 顯示 v5 元件，隱藏 v6 元件
    document.getElementById('summarySection').style.display = 'block';
    document.getElementById('filterBar').style.display = 'flex';
    document.getElementById('marketSummary').style.display = 'block';
    
    document.getElementById('aiSummarySection').style.display = 'none';
    document.getElementById('aiGroupsSection').style.display = 'none';
    
    renderHeader();
    renderSummary();
    renderStockList();
}

function renderHeader() {
    document.getElementById('marketSummary').textContent = 
        reportData.summary?.market_overview || '市場概況資料不足';
}

function renderSummary() {
    const stocks = reportData.stocks || [];
    
    const counts = { '可留意': 0, '觀察': 0, '偏保守': 0, '暫不考慮': 0 };
    const lists = { '可留意': [], '觀察': [], '偏保守': [], '暫不考慮': [] };
    
    stocks.forEach(stock => {
        if (counts.hasOwnProperty(stock.action_bias)) {
            counts[stock.action_bias]++;
            lists[stock.action_bias].push(stock.name);
        }
    });
    
    document.getElementById('topPicksCount').textContent = counts['可留意'];
    document.getElementById('watchlistCount').textContent = counts['觀察'];
    document.getElementById('avoidCount').textContent = counts['偏保守'] + counts['暫不考慮'];
    
    document.getElementById('topPicksList').textContent = lists['可留意'].slice(0, 2).join('、') || '無';
    document.getElementById('watchlistList').textContent = lists['觀察'].slice(0, 2).join('、') || '無';
    document.getElementById('avoidList').textContent = lists['暫不考慮'].slice(0, 2).join('、') || '無';
}

function renderStockList() {
    const container = document.getElementById('stockList');
    let filteredStocks = reportData.stocks || [];
    
    if (currentFilter !== 'all') {
        filteredStocks = filteredStocks.filter(s => s.action_bias === currentFilter);
    }
    
    if (filteredStocks.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">🔍</div>
                <div class="empty-state-text">沒有符合「${escapeHtml(currentFilter)}」條件的股票</div>
            </div>
        `;
        return;
    }
    
    container.innerHTML = filteredStocks.map(stock => createV5StockCard(stock)).join('');
    
    document.querySelectorAll('.stock-header').forEach(header => {
        header.addEventListener('click', function() {
            const details = this.closest('.stock-card').querySelector('.stock-details');
            details.classList.toggle('expanded');
        });
    });
}

function createV5StockCard(stock) {
    const gradeClass = `grade-${stock.score_grade || 'C'}`;
    const biasClass = `bias-${stock.action_bias}`;
    
    const reasonsList = (stock.plain_reasons || [])
        .map(r => `<li>${escapeHtml(r)}</li>`).join('');
    
    const risksList = (stock.plain_risks || [])
        .map(r => `<li>${escapeHtml(r)}</li>`).join('');
    
    const indicators = stock.indicators || {};
    const signals = stock.signals || {};
    
    return `
        <div class="stock-card" data-bias="${escapeHtml(stock.action_bias)}">
            <div class="stock-header">
                <div class="stock-main">
                    <div class="stock-info">
                        <div class="stock-symbol">${escapeHtml(stock.symbol)}</div>
                        <div class="stock-name">${escapeHtml(stock.name)}</div>
                    </div>
                    <div class="stock-rank">
                        <div class="rank-number">${stock.rank || '--'}</div>
                        <div class="rank-label">名次</div>
                    </div>
                    <div class="stock-score">
                        <div class="score-value">${stock.score || 0}</div>
                        <span class="score-grade ${gradeClass}">
                            ${stock.score_grade || '?'} ${stock.score_label || ''}
                        </span>
                    </div>
                </div>
                
                <div class="action-bias ${biasClass}">${escapeHtml(stock.action_bias)}</div>
                
                <div class="one-line-summary">
                    ${escapeHtml(stock.one_line_summary || '暫無摘要')}
                </div>
                
                <div class="expand-hint">
                    點擊展開詳情 <span class="expand-icon">▼</span>
                </div>
            </div>
            
            <div class="stock-details">
                <div class="details-section">
                    <div class="details-title">選股理由</div>
                    <ul class="details-list">
                        ${reasonsList || '<li>暫無資料</li>'}
                    </ul>
                </div>
                
                <div class="details-section">
                    <div class="details-title risk">風險提醒</div>
                    <ul class="details-list risk-list">
                        ${risksList || '<li>暫無資料</li>'}
                    </ul>
                </div>
                
                <div class="details-section">
                    <div class="details-title">技術數據</div>
                    <div class="indicators-grid">
                        <div class="indicator-item">
                            <div class="indicator-label">收盤價</div>
                            <div class="indicator-value">${formatNumber(indicators.close)}</div>
                        </div>
                        <div class="indicator-item">
                            <div class="indicator-label">成交量比</div>
                            <div class="indicator-value">${formatPercent(indicators.volume_ratio)}</div>
                        </div>
                        <div class="indicator-item">
                            <div class="indicator-label">趨勢</div>
                            <div class="indicator-value">${escapeHtml(signals.trend || '--')}</div>
                        </div>
                        <div class="indicator-item">
                            <div class="indicator-label">法人動向</div>
                            <div class="indicator-value">${escapeHtml(signals.institutional || '--')}</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

// ============================================
// 共用渲染
// ============================================

function renderFooter() {
    const stocks = reportData.stocks || [];
    const goodCount = stocks.filter(s => s.action_bias === '可留意').length;
    
    document.getElementById('footerDate').textContent = currentDate || '--';
    document.getElementById('totalCount').textContent = stocks.length;
    document.getElementById('goodCount').textContent = goodCount;
}

function renderLastUpdated() {
    const timeValue = reportData.metadata?.last_updated 
        || reportData.created_at 
        || reportData.generated_at 
        || null;
    const element = document.getElementById('lastUpdated');
    
    if (timeValue) {
        try {
            const date = new Date(timeValue);
            if (!isNaN(date.getTime())) {
                const twDate = new Date(date.getTime() + (date.getTimezoneOffset() + 480) * 60000);
                const formatted = twDate.toLocaleString('zh-TW', {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    hour12: false
                });
                element.textContent = `最後更新: ${formatted}`;
                
                const today = getTodayString();
                const updateDate = twDate.toISOString().split('T')[0];
                if (updateDate === today) {
                    element.classList.add('today');
                }
                return;
            }
        } catch (e) {
            // fall through
        }
    }
    
    const dateValue = reportData.date;
    if (dateValue) {
        element.textContent = `最後更新: ${dateValue}`;
        return;
    }
    
    element.textContent = '最後更新: --';
}

// ============================================
// 篩選功能（v5 兼容）
// ============================================

function setupFilters() {
    const buttons = document.querySelectorAll('.filter-btn');
    
    buttons.forEach(btn => {
        btn.addEventListener('click', function() {
            buttons.forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            currentFilter = this.dataset.filter;
            
            // 只在 v5 模式使用
            if (!aiReportData) {
                renderStockList();
            }
        });
    });
}

// ============================================
// 事件綁定
// ============================================

function setupEventListeners() {
    document.getElementById('reloadBtn').addEventListener('click', reloadLatest);
    
    document.getElementById('errorCloseBtn').addEventListener('click', hideError);
    document.getElementById('errorRetryBtn').addEventListener('click', () => {
        hideError();
        reloadLatest();
    });
    
    window.addEventListener('popstate', () => {
        const urlDate = getUrlParam('date');
        if (urlDate && urlDate !== currentDate) {
            currentDate = urlDate;
            document.getElementById('dateDropdown').value = urlDate;
            loadAndRenderReport(urlDate);
        }
    });
}

// ============================================
// 初始化
// ============================================

function init() {
    setupFilters();
    setupEventListeners();
    initialize();
}

// 頁面載入完成後初始化
document.addEventListener('DOMContentLoaded', init);

// 暴露全域函式
window.loadSampleData = async function() {
    hideEmptyState();
    try {
        reportData = await loadSampleData();
        aiReportData = null; // 測試資料無 AI 分析
        currentDate = reportData.date;
        indexData = {
            latest_date: currentDate,
            reports: [{ date: currentDate, has_lite: true, has_full: false }]
        };
        populateDateDropdown();
        updateDateBadge();
        renderPage();
    } catch (error) {
        showError('測試資料載入失敗', error.message);
    }
};

window.showStockDetail = function(symbol) {
    // 滾動到該股票卡片
    const cards = document.querySelectorAll('.stock-card');
    cards.forEach(card => {
        if (card.querySelector('.stock-symbol')?.textContent === symbol) {
            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
            card.style.animation = 'pulse 1s';
            setTimeout(() => card.style.animation = '', 1000);
        }
    });
};

// 開發用除錯
window.kanpanApp = {
    getData: () => ({ reportData, aiReportData, indexData, currentDate, currentFilter }),
    reload: reloadLatest
};
