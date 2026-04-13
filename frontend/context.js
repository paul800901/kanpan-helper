'use strict';

const IS_GITHUB = window.location.hostname === 'paul800901.github.io';
const BASE = IS_GITHUB
    ? 'https://paul800901.github.io/kanpan-helper/reports'
    : '../reports';

const VALID_CONFIDENCE = new Set(['low', 'medium', 'high']);
const VALID_RELATION = new Set(['aligned', 'conflict', 'neutral']);
const REQUIRED_CARD_FIELDS = [
    'id',
    'title',
    'event',
    'anomaly',
    'keywords',
    'themes',
    'trace',
    'candidate_stocks',
    'reasoning_chain',
    'confidence',
    'relation_to_technical',
    'source_type',
    'generated_at'
];

const REQUIRED_TRACE_FIELDS = ['event', 'keywords', 'themes'];
const REQUIRED_CANDIDATE_FIELDS = ['symbol', 'from_theme', 'trace_event', 'reason'];

let indexData = null;
let currentDate = null;
let requestVersion = String(Date.now());
let currentStrategyChoice = null;

function buildFreshUrl(url, version = requestVersion) {
    const target = new URL(url, window.location.href);
    target.searchParams.set('_ts', version);
    return target.toString();
}

function esc(text) {
    if (text == null) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
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

function getZoneFlags(stock, summary = getDecisionSummary(stock)) {
    const indicators = stock?.indicators || {};
    const score = toNum(stock?.score);
    const close = toNum(indicators.close);
    const ma5 = toNum(indicators.ma5);
    const ma20 = toNum(indicators.ma20);
    const advice = summary?.advice || '先觀望';
    const isWeakBelowMa20 = score != null && score < 60 && close != null && ma20 != null && close < ma20;
    const pilotLow = ma5 != null ? ma5 * 0.98 : null;
    const pilotHigh = ma5 != null ? ma5 * 1.02 : null;
    const inPilotZone = close != null && pilotLow != null && pilotHigh != null && close >= pilotLow && close <= pilotHigh;

    let inObserveZone = false;
    if (!isAvoidAdvice(advice) && close != null && ma5 != null && close < ma5) {
        inObserveZone = Math.abs(close - ma5) / Math.abs(ma5) <= 0.01;
    }

    return {
        inPilotZone,
        inObserveZone,
        isWeakBlocked: isWeakBelowMa20
    };
}

function buildTechnicalMap(fullReport) {
    if (!fullReport || !Array.isArray(fullReport.stocks)) {
        return new Map();
    }

    return new Map(fullReport.stocks.map(stock => {
        const summary = getDecisionSummary(stock);
        const indicators = stock?.indicators || {};
        return [stock.symbol, {
            symbol: stock.symbol,
            name: stock.name || stock.symbol,
            summary,
            zoneFlags: getZoneFlags(stock, summary),
            indicators: {
                close: toNum(indicators.close),
                ma5: toNum(indicators.ma5),
                ma20: toNum(indicators.ma20),
                k: toNum(indicators.k),
                volumeRatio: toNum(indicators.volume_ratio)
            },
            raw: stock
        }];
    }));
}

function formatPercentValue(value) {
    if (value == null) return '--';
    return `${Number(value).toLocaleString('zh-TW', {
        minimumFractionDigits: 0,
        maximumFractionDigits: 2
    })}%`;
}

function formatGapThreshold(value) {
    if (value == null) return '--';
    return `${(Number(value) * 100).toLocaleString('zh-TW', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    })}%`;
}

function validateStrategyAnalysisReport(report) {
    if (!report || typeof report !== 'object') return false;
    if (report.report_version !== 'v16-strategy-analysis') return false;
    if (!report.strategies || typeof report.strategies !== 'object') return false;
    return Boolean(report.strategies.sniper && report.strategies.steady);
}

function validateSignalDensityReport(report) {
    if (!report || typeof report !== 'object') return false;
    if (report.report_version !== 'v17-signal-density-analysis') return false;
    return Array.isArray(report.daily_hit_counts);
}

function showLoading(text = '載入情境卡中...') {
    const loading = document.getElementById('loadingState');
    loading.textContent = text;
    loading.style.display = 'block';
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('candidateOverview').style.display = 'none';
    document.getElementById('cardList').style.display = 'none';
}

function showEmpty(text) {
    document.getElementById('loadingState').style.display = 'none';
    const empty = document.getElementById('emptyState');
    empty.textContent = text;
    empty.style.display = 'block';
    document.getElementById('candidateOverview').style.display = 'none';
    document.getElementById('cardList').style.display = 'none';
}

function updateHeaderMeta(reportVersion, count) {
    document.getElementById('schemaChip').textContent = reportVersion ? `schema ${reportVersion}` : 'schema --';
    document.getElementById('countChip').textContent = `${count} 張卡`;
}

function fetchJSON(url) {
    return fetch(buildFreshUrl(url), { cache: 'no-store' }).then(async response => {
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
    });
}

function validateContextCard(card) {
    if (!card || typeof card !== 'object') return false;
    for (const field of REQUIRED_CARD_FIELDS) {
        if (!(field in card)) return false;
    }

    if (!Array.isArray(card.reasoning_chain) || card.reasoning_chain.length < 3 || card.reasoning_chain.length > 4) {
        return false;
    }
    if (!Array.isArray(card.keywords) || card.keywords.length < 2 || card.keywords.length > 4) return false;
    if (!Array.isArray(card.themes) || card.themes.length < 2 || card.themes.length > 4) return false;
    if (!VALID_CONFIDENCE.has(card.confidence)) return false;
    if (!VALID_RELATION.has(card.relation_to_technical)) return false;

    const textFields = ['id', 'title', 'event', 'anomaly', 'source_type', 'generated_at'];
    for (const field of textFields) {
        if (typeof card[field] !== 'string' || !card[field].trim()) {
            return false;
        }
    }

    if (!card.keywords.every(item => typeof item === 'string' && item.trim())) return false;
    if (!card.themes.every(item => typeof item === 'string' && item.trim())) return false;
    return card.reasoning_chain.every(item => typeof item === 'string' && item.trim());
}

function validateTraceCatalog(catalog) {
    if (!catalog || typeof catalog !== 'object') return false;
    if (typeof catalog.keyword_dictionary_version !== 'string' || !catalog.keyword_dictionary_version) return false;
    if (typeof catalog.theme_taxonomy_version !== 'string' || !catalog.theme_taxonomy_version) return false;
    if (typeof catalog.event_trace_version !== 'string' || !catalog.event_trace_version) return false;
    if (!catalog.keyword_dictionary || typeof catalog.keyword_dictionary !== 'object') return false;
    if (!catalog.theme_taxonomy || typeof catalog.theme_taxonomy !== 'object') return false;
    if (!catalog.event_trace_map || typeof catalog.event_trace_map !== 'object') return false;
    return true;
}

function validateStockMappingCatalog(catalog) {
    if (!catalog || typeof catalog !== 'object') return false;
    if (catalog.theme_stock_mapping_version !== 'context-theme-stocks-v1') return false;
    if (!catalog.theme_stock_rules || typeof catalog.theme_stock_rules !== 'object') return false;
    if (!catalog.themes_to_stocks || typeof catalog.themes_to_stocks !== 'object') return false;
    return true;
}

function validateTrace(card, catalog) {
    const trace = card.trace;
    if (!trace || typeof trace !== 'object') return false;
    for (const field of REQUIRED_TRACE_FIELDS) {
        if (!(field in trace)) return false;
    }
    if (typeof trace.event !== 'string' || !trace.event.trim()) return false;
    if (!(trace.event in catalog.event_trace_map)) return false;
    if (!Array.isArray(trace.keywords) || trace.keywords.length < 2 || trace.keywords.length > 4) return false;
    if (!Array.isArray(trace.themes) || trace.themes.length < 2 || trace.themes.length > 4) return false;
    if (!trace.keywords.every(id => typeof id === 'string' && catalog.keyword_dictionary[id])) return false;
    if (!trace.themes.every(id => typeof id === 'string' && catalog.theme_taxonomy[id])) return false;

    const expectedKeywords = trace.keywords.map(id => catalog.keyword_dictionary[id]);
    const expectedThemes = trace.themes.map(id => catalog.theme_taxonomy[id].label);
    if (JSON.stringify(expectedKeywords) !== JSON.stringify(card.keywords)) return false;
    if (JSON.stringify(expectedThemes) !== JSON.stringify(card.themes)) return false;
    return true;
}

function validateCandidateStocks(card, report) {
    if (!Array.isArray(card.candidate_stocks)) return false;
    return card.candidate_stocks.every(candidate => {
        if (!candidate || typeof candidate !== 'object') return false;
        for (const field of REQUIRED_CANDIDATE_FIELDS) {
            if (typeof candidate[field] !== 'string' || !candidate[field].trim()) return false;
        }
        if (candidate.trace_event !== card.trace.event) return false;
        if (!card.trace.themes.includes(candidate.from_theme)) return false;
        const mapped = report.stock_mapping_catalog.themes_to_stocks[candidate.from_theme];
        if (!Array.isArray(mapped) || !mapped.includes(candidate.symbol)) return false;
        return true;
    });
}

function validateContextReport(report) {
    if (!report || typeof report !== 'object') return false;
    if (report.report_version !== 'v9-context') return false;
    if (!validateTraceCatalog(report.trace_catalog)) return false;
    if (!validateStockMappingCatalog(report.stock_mapping_catalog)) return false;
    if (!Array.isArray(report.cards) || report.cards.length === 0) return false;
    return report.cards.every(card => (
        validateContextCard(card)
        && validateTrace(card, report.trace_catalog)
        && validateCandidateStocks(card, report)
    ));
}

function createFallbackCard(reason) {
    const now = new Date().toISOString();
    return {
        id: 'ui-fallback',
        title: '情境卡暫時不可用',
        event: '本頁仍可正常開啟，但目前沒有可用的情境卡資料。',
        anomaly: reason,
        keywords: ['資料不足', '頁面保底'],
        themes: ['系統保底', '情境待補'],
        trace: {
            event: 'context_unavailable',
            keywords: ['data_shortage', 'ui_fallback'],
            themes: ['system_fallback', 'trace_pending']
        },
        candidate_stocks: [],
        reasoning_chain: [
            '目前無法取得符合 v9 固定 schema、trace chain 與股票映射的資料。',
            '目前只回退到頁面保底訊息，不影響首頁與個股頁。',
            '情境卡資料補齊後，頁面會自動恢復正常顯示。'
        ],
        confidence: 'low',
        relation_to_technical: 'neutral',
        source_type: 'ui_fallback',
        generated_at: now
    };
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

function formatGeneratedAt(text) {
    if (!text) return '--';
    return text.replace('T', ' ').replace(/\+08:00$/, '');
}

function renderTagList(items, className) {
    return items.map(item => `<span class="tag-chip ${className}">${esc(item)}</span>`).join('');
}

function renderTraceList(items) {
    return items.map(item => `<span class="trace-chip">${esc(item)}</span>`).join('');
}

function eventLabel(eventId, eventMap) {
    return eventMap[eventId] || eventId;
}

function themeLabel(themeId, catalog) {
    return catalog?.theme_taxonomy?.[themeId]?.label || themeId;
}

function getAdviceToneClass(advice) {
    if (advice === '強勢續看' || advice === '可偏多觀察' || advice === '可留意') {
        return 'positive';
    }
    if (advice === '先觀望') {
        return 'watch';
    }
    return 'avoid';
}

function getZonePriority(zoneFlags) {
    if (zoneFlags?.inPilotZone) return 2;
    if (zoneFlags?.inObserveZone) return 1;
    return 0;
}

function getZonePriorityLabel(zoneFlags) {
    if (zoneFlags?.inPilotZone) return '試單區優先';
    if (zoneFlags?.inObserveZone) return '觀察區次優先';
    return '區間外';
}

function formatPriorityRank(rank) {
    return String(rank).padStart(2, '0');
}

function getSortedUniverseDates() {
    if (!Array.isArray(indexData?.reports)) {
        return [];
    }

    return indexData.reports
        .filter(report => report?.has_universe === true && typeof report.date === 'string')
        .map(report => report.date)
        .sort();
}

function getPreviousUniverseDate(date) {
    const dates = getSortedUniverseDates();
    const index = dates.indexOf(date);
    if (index <= 0) {
        return null;
    }
    return dates[index - 1];
}

function isStrategyLowPosition(technical, lowerThirdCutoff) {
    const close = toNum(technical?.indicators?.close);
    const ma20 = toNum(technical?.indicators?.ma20);
    const gap = getMa20Diff(close, ma20);
    return gap != null && lowerThirdCutoff != null && gap <= lowerThirdCutoff;
}

function isStrategyJustBreakMa20(currentTechnical, previousTechnical) {
    const previousClose = toNum(previousTechnical?.indicators?.close);
    const previousMa20 = toNum(previousTechnical?.indicators?.ma20);
    const currentClose = toNum(currentTechnical?.indicators?.close);
    const currentMa20 = toNum(currentTechnical?.indicators?.ma20);

    return previousClose != null
        && previousMa20 != null
        && previousMa20 !== 0
        && currentClose != null
        && currentMa20 != null
        && currentMa20 !== 0
        && previousClose >= previousMa20
        && currentClose < currentMa20;
}

function isStrategyLowKTurnUp(currentTechnical, previousTechnical) {
    const previousK = toNum(previousTechnical?.indicators?.k);
    const currentK = toNum(currentTechnical?.indicators?.k);
    return previousK != null
        && currentK != null
        && currentK < 30
        && currentK > previousK;
}

function buildStrategyMatchMap(overview, report) {
    const matches = {
        sniper: [],
        steady: []
    };
    const strategyAnalysis = report?.strategy_analysis;
    const technicalMap = report?.technical_map instanceof Map ? report.technical_map : new Map();
    const previousTechnicalMap = report?.previous_technical_map instanceof Map ? report.previous_technical_map : new Map();
    const lowerThirdCutoff = toNum(strategyAnalysis?.low_position_definition?.lower_third_cutoff);

    if (!strategyAnalysis || lowerThirdCutoff == null || !overview?.sortedItems?.length) {
        return matches;
    }

    overview.sortedItems.forEach(item => {
        const currentTechnical = technicalMap.get(item.symbol);
        const previousTechnical = previousTechnicalMap.get(item.symbol);
        if (!currentTechnical) {
            return;
        }

        const isLowPosition = isStrategyLowPosition(currentTechnical, lowerThirdCutoff);
        if (!isLowPosition) {
            return;
        }

        const baseMatch = {
            ...item,
            name: currentTechnical.name || item.symbol,
            explanation: buildPriorityExplanation(item, currentTechnical)
        };

        if (isStrategyJustBreakMa20(currentTechnical, previousTechnical)) {
            matches.sniper.push({
                ...baseMatch,
                reasons: ['剛跌破 MA20', '低位因子']
            });
        }

        if (isStrategyLowKTurnUp(currentTechnical, previousTechnical)) {
            matches.steady.push({
                ...baseMatch,
                reasons: ['KD 低檔翻揚', '低位因子']
            });
        }
    });

    return matches;
}

function getStrategyRoleLabels(strategyAnalysis) {
    return {
        highReturn: strategyAnalysis?.style_choice?.high_return?.strategy || null,
        steady: strategyAnalysis?.style_choice?.steady?.strategy || null
    };
}

function renderStrategyMatchList(matches) {
    if (!matches.length) {
        return '<div class="strategy-empty">目前候選清單中，暫時沒有符合這條策略的標的。</div>';
    }

    return `<div class="strategy-match-list">${matches.map(match => `
        <div class="strategy-match-item">
            <div class="strategy-match-top">
                <div class="strategy-match-symbol-line">
                    <span class="strategy-match-rank">#${formatPriorityRank(match.priorityRank)}</span>
                    <span class="strategy-match-symbol">${esc(match.symbol)}</span>
                    <span class="strategy-match-name">${esc(match.name)}</span>
                </div>
                <span class="strategy-match-count">${match.events.length} 個情境</span>
            </div>
            <div class="strategy-match-note">策略命中：${esc(match.reasons.join(' + '))}</div>
            <div class="strategy-match-meta">既有排序依據：${esc(match.explanation)}</div>
        </div>
    `).join('')}</div>`;
}

function getSignalDaySummary(signalDensity) {
    if (!signalDensity || !Array.isArray(signalDensity.daily_hit_counts)) {
        return null;
    }

    return signalDensity.daily_hit_counts.find(item => item?.date === currentDate) || null;
}

function getSignalWeekSummary(signalDensity) {
    if (!signalDensity || !Array.isArray(signalDensity.weekly_hit_counts) || !currentDate) {
        return null;
    }

    return signalDensity.weekly_hit_counts.find(item => (
        typeof item?.start_date === 'string'
        && typeof item?.end_date === 'string'
        && currentDate >= item.start_date
        && currentDate <= item.end_date
    )) || null;
}

function renderSignalDensityDiagnostic(strategyName, report) {
    const signalDensity = report?.signal_density;
    const daySummary = getSignalDaySummary(signalDensity);
    if (!daySummary) {
        return '';
    }

    const weekSummary = getSignalWeekSummary(signalDensity);
    const strategyHitsToday = Number(daySummary?.strategy_hits?.[strategyName] || 0);
    const strategyHitsThisWeek = Number(weekSummary?.strategy_hits?.[strategyName] || 0);
    const blocker = daySummary?.strategy_blockers?.[strategyName] || null;
    const todayStrictest = daySummary?.strictest_condition || null;
    const overallStrictest = signalDensity?.overall_condition_density?.strictest_condition || null;
    const totalCandidates = Number(daySummary?.candidate_count || 0);

    const todayStrictestText = todayStrictest
        ? `${todayStrictest.label} ${todayStrictest.pass_count}/${totalCandidates}`
        : '--';
    const strategyBlockerText = blocker?.strictest_condition
        ? `${blocker.strictest_condition.label} ${blocker.strictest_condition.pass_count}/${totalCandidates}`
        : '--';
    const overallStrictestText = overallStrictest
        ? `${overallStrictest.label} ${formatPercentValue(overallStrictest.pass_rate_pct)}`
        : '--';

    return `
        <div class="strategy-density-shell">
            <div class="strategy-density-title">v17 訊號密度診斷</div>
            <div class="strategy-density-grid">
                <div class="strategy-density-item">
                    <div class="strategy-density-label">今日命中</div>
                    <div class="strategy-density-value">${esc(String(strategyHitsToday))}</div>
                </div>
                <div class="strategy-density-item">
                    <div class="strategy-density-label">本週命中</div>
                    <div class="strategy-density-value">${esc(String(strategyHitsThisWeek))}</div>
                </div>
                <div class="strategy-density-item">
                    <div class="strategy-density-label">今日最嚴</div>
                    <div class="strategy-density-value strategy-density-value-sm">${esc(todayStrictestText)}</div>
                </div>
                <div class="strategy-density-item">
                    <div class="strategy-density-label">本策略卡點</div>
                    <div class="strategy-density-value strategy-density-value-sm">${esc(strategyBlockerText)}</div>
                </div>
            </div>
            <div class="strategy-density-note">${esc(daySummary?.zero_hit_diagnosis?.summary || '')}</div>
            <div class="strategy-density-note">${esc(blocker?.summary || '')}</div>
            <div class="strategy-density-foot">歷史最嚴條件：${esc(overallStrictestText)}</div>
        </div>
    `;
}

function renderStrategyFocusPanel(strategyName, strategy, matches, report) {
    const previousUniverseDate = report?.previous_universe_date;
    const lowerThirdCutoff = toNum(report?.strategy_analysis?.low_position_definition?.lower_third_cutoff);
    const previousNote = previousUniverseDate
        ? `當前歸屬判定會參考 ${previousUniverseDate} 與 ${currentDate} 兩天的技術資料。`
        : '目前缺少前一個交易日 universe，當前歸屬僅能顯示歷史統計差異。';

    return `
        <div class="strategy-focus-head">
            <div>
                <div class="strategy-focus-title">已選風格：${esc(strategy.label)}</div>
                <div class="strategy-focus-meta">${esc(strategy.selection_hint)}</div>
            </div>
            <div class="strategy-focus-side">低位門檻 ${esc(formatGapThreshold(lowerThirdCutoff))}</div>
        </div>
        <div class="strategy-focus-caption">${esc(previousNote)}</div>
        ${renderStrategyMatchList(matches)}
        ${renderSignalDensityDiagnostic(strategyName, report)}
    `;
}

function renderStrategySection(overview, report) {
    const strategyAnalysis = report?.strategy_analysis;
    if (!strategyAnalysis || !strategyAnalysis.strategies) {
        return '';
    }

    const strategies = strategyAnalysis.strategies;
    const strategyNames = Array.isArray(strategyAnalysis.strategy_names)
        ? strategyAnalysis.strategy_names.filter(name => strategies[name])
        : Object.keys(strategies);
    if (!strategyNames.length) {
        return '';
    }

    const matchMap = buildStrategyMatchMap(overview, report);
    const roleLabels = getStrategyRoleLabels(strategyAnalysis);
    const selectedKey = strategies[currentStrategyChoice]
        ? currentStrategyChoice
        : roleLabels.highReturn || strategyNames[0];
    currentStrategyChoice = selectedKey;

    const cardsHTML = strategyNames.map(strategyName => {
        const strategy = strategies[strategyName];
        const isSelected = strategyName === selectedKey;
        const currentMatchCount = (matchMap[strategyName] || []).length;
        const badges = [];
        if (roleLabels.highReturn === strategyName) {
            badges.push('<span class="strategy-role-chip strategy-role-return">高報酬代表</span>');
        }
        if (roleLabels.steady === strategyName) {
            badges.push('<span class="strategy-role-chip strategy-role-steady">穩定代表</span>');
        }

        return `
            <button type="button" class="strategy-card${isSelected ? ' active' : ''}" data-strategy-choice="${esc(strategyName)}">
                <div class="strategy-card-top">
                    <div>
                        <div class="strategy-title-line">
                            <span class="strategy-title">${esc(strategy.label)}</span>
                            <span class="strategy-style-chip">${esc(strategy.style_focus)}</span>
                        </div>
                        <div class="strategy-card-desc">${esc(strategy.description)}</div>
                    </div>
                    <div class="strategy-role-row">${badges.join('')}</div>
                </div>
                <div class="strategy-metric-grid">
                    <div class="strategy-metric">
                        <div class="strategy-metric-label">平均報酬</div>
                        <div class="strategy-metric-value">${esc(formatPercentValue(strategy.avg_return_pct))}</div>
                    </div>
                    <div class="strategy-metric">
                        <div class="strategy-metric-label">勝率</div>
                        <div class="strategy-metric-value">${esc(formatPercentValue(strategy.win_rate_pct))}</div>
                    </div>
                    <div class="strategy-metric">
                        <div class="strategy-metric-label">樣本數</div>
                        <div class="strategy-metric-value">${esc(String(strategy.sample_count ?? 0))}</div>
                    </div>
                </div>
                <div class="strategy-card-note">${esc(strategy.selection_hint)}</div>
                <div class="strategy-card-current">目前候選符合 ${esc(String(currentMatchCount))} 檔</div>
            </button>`;
    }).join('');

    return `
        <section class="strategy-section" id="strategySection">
            <div class="strategy-section-head">
                <div class="strategy-section-title">策略視角</div>
                <div class="strategy-section-meta">這裡只把候選拆成「高報酬」與「穩定」兩種風格供你選擇；下方 v10.5 優先清單排序完全不變。</div>
            </div>
            <div class="strategy-card-grid">${cardsHTML}</div>
            <div class="strategy-focus-shell" id="strategyFocusShell">${renderStrategyFocusPanel(selectedKey, strategies[selectedKey], matchMap[selectedKey] || [], report)}</div>
        </section>`;
}

function bindStrategySelector(overview, report) {
    const section = document.getElementById('strategySection');
    const focusShell = document.getElementById('strategyFocusShell');
    if (!section || !focusShell || !report?.strategy_analysis?.strategies) {
        return;
    }

    const matchMap = buildStrategyMatchMap(overview, report);
    const strategies = report.strategy_analysis.strategies;

    section.querySelectorAll('[data-strategy-choice]').forEach(button => {
        button.addEventListener('click', () => {
            const strategyName = button.getAttribute('data-strategy-choice');
            if (!strategies[strategyName]) {
                return;
            }
            currentStrategyChoice = strategyName;
            section.querySelectorAll('[data-strategy-choice]').forEach(item => {
                item.classList.toggle('active', item === button);
            });
            focusShell.innerHTML = renderStrategyFocusPanel(strategyName, strategies[strategyName], matchMap[strategyName] || [], report);
        });
    });
}

function renderTechnicalChips(technical) {
    if (!technical) {
        return '<div class="overview-tech-list"><span class="overview-status-chip tech-missing">主報表缺技術資料</span></div>';
    }

    const { summary, zoneFlags } = technical;
    const chips = [
        `<span class="overview-status-chip advice-${getAdviceToneClass(summary.advice)}">${esc(summary.advice)}</span>`,
        `<span class="overview-status-chip ${zoneFlags.inPilotZone ? 'flag-on' : 'flag-off'}">${zoneFlags.inPilotZone ? '位於試單區' : '未在試單區'}</span>`,
        `<span class="overview-status-chip ${zoneFlags.inObserveZone ? 'flag-on' : 'flag-off'}">${zoneFlags.inObserveZone ? '位於觀察區' : '未在觀察區'}</span>`,
        `<span class="overview-status-chip ${zoneFlags.isWeakBlocked ? 'flag-blocked' : 'flag-clear'}">${zoneFlags.isWeakBlocked ? '弱股封鎖' : '非弱股'}</span>`
    ];

    return `<div class="overview-tech-list">${chips.join('')}</div>`;
}

function compareOverviewItems(left, right, technicalMap) {
    const leftTechnical = technicalMap instanceof Map ? technicalMap.get(left.symbol) : null;
    const rightTechnical = technicalMap instanceof Map ? technicalMap.get(right.symbol) : null;

    const eventDiff = right.events.length - left.events.length;
    if (eventDiff !== 0) return eventDiff;

    const adviceDiff = getAdvicePriority(rightTechnical?.summary?.advice) - getAdvicePriority(leftTechnical?.summary?.advice);
    if (adviceDiff !== 0) return adviceDiff;

    const zoneDiff = getZonePriority(rightTechnical?.zoneFlags) - getZonePriority(leftTechnical?.zoneFlags);
    if (zoneDiff !== 0) return zoneDiff;

    return left.firstSeenOrder - right.firstSeenOrder;
}

function buildPriorityExplanation(item, technical) {
    const advice = technical?.summary?.advice || '技術資料不足';
    const zone = getZonePriorityLabel(technical?.zoneFlags);
    return `${item.events.length} 情境 > ${advice} > ${zone}`;
}

function buildCandidateOverview(report) {
    const cards = Array.isArray(report?.cards) ? report.cards : [];
    const eventMap = {};
    const entries = new Map();
    const groupOrder = [];
    const technicalMap = report?.technical_map instanceof Map ? report.technical_map : new Map();
    let firstSeenOrder = 0;

    for (const card of cards) {
        eventMap[card.trace.event] = card.title;
        for (const candidate of card.candidate_stocks) {
            const existing = entries.get(candidate.symbol);
            if (!existing) {
                const next = {
                    symbol: candidate.symbol,
                    primaryTheme: candidate.from_theme,
                    themes: [candidate.from_theme],
                    events: [candidate.trace_event],
                    firstSeenOrder
                };
                entries.set(candidate.symbol, next);
                firstSeenOrder += 1;
                if (!groupOrder.includes(candidate.from_theme)) {
                    groupOrder.push(candidate.from_theme);
                }
                continue;
            }
            if (!existing.themes.includes(candidate.from_theme)) {
                existing.themes.push(candidate.from_theme);
            }
            if (!existing.events.includes(candidate.trace_event)) {
                existing.events.push(candidate.trace_event);
            }
        }
    }

    const sortedItems = Array.from(entries.values()).sort((left, right) => compareOverviewItems(left, right, technicalMap));
    sortedItems.forEach((item, index) => {
        item.priorityRank = index + 1;
    });

    const grouped = groupOrder.map(themeId => ({
        themeId,
        items: sortedItems.filter(item => item.primaryTheme === themeId)
    })).filter(group => group.items.length > 0);

    return {
        totalUnique: entries.size,
        groups: grouped,
        eventMap,
        sortedItems
    };
}

function renderPriorityList(overview, report) {
    const itemsHTML = overview.sortedItems.map(item => {
        const technical = report?.technical_map instanceof Map ? report.technical_map.get(item.symbol) : null;
        const technicalHTML = renderTechnicalChips(technical);
        const stockName = technical?.name ? `<span class="priority-name">${esc(technical.name)}</span>` : '';
        const explanation = buildPriorityExplanation(item, technical);

        return `
            <div class="priority-item">
                <div class="priority-rank">#${formatPriorityRank(item.priorityRank)}</div>
                <div class="priority-content">
                    <div class="priority-top">
                        <div class="priority-symbol-line">
                            <span class="priority-symbol">${esc(item.symbol)}</span>
                            ${stockName}
                        </div>
                        <span class="priority-count">${item.events.length} 個情境</span>
                    </div>
                    ${technicalHTML}
                    <div class="priority-explain">排序依據：${esc(explanation)}</div>
                </div>
            </div>`;
    }).join('');

    return `
        <section class="priority-section">
            <div class="priority-section-head">
                <div class="priority-section-title">優先關注清單</div>
                <div class="priority-section-meta">排序規則：先比命中情境數，再比技術面狀態，最後比區間位置（試單區優先）；同分保留原出現順序。</div>
            </div>
            <div class="priority-list">${itemsHTML}</div>
        </section>`;
}

function renderOverviewGroup(group, report, eventMap) {
    const itemsHTML = group.items.map(item => {
        const technical = report?.technical_map instanceof Map ? report.technical_map.get(item.symbol) : null;
        const themeHTML = renderTagList(item.themes.map(themeId => themeLabel(themeId, report.trace_catalog)), 'theme-chip');
        const eventHTML = item.events
            .map(eventId => `<span class="overview-event-chip" title="${esc(eventLabel(eventId, eventMap))}">${esc(eventId)}</span>`)
            .join('');
        const technicalHTML = renderTechnicalChips(technical);
        const stockName = technical?.name ? `<span class="overview-name">${esc(technical.name)}</span>` : '';
        const explanation = buildPriorityExplanation(item, technical);

        return `
            <div class="overview-item">
                <div class="overview-item-top">
                    <div class="overview-symbol-line">
                        <span class="overview-symbol">${esc(item.symbol)}</span>
                        ${stockName}
                    </div>
                    <div class="overview-item-meta">
                        <span class="overview-priority-chip">#${formatPriorityRank(item.priorityRank)}</span>
                        <span class="overview-count">${item.events.length} 個情境</span>
                    </div>
                </div>
                ${technicalHTML}
                <div class="overview-priority-note">排序依據：${esc(explanation)}</div>
                <div class="overview-row">
                    <span class="overview-label">themes</span>
                    <div class="tag-list">${themeHTML}</div>
                </div>
                <div class="overview-row">
                    <span class="overview-label">events</span>
                    <div class="overview-event-list">${eventHTML}</div>
                </div>
            </div>`;
    }).join('');

    return `
        <section class="overview-group">
            <div class="overview-group-head">
                <div class="overview-group-title">${esc(themeLabel(group.themeId, report.trace_catalog))}</div>
                <div class="overview-group-count">${group.items.length} 檔</div>
            </div>
            <div class="overview-group-list">${itemsHTML}</div>
        </section>`;
}

function renderCandidateOverview(report) {
    const section = document.getElementById('candidateOverview');
    const meta = document.getElementById('overviewMeta');
    const body = document.getElementById('overviewBody');
    const overview = buildCandidateOverview(report);

    if (!overview.totalUnique) {
        meta.textContent = '目前沒有可收斂的候選股票。';
        body.innerHTML = '<div class="overview-empty">底層原始候選仍保留，但目前沒有可顯示的收斂清單。</div>';
        section.style.display = 'block';
        return;
    }

    meta.textContent = `跨卡去重後共 ${overview.totalUnique} 檔；優先層只用「情境數 > 技術面 > 試單區」排序，不改原始候選資料與 summary。`;
    body.innerHTML = `${renderStrategySection(overview, report)}${renderPriorityList(overview, report)}<div class="overview-group-shell"><div class="overview-group-shell-title">依題材分組</div>${overview.groups
        .map(group => renderOverviewGroup(group, report, overview.eventMap))
        .join('')}</div>`;
    bindStrategySelector(overview, report);
    section.style.display = 'block';
}

function renderCandidateStocks(candidateStocks, report) {
    if (!candidateStocks.length) {
        return '<div class="candidate-empty">這張卡目前沒有對應的固定候選股票池。</div>';
    }

    const items = candidateStocks.map(candidate => `
        <div class="candidate-item">
            <div class="candidate-top">
                <span class="candidate-symbol">${esc(candidate.symbol)}</span>
                <span class="candidate-theme">${esc(themeLabel(candidate.from_theme, report.trace_catalog))}</span>
            </div>
            <div class="candidate-meta">event: ${esc(candidate.trace_event)}</div>
            <div class="candidate-reason">${esc(candidate.reason)}</div>
        </div>
    `).join('');

    return `<div class="candidate-list">${items}</div>`;
}

function renderCard(card, report) {
    const reasoningHTML = card.reasoning_chain
        .map(item => `<li class="reasoning-item">${esc(item)}</li>`)
        .join('');
    const keywordsHTML = renderTagList(card.keywords, 'keyword-chip');
    const themesHTML = renderTagList(card.themes, 'theme-chip');
    const traceKeywordsHTML = renderTraceList(card.trace.keywords);
    const traceThemesHTML = renderTraceList(card.trace.themes);
    const candidatesHTML = renderCandidateStocks(card.candidate_stocks, report);

    return `
        <article class="scenario-card" data-card-id="${esc(card.id)}">
            <div class="scenario-card-top">
                <div class="scenario-card-title">${esc(card.title)}</div>
                <div class="scenario-card-meta">
                    <span class="meta-chip confidence-${esc(card.confidence)}">${esc(confidenceLabel(card.confidence))}</span>
                    <span class="meta-chip relation-${esc(card.relation_to_technical)}">${esc(relationLabel(card.relation_to_technical))}</span>
                </div>
            </div>
            <div class="scenario-row">
                <div class="scenario-label">事件</div>
                <div class="scenario-text">${esc(card.event)}</div>
            </div>
            <div class="scenario-row">
                <div class="scenario-label">異常點</div>
                <div class="scenario-text">${esc(card.anomaly)}</div>
            </div>
            <div class="scenario-row">
                <div class="scenario-label">關鍵詞</div>
                <div class="scenario-text"><div class="tag-list">${keywordsHTML}</div></div>
            </div>
            <div class="scenario-row">
                <div class="scenario-label">題材</div>
                <div class="scenario-text"><div class="tag-list">${themesHTML}</div></div>
            </div>
            <div class="scenario-row">
                <div class="scenario-label">追溯鏈</div>
                <div class="scenario-text">
                    <div class="trace-block">
                        <div class="trace-caption">event → keywords → themes</div>
                        <div class="trace-line"><span class="trace-chip trace-event">${esc(card.trace.event)}</span></div>
                        <div class="trace-arrow">↓</div>
                        <div class="trace-line">${traceKeywordsHTML}</div>
                        <div class="trace-arrow">↓</div>
                        <div class="trace-line">${traceThemesHTML}</div>
                    </div>
                </div>
            </div>
            <div class="scenario-row">
                <div class="scenario-label">候選股票</div>
                <div class="scenario-text">${candidatesHTML}</div>
            </div>
            <div class="scenario-row">
                <div class="scenario-label">推論鏈</div>
                <div class="scenario-text">
                    <ul class="reasoning-list">${reasoningHTML}</ul>
                </div>
            </div>
            <div class="scenario-footer">
                <span>source: ${esc(card.source_type)}</span>
                <span>generated: ${esc(formatGeneratedAt(card.generated_at))}</span>
            </div>
        </article>`;
}

function renderCards(cards, reportVersion, report) {
    updateHeaderMeta(reportVersion, cards.length);
    document.getElementById('loadingState').style.display = 'none';
    document.getElementById('emptyState').style.display = 'none';
    renderCandidateOverview(report);
    const list = document.getElementById('cardList');
    list.innerHTML = cards.map(card => renderCard(card, report)).join('');
    list.style.display = 'grid';
}

function buildDateDropdown() {
    const select = document.getElementById('dateSelect');
    if (!indexData?.reports?.length) {
        select.innerHTML = '<option value="">無可用日期</option>';
        return;
    }

    select.innerHTML = indexData.reports.map(report => {
        const selected = report.date === currentDate ? ' selected' : '';
        const suffix = report.date === indexData.latest_date ? ' (最新)' : '';
        return `<option value="${report.date}"${selected}>${report.date}${suffix}</option>`;
    }).join('');
}

async function loadIndex() {
    indexData = await fetchJSON(`${BASE}/index.json`);
}

async function loadContextCards(date) {
    showLoading(`載入 ${date} 情境卡中...`);
    try {
        const previousUniverseDate = getPreviousUniverseDate(date);
        const [contextResult, universeResult, fullResult, strategyResult, signalDensityResult, previousUniverseResult] = await Promise.allSettled([
            fetchJSON(`${BASE}/${date}-context.json`),
            fetchJSON(`${BASE}/${date}-universe.json`),
            fetchJSON(`${BASE}/${date}.json`),
            fetchJSON(`${BASE}/strategy_analysis.json`),
            fetchJSON(`${BASE}/signal_density.json`),
            previousUniverseDate ? fetchJSON(`${BASE}/${previousUniverseDate}-universe.json`) : Promise.resolve(null)
        ]);

        if (contextResult.status !== 'fulfilled') {
            throw contextResult.reason;
        }

        const report = contextResult.value;
        if (!validateContextReport(report)) {
            const fallback = createFallbackCard('情境卡格式不符合固定 schema，已改用頁面保底訊息。');
            renderCards([fallback], 'fallback', {
                cards: [fallback],
                trace_catalog: { theme_taxonomy: {} },
                stock_mapping_catalog: { themes_to_stocks: {} },
                technical_map: new Map()
            });
            return;
        }

        renderCards(report.cards, report.report_version, {
            ...report,
            technical_map: universeResult.status === 'fulfilled'
                ? buildTechnicalMap(universeResult.value)
                : fullResult.status === 'fulfilled'
                    ? buildTechnicalMap(fullResult.value)
                    : new Map(),
            previous_technical_map: previousUniverseResult.status === 'fulfilled' && previousUniverseResult.value
                ? buildTechnicalMap(previousUniverseResult.value)
                : new Map(),
            previous_universe_date: previousUniverseDate,
            strategy_analysis: strategyResult.status === 'fulfilled' && validateStrategyAnalysisReport(strategyResult.value)
                ? strategyResult.value
                : null,
            signal_density: signalDensityResult.status === 'fulfilled' && validateSignalDensityReport(signalDensityResult.value)
                ? signalDensityResult.value
                : null
        });
    } catch (error) {
        const fallback = createFallbackCard(`找不到 ${date}-context.json 或載入失敗。`);
        renderCards([fallback], 'fallback', {
            cards: [fallback],
            trace_catalog: { theme_taxonomy: {} },
            stock_mapping_catalog: { themes_to_stocks: {} },
            technical_map: new Map(),
            previous_technical_map: new Map(),
            previous_universe_date: null,
            strategy_analysis: null,
            signal_density: null
        });
    }
}

async function init() {
    try {
        await loadIndex();
        currentDate = new URLSearchParams(window.location.search).get('date') || indexData.latest_date;
        buildDateDropdown();
        document.getElementById('dateSelect').addEventListener('change', async event => {
            currentDate = event.target.value;
            const nextUrl = new URL(window.location.href);
            nextUrl.searchParams.set('date', currentDate);
            window.history.replaceState({}, '', nextUrl.toString());
            requestVersion = String(Date.now());
            await loadContextCards(currentDate);
        });
        await loadContextCards(currentDate);
    } catch (error) {
        updateHeaderMeta('fallback', 1);
        showEmpty('情境頁初始化失敗，請稍後重新整理。');
    }
}

init();
