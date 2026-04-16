'use strict';

/**
 * V10.1.1: Priority Validation 第二頁 - Contract-Only Render
 * 
 * 責任邊界：
 * - 只讀取 priority_validation_v10_1_schema_version
 * - 只讀取 priority_snapshot_v10_1
 * - 只讀取 priority_candidates_v10_1
 * - 不得從 legacy 結構（cards, trace_catalog 等）重建資料
 * - 純 render-only，不重建邏輯
 */

const IS_GITHUB = window.location.hostname === 'paul800901.github.io';
const BASE = IS_GITHUB
    ? 'https://paul800901.github.io/kanpan-helper/reports'
    : '../reports';

const PRIORITY_SCHEMA_VERSION = 'priority-validation-v10.1';
const REQUIRED_SNAPSHOT_FIELDS = [
    'as_of_date',
    'market_regime',
    'breadth_state',
    'volume_state',
    'leader_state',
    'validation_summary',
    'confidence',
    'generated_at'
];
const REQUIRED_CANDIDATE_FIELDS = [
    'symbol',
    'name',
    'score',
    'rank',
    'score_grade',
    'category',
    'theme',
    'validation_reason',
    'risk_note'
];
const THEME_LABELS = {
    electronics_axis: '電子主線',
    semiconductor_axis: '半導體主線',
    optics_axis: '光學主線',
    finance_axis: '金融主線',
    bio_axis: '生技主線'
};

let currentDate = null;

function formatConfidenceLabel(confidence) {
    if (confidence === 'high') return '高';
    if (confidence === 'medium') return '中';
    return '低';
}

function formatTheme(theme) {
    const normalized = String(theme || '').trim();
    return THEME_LABELS[normalized] || normalized || '其他';
}

function formatValidationReason(reason) {
    return String(reason || '')
        .replace(/命中\s*(\d+)\s*情境/g, '符合 $1 個市場重點')
        .replace(/steady_v5/gi, '市場環境燈號');
}

function buildFreshUrl(url) {
    const target = new URL(url, window.location.href);
    target.searchParams.set('_ts', String(Date.now()));
    return target.toString();
}

function fetchJSON(url) {
    return fetch(buildFreshUrl(url), { cache: 'no-store' }).then(async response => {
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${url}`);
        }
        return response.json();
    });
}

function esc(text) {
    if (text == null) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

function getConfidenceClass(confidence) {
    if (confidence === 'high') return 'confidence-high';
    if (confidence === 'medium') return 'confidence-medium';
    return 'confidence-low';
}

function getGradeClass(grade) {
    if (grade === 'A') return 'grade-a';
    if (grade === 'B') return 'grade-b';
    if (grade === 'C') return 'grade-c';
    return 'grade-d';
}

function formatRegime(regime) {
    const map = {
        'trending': '趨勢盤',
        'balanced': '平衡盤',
        'choppy': '震盪盤',
        'unknown': '未知'
    };
    return map[regime] || regime;
}

function formatBreadth(state) {
    const map = {
        'strong_breadth': '強廣度',
        'weak_breadth': '弱廣度',
        'mixed_breadth': '混合廣度',
        'unknown': '未知'
    };
    return map[state] || state;
}

function formatVolume(state) {
    const map = {
        'expanding': '擴張',
        'contracting': '萎縮',
        'neutral': '中性',
        'unknown': '未知'
    };
    return map[state] || state;
}

function formatLeaders(state) {
    const map = {
        'strong_leaders': '強領漲',
        'moderate_leaders': '中等領漲',
        'weak_leaders': '弱領漲',
        'unknown': '未知'
    };
    return map[state] || state;
}

function showLoading() {
    document.getElementById('loadingState').style.display = 'block';
    document.getElementById('errorState').style.display = 'none';
    document.getElementById('contentArea').style.display = 'none';
}

function showError(message) {
    document.getElementById('loadingState').style.display = 'none';
    document.getElementById('errorState').style.display = 'block';
    document.getElementById('errorState').textContent = message;
    document.getElementById('contentArea').style.display = 'none';
}

function showContent() {
    document.getElementById('loadingState').style.display = 'none';
    document.getElementById('errorState').style.display = 'none';
    document.getElementById('contentArea').style.display = 'block';
}

/**
 * V10.1.1: 驗證 priority_validation_v10_1 contract
 * 確保第二頁只消費正式欄位
 */
function validatePriorityContract(report) {
    // 驗證 schema_version
    const schemaVersion = report?.priority_validation_v10_1_schema_version;
    if (schemaVersion !== PRIORITY_SCHEMA_VERSION) {
        throw new Error(`Schema 版本不符: 預期 ${PRIORITY_SCHEMA_VERSION}, 實際 ${schemaVersion}`);
    }

    // 驗證 snapshot
    const snapshot = report?.priority_snapshot_v10_1;
    if (!snapshot) {
        throw new Error('缺少 priority_snapshot_v10_1');
    }
    const missingSnapshot = REQUIRED_SNAPSHOT_FIELDS.filter(f => !(f in snapshot));
    if (missingSnapshot.length > 0) {
        throw new Error(`snapshot 缺少欄位: ${missingSnapshot.join(', ')}`);
    }

    // 驗證 candidates
    const candidates = report?.priority_candidates_v10_1;
    if (!Array.isArray(candidates)) {
        throw new Error('priority_candidates_v10_1 必須是陣列');
    }

    return { snapshot, candidates };
}

/**
 * V10.1.1: 渲染 Market Snapshot
 */
function renderSnapshot(snapshot) {
    const grid = document.getElementById('snapshotGrid');
    
    const items = [
        { label: '盤勢型態', value: formatRegime(snapshot.market_regime) },
        { label: '盤面廣度', value: formatBreadth(snapshot.breadth_state) },
        { label: '量能狀況', value: formatVolume(snapshot.volume_state) },
        { label: '強勢族群', value: formatLeaders(snapshot.leader_state) },
        { label: '判斷把握', value: formatConfidenceLabel(snapshot.confidence), class: getConfidenceClass(snapshot.confidence) },
        { label: '資料日期', value: snapshot.as_of_date }
    ];

    grid.innerHTML = items.map(item => `
        <div class="snapshot-item">
            <div class="snapshot-label">${esc(item.label)}</div>
            <div class="snapshot-value ${item.class || ''}">${esc(item.value)}</div>
        </div>
    `).join('');

    // 更新 header meta
    document.getElementById('dateChip').textContent = snapshot.as_of_date;
    document.getElementById('confidenceChip').textContent = `判斷把握：${formatConfidenceLabel(snapshot.confidence)}`;
    document.getElementById('confidenceChip').className = `meta-chip ${getConfidenceClass(snapshot.confidence)}`;
}

/**
 * V10.1.1: 渲染 Candidates 列表
 */
function renderCandidates(candidates) {
    const list = document.getElementById('candidateList');
    
    list.innerHTML = candidates.map(c => `
        <div class="candidate-card">
            <div class="candidate-top">
                <div class="candidate-symbol">${esc(c.symbol)} ${esc(c.name)}</div>
                <div class="candidate-rank">${c.rank}</div>
            </div>
            <div class="candidate-meta">
                <div class="candidate-meta-item">
                    關注度: <span class="candidate-meta-value">${c.score}</span>
                    <span class="${getGradeClass(c.score_grade)}">(${c.score_grade})</span>
                </div>
                <div class="candidate-meta-item">
                    類別: <span class="candidate-meta-value">${esc(c.category)}</span>
                </div>
                <div class="candidate-meta-item">
                    主題: <span class="candidate-meta-value">${esc(formatTheme(c.theme))}</span>
                </div>
            </div>
            <div class="candidate-reason">${esc(formatValidationReason(c.validation_reason))}</div>
            <div class="candidate-risk">風險提醒: ${esc(c.risk_note)}</div>
        </div>
    `).join('');
}

async function loadLatestDate() {
    const index = await fetchJSON(`${BASE}/index.json`);
    return index?.latest_date || new Date().toISOString().split('T')[0];
}

/**
 * V10.1.1: 載入 Priority Validation 資料
 * 只讀取正式 contract 欄位
 */
async function loadPriorityValidation(date) {
    showLoading();
    currentDate = date;

    try {
        // V10.1.1: 直接載入 priority report
        const report = await fetchJSON(`${BASE}/${date}-priority.json`);
        
        // V10.1.1: 驗證並解構正式 contract 欄位
        const { snapshot, candidates } = validatePriorityContract(report);
        
        // V10.1.1: 純 render-only，不重建邏輯
        renderSnapshot(snapshot);
        renderCandidates(candidates);
        
        showContent();
    } catch (error) {
        console.error('載入失敗:', error);
        showError(`今日名單暫時讀不到：${error.message}`);
    }
}

// 初始化
async function init() {
    const urlParams = new URLSearchParams(window.location.search);
    let date = urlParams.get('date');
    
    try {
        if (!date) {
            date = await loadLatestDate();
        }
        loadPriorityValidation(date);
    } catch (error) {
        console.error('初始化失敗:', error);
        showError('今日名單暫時讀不到，請稍後再試。');
    }
}

document.addEventListener('DOMContentLoaded', init);
