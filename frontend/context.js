'use strict';

const IS_GITHUB = window.location.hostname === 'paul800901.github.io';
const BASE = IS_GITHUB
    ? 'https://paul800901.github.io/kanpan-helper/reports'
    : '../reports';

const CONTEXT_SCHEMA_VERSION = 'v8.5-context-card';
const REQUIRED_CARD_FIELDS = [
    'id',
    'title',
    'event',
    'anomaly',
    'reasoning_chain',
    'keywords',
    'themes',
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
    '建議賣',
    '積極留意',
    '可留意',
    '布局'
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

function averageNumbers(values) {
    const nums = values.filter(value => Number.isFinite(value));
    if (!nums.length) return null;
    return nums.reduce((sum, value) => sum + value, 0) / nums.length;
}

function uniqueStrings(values) {
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

function formatStrengthScore(snapshot) {
    if (snapshot?.marketStrengthScore != null) {
        return `${formatNum(snapshot.marketStrengthScore, 0)} 分`;
    }
    if (snapshot?.avgScore != null) {
        return `${formatNum(snapshot.avgScore)} 分`;
    }
    return '--';
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

function parseMarketOverviewMeta(text) {
    const source = String(text || '');
    const scoreMatch = source.match(/(\d+(?:\.\d+)?)分/);
    const strongMatch = source.match(/強勢股\s*(\d+)\s*檔/);

    return {
        strengthScore: toNum(scoreMatch?.[1]),
        strongStockCount: toNum(strongMatch?.[1])
    };
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

    const summary = fullReport?.summary || {};
    const marketMeta = parseMarketOverviewMeta(summary.market_overview);
    const topSample = [...stocks]
        .sort((left, right) => (toNum(left?.rank) ?? 999) - (toNum(right?.rank) ?? 999))
        .slice(0, Math.min(10, stocks.length));
    const categoryCounter = buildCategoryCounter(topSample);
    const topCategoryEntries = getTopEntries(categoryCounter, 2);
    const topTwoTotal = topCategoryEntries.reduce((sum, [, count]) => sum + count, 0);
    const topTwoShare = topSample.length ? topTwoTotal / topSample.length : null;
    const topSampleAvgVolumeRatio = averageNumbers(topSample.map(stock => {
        return toNum(stock?.volume_ratio ?? stock?.indicators?.volume_ratio);
    }));

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
        topSampleAvgVolumeRatio,
        categoryCounter,
        topCategoryEntries,
        topCategoryLabels: topCategoryEntries.map(([label]) => label),
        topTwoShare,
        hotStocks,
        hotCategoryCounter,
        hotShare: stocks.length ? hotStocks.length / stocks.length : null,
        hotHighScoreCount,
        overlapCategories,
        technicalDirection,
        aiDirection: parseAIDirection(aiReport?.market_overview_ai),
        marketOverview: String(summary.market_overview || ''),
        marketStrengthScore: marketMeta.strengthScore,
        marketStrongCount: marketMeta.strongStockCount ?? (Array.isArray(summary.top_picks) ? summary.top_picks.length : null),
        watchlistCount: Array.isArray(summary.watchlist) ? summary.watchlist.length : 0,
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
        event: '目前可用市場資料不足，第三頁先保留弱訊號載體。',
        anomaly: reason,
        reasoning_chain: [
            '訊號 A：必要市場資料缺口過大，無法完成雙訊號以上的交叉判讀。',
            '訊號 B：為了維持固定 schema，系統先保留 v8.5 的載體欄位，不中斷後續頁面使用。',
            '交叉判讀：當前資訊不足以形成可驗證的弱訊號，所以只能回退到保底描述。',
            '限制：這個 fallback 不影響首頁、股票總覽與個股頁的既有功能。'
        ],
        keywords: ['資料不足', '固定載體'],
        themes: ['fallback'],
        confidence: 'low',
        relation_to_technical: 'neutral',
        source_type: 'ui_fallback',
        generated_at: generatedAt || new Date().toISOString()
    };
}

function createBreadthCard(snapshot) {
    if (!snapshot) {
        return buildFallbackCard(1, '缺少 full/universe 報表，無法建立盤面廣度推理卡。');
    }

    const breadthGap = snapshot.positiveCount - snapshot.cautiousCount;
    const scoreText = formatStrengthScore(snapshot);
    const strongCountText = snapshot.marketStrongCount != null ? `${snapshot.marketStrongCount} 檔` : '未提供';
    const aiAligned = snapshot.aiDirection !== '中性' && snapshot.aiDirection === snapshot.technicalDirection;
    let event = '市場廣度、總覽分數與 AI 方向同向，偏強結構具備可驗證的弱訊號。';

    if (breadthGap < 0) {
        event = aiAligned
            ? '市場廣度與 AI 方向同時轉保守，偏弱結構已形成可追蹤弱訊號。'
            : '市場廣度偏保守，但 AI 敘事沒有完全同步，偏弱訊號仍待驗證。';
    } else if (Math.abs(breadthGap) < 6) {
        event = '整體分數仍偏正面，但廣度優勢尚未拉開，市場只形成初步弱訊號。';
    } else if (!aiAligned) {
        event = snapshot.aiDirection === '中性'
            ? '盤面廣度偏強，但 AI 敘事仍偏保留，偏強訊號需要後續驗證。'
            : '盤面廣度與 AI 方向不同步，這層偏強訊號暫時只算待確認。';
    }

    let confidence = 'low';
    if (Math.abs(breadthGap) >= 10 && snapshot.avgScore != null && snapshot.avgScore >= 60) {
        confidence = aiAligned || snapshot.aiDirection === '中性' ? 'high' : 'medium';
    } else if (Math.abs(breadthGap) >= 4 && snapshot.avgScore != null) {
        confidence = 'medium';
    }

    return {
        id: 'breadth-balance',
        title: '盤面廣度與強弱分布',
        event,
        anomaly: `市場總覽約 ${scoreText}，強勢樣本約 ${strongCountText}，A/B ${snapshot.positiveCount} 檔、C/D ${snapshot.cautiousCount} 檔。`,
        reasoning_chain: [
            `訊號 A：市場總覽顯示平均強度約 ${scoreText}，強勢樣本約 ${strongCountText}，代表風險承擔沒有快速收縮。`,
            `訊號 B：A/B 比 C/D ${breadthGap >= 0 ? `多 ${breadthGap} 檔` : `少 ${Math.abs(breadthGap)} 檔`}，平均分數約 ${formatNum(snapshot.avgScore)}，盤面不是只靠少數極端樣本撐住。`,
            `交叉判讀：AI 方向目前為「${snapshot.aiDirection}」，${aiAligned ? '與橫截面結構同向，情緒端暫時有接到結構訊號。' : snapshot.aiDirection === '中性' ? '代表情緒端仍保留中性，這個弱訊號只完成一部分驗證。' : '與橫截面不同向，情緒端還沒有完全接球。'}`,
            '限制：這張卡只保留市場層推理，不延伸到任何股票與操作結論。'
        ],
        keywords: uniqueStrings(['市場廣度', breadthGap >= 0 ? '風險承擔' : '防守結構', `AI${snapshot.aiDirection}`]),
        themes: uniqueStrings(['市場廣度', '情緒校準']),
        confidence,
        relation_to_technical: snapshot.technicalDirection === '中性' ? 'neutral' : 'aligned',
        source_type: 'market_overview+score_distribution+ai_market_overview',
        generated_at: snapshot.generatedAt
    };
}

function createSectorCard(snapshot, activationReport) {
    if (!snapshot || !snapshot.topCategoryEntries.length) {
        return buildFallbackCard(2, '缺少類別集中度資料，無法建立主軸收斂推理卡。', snapshot?.generatedAt);
    }

    const capitalLabel = String(activationReport?.current_market_snapshot?.capital_concentration?.label || '未提供');
    const overlapText = snapshot.overlapCategories.length
        ? snapshot.overlapCategories.join('、')
        : '尚未與主軸明顯重疊';
    const topSummary = summarizeCounter(snapshot.categoryCounter);
    let event = '主軸集中與放量重疊同時出現，盤面開始形成可追蹤的弱主題。';

    if ((snapshot.topTwoShare || 0) < 0.45) {
        event = '前段類別仍偏分散，主題輪動尚未沉澱成穩定弱訊號。';
    } else if (!snapshot.overlapCategories.length) {
        event = '前段類別已有主軸，但放量訊號沒有同步跟上，主題仍在試圖成形。';
    } else if (capitalLabel !== '集中') {
        event = '前段主軸已有輪廓，但制度層仍把集中度視為可接受範圍，代表主題尚未完全鎖定。';
    }

    return {
        id: 'sector-concentration',
        title: '主軸集中度',
        event,
        anomaly: `前 ${snapshot.topSampleCount} 名樣本中，前兩大類別占比約 ${formatPct((snapshot.topTwoShare || 0) * 100)}，放量重疊類別為 ${overlapText}。`,
        reasoning_chain: [
            `訊號 A：前 ${snapshot.topSampleCount} 名樣本裡，主軸目前集中在 ${topSummary}，代表資金注意力開始收斂。`,
            `訊號 B：放量樣本與前段主軸重疊在 ${overlapText}，用來確認主題不是只有排名集中，還有量能呼應。`,
            `訊號 C：steady_v5 的資金集中度欄位目前標記為「${capitalLabel}」，制度層也把這個結構納入環境判讀。`,
            `${(snapshot.topTwoShare || 0) >= 0.45 && snapshot.overlapCategories.length ? '交叉判讀：類別集中與量能重疊同時存在，主題輪廓比較像可追蹤的弱訊號。' : '交叉判讀：集中度或量能其中一邊尚未到位，所以只能先視為題材輪動線索。'}`
        ],
        keywords: uniqueStrings(['主軸收斂', '量能共振', capitalLabel === '集中' ? '集中驗證' : '輪動延續']),
        themes: uniqueStrings(snapshot.topCategoryLabels.length ? snapshot.topCategoryLabels : ['市場主軸']),
        confidence: (snapshot.topTwoShare || 0) >= 0.6 && snapshot.overlapCategories.length ? 'high' : (snapshot.topTwoShare || 0) >= 0.45 ? 'medium' : 'low',
        relation_to_technical: (snapshot.topTwoShare || 0) >= 0.45 && snapshot.overlapCategories.length ? 'aligned' : 'neutral',
        source_type: 'sector_concentration+volume_anomaly+strategy_activation',
        generated_at: snapshot.generatedAt
    };
}

function createVolumeCard(snapshot, activationReport) {
    if (!snapshot) {
        return buildFallbackCard(3, '缺少量能資料，無法建立量能擴散推理卡。');
    }

    const volumeLabel = String(activationReport?.current_market_snapshot?.volume?.label || '未提供');
    const hotSummary = summarizeCounter(snapshot.hotCategoryCounter);
    const frontAvgVolumeText = snapshot.topSampleAvgVolumeRatio != null
        ? formatNum(snapshot.topSampleAvgVolumeRatio, 2)
        : '--';
    let event = '量能擴散與高分結構同步，市場注意力不是孤點放量。';

    if (!snapshot.hotStocks.length) {
        event = '量能尚未形成有效擴散，市場只剩局部觀察訊號。';
    } else if (volumeLabel !== '放量') {
        event = '局部放量已出現，但制度層未確認整體放量，弱訊號仍偏早。';
    } else if (snapshot.hotHighScoreCount < Math.max(1, Math.ceil(snapshot.hotStocks.length / 2))) {
        event = '有放量，但高分結構承接不足，訊號品質仍待確認。';
    }

    return {
        id: 'volume-focus',
        title: '量能異常與擴散',
        event,
        anomaly: `量比大於等於 1.5 的樣本共 ${snapshot.hotStocks.length} 檔，占全體約 ${formatPct((snapshot.hotShare || 0) * 100)}；前段平均量比約 ${frontAvgVolumeText}，制度量能標記為「${volumeLabel}」。`,
        reasoning_chain: [
            `訊號 A：放量樣本主要落在 ${hotSummary}，共 ${snapshot.hotStocks.length} 檔，占全體約 ${formatPct((snapshot.hotShare || 0) * 100)}。`,
            `訊號 B：放量樣本中有 ${snapshot.hotHighScoreCount} 檔同時位於 A/B 區，而整體 breadth 仍是 A/B ${snapshot.positiveCount} 對 C/D ${snapshot.cautiousCount}，代表量能不是只落在弱勢端。`,
            `訊號 C：steady_v5 的量能欄位標記為「${volumeLabel}」，前段平均量比約 ${frontAvgVolumeText}，可用來確認放量是否只是零星雜訊。`,
            `${snapshot.hotStocks.length >= 4 && snapshot.hotHighScoreCount >= 2 && volumeLabel === '放量' ? '交叉判讀：量能、廣度與制度量能同向，這層訊號比較像市場注意力已開始擴散。' : '交叉判讀：量能雖有變化，但廣度或制度層尚未完全接手，所以目前只能算弱訊號。'}`
        ],
        keywords: uniqueStrings(['量能擴散', '高分共振', volumeLabel === '放量' ? '放量驗證' : '量能保留']),
        themes: uniqueStrings(snapshot.overlapCategories.length
            ? [...snapshot.overlapCategories.slice(0, 2), '量能驗證']
            : [...snapshot.topCategoryLabels.slice(0, 1), '量能驗證']),
        confidence: snapshot.hotStocks.length >= 4 && snapshot.hotHighScoreCount >= 2 && volumeLabel === '放量'
            ? 'high'
            : snapshot.hotStocks.length >= 2
                ? 'medium'
                : 'low',
        relation_to_technical: volumeLabel === '放量' && snapshot.hotHighScoreCount >= Math.max(1, Math.floor(snapshot.hotStocks.length / 2))
            ? 'aligned'
            : 'neutral',
        source_type: 'volume_anomaly+score_distribution+strategy_activation',
        generated_at: snapshot.generatedAt
    };
}

function createAIOverlayCard(snapshot, aiReport, activationReport) {
    if (!snapshot || !String(aiReport?.market_overview_ai || '').trim()) {
        return null;
    }

    const relation = relationTone(snapshot.aiDirection, snapshot.technicalDirection);
    const passCount = toNum(activationReport?.decision?.pass_count) ?? 0;
    const totalCount = toNum(activationReport?.decision?.total_condition_count) ?? 3;
    const action = String(activationReport?.decision?.action || '未提供').trim() || '未提供';
    let event = 'AI 敘事與橫截面、制度訊號大致同向，可作為市場情緒的弱驗證。';

    if (relation === 'conflict') {
        event = 'AI 敘事方向與橫截面、制度訊號有落差，這張卡只保留分歧。';
    } else if (relation === 'neutral' || passCount < 2) {
        event = 'AI 敘事提供方向，但橫截面或制度訊號仍只做到部分驗證。';
    }

    return {
        id: 'ai-overlay',
        title: 'AI 摘要與技術面對照',
        event,
        anomaly: `AI 方向「${snapshot.aiDirection}」，技術結構「${snapshot.technicalDirection}」，steady_v5 通過 ${passCount}/${totalCount} 項。`,
        reasoning_chain: [
            `訊號 A：AI 只提供市場方向，這裡先把它壓縮成「${snapshot.aiDirection}」，不帶入任何股票敘事。`,
            `訊號 B：橫截面目前平均分數約 ${formatNum(snapshot.avgScore)}，放量樣本占比約 ${formatPct((snapshot.hotShare || 0) * 100)}，用來檢查敘事是否有結構支撐。`,
            `訊號 C：steady_v5 目前通過 ${passCount}/${totalCount} 項條件，狀態為「${action}」，可用來判斷制度面是否同意這個方向。`,
            `${relation === 'aligned' ? '交叉判讀：AI、橫截面與制度訊號大致同向，這層敘事比較像可驗證的弱訊號。' : relation === 'neutral' ? '交叉判讀：AI 有方向，但橫截面或制度面還沒完全跟上，所以只能當補充線索。' : '交叉判讀：AI 與橫截面不同向，代表情緒端和市場結構存在落差。'}`
        ],
        keywords: uniqueStrings(['AI對照', `AI${snapshot.aiDirection}`, `制度${action}`]),
        themes: uniqueStrings(['情緒校準', '敘事驗證']),
        confidence: relation === 'aligned' && passCount >= 2 && (snapshot.hotShare || 0) >= 0.08
            ? 'high'
            : relation === 'conflict'
                ? 'low'
                : 'medium',
        relation_to_technical: relation,
        source_type: 'ai_market_overview+score_distribution+volume_anomaly+strategy_activation',
        generated_at: selectGeneratedAt(aiReport?.generated_at, snapshot.generatedAt)
    };
}

function createActivationCard(snapshot, activationReport) {
    if (!activationReport || typeof activationReport !== 'object') {
        return null;
    }

    const passCount = toNum(activationReport?.decision?.pass_count) ?? 0;
    const totalCount = toNum(activationReport?.decision?.total_condition_count) ?? 3;
    const action = String(activationReport?.decision?.action || '未提供').trim() || '未提供';
    const trend = String(activationReport?.current_market_snapshot?.market_trend?.market_trend || '--');
    const concentration = String(activationReport?.current_market_snapshot?.capital_concentration?.label || '--');
    const volume = String(activationReport?.current_market_snapshot?.volume?.label || '--');
    const failedConditions = Array.isArray(activationReport?.decision?.failed_conditions)
        ? activationReport.decision.failed_conditions.join('、')
        : '無';
    const isAlignedDate = activationReport?.as_of_date === currentDate;
    const breadthText = snapshot
        ? `A/B ${snapshot.positiveCount} 對 C/D ${snapshot.cautiousCount}`
        : 'breadth 未提供';
    const concentrationShareText = snapshot?.topTwoShare != null
        ? formatPct(snapshot.topTwoShare * 100)
        : '--';
    let event = 'steady_v5 條件不足，制度層與目前市場結構仍有缺口。';

    if (!isAlignedDate) {
        event = 'steady_v5 最新環境判讀可作背景座標，但不能直接覆蓋所選日期。';
    } else if (passCount === totalCount) {
        event = 'steady_v5 適用環境完整，制度層與市場結構同向。';
    } else if (passCount >= 2) {
        event = 'steady_v5 只通過部分條件，顯示環境接近但還不是完整型態。';
    }

    const relation = trend === '上升' && snapshot?.technicalDirection === '偏多'
        ? 'aligned'
        : trend === '上升' && snapshot?.technicalDirection === '偏保守'
            ? 'conflict'
            : 'neutral';

    return {
        id: 'regime-activation',
        title: 'steady_v5 啟用環境',
        event,
        anomaly: `大盤趨勢 ${trend}、資金集中度 ${concentration}、量能 ${volume}；${breadthText}，前兩大類別占比約 ${concentrationShareText}。`,
        reasoning_chain: [
            `訊號 A：steady_v5 目前通過 ${passCount}/${totalCount} 項條件，未通過的主要缺口是 ${failedConditions || '無'}。`,
            `訊號 B：同一批市場橫截面資料裡，平均分數約 ${formatNum(snapshot?.avgScore)}，${breadthText}，代表風險承擔是否還撐得住。`,
            `訊號 C：前兩大類別占比約 ${concentrationShareText}，而量能標記為「${volume}」，可用來判斷是分散輪動還是集中衝刺。`,
            isAlignedDate
                ? '同日校準：這張卡與目前日期對齊，所以可以拿來當制度背景。'
                : `日期限制：啟用判斷日期為 ${activationReport.as_of_date}，與目前查看日期不同，只能當背景參考。`,
            '限制：這張卡只保留制度與市場結構的交叉判讀，不轉成股票清單或操作指令。'
        ],
        keywords: uniqueStrings(['制度門檻', '制度環境', concentration === '集中' ? '集中缺口' : '分散輪動']),
        themes: uniqueStrings(['制度環境', '策略適配']),
        confidence: isAlignedDate
            ? (passCount === totalCount ? 'high' : passCount >= 2 ? 'medium' : 'low')
            : 'low',
        relation_to_technical: relation,
        source_type: 'strategy_activation+score_distribution+sector_concentration+volume_anomaly',
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
        ...(Array.isArray(card.reasoning_chain) ? card.reasoning_chain : []),
        ...(Array.isArray(card.keywords) ? card.keywords : []),
        ...(Array.isArray(card.themes) ? card.themes : [])
    ].map(item => String(item || ''));
}

function cardNarrativeFragments(card) {
    return [
        card.title,
        card.event,
        card.anomaly,
        ...(Array.isArray(card.reasoning_chain) ? card.reasoning_chain : []),
        ...(Array.isArray(card.keywords) ? card.keywords : []),
        ...(Array.isArray(card.themes) ? card.themes : [])
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

    if (!Array.isArray(card.reasoning_chain) || card.reasoning_chain.length < 4) return false;
    if (!card.reasoning_chain.every(item => typeof item === 'string' && item.trim())) return false;
    if (!Array.isArray(card.keywords) || card.keywords.length < 2) return false;
    if (!card.keywords.every(item => typeof item === 'string' && item.trim())) return false;
    if (!Array.isArray(card.themes) || card.themes.length < 1) return false;
    if (!card.themes.every(item => typeof item === 'string' && item.trim())) return false;
    if (!VALID_CONFIDENCE.has(card.confidence)) return false;
    if (!VALID_RELATION.has(card.relation_to_technical)) return false;
    if (card.source_type !== 'ui_fallback' && card.source_type.split('+').length < 2) return false;

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
            : buildFallbackCard(normalized.length + 1, '原始情境卡內容不符合 v8.5 固定 schema，已改用保底卡。', generatedAt));
    });

    while (normalized.length < 3) {
        normalized.push(buildFallbackCard(normalized.length + 1, '可用市場資料不足，已補上保底卡。', generatedAt));
    }

    return normalized.slice(0, 5);
}

function renderChipList(items, chipClass) {
    return `<div class="scenario-chip-list">${items.map(item => {
        return `<span class="signal-chip ${chipClass}">${esc(item)}</span>`;
    }).join('')}</div>`;
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
                    <div class="scenario-label">keywords</div>
                    <div class="scenario-text">${renderChipList(card.keywords, 'keyword-chip')}</div>
                </div>
                <div class="scenario-row">
                    <div class="scenario-label">themes</div>
                    <div class="scenario-text">${renderChipList(card.themes, 'theme-chip')}</div>
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
            createSectorCard(snapshot, activationReport),
            createVolumeCard(snapshot, activationReport),
            createAIOverlayCard(snapshot, aiReport, activationReport),
            createActivationCard(snapshot, activationReport)
        ], bannedTerms, generatedAt);

        const fallbackCount = cards.filter(card => card.source_type === 'ui_fallback').length;
        if (fallbackCount > 0) {
            showFallbackBanner(`本頁已自動補上 ${fallbackCount} 張保底卡，原因是部分日期缺少資料，或原始內容不符合 v8.5 固定 schema。`);
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