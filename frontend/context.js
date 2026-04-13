'use strict';

const IS_GITHUB = window.location.hostname === 'paul800901.github.io';
const BASE = IS_GITHUB
    ? 'https://paul800901.github.io/kanpan-helper/reports'
    : '../reports';

const CONTEXT_SCHEMA_VERSION = 'v8.1-context-card';
const REQUIRED_CARD_FIELDS = [
    'id',
    'title',
    'event',
    'anomaly',
    'reasoning_chain',
    'confidence',
    'relation_to_technical',
    'source_type',
    'generated_at'
];
const VALID_CONFIDENCE = new Set(['low', 'medium', 'high']);
const VALID_RELATION = new Set(['aligned', 'neutral', 'conflict']);
const PROHIBITED_TEXT_SNIPPETS = [
    '買進',
    '買入',
    '賣出',
    '進場',
    '出場',
    '加碼',
    '減碼',
    '停損',
    '停利',
    '建議買',
    '建議賣'
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

function toNum(value) {
    if (value == null || value === '') return null;
    const num = Number(value);
    return Number.isFinite(num) ? num : null;
}

function formatPct(value, digits = 0) {
    if (value == null) return '--';
    return `${Number(value).toLocaleString('zh-TW', {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits
    })}%`;
}

function formatNum(value, digits = 1) {
    if (value == null) return '--';
    return Number(value).toLocaleString('zh-TW', {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits
    });
}

function formatGeneratedAt(text) {
    if (!text) return '--';
    return String(text).replace('T', ' ').replace(/\+08:00$/, '');
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
    list.innerHTML = REQUIRED_CARD_FIELDS
        .map(field => `<span class="schema-field-chip">${esc(field)}</span>`)
        .join('');
}

function updateHeaderMeta(count) {
    document.getElementById('schemaChip').textContent = `schema ${CONTEXT_SCHEMA_VERSION}`;
    document.getElementById('countChip').textContent = `${count} 張卡`;
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

function parseAIDirection(text) {
    const source = String(text || '');
    if (/偏多|強勢|主流|積極|續強/.test(source)) return '偏多';
    if (/偏保守|保守|防守|轉弱|震盪|分歧|觀望/.test(source)) return '偏保守';
    return '中性';
}

function summarizeCounter(counter, limit = 2) {
    const entries = Object.entries(counter || {}).sort((left, right) => right[1] - left[1]);
    if (!entries.length) return '分布未明';
    return entries.slice(0, limit).map(([label, count]) => `${label}${count} 項`).join('、');
}

function getTopEntries(counter, limit = 2) {
    return Object.entries(counter || {}).sort((left, right) => right[1] - left[1]).slice(0, limit);
}

function buildCategoryCounter(stocks) {
    const counter = {};
    stocks.forEach(stock => {
        const category = String(stock?.category || '其他').trim() || '其他';
        counter[category] = (counter[category] || 0) + 1;
    });
    return counter;
}

function gradeLabel(stock) {
    const grade = String(stock?.score_grade || '').trim().toUpperCase();
    if (grade) return grade;
    const score = toNum(stock?.score);
    if (score == null) return 'U';
    if (score >= 75) return 'A';
    if (score >= 60) return 'B';
    if (score >= 45) return 'C';
    return 'D';
}

function selectGeneratedAt(...values) {
    for (const value of values) {
        if (typeof value === 'string' && value.trim()) {
            return value;
        }
    }
    return new Date().toISOString();
}

function buildSnapshot(fullReport, universeReport, aiReport, activationReport) {
    const universeStocks = Array.isArray(universeReport?.stocks) ? universeReport.stocks : [];
    const fullStocks = Array.isArray(fullReport?.stocks) ? fullReport.stocks : [];
    const stocks = universeStocks.length ? universeStocks : fullStocks;
    if (!stocks.length) {
        return null;
    }

    const topSample = [...stocks]
        .sort((left, right) => (toNum(left?.rank) ?? 999) - (toNum(right?.rank) ?? 999))
        .slice(0, Math.min(10, stocks.length));
    const categoryCounter = buildCategoryCounter(topSample);
    const topCategoryEntries = getTopEntries(categoryCounter, 2);
    const topTwoTotal = topCategoryEntries.reduce((sum, [, count]) => sum + count, 0);
    const topTwoShare = topSample.length ? topTwoTotal / topSample.length : null;

    const hotStocks = stocks.filter(stock => {
        const volumeRatio = toNum(stock?.volume_ratio ?? stock?.indicators?.volume_ratio);
        return volumeRatio != null && volumeRatio >= 1.5;
    });
    const hotCategoryCounter = buildCategoryCounter(hotStocks);
    const hotHighScoreCount = hotStocks.filter(stock => {
        const grade = gradeLabel(stock);
        return grade === 'A' || grade === 'B';
    }).length;
    const overlapCategories = getTopEntries(categoryCounter, 3)
        .map(([category]) => category)
        .filter(category => hotCategoryCounter[category]);

    let avgScore = 0;
    let positiveCount = 0;
    let cautiousCount = 0;
    let counted = 0;

    stocks.forEach(stock => {
        const score = toNum(stock?.score);
        if (score != null) {
            avgScore += score;
            counted += 1;
        }
        const grade = gradeLabel(stock);
        if (grade === 'A' || grade === 'B') {
            positiveCount += 1;
        } else if (grade === 'C' || grade === 'D') {
            cautiousCount += 1;
        }
    });

    avgScore = counted ? avgScore / counted : null;

    let technicalDirection = '中性';
    if (avgScore != null) {
        if (avgScore >= 65 && positiveCount >= cautiousCount) {
            technicalDirection = '偏多';
        } else if (avgScore < 55 || cautiousCount > positiveCount) {
            technicalDirection = '偏保守';
        }
    }

    return {
        date: currentDate,
        totalCount: stocks.length,
        avgScore,
        positiveCount,
        cautiousCount,
        topSampleCount: topSample.length,
        categoryCounter,
        topCategoryEntries,
        topTwoShare,
        hotStocks,
        hotCategoryCounter,
        hotShare: stocks.length ? hotStocks.length / stocks.length : null,
        hotHighScoreCount,
        overlapCategories,
        technicalDirection,
        aiDirection: parseAIDirection(aiReport?.market_overview_ai),
        marketOverview: String(fullReport?.summary?.market_overview || ''),
        aiMarketOverview: String(aiReport?.market_overview_ai || ''),
        generatedAt: selectGeneratedAt(
            universeReport?.generated_at,
            fullReport?.generated_at,
            aiReport?.generated_at,
            activationReport?.generated_at
        )
    };
}

function collectBannedTerms(fullReport, universeReport) {
    const terms = new Set();
    const sources = [];
    if (Array.isArray(fullReport?.stocks)) sources.push(fullReport.stocks);
    if (Array.isArray(universeReport?.stocks)) sources.push(universeReport.stocks);

    sources.forEach(stocks => {
        stocks.forEach(stock => {
            const symbol = String(stock?.symbol || '').trim();
            const name = String(stock?.name || '').trim();
            if (symbol) terms.add(symbol);
            if (name) terms.add(name);
        });
    });
    return terms;
}

function relationLabel(value) {
    if (value === 'aligned') return '技術面一致';
    if (value === 'conflict') return '技術面有落差';
    return '技術面中性';
}

function confidenceLabel(value) {
    if (value === 'high') return '高可信';
    if (value === 'medium') return '中可信';
    return '低可信';
}

function relationTone(aiDirection, technicalDirection) {
    if (aiDirection === '中性' || technicalDirection === '中性') return 'neutral';
    return aiDirection === technicalDirection ? 'aligned' : 'conflict';
}

function buildFallbackCard(index, reason, generatedAt) {
    return {
        id: `fallback-${index}`,
        title: `保底情境卡 ${index}`,
        event: '目前可用市場資料不足，第三頁先保留固定載體。',
        anomaly: reason,
        reasoning_chain: [
            '本頁仍維持固定 schema，避免後續推理載體中斷。',
            '目前沒有足夠資料支撐完整市場情境，因此先回退到系統保底描述。',
            '這個 fallback 不影響首頁、股票總覽與個股頁的既有功能。'
        ],
        confidence: 'low',
        relation_to_technical: 'neutral',
        source_type: 'ui_fallback',
        generated_at: generatedAt || new Date().toISOString()
    };
}

function createBreadthCard(snapshot) {
    if (!snapshot) {
        return buildFallbackCard(1, '缺少 full/universe 報表，無法建立盤面廣度情境卡。');
    }

    let event = '中高分樣本占優，盤面仍有可辨識的強弱層次。';
    if (snapshot.positiveCount === snapshot.cautiousCount) {
        event = '中高分與中低分樣本接近，盤面仍偏拉鋸。';
    } else if (snapshot.positiveCount < snapshot.cautiousCount) {
        event = '中低分樣本偏多，盤面整體結構仍偏保守。';
    }

    const confidence = snapshot.avgScore != null && Math.abs(snapshot.positiveCount - snapshot.cautiousCount) >= 6
        ? 'high'
        : 'medium';

    return {
        id: 'breadth-balance',
        title: '盤面廣度與強弱分布',
        event,
        anomaly: `A/B 合計 ${snapshot.positiveCount} 檔，C/D 合計 ${snapshot.cautiousCount} 檔，平均分數約 ${formatNum(snapshot.avgScore)}。`,
        reasoning_chain: [
            `當日可用樣本共 ${snapshot.totalCount} 檔，這張卡先用分數分布確認盤面是否仍有前段結構。`,
            `目前 A/B 與 C/D 的差距為 ${Math.abs(snapshot.positiveCount - snapshot.cautiousCount)} 檔，可用來判斷盤面偏多還是偏保守。`,
            '這張卡只描述市場結構，不延伸到個股名稱，也不提供任何操作結論。'
        ],
        confidence,
        relation_to_technical: snapshot.technicalDirection === '中性' ? 'neutral' : 'aligned',
        source_type: 'market_overview+score_distribution',
        generated_at: snapshot.generatedAt
    };
}

function createSectorCard(snapshot) {
    if (!snapshot || !snapshot.topCategoryEntries.length) {
        return buildFallbackCard(2, '缺少類別集中度資料，無法建立主軸收斂情境卡。', snapshot?.generatedAt);
    }

    const topSummary = summarizeCounter(snapshot.categoryCounter);
    let event = '前段樣本集中在少數類別，市場主軸偏收斂。';
    if ((snapshot.topTwoShare || 0) < 0.6) {
        event = (snapshot.topTwoShare || 0) >= 0.45
            ? '前段類別已有主軸，但輪動仍未完全結束。'
            : '前段類別分散，主軸尚未完全收斂。';
    }

    return {
        id: 'sector-concentration',
        title: '主軸集中度',
        event,
        anomaly: `前 ${snapshot.topSampleCount} 名樣本中，前兩大類別占比約 ${formatPct((snapshot.topTwoShare || 0) * 100)}，主要落在 ${topSummary}。`,
        reasoning_chain: [
            `這張卡只看前 ${snapshot.topSampleCount} 名樣本，因為前段名次最能反映當日資金偏好的聚焦程度。`,
            `當前兩大類別占比過高時，代表市場注意力集中；若占比下降，則代表主軸仍在輪動。`,
            '這裡只保留類別與結構描述，不做題材到股票的映射，也不點名任何公司。'
        ],
        confidence: (snapshot.topTwoShare || 0) >= 0.6 ? 'high' : 'medium',
        relation_to_technical: (snapshot.topTwoShare || 0) >= 0.45 ? 'aligned' : 'neutral',
        source_type: 'sector_concentration+universe',
        generated_at: snapshot.generatedAt
    };
}

function createVolumeCard(snapshot) {
    if (!snapshot) {
        return buildFallbackCard(3, '缺少量能資料，無法建立量能異常情境卡。');
    }

    const hotSummary = summarizeCounter(snapshot.hotCategoryCounter);
    let event = '量能異常有形成群聚，但擴散仍集中在少數區塊。';
    if (!snapshot.hotStocks.length) {
        event = '量能異常有限，市場注意力尚未形成可辨識的擴散。';
    } else if ((snapshot.hotShare || 0) < 0.08) {
        event = '量能異常存在，但仍屬局部升溫，尚未形成明顯擴散。';
    }

    const overlapText = snapshot.overlapCategories.length
        ? snapshot.overlapCategories.join('、')
        : '目前與前段類別重疊有限';

    return {
        id: 'volume-focus',
        title: '量能異常與擴散',
        event,
        anomaly: `量比大於等於 1.5 的樣本共 ${snapshot.hotStocks.length} 檔，占全體約 ${formatPct((snapshot.hotShare || 0) * 100)}；其中 ${snapshot.hotHighScoreCount} 檔同時位於 A/B 區。`,
        reasoning_chain: [
            '量能不是用來下單，而是用來驗證當日市場注意力是否開始聚集。',
            `目前放量樣本主要落在 ${hotSummary}，與前段主軸的重疊情況為 ${overlapText}。`,
            '若放量樣本集中但沒有對應的前段結構，這張卡就只保留中性描述，不外推到股票層。'
        ],
        confidence: snapshot.hotStocks.length >= 4 && snapshot.hotHighScoreCount >= 2 ? 'high' : snapshot.hotStocks.length ? 'medium' : 'low',
        relation_to_technical: snapshot.hotHighScoreCount >= Math.max(1, Math.floor(snapshot.hotStocks.length / 2)) ? 'aligned' : 'neutral',
        source_type: 'volume_anomaly+universe',
        generated_at: snapshot.generatedAt
    };
}

function createAIOverlayCard(snapshot, aiReport) {
    if (!snapshot || !String(aiReport?.market_overview_ai || '').trim()) {
        return null;
    }

    const relation = relationTone(snapshot.aiDirection, snapshot.technicalDirection);
    let event = 'AI 摘要方向與橫截面資料一致，可作為市場敘事的輔助驗證。';
    if (relation === 'conflict') {
        event = 'AI 摘要方向與橫截面資料有落差，這張卡保留疑點而不延伸敘事。';
    } else if (relation === 'neutral') {
        event = 'AI 摘要提供方向感，但橫截面資料仍保留中性空間。';
    }

    return {
        id: 'ai-overlay',
        title: 'AI 摘要與技術面對照',
        event,
        anomaly: `AI 市場總覽偏向「${snapshot.aiDirection}」，橫截面技術結構偏向「${snapshot.technicalDirection}」。`,
        reasoning_chain: [
            'AI 市場總覽只拿來補充方向，不直接參與個股結論，也不允許自由點名股票。',
            `目前平均分數約 ${formatNum(snapshot.avgScore)}，放量樣本占比約 ${formatPct((snapshot.hotShare || 0) * 100)}，可用來檢查 AI 敘事是否有市場結構支撐。`,
            '當 AI 與橫截面一致時，情境可信度提高；若不一致，這張卡就保留分歧，不外推到買賣決策。'
        ],
        confidence: relation === 'aligned' && (snapshot.hotShare || 0) >= 0.08 ? 'high' : 'medium',
        relation_to_technical: relation,
        source_type: 'ai_market_overview+technical_snapshot',
        generated_at: selectGeneratedAt(aiReport?.generated_at, snapshot.generatedAt)
    };
}

function createActivationCard(snapshot, activationReport) {
    if (!activationReport || typeof activationReport !== 'object') {
        return null;
    }

    const passCount = toNum(activationReport?.decision?.pass_count) ?? 0;
    const totalCount = toNum(activationReport?.decision?.total_condition_count) ?? 0;
    const action = String(activationReport?.decision?.action || '未提供').trim() || '未提供';
    const trend = String(activationReport?.current_market_snapshot?.market_trend?.market_trend || '--');
    const concentration = String(activationReport?.current_market_snapshot?.capital_concentration?.label || '--');
    const volume = String(activationReport?.current_market_snapshot?.volume?.label || '--');
    const isAlignedDate = activationReport?.as_of_date === currentDate;

    let event = `steady_v5 目前狀態為「${action}」，市場環境仍有部分條件未齊。`;
    if (!isAlignedDate) {
        event = `steady_v5 最新狀態為「${action}」，但目前選擇日期與啟用判斷日期不同。`;
    }

    const relation = snapshot?.technicalDirection === '偏多' && trend === '上升'
        ? 'aligned'
        : 'neutral';

    return {
        id: 'regime-activation',
        title: 'steady_v5 啟用環境',
        event,
        anomaly: `大盤趨勢 ${trend}、資金集中度 ${concentration}、量能 ${volume}，共通過 ${passCount}/${totalCount || 3} 項條件。`,
        reasoning_chain: [
            '這張卡只描述市場環境是否接近 steady_v5 的適用條件，不把策略判斷直接翻成買賣建議。',
            '若啟用判斷日期與目前查看日期不同，這張卡就只作為背景補充，避免把不同日期的環境混在一起。',
            '這裡保留的是 regime 與 activation 層訊號，供後續題材推理做市場背景參考。'
        ],
        confidence: isAlignedDate ? 'medium' : 'low',
        relation_to_technical: relation,
        source_type: 'strategy_activation+regime_snapshot',
        generated_at: selectGeneratedAt(activationReport?.generated_at)
    };
}

function cardTextFragments(card) {
    return [
        card.id,
        card.title,
        card.event,
        card.anomaly,
        card.source_type,
        card.generated_at,
        ...(Array.isArray(card.reasoning_chain) ? card.reasoning_chain : [])
    ].map(item => String(item || ''));
}

function cardNarrativeFragments(card) {
    return [
        card.title,
        card.event,
        card.anomaly,
        ...(Array.isArray(card.reasoning_chain) ? card.reasoning_chain : [])
    ].map(item => String(item || ''));
}

function isValidCard(card, bannedTerms) {
    if (!card || typeof card !== 'object') return false;
    if (REQUIRED_CARD_FIELDS.some(field => !(field in card))) return false;

    for (const field of ['id', 'title', 'event', 'anomaly', 'source_type', 'generated_at']) {
        if (typeof card[field] !== 'string' || !card[field].trim()) {
            return false;
        }
    }

    if (!Array.isArray(card.reasoning_chain) || card.reasoning_chain.length < 3) return false;
    if (!card.reasoning_chain.every(item => typeof item === 'string' && item.trim())) return false;
    if (!VALID_CONFIDENCE.has(card.confidence)) return false;
    if (!VALID_RELATION.has(card.relation_to_technical)) return false;

    const texts = cardTextFragments(card);
    if (texts.some(text => PROHIBITED_TEXT_SNIPPETS.some(snippet => text.includes(snippet)))) {
        return false;
    }
    const narrativeTexts = cardNarrativeFragments(card);
    if (narrativeTexts.some(text => Array.from(bannedTerms).some(term => term && text.includes(term)))) {
        return false;
    }

    return true;
}

function normalizeCards(cards, bannedTerms, generatedAt) {
    const normalized = [];

    cards.forEach(card => {
        if (!card) return;
        normalized.push(isValidCard(card, bannedTerms)
            ? card
            : buildFallbackCard(normalized.length + 1, '原始情境卡內容不符合 v8.1 固定 schema，已改用保底卡。', generatedAt));
    });

    while (normalized.length < 3) {
        normalized.push(buildFallbackCard(normalized.length + 1, '可用市場資料不足，已補上保底卡。', generatedAt));
    }

    return normalized.slice(0, 5);
}

function renderCard(card) {
    const reasoningHTML = card.reasoning_chain
        .map(item => `<li class="reasoning-item">${esc(item)}</li>`)
        .join('');

    return `
        <article class="scenario-card" data-card-id="${esc(card.id)}">
            <div class="scenario-card-top">
                <div class="scenario-title-block">
                    <div class="scenario-id">${esc(card.id)}</div>
                    <div class="scenario-card-title">${esc(card.title)}</div>
                </div>
                <div class="scenario-card-meta">
                    <span class="meta-chip confidence-${esc(card.confidence)}">${esc(confidenceLabel(card.confidence))}</span>
                    <span class="meta-chip relation-${esc(card.relation_to_technical)}">${esc(relationLabel(card.relation_to_technical))}</span>
                </div>
            </div>
            <div class="scenario-grid">
                <div class="scenario-row">
                    <div class="scenario-label">event</div>
                    <div class="scenario-text">${esc(card.event)}</div>
                </div>
                <div class="scenario-row">
                    <div class="scenario-label">anomaly</div>
                    <div class="scenario-text">${esc(card.anomaly)}</div>
                </div>
                <div class="scenario-row">
                    <div class="scenario-label">reasoning_chain</div>
                    <div class="scenario-text"><ul class="reasoning-list">${reasoningHTML}</ul></div>
                </div>
                <div class="scenario-row">
                    <div class="scenario-label">source_type</div>
                    <div class="scenario-text">${esc(card.source_type)}</div>
                </div>
            </div>
            <div class="scenario-footer">
                <span>generated_at: ${esc(formatGeneratedAt(card.generated_at))}</span>
                <span>schema: ${esc(CONTEXT_SCHEMA_VERSION)}</span>
            </div>
        </article>`;
}

function renderCards(cards) {
    updateHeaderMeta(cards.length);
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
    showLoading(`載入 ${date} 市場情境卡中...`);

    try {
        const [fullResult, universeResult, aiResult, activationResult] = await Promise.allSettled([
            fetchJSON(`${BASE}/${date}.json`),
            fetchJSON(`${BASE}/${date}-universe.json`),
            fetchJSON(`${BASE}/${date}-ai.json`),
            fetchJSON(`${BASE}/strategy_activation.json`)
        ]);

        const fullReport = fullResult.status === 'fulfilled' ? fullResult.value : null;
        const universeReport = universeResult.status === 'fulfilled' ? universeResult.value : null;
        const aiReport = aiResult.status === 'fulfilled' ? aiResult.value : null;
        const activationReport = activationResult.status === 'fulfilled' ? activationResult.value : null;

        const snapshot = buildSnapshot(fullReport, universeReport, aiReport, activationReport);
        const generatedAt = selectGeneratedAt(
            universeReport?.generated_at,
            fullReport?.generated_at,
            aiReport?.generated_at,
            activationReport?.generated_at
        );
        const bannedTerms = collectBannedTerms(fullReport, universeReport);

        const cards = normalizeCards([
            createBreadthCard(snapshot),
            createSectorCard(snapshot),
            createVolumeCard(snapshot),
            createAIOverlayCard(snapshot, aiReport),
            createActivationCard(snapshot, activationReport)
        ], bannedTerms, generatedAt);

        const fallbackCount = cards.filter(card => card.source_type === 'ui_fallback').length;
        if (fallbackCount > 0) {
            showFallbackBanner(`本頁已自動補上 ${fallbackCount} 張保底卡，原因是部分日期缺少資料，或原始內容不符合 v8.1 固定 schema。`);
        } else {
            hideFallbackBanner();
        }

        renderCards(cards);
    } catch (error) {
        const fallbackCards = normalizeCards([], new Set(), new Date().toISOString());
        showFallbackBanner('資料載入失敗，已回退到保底卡。');
        renderCards(fallbackCards);
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
        updateHeaderMeta(3);
        showEmpty('情境頁初始化失敗，已停止載入。');
    }
}

init();