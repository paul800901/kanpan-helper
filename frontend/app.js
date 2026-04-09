/**
 * 看盤助手 v5 - PWA 版應用程式
 * 支援索引載入、日期切換、Service Worker
 * GitHub Pages 單一 workflow 部署
 */

// 全域狀態
let reportData = null;
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
    // 載入報告索引
    try {
        const response = await fetch(CONFIG.INDEX_PATH);
        if (!response.ok) {
            if (response.status === 404) {
                return null; // 索引不存在
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
    // 載入指定日期的報告
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

async function loadSampleData() {
    // 載入測試資料
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
        
        // 更新 URL（不重新載入頁面）
        const url = new URL(window.location);
        url.searchParams.set('date', selectedDate);
        window.history.pushState({}, '', url);
        
        // 載入選擇的報告
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
    
    // 只顯示有 lite 版本的報告
    const availableReports = indexData.reports.filter(r => r.has_lite);
    
    availableReports.forEach(report => {
        const option = document.createElement('option');
        option.value = report.date;
        
        // 標示最新
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
    // 載入索引
    indexData = await loadIndex();
    
    // 決定要載入的日期
    const urlDate = getUrlParam('date');
    
    if (urlDate) {
        // URL 指定日期
        currentDate = urlDate;
    } else if (indexData && indexData.latest_date) {
        // 使用最新日期
        currentDate = indexData.latest_date;
    } else {
        // 無可用報告
        showEmptyState();
        document.getElementById('stockList').innerHTML = '';
        return;
    }
    
    // 初始化日期選擇器
    populateDateDropdown();
    initDateDropdown();
    
    // 載入報告
    await loadAndRenderReport(currentDate);
}

async function loadAndRenderReport(dateStr) {
    const listContainer = document.getElementById('stockList');
    listContainer.innerHTML = '<div class="loading">載入報告中...</div>';
    
    try {
        reportData = await loadReportByDate(dateStr);
        currentDate = dateStr;
        
        updateDateBadge();
        renderPage();
        hideError();
        
    } catch (error) {
        console.error('載入報告失敗:', error);
        
        // 檢查是否為歷史日期遺失
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
    // 重新載入最新報告
    // 重新載入索引
    indexData = await loadIndex();
    
    if (!indexData || !indexData.latest_date) {
        showEmptyState();
        return;
    }
    
    // 清除 URL 參數
    const url = new URL(window.location);
    url.searchParams.delete('date');
    window.history.pushState({}, '', url);
    
    // 更新日期選擇器
    populateDateDropdown();
    
    // 載入最新
    currentDate = indexData.latest_date;
    await loadAndRenderReport(currentDate);
}

// ============================================
// 渲染函式
// ============================================

function renderPage() {
    if (!reportData) return;
    
    renderHeader();
    renderSummary();
    renderStockList();
    renderFooter();
    renderLastUpdated();
}

function renderHeader() {
    document.getElementById('marketSummary').textContent = 
        reportData.summary?.market_overview || '市場概況資料不足';
}

function renderSummary() {
    const stocks = reportData.stocks || [];
    
    // 統計各類別
    const counts = { '可留意': 0, '觀察': 0, '偏保守': 0, '暫不考慮': 0 };
    const lists = { '可留意': [], '觀察': [], '偏保守': [], '暫不考慮': [] };
    
    stocks.forEach(stock => {
        if (counts.hasOwnProperty(stock.action_bias)) {
            counts[stock.action_bias]++;
            lists[stock.action_bias].push(stock.name);
        }
    });
    
    // 更新數量
    document.getElementById('topPicksCount').textContent = counts['可留意'];
    document.getElementById('watchlistCount').textContent = counts['觀察'];
    document.getElementById('avoidCount').textContent = counts['偏保守'] + counts['暫不考慮'];
    
    // 更新列表
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
    
    container.innerHTML = filteredStocks.map(stock => createStockCard(stock)).join('');
    
    // 綁定點擊事件
    document.querySelectorAll('.stock-header').forEach(header => {
        header.addEventListener('click', function() {
            const details = this.closest('.stock-card').querySelector('.stock-details');
            const hint = this.querySelector('.expand-hint');
            const isExpanded = details.classList.toggle('expanded');
            hint.innerHTML = isExpanded 
                ? '點擊收起 <span class="expand-icon">▲</span>'
                : '點擊展開詳情 <span class="expand-icon">▼</span>';
        });
    });
}

function createStockCard(stock) {
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

function renderFooter() {
    const stocks = reportData.stocks || [];
    const goodCount = stocks.filter(s => s.action_bias === '可留意').length;
    
    document.getElementById('footerDate').textContent = currentDate || '--';
    document.getElementById('totalCount').textContent = stocks.length;
    document.getElementById('goodCount').textContent = goodCount;
}

function renderLastUpdated() {
    const lastUpdated = reportData.metadata?.last_updated || reportData.created_at || null;
    const element = document.getElementById('lastUpdated');
    
    if (lastUpdated) {
        try {
            const date = new Date(lastUpdated);
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
            
            // 如果是當天更新，加上特殊樣式
            const today = getTodayString();
            const updateDate = twDate.toISOString().split('T')[0];
            if (updateDate === today) {
                element.classList.add('today');
            }
        } catch (e) {
            element.textContent = `最後更新: ${lastUpdated}`;
        }
    } else {
        element.textContent = '最後更新: --';
    }
}

// ============================================
// 篩選功能
// ============================================

function setupFilters() {
    const buttons = document.querySelectorAll('.filter-btn');
    
    buttons.forEach(btn => {
        btn.addEventListener('click', function() {
            buttons.forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            currentFilter = this.dataset.filter;
            renderStockList();
        });
    });
}

// ============================================
// 事件綁定
// ============================================

function setupEventListeners() {
    // 重新載入按
    document.getElementById('reloadBtn').addEventListener('click', reloadLatest);
    
    // 錯誤 Modal 按
    document.getElementById('errorCloseBtn').addEventListener('click', hideError);
    document.getElementById('errorRetryBtn').addEventListener('click', () => {
        hideError();
        reloadLatest();
    });
    
    // 瀏覽器返回按鈕支援
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

// 暴露全域函式（供 HTML onclick 使用）
window.loadSampleData = async function() {
    hideEmptyState();
    try {
        reportData = await loadSampleData();
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

// 開發用除錯
window.kanpanApp = {
    getData: () => ({ reportData, indexData, currentDate, currentFilter }),
    reload: reloadLatest
};
