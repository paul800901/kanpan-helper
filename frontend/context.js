'use strict';

const IS_GITHUB = window.location.hostname === 'paul800901.github.io';
const BASE = IS_GITHUB
    ? 'https://paul800901.github.io/kanpan-helper/reports'
    : '../reports';

const CONTEXT_SCHEMA_VERSION = 'scenario-cards-v9';
const REQUIRED_CARD_FIELDS = [
    'id',
    'title',
    'summary',
    'confidence',
    'relation_to_technical',
    'source_types',
    'source_type',
    'themes',
    'reasoning_chain',
    'priority_score',
    'priority_rank',
    'priority_reasons',
    'is_fallback',
    'generated_at'
];
const VALID_CONFIDENCE = new Set(['low', 'medium', 'high']);
const VALID_RELATION = new Set(['aligned', 'neutral', 'diverged', 'conflict']);
const GUIDE_FIELDS = [
    '市場重點',
    '為什麼這樣看',
    '關注主題',
    '關注程度',
    '觀察依據',
    '更新時間'
];
const SOURCE_TYPE_LABELS = {
    ai_market_overview: 'AI 摘要',
    market_overview: '市場總覽',
    score_distribution: '盤面強弱',
    volume_anomaly: '量能變化',
    volume_cluster: '量能變化',
    strategy_activation: '市場環境',
    sector_concentration: '主題集中度',
    system_fallback: '系統保底'
};
const PRIORITY_REASON_LABELS = {
    'confidence=high': '高可信',
    'confidence=medium': '中可信',
    'confidence=low': '低可信',
    '有制度層支持': '有制度面支持',
    '無制度層支持': '尚未看到制度面支持',
    '量能與廣度交叉驗證成立': '量能與盤面結構一致',
    '量能或廣度部分驗證': '量能或盤面結構部分一致',
    'reasoning_chain=strong': '判斷理由完整',
    '前端 defensive fallback': '系統保底'
};
const TEXT_REPLACEMENTS = [
    [/steady_v5/gi, '市場環境燈號'],
    [/electronics_axis/gi, '電子主線'],
    [/semiconductor_axis/gi, '半導體主線'],
    [/optics_axis/gi, '光學主線'],
    [/finance_axis/gi, '金融主線'],
    [/bio_axis/gi, '生技主線']
];

let indexData = null;
let currentDate = null;
let requestVersion = String(Date.now());

function buildFreshUrl(url, version = requestVersion) {
    const target = new URL(url, window.location.href);
    target.searchParams.set('_ts', version);
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

function formatGeneratedAt(text) {
    if (!text) return '--';
    return String(text).replace('T', ' ').replace(/\+08:00$/, '');
}

function formatSchemaVersion(version) {
    const text = String(version || '').trim();
    if (!text) return '--';
    const match = text.match(/v\d+(?:\.\d+)?/i);
    if (match) return match[0].toLowerCase();
    if (text.startsWith('scenario-cards-')) {
        return text.replace('scenario-cards-', 'v');
    }
    return text;
}

function humanizeText(value) {
    let text = String(value || '').trim();
    for (const [pattern, replacement] of TEXT_REPLACEMENTS) {
        text = text.replace(pattern, replacement);
    }
    return text;
}

function normalizeRelationToTechnical(value) {
    const relation = String(value || '').trim();
    if (relation === 'diverged') return 'conflict';
    return VALID_RELATION.has(relation) ? relation : 'neutral';
}

function relationLabel(value) {
    const normalized = normalizeRelationToTechnical(value);
    if (normalized === 'aligned') return '技術面一致';
    if (normalized === 'conflict') return '技術面有落差';
    return '技術面中性';
}

function confidenceLabel(value) {
    if (value === 'high') return '高可信';
    if (value === 'medium') return '中可信';
    return '低可信';
}

function showLoading(text = '載入情境卡中...') {
    const loading = document.getElementById('loadingState');
    loading.textContent = text;
    loading.style.display = 'block';
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('cardList').style.display = 'none';
    hideFallbackBanner();
}

function showEmpty(text) {
    document.getElementById('loadingState').style.display = 'none';
    const empty = document.getElementById('emptyState');
    empty.textContent = text;
    empty.style.display = 'block';
    document.getElementById('cardList').style.display = 'none';
}

function showFallbackBanner(text) {
    const banner = document.getElementById('fallbackBanner');
    banner.textContent = text;
    banner.style.display = 'block';
}

function hideFallbackBanner() {
    const banner = document.getElementById('fallbackBanner');
    banner.textContent = '';
    banner.style.display = 'none';
}

function renderSchemaFields() {
    const list = document.getElementById('schemaFieldList');
    list.innerHTML = GUIDE_FIELDS
        .map(field => `<span class="schema-field-chip">${esc(field)}</span>`)
        .join('');
}

function updateHeaderMeta(count, schemaVersion = CONTEXT_SCHEMA_VERSION) {
    document.getElementById('schemaChip').textContent = `資料版本 ${formatSchemaVersion(schemaVersion)}`;
    document.getElementById('countChip').textContent = `${count} 個重點`;
}

function buildDateDropdown() {
    const select = document.getElementById('dateSelect');
    const reports = Array.isArray(indexData?.reports)
        ? indexData.reports.filter(report => report?.has_full || report?.has_universe)
        : [];

    if (!reports.length) {
        select.innerHTML = '<option value="">無可用日期</option>';
        return;
    }

    select.innerHTML = reports.map(report => {
        const selected = report.date === currentDate ? ' selected' : '';
        const suffix = report.date === indexData.latest_date ? ' (最新)' : '';
        return `<option value="${report.date}"${selected}>${report.date}${suffix}</option>`;
    }).join('');
}

function normalizeStringList(values) {
    if (!Array.isArray(values)) return [];
    const seen = new Set();
    const items = [];
    values.forEach(value => {
        const text = String(value || '').trim();
        if (!text || seen.has(text)) return;
        seen.add(text);
        items.push(text);
    });
    return items;
}

function buildDefensiveFallbackCard(reason, generatedAt) {
    const sourceTypes = ['system_fallback'];
    return {
        id: 'fallback-frontend',
        title: '市場重點暫時讀不到',
        summary: reason,
        confidence: 'low',
        relation_to_technical: 'neutral',
        source_types: sourceTypes,
        source_type: sourceTypes.join('+'),
        themes: ['資料待補'],
        reasoning_chain: [
            '系統暫時拿不到完整的市場重點資料。',
            '目前先用保底卡提醒你，避免顯示錯誤內容。',
            '等報告更新完成後，再重新整理頁面即可。'
        ],
        priority_score: -999,
        priority_rank: 1,
        priority_reasons: ['前端 defensive fallback'],
        is_fallback: true,
        generated_at: generatedAt || new Date().toISOString()
    };
}

function describeSourceType(value) {
    const normalized = String(value || '').trim();
    if (!normalized) return '其他訊號';
    if (SOURCE_TYPE_LABELS[normalized]) return SOURCE_TYPE_LABELS[normalized];
    if (normalized.includes('ai')) return 'AI 摘要';
    if (normalized.includes('market')) return '市場總覽';
    if (normalized.includes('score')) return '盤面強弱';
    if (normalized.includes('volume')) return '量能變化';
    if (normalized.includes('strategy')) return '市場環境';
    if (normalized.includes('sector')) return '主題集中度';
    return '其他訊號';
}

function describePriorityReason(value) {
    const normalized = String(value || '').trim();
    const countMatch = normalized.match(/^訊號來源\s*(\d+)\s*類$/);
    if (countMatch) {
        return `參考 ${countMatch[1]} 種訊號`;
    }
    if (PRIORITY_REASON_LABELS[normalized]) {
        return PRIORITY_REASON_LABELS[normalized];
    }
    if (normalized.includes('=') || normalized.includes('_')) {
        return '補充訊號';
    }
    return normalized;
}

function buildCardKicker(card) {
    if (card?.is_fallback) return '暫時保底';
    return '市場重點';
}

function normalizeScenarioCard(card, generatedAt) {
    if (!card || typeof card !== 'object') {
        return buildDefensiveFallbackCard('卡片格式錯誤，已回退到前端保底。', generatedAt);
    }

    if (REQUIRED_CARD_FIELDS.some(field => !(field in card))) {
        return buildDefensiveFallbackCard('卡片缺少 v9 必要欄位，已回退到前端保底。', generatedAt);
    }

    const sourceTypes = normalizeStringList(card.source_types);
    if (!sourceTypes.length) {
        return buildDefensiveFallbackCard('卡片 source_types 為空，已回退到前端保底。', generatedAt);
    }

    const normalized = {
        id: String(card.id || '').trim(),
        title: String(card.title || '').trim(),
        summary: String(card.summary || '').trim(),
        confidence: String(card.confidence || '').trim(),
        relation_to_technical: normalizeRelationToTechnical(card.relation_to_technical),
        source_types: sourceTypes,
        source_type: String(card.source_type || sourceTypes.join('+')).trim(),
        themes: normalizeStringList(card.themes),
        reasoning_chain: normalizeStringList(card.reasoning_chain),
        priority_score: Number.isFinite(Number(card.priority_score)) ? Number(card.priority_score) : -999,
        priority_rank: Number.isInteger(card.priority_rank) ? card.priority_rank : 0,
        priority_reasons: normalizeStringList(card.priority_reasons),
        is_fallback: Boolean(card.is_fallback),
        generated_at: String(card.generated_at || '').trim()
    };

    if (!normalized.id || !normalized.title || !normalized.summary || !normalized.source_type || !normalized.generated_at) {
        return buildDefensiveFallbackCard('卡片文字欄位不完整，已回退到前端保底。', generatedAt);
    }
    if (!VALID_CONFIDENCE.has(normalized.confidence)) {
        return buildDefensiveFallbackCard('卡片 confidence 不合法，已回退到前端保底。', generatedAt);
    }
    if (!normalized.themes.length || !normalized.reasoning_chain.length || !normalized.priority_reasons.length) {
        return buildDefensiveFallbackCard('卡片列表欄位不完整，已回退到前端保底。', generatedAt);
    }

    return normalized;
}

function normalizeScenarioCards(cards, generatedAt) {
    if (!Array.isArray(cards) || !cards.length) {
        return [buildDefensiveFallbackCard('缺少 scenario_cards_v9，已回退到前端保底。', generatedAt)];
    }

    return cards.map(card => normalizeScenarioCard(card, generatedAt));
}

function renderChipList(items, chipClass) {
    return `<div class="scenario-chip-list">${items.map(item => {
        return `<span class="signal-chip ${chipClass}">${esc(item)}</span>`;
    }).join('')}</div>`;
}

function renderCard(card) {
    const normalizedRelation = normalizeRelationToTechnical(card.relation_to_technical);
    const reasoningHTML = card.reasoning_chain
        .map(item => `<li class="reasoning-item">${esc(humanizeText(item))}</li>`)
        .join('');
    const priorityReasonsHTML = renderChipList(card.priority_reasons.map(describePriorityReason), 'reason-chip');
    const sourceTypeHTML = renderChipList(card.source_types.map(describeSourceType), 'keyword-chip');

    return `
        <article class="scenario-card" data-card-id="${esc(card.id)}">
            <div class="scenario-card-top">
                <div class="scenario-title-block">
                    <div class="scenario-id">${esc(buildCardKicker(card))}</div>
                    <div class="scenario-card-title">${esc(humanizeText(card.title))}</div>
                </div>
                <div class="scenario-card-meta">
                    <span class="priority-chip">第 ${esc(card.priority_rank)} 位</span>
                    <span class="priority-chip">關注度 ${esc(card.priority_score)}</span>
                    <span class="meta-chip confidence-${esc(card.confidence)}">${esc(confidenceLabel(card.confidence))}</span>
                    <span class="meta-chip relation-${esc(normalizedRelation)}">${esc(relationLabel(normalizedRelation))}</span>
                </div>
            </div>
            <div class="scenario-grid">
                <div class="scenario-row">
                    <div class="scenario-label">重點摘要</div>
                    <div class="scenario-text">${esc(humanizeText(card.summary))}</div>
                </div>
                <div class="scenario-row">
                    <div class="scenario-label">為什麼這樣看</div>
                    <div class="scenario-text"><ul class="reasoning-list">${reasoningHTML}</ul></div>
                </div>
                <div class="scenario-row">
                    <div class="scenario-label">關注主題</div>
                    <div class="scenario-text">${renderChipList(card.themes.map(humanizeText), 'theme-chip')}</div>
                </div>
                <div class="scenario-row">
                    <div class="scenario-label">關注程度</div>
                    <div class="scenario-text">
                        <div class="scenario-priority-strip">
                            <span class="priority-chip">第 ${esc(card.priority_rank)} 位</span>
                            <span class="priority-chip">關注度 ${esc(card.priority_score)}</span>
                        </div>
                        ${priorityReasonsHTML}
                    </div>
                </div>
                <div class="scenario-row">
                    <div class="scenario-label">觀察依據</div>
                    <div class="scenario-text">${sourceTypeHTML}</div>
                </div>
            </div>
            <div class="scenario-footer">
                <span>更新時間：${esc(formatGeneratedAt(card.generated_at))}</span>
                <span>資料版本：${esc(formatSchemaVersion(CONTEXT_SCHEMA_VERSION))}</span>
            </div>
        </article>`;
}

function renderCards(cards, schemaVersion) {
    updateHeaderMeta(cards.length, schemaVersion);
    document.getElementById('loadingState').style.display = 'none';
    document.getElementById('emptyState').style.display = 'none';
    const list = document.getElementById('cardList');
    list.innerHTML = cards.map(renderCard).join('');
    list.style.display = 'grid';
}

async function loadIndex() {
    indexData = await fetchJSON(`${BASE}/index.json`);
}

async function loadContextCards(date) {
    showLoading(`正在整理 ${date} 的市場重點...`);

    try {
        const contextReport = await fetchJSON(`${BASE}/${date}-context.json`);
        const schemaVersion = String(contextReport?.scenario_cards_v9_schema_version || CONTEXT_SCHEMA_VERSION);
        const generatedAt = String(contextReport?.generated_at || new Date().toISOString());
        const cards = normalizeScenarioCards(contextReport?.scenario_cards_v9, generatedAt);

        if (cards.some(card => card.is_fallback)) {
            showFallbackBanner('今天的市場重點有部分資料不足，畫面已先顯示保底說明。');
        } else {
            hideFallbackBanner();
        }

        renderCards(cards, schemaVersion);
    } catch (error) {
        const fallbackCards = [buildDefensiveFallbackCard('系統暫時讀不到今天的市場重點，先用保底說明提醒你稍後再看。', new Date().toISOString())];
        showFallbackBanner('今天的市場重點暫時讀不到，畫面先顯示保底說明。');
        renderCards(fallbackCards, CONTEXT_SCHEMA_VERSION);
    }
}

async function init() {
    renderSchemaFields();

    try {
        await loadIndex();
        currentDate = new URLSearchParams(window.location.search).get('date') || indexData.latest_date;
        buildDateDropdown();

        document.getElementById('dateSelect').addEventListener('change', async event => {
            currentDate = event.target.value;
            requestVersion = String(Date.now());
            const nextUrl = new URL(window.location.href);
            nextUrl.searchParams.set('date', currentDate);
            window.history.replaceState({}, '', nextUrl.toString());
            await loadContextCards(currentDate);
        });

        await loadContextCards(currentDate);
    } catch (error) {
        showEmpty('暫時讀不到市場重點，請稍後再試。');
    }
}

document.addEventListener('DOMContentLoaded', init);
