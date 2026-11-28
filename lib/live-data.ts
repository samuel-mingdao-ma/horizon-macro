import { validatePathSimulation } from './path-simulation-validation.ts';
import { validateJointStress } from './joint-stress-validation.ts';
import { validateCurveStability } from './curve-stability-validation.ts';
/** Live public-data inference. Fitting and validation stay in research/build_model.py. */
export type Observation = { date: string; value: number };
export type MacroSnapshot = Record<string, any>;
const IDS = ['GS10', 'TB3MS', 'NFCICREDIT', 'UNRATE', 'CPIAUCSL', 'FEDFUNDS', 'GS1', 'GS2', 'GS5', 'GS30'];
const TTL = 60 * 60 * 1000;
export const RESEARCH_SNAPSHOT_URL = 'https://raw.githubusercontent.com/samuel-mingdao-ma/horizon-macro/main/public/data/snapshot.json';
/** Bypass named-branch CDN entries when the hourly application cache expires. */
export function uncachedResearchUrl(canonicalUrl: string, checkedAt = Date.now()): string {
  const url = new URL(canonicalUrl);
  url.searchParams.set('_horizon_refresh', String(checkedAt));
  return url.toString();
}
let cached: { at: number; value: MacroSnapshot } | undefined;
let inFlight: Promise<MacroSnapshot> | undefined;

export function monthOffset(month: string, n: number): string {
  const [year, mon] = month.slice(0, 7).split('-').map(Number);
  const result = new Date(Date.UTC(year, mon - 1 + n, 1));
  return result.toISOString().slice(0, 10);
}

export function parseFredCsv(csv: string): Observation[] {
  const rows = csv.trim().split(/\r?\n/);
  if (!/^observation_date,/.test(rows[0] ?? '') && !/^DATE,/.test(rows[0] ?? '')) throw new Error('Unexpected provider format');
  const result: Observation[] = [];
  for (const row of rows.slice(1)) {
    const [date, raw] = row.split(',');
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date ?? '') || !raw?.trim() || raw.trim() === '.') continue;
    const value = Number(raw.replaceAll('"', ''));
    if (Number.isFinite(value)) result.push({ date, value });
  }
  if (!result.length) throw new Error('Provider returned no observations');
  return result.sort((a, b) => a.date.localeCompare(b.date));
}

export function monthlyMean(rows: Observation[], beforeMonth: string): Map<string, number> {
  const grouped = new Map<string, number[]>();
  for (const row of rows) {
    const month = row.date.slice(0, 7) + '-01';
    if (month >= beforeMonth) continue;
    const values = grouped.get(month) ?? [];
    values.push(row.value);
    grouped.set(month, values);
  }
  return new Map([...grouped].map(([month, values]) => [month, values.reduce((a, b) => a + b, 0) / values.length]));
}

export function featureVector(series: Record<string, Map<string, number>>, featureMonth: string): { slope: number; credit: number; labor: number } {
  const at = (id: string, n = 0) => {
    const value = series[id]?.get(monthOffset(featureMonth, n));
    if (value === undefined || !Number.isFinite(value)) throw new Error(`Incomplete aligned inputs: ${id}`);
    return value;
  };
  const unemploymentAverage = (n: number) => {
    const values = [n, n - 1, n - 2].map(offset => series.UNRATE?.get(monthOffset(featureMonth, offset))).filter((value): value is number => value !== undefined && Number.isFinite(value));
    if (values.length < 2) throw new Error('Fewer than two observed unemployment months in a three-month window');
    return values.reduce((sum, value) => sum + value, 0) / values.length;
  };
  const smooth = unemploymentAverage(0);
  const min = Math.min(...Array.from({ length: 12 }, (_, i) => unemploymentAverage(-i)));
  return { slope: at('GS10') - at('TB3MS'), credit: at('NFCICREDIT'), labor: smooth - min };
}

export function score(features: Record<string, number>, model: MacroSnapshot): { probability: number; contributions: MacroSnapshot[] } {
  const labels: Record<string, string> = { slope: 'Yield curve', credit: 'Credit conditions', labor: 'Labor momentum' };
  const contributions = model.featureOrder.map((key: string, index: number) => {
    const standardized = (features[key] - model.means[index]) / model.scales[index];
    return { key, label: labels[key] ?? key, value: features[key], standardized, coefficient: model.coefficients[index], logOdds: standardized * model.coefficients[index] };
  });
  const logit = model.intercept + contributions.reduce((sum: number, item: MacroSnapshot) => sum + item.logOdds, 0);
  const probability = logit >= 0 ? 1 / (1 + Math.exp(-logit)) : Math.exp(logit) / (1 + Math.exp(logit));
  return { probability, contributions };
}

async function loadSeries(id: string, since: string): Promise<Observation[]> {
  const url = new URL('https://fred.stlouisfed.org/graph/fredgraph.csv');
  url.searchParams.set('id', id);
  url.searchParams.set('cosd', since);
  const response = await fetch(url, { signal: AbortSignal.timeout(8_000), headers: { Accept: 'text/csv' } });
  if (!response.ok) throw new Error(`Provider request failed: ${id} (${response.status})`);
  return parseFredCsv(await response.text());
}

export async function refreshSnapshot(base: MacroSnapshot, now = new Date(), loader = loadSeries): Promise<MacroSnapshot> {
  const checkedAt = now.toISOString();
  const currentMonth = checkedAt.slice(0, 7) + '-01';
  const since = monthOffset(currentMonth, -40);
  const raw: Record<string, Observation[]> = {};
  // Missing model inputs invalidate the whole inference; missing optional displays
  // retain their explicitly dated snapshot values instead of fabricating data.
  const settled = await Promise.allSettled(IDS.map(async id => { raw[id] = await loader(id, since); }));
  for (const [i, result] of settled.entries()) {
    if (result.status === 'rejected' && ['GS10', 'TB3MS', 'NFCICREDIT', 'UNRATE'].includes(IDS[i])) throw result.reason;
  }
  const monthly: Record<string, Map<string, number>> = {};
  for (const [id, rows] of Object.entries(raw)) monthly[id] = monthlyMean(rows, currentMonth);
  let featureDate = monthOffset(currentMonth, -2);
  let features: ReturnType<typeof featureVector> | undefined;
  for (let lag = 0; lag <= 12; lag++) {
    try { features = featureVector(monthly, featureDate); break; } catch { featureDate = monthOffset(featureDate, -1); }
  }
  if (!features) throw new Error('No complete aligned feature month');
  // Do not regress below a bundled, newer snapshot if the provider returns partial history.
  if (featureDate < base.latest.featureDate) throw new Error('Provider data older than the bundled snapshot');
  const issueDate = monthOffset(featureDate, 2);
  const result = score(features, base.model);
  let previousProbability = base.latest.previousProbability;
  try { previousProbability = score(featureVector(monthly, monthOffset(featureDate, -1)), base.model).probability; } catch { /* preserve dated fallback */ }
  const copy = structuredClone(base);
  const indicatorDates = [...(monthly.GS10?.keys() ?? [])].filter(date => ['GS10', 'TB3MS', 'UNRATE', 'FEDFUNDS'].every(id => monthly[id]?.has(date))).sort();
  const indicatorDate = indicatorDates.at(-1) ?? featureDate;
  const observed = (id: string) => monthly[id]?.get(indicatorDate);
  const inflationDates = [...(monthly.CPIAUCSL?.keys() ?? [])].filter(date => date <= indicatorDate && monthly.CPIAUCSL?.has(monthOffset(date, -12))).sort();
  const inflationDate = inflationDates.at(-1);
  const inflationCurrent = inflationDate ? monthly.CPIAUCSL?.get(inflationDate) : undefined;
  const inflationYearAgo = inflationDate ? monthly.CPIAUCSL?.get(monthOffset(inflationDate, -12)) : undefined;
  const indicators = {
    ...base.latest.indicators,
    gs10: observed('GS10'), tb3ms: observed('TB3MS'), unemployment: observed('UNRATE'),
    ...(inflationCurrent !== undefined && inflationYearAgo !== undefined ? { inflation: (inflationCurrent / inflationYearAgo - 1) * 100, inflationDate } : {}),
    ...(observed('FEDFUNDS') !== undefined ? { fedFunds: observed('FEDFUNDS') } : {}),
  };
  copy.latest = { ...copy.latest, ...result, previousProbability, change: result.probability - previousProbability,
    regime: result.probability >= 0.3 ? 'Elevated' : result.probability >= 0.15 ? 'Watchful' : 'Contained',
    features, featureDate, issueDate, indicatorDate, forecastStart: monthOffset(issueDate, 1), forecastEnd: monthOffset(issueDate, 12), indicators };
  copy.meta = { ...copy.meta, issueDate, featureDate, forecastStart: monthOffset(issueDate, 1), forecastEnd: monthOffset(issueDate, 12),
    refresh: { status: 'fresh', checkedAt, lastSuccessfulRefresh: checkedAt, cacheTtlSeconds: TTL / 1000, inputMonthsBehind: (Number(currentMonth.slice(0, 4)) - Number(issueDate.slice(0, 4))) * 12 + Number(currentMonth.slice(5, 7)) - Number(issueDate.slice(5, 7)), mode: 'Live inputs · fixed model', source: 'fred-direct', sourceUpdatedAt: checkedAt,
      note: 'FRED inputs refreshed on request; model coefficients and historical validation remain at the last research build.' } };
  copy.sources = (copy.sources ?? []).map((source: MacroSnapshot) => {
    const latest = raw[source.id]?.at(-1);
    return latest ? { ...source, lastDate: latest.date, lastValue: latest.value, retrievedAt: checkedAt } : source;
  });
  const lastHistoryDate = copy.history?.at(-1)?.date;
  if (lastHistoryDate && lastHistoryDate < issueDate) {
    for (let date = monthOffset(lastHistoryDate, 1); date <= issueDate; date = monthOffset(date, 1)) {
      const month = monthOffset(date, -2);
      try {
        const inputs = featureVector(monthly, month);
        copy.history.push({ date, featureDate: month, probability: score(inputs, base.model).probability,
          baseline: base.latest.baselineProbability, curveProbability: null, target: null, recession: null,
          ...inputs, forecastType: 'live-fixed-model' });
      } catch { /* Never fill missing historical inputs with guesses. */ }
    }
  }
  const tenors = [{ id: 'TB3MS', tenor: '3M', years: 0.25 }, { id: 'GS1', tenor: '1Y', years: 1 }, { id: 'GS2', tenor: '2Y', years: 2 }, { id: 'GS5', tenor: '5Y', years: 5 }, { id: 'GS10', tenor: '10Y', years: 10 }, { id: 'GS30', tenor: '30Y', years: 30 }];
  const curveDates = [...(monthly.GS10?.keys() ?? [])].filter(date => tenors.every(tenor => monthly[tenor.id]?.has(date))).sort();
  const curveDate = curveDates.at(-1);
  if (curveDate) copy.yieldCurve = tenors.map(tenor => ({ tenor: tenor.tenor, years: tenor.years, value: monthly[tenor.id].get(curveDate), previousValue: monthly[tenor.id].get(monthOffset(curveDate, -1)) ?? null, date: curveDate, series: tenor.id, quoteBasis: tenor.id === 'TB3MS' ? 'discount' : 'investment' }));
  return copy;
}

/** Validate that a refreshed alarm experiment still evaluates the published conditional risks. */
function validateMomentum(value: MacroSnapshot, previous: MacroSnapshot): void {
  const t = value.momentumTrial, parent = value.expansionTrial, current = t?.latest;
  const fail = (why: string): never => { throw new Error('Risk momentum ' + why); };
  const equalRisk = (a: unknown, b: unknown) => (a === null && b === null)
    || (typeof a === 'number' && typeof b === 'number' && Math.abs(a - b) < 1e-8);
  const spec = t?.spec;
  if (!current || !parent || spec?.id !== previous.spec.id || spec.parentId !== parent.spec.id
    || spec.warningThreshold !== .3 || spec.momentumFloor !== .2 || spec.lookbackMonths !== 3
    || spec.projectionMonths?.quarter !== 3 || spec.projectionMonths?.month !== 1
    || !Array.isArray(t.history) || t.history.length !== parent.history.length
    || !['issueDate','featureDate','forecastStart','forecastEnd','available','refitDate'].every(k => current[k] === parent.latest[k])
    || !equalRisk(current.probability, parent.latest.probability)) fail('has an inconsistent forecast or decision definition');

  function checkDecisions(row: MacroSnapshot) {
    const values = [row.lag3Probability, row.lag2Probability, row.lag1Probability, row.probability];
    if (!values.every(p => p === null || (Number.isFinite(p) && p >= 0 && p <= 1))) fail('has an invalid risk path');
    const [start, , last, p] = values.map(n => n === null ? null : Math.round(n * 1e12));
    const complete = values.every(n => n !== null);
    const delta = complete ? p! - start! : null;
    const one = p !== null && last !== null ? p - last : null;
    const level = p === null ? null : p >= 300e9;
    const rising = complete && p! >= 200e9 && one! > 0 && delta! > 0;
    if (row.paceAvailable !== complete || !equalRisk(row.change1m, one === null ? null : one / 1e12)
      || !equalRisk(row.change3m, delta === null ? null : delta / 1e12)
      || row.levelAlert !== level || row.quarterAlert !== (level === null ? null : level || rising && p! + delta! >= 300e9)
      || row.monthAlert !== (level === null ? null : level || rising && 3*p! + delta! >= 900e9)) fail('decisions disagree with the risk path');
  }
  checkDecisions(current);
  if (!Array.isArray(current.path) || current.path.length !== 4) fail('lacks four calendar slots');
  const featureKeys = ['slope','credit','labor','permitGrowth6','claimsGrowth12'];
  const parentRows = new Map<string, MacroSnapshot>(parent.history.map((r: MacroSnapshot) => [r.date,r]));
  current.path.forEach((point: MacroSnapshot, i: number) => {
    const date = monthOffset(current.issueDate,i-3);
    const source = i === 3 ? parent.latest : parentRows.get(date);
    if (point.date !== date || point.featureDate !== monthOffset(date,-2)
      || !equalRisk(point.probability,[current.lag3Probability,current.lag2Probability,current.lag1Probability,current.probability][i]))
      fail('has a misdated live lookback');
    if (current.available) {
      if (!point.features || !featureKeys.every(k => equalRisk(point.features[k],source?.[k] ?? null))) fail('uses inconsistent monthly inputs');
      const risk = featureKeys.every(k => Number.isFinite(point.features[k]))
        ? (score(point.features,parent.currentModel).probability + parent.latest.expansionPriorProbability)/2 : null;
      if (!equalRisk(point.probability,risk)) fail('lookback disagrees with the frozen fit');
    }
  });
  t.history.forEach((row: MacroSnapshot, i: number) => {
    const r = parent.history[i];
    if (!['date','featureDate','refitDate','commonMature','issuePhase','target','onsetDate'].every(k => row[k] === r[k])
      || !equalRisk(row.probability,r.probability)) fail('replay disagrees with the expansion-origin forecasts');
    checkDecisions(row);
  });
  for (const key of ['all','rolling120']) {
    const w = t.windows?.[key], ref = parent.metrics[key], alarms = parent.warnings.windows[key];
    if (!w || !['windowStart','windowEnd','n','quietExpansionN','preOnsetN','completeEpisodes'].every(k => w[k] === alarms[k])
      || w.summary?.level?.quietAlerts !== alarms.summary.candidate.quietAlerts
      || !['brier','logLoss','auc'].every(k => equalRisk(w.probabilityScores?.[k],ref.models.candidate[k])))
      fail('uses different scoring windows or probabilities');
    const rows: MacroSnapshot[] = t.history.filter((r: MacroSnapshot) => r.commonMature && r.date >= w.windowStart && r.date <= w.windowEnd);
    const diagnostic = w.caseComparison;
    const caseRow = t.history.find((r: MacroSnapshot) => r.date === '2000-05-01');
    if (!Array.isArray(w.episodes) || diagnostic?.date !== '2000-05-01'
      || typeof diagnostic.available !== 'boolean' || !Array.isArray(diagnostic.matches)
      || (diagnostic.available && !caseRow?.paceAvailable)) fail('lacks the case comparison');
    const fields = ['probability','change1m','change3m'];
    const matches = diagnostic.available ? rows.filter(r => r.target === 0 && r.paceAvailable && !r.levelAlert
      && fields.every(k => Math.round(r[k] * 1e12) >= Math.round(caseRow[k] * 1e12))) : [];
    if (matches.length !== diagnostic.matches.length || matches.some((r,i) =>
      diagnostic.matches[i]?.date !== r.date || fields.some(k => !equalRisk(diagnostic.matches[i][k],r[k]))))
      fail('quiet case comparisons disagree with the replay');
    for (const rule of ['quarter','month']) {
      if (typeof t.gate?.[rule]?.passed !== 'boolean' || !w[rule + 'Comparison']
        || w.episodes.some((e: MacroSnapshot) => !e.methods?.level || !e.methods?.[rule]))
        fail('lacks comparable alert timing');
      const added = rows.filter(r => r[rule + 'Alert'] && !r.levelAlert);
      for (const [field,target] of [['quietDates',0],['preOnsetDates',1]] as const) {
        if (JSON.stringify(w.changes?.[rule]?.[field]) !== JSON.stringify(added.filter(r => r.target === target).map(r => r.date)))
          fail('incremental alert dates disagree with underlying decisions');
      }
      if (w.summary[rule].quietAlerts !== w.summary.level.quietAlerts + w.changes[rule].quietDates.length
        || w.summary[rule].preOnsetAlerts !== w.summary.level.preOnsetAlerts + w.changes[rule].preOnsetDates.length)
        fail('incremental alert counts are inconsistent');
    }
  }
  const a = t.prospective;
  if (previous.prospective?.receiptCount || a) {
    if (!a?.chainValid || !Array.isArray(a.receipts) || a.receipts.length !== a.receiptCount
      || ![a.pendingCount,a.maturedCount,a.excludedCount].every(n => Number.isInteger(n) && n >= 0)
      || a.receiptCount !== a.pendingCount + a.maturedCount + a.excludedCount
      || previous.prospective?.receipts?.some((r: MacroSnapshot,i: number) => r.hash !== a.receipts[i]?.hash))
      fail('forecast records are inconsistent or regressive');
  }
}

function replayEqual(a: unknown,b: unknown): boolean {
  return a === b || (typeof a === 'number' && typeof b === 'number' && Math.abs(a-b) < 1e-9);
}

function validateOverlayResults(trial: MacroSnapshot, pace: MacroSnapshot, previous: MacroSnapshot, rules: string[], fail: (detail: string) => never): void {
  const methods = ['level','quarter',...rules];
  for (const key of ['all','rolling120']) {
    const w = trial.windows?.[key], reference = pace.windows[key];
    if (!w || !['windowStart','windowEnd','n','quietExpansionN','preOnsetN','completeEpisodes'].every(k => w[k] === reference[k])
      || !Array.isArray(w.episodes) || !['brier','auc','logLoss'].every(k => replayEqual(w.probabilityScores?.[k],reference.probabilityScores[k])))
      fail('has inconsistent denominators or probability scores');
    const paired: MacroSnapshot[] = trial.history.filter((r: MacroSnapshot) => r.commonMature && r.date >= w.windowStart && r.date <= w.windowEnd);
    for (const method of methods) {
      const added = paired.filter(r => r[method+'Alert'] && !r.levelAlert);
      const quiet = added.filter(r => r.target === 0).map(r => r.date);
      const pre = added.filter(r => r.target === 1).map(r => r.date);
      if (w.summary?.[method]?.quietAlerts !== reference.summary.level.quietAlerts + quiet.length
        || w.summary?.[method]?.preOnsetAlerts !== reference.summary.level.preOnsetAlerts + pre.length
        || w.episodes.some((ep: MacroSnapshot) => !ep.methods?.[method])
        || (method !== 'level' && (JSON.stringify(quiet) !== JSON.stringify(w.changes?.[method]?.quietDates)
          || JSON.stringify(pre) !== JSON.stringify(w.changes?.[method]?.preOnsetDates)))) fail('alert counts disagree with monthly decisions');
    }
  }
  const may = trial.history.find((r: MacroSnapshot) => r.date === '2000-05-01');
  const ep = trial.windows.all.episodes.find((e: MacroSnapshot) => e.onsetDate === '2001-04-01' && e.coverage === 'full');
  for (const rule of rules) {
    const gate = trial.gate?.[rule];
    const [full,recent] = [trial.windows.all,trial.windows.rolling120].map(w => w[rule+'Comparison']);
    const kept = !!(ep && may?.commonMature && may.target === 1 && may.onsetDate === ep.onsetDate
      && !may.levelAlert && may.quarterAlert && may[rule+'Alert'] && ep.methods[rule].leadMonths >= 11
      && ep.methods[rule].leadMonths > (ep.methods.level.leadMonths ?? 0));
    if (!full || !recent || !gate || gate.mayRetained !== kept || gate.allNoAddedFalse !== full.noMoreFalseAlarms
      || gate.rolling120NoAddedFalse !== recent.noMoreFalseAlarms || gate.maintainedHitsBoth !== (full.maintainedHits && recent.maintainedHits)
      || gate.passed !== (kept && full.sufficient && recent.sufficient && gate.maintainedHitsBoth && gate.allNoAddedFalse && gate.rolling120NoAddedFalse))
      fail('reports an inconsistent joint test');
  }
  const archive = trial.prospective;
  if (archive || previous.prospective?.receiptCount) {
    if (!archive?.chainValid || !Array.isArray(archive.receipts) || archive.receiptCount !== archive.receipts.length
      || ![archive.pendingCount,archive.maturedCount,archive.excludedCount].every(n => Number.isInteger(n) && n >= 0)
      || archive.receiptCount !== archive.pendingCount + archive.maturedCount + archive.excludedCount
      || previous.prospective?.receipts?.some((r: MacroSnapshot,i: number) => r.hash !== archive.receipts[i]?.hash))
      fail('has missing or regressive frozen records');
  }
}

/** Validate the confirmation votes against the same months and probabilities used by the pace replay. */
function validateConfirmation(value: MacroSnapshot, previous: MacroSnapshot): void {
  const trial = value.confirmationTrial, pace = value.momentumTrial, expansion = value.expansionTrial;
  const fail = (detail: string): never => { throw new Error('Signal confirmation ' + detail); };
  const rules = ['pressure','direction','breadth'];
  if (!trial?.latest || trial.spec?.id !== previous.spec.id || trial.spec.parentId !== pace?.spec?.id
    || trial.spec.threshold !== .3 || trial.spec.featureLagMonths !== 2 || trial.spec.signalLookbackMonths !== 3
    || !Array.isArray(trial.history) || trial.history.length !== pace.history.length) fail('is missing or misaligned');

  const origins = new Map<string,MacroSnapshot>(expansion.history.map((r: MacroSnapshot) => [r.date,r]));
  function verifyIssue(date: string, r: MacroSnapshot, p: MacroSnapshot, source: MacroSnapshot) {
    const prior = origins.get(monthOffset(date,-3));
    if (!['featureDate','refitDate','levelAlert','quarterAlert','probability','change1m','change3m'].every(k => replayEqual(r[k],p[k]))
      || r.lagFeatureDate !== monthOffset(date,-5)) fail('disagrees with the parent alarm or feature dates');
    for (const [signal,lag] of [['permitGrowth6','lagPermitGrowth6'],['claimsGrowth12','lagClaimsGrowth12'],['credit','lagCredit']]) {
      if (!replayEqual(r[signal],source[signal]) || !replayEqual(r[lag],prior?.[signal] ?? null)) fail('uses different economic inputs');
    }
    const higher = (a: number | null, b: number | null) => a === null || b === null ? null : a > b;
    const votes = {
      permitsNegative:higher(0,r.permitGrowth6), claimsPositive:higher(r.claimsGrowth12,0),
      creditTightening:higher(r.credit,r.lagCredit), permitsSlowing:higher(r.lagPermitGrowth6,r.permitGrowth6),
      claimsRising:higher(r.claimsGrowth12,r.lagClaimsGrowth12),
    };
    const count = (v: (boolean|null)[]) => v.includes(null) ? null : v.filter(x => x).length;
    const pressure = count([votes.permitsNegative,votes.claimsPositive,votes.creditTightening]);
    const direction = count([votes.permitsSlowing,votes.claimsRising,votes.creditTightening]);
    const alert = (passes: boolean) => p.levelAlert === null ? null : p.levelAlert || (p.quarterAlert && passes);
    if (Object.entries(votes).some(([k,v]) => r[k] !== v) || r.pressureVotes !== pressure || r.directionVotes !== direction
      || r.pressureAlert !== alert(pressure === 3) || r.directionAlert !== alert(direction === 3)
      || r.breadthAlert !== alert(pressure !== null && pressure >= 2)) fail('votes or warning decisions disagree with inputs');
  }
  const current = trial.latest;
  if (!['issueDate','forecastStart','forecastEnd','available'].every(k => current[k] === pace.latest[k]))
    fail('has an inconsistent live issue');
  verifyIssue(current.issueDate,current,pace.latest,expansion.latest);
  trial.history.forEach((r: MacroSnapshot,i: number) => {
    const p = pace.history[i];
    if (!['date','commonMature','target','issuePhase','onsetDate'].every(k => r[k] === p[k])) fail('changed the evaluation cohort');
    verifyIssue(r.date,r,p,expansion.history[i]);
  });
  validateOverlayResults(trial,pace,previous,rules,fail);
  for (const date of ['2000-05-01','2019-02-01']) {
    const parts = trial.caseAttribution?.[date], p = pace.history.find((r: MacroSnapshot) => r.date === date);
    if (parts === null && !p?.paceAvailable) continue;
    if (!p || !parts || !replayEqual(parts.startRisk,p.lag3Probability) || !replayEqual(parts.endRisk,p.probability)
      || !replayEqual(parts.change,p.change3m) || !parts.effects || !replayEqual(parts.change,
        ['slope','credit','labor','permitGrowth6'].reduce((sum,k) => sum + parts.effects[k],0))) fail('risk contributions do not reconcile');
  }
}

function validateCurveLegs(value: MacroSnapshot, previous: MacroSnapshot): void {
  const trial = value.curveLegsTrial, pace = value.momentumTrial, expansion = value.expansionTrial;
  const fail = (detail: string): never => { throw new Error('Yield curve legs ' + detail); };
  const rules = ['shortLead','bear','sustained','mixedTwoToOne'];
  const spec = trial?.spec;
  if (!trial?.latest || spec?.id !== previous.spec.id || spec.parentId !== pace?.spec?.id
    || spec.shortSeries !== 'TB3MS' || spec.longSeries !== 'GS10' || spec.lookbackMonths !== 3
    || spec.threshold !== .30 || spec.featureLagMonths !== 2
    || JSON.stringify(spec.preReplayRules) !== JSON.stringify(rules.slice(0,3))
    || JSON.stringify(spec.postHocRules) !== JSON.stringify(['mixedTwoToOne'])
    || !Array.isArray(trial.history) || trial.history.length !== pace.history.length) fail('has an inconsistent design or cohort');

  const suffixes = ['Start','Step1','Step2','End'];
  // The same observation month must carry the same vintage throughout this replay.
  const observations = new Map<string, [number|null,number|null]>();
  const diff = (a: number|null,b: number|null) => a === null || b === null ? null : a-b;
  const asRate = (u: number|null) => u === null ? null : u / 1e12;
  function verify(r: MacroSnapshot,p: MacroSnapshot,source: MacroSnapshot,live: boolean) {
    const date = live ? r.issueDate : r.date;
    const shape = live ? ['issueDate','forecastStart','forecastEnd','available'] : ['date','target','commonMature','issuePhase','onsetDate'];
    if (!shape.every(k => r[k] === p[k]) || !['featureDate','refitDate','probability','change1m','change3m','levelAlert','quarterAlert'].every(k => replayEqual(r[k],p[k]))
      || r.lagFeatureDate !== monthOffset(date,-5) || (live && (!Array.isArray(r.yieldPath) || r.yieldPath.length !== 4))) fail('does not reproduce the parent issue');
    const bills: (number|null)[] = [];
    const bonds: (number|null)[] = [];
    for (let i=0; i<4; i++) {
      const observation = monthOffset(date,i-5);
      const bill = r['short'+suffixes[i]], bond = r['long'+suffixes[i]];
      if (![bill,bond].every(x => x === null || Number.isFinite(x))) fail('has an invalid yield');
      const saved = observations.get(observation);
      if (saved && (saved[0] !== bill || saved[1] !== bond)) fail('assigns two values to the same monthly rate');
      observations.set(observation,[bill,bond]);
      if (live && (r.yieldPath[i]?.date !== observation || r.yieldPath[i].shortYield !== bill || r.yieldPath[i].longYield !== bond)) fail('misdates a frozen yield');
      bills.push(bill === null ? null : Math.round(bill*1e12));
      bonds.push(bond === null ? null : Math.round(bond*1e12));
    }
    const s = diff(bills[3],bills[0]), l = diff(bonds[3],bonds[0]), f = diff(s,l);
    const start = diff(bonds[0],bills[0]), end = diff(bonds[3],bills[3]);
    const rises = bills.includes(null) ? null : bills.slice(1).filter((b,i) => b! > bills[i]!).length;
    const driver = f === null ? 'unavailable' : f <= 0 ? 'no-flattening' : s! > -l! ? 'short-led' : s! < -l! ? 'long-led' : 'equal';
    const pattern = f === null || f <= 0 ? driver : l! > 0 ? 'long-rise-offset' : s! < 0 ? 'short-fall-offset' : l === 0 ? 'short-only' : s === 0 ? 'long-only' : 'both-flatten';
    if (![ [r.shortChange,s],[r.longChange,l],[r.flattening,f],[r.startSlope,start],[r.endSlope,end] ].every(([v,u]) => replayEqual(v,asRate(u)))
      || (end !== null && source.slope !== null && !replayEqual(asRate(end),source.slope))
      || r.driver !== driver || r.pattern !== pattern || r.shortRiseCount !== rises) fail('decomposition disagrees with observed rates');
    const led = f === null ? null : f>0 && s!>0 && s! > -l!;
    const eligible = [led, led === null ? null : led && l!>=0, led === null || rises === null ? null : led && rises===3,
      f === null ? null : f>0 && s!>0 && l!<=0 && s! >= -2*l!];
    rules.forEach((k,i) => {
      if (r[k] !== eligible[i] || r[k+'Alert'] !== (p.levelAlert === null ? null : p.levelAlert || (p.quarterAlert && eligible[i] === true)))
        fail('warning decisions disagree with the two yields');
    });
  }
  trial.history.forEach((r: MacroSnapshot,i: number) => verify(r,pace.history[i],expansion.history[i],false));
  verify(trial.latest,pace.latest,expansion.latest,true);
  validateOverlayResults(trial,pace,previous,rules,fail);
  for (const date of ['2000-05-01','2019-02-01']) {
    const effect = trial.caseEffects?.[date], original = value.confirmationTrial.caseAttribution[date];
    const row = trial.history.find((r: MacroSnapshot) => r.date === date);
    if (!row || !original || !(row.flattening > 0)) {
      if (effect !== null) fail('has unsupported risk attribution');
      continue;
    }
    const curve = original.effects.slope;
    if (!effect || !replayEqual(effect.curveEffect,curve) || !replayEqual(effect.shortEffect,curve*row.shortChange/row.flattening)
      || !replayEqual(effect.longEffect,-curve*row.longChange/row.flattening)) fail('risk attribution does not add up');
  }
}

/** Validate remote research before allowing it to replace a known bundled build. */
export function validateResearchSnapshot(candidate: unknown, base: MacroSnapshot, now = new Date()): MacroSnapshot {
  if (!candidate || typeof candidate !== 'object') throw new Error('Research snapshot is not an object');
  const value = candidate as MacroSnapshot;
  const isMonth = (date: unknown): date is string => typeof date === 'string' && /^\d{4}-(0[1-9]|1[0-2])-01$/.test(date);
  const currentMonth = now.toISOString().slice(0, 7) + '-01';
  if (!value.meta || value.meta.version !== base.meta.version || !value.latest || !value.model) throw new Error('Unsupported research snapshot version or structure');
  const { latest, model, meta } = value;
  if (!isMonth(latest.issueDate) || !isMonth(latest.featureDate) || latest.issueDate > currentMonth
    || latest.issueDate < base.latest.issueDate || latest.featureDate !== monthOffset(latest.issueDate, -2)
    || meta.issueDate !== latest.issueDate || meta.featureDate !== latest.featureDate
    || meta.forecastStart !== monthOffset(latest.issueDate, 1) || meta.forecastEnd !== monthOffset(latest.issueDate, 12)
    || latest.forecastStart !== meta.forecastStart || latest.forecastEnd !== meta.forecastEnd) throw new Error('Inconsistent or regressive research dates');
  const generatedAt = Date.parse(meta.generatedAt);
  const baseGeneratedAt = Date.parse(base.meta.generatedAt);
  if (!Number.isFinite(generatedAt) || generatedAt > now.getTime() + 300_000
    || (Number.isFinite(baseGeneratedAt) && generatedAt < baseGeneratedAt)) throw new Error('Stale or future-dated research build');
  const keys = ['slope', 'credit', 'labor'];
  if (JSON.stringify(model.featureOrder) !== JSON.stringify(keys)
    || !['means', 'scales', 'coefficients'].every(key => Array.isArray(model[key]) && model[key].length === keys.length && model[key].every((item: unknown) => typeof item === 'number' && Number.isFinite(item)))
    || model.scales.some((item: number) => item <= 0) || typeof model.intercept !== 'number' || !Number.isFinite(model.intercept)
    || !latest.features || !keys.every(key => typeof latest.features[key] === 'number' && Number.isFinite(latest.features[key]))
    || latest.features.labor < -1e-10 || typeof latest.probability !== 'number' || !Number.isFinite(latest.probability)
    || latest.probability < 0 || latest.probability > 1) throw new Error('Invalid research model parameters');
  if (Math.abs(score(latest.features, model).probability - latest.probability) > 1e-8) throw new Error('Research probability does not match published model');
  if (!['history', 'sources', 'yieldCurve', 'calibration', 'recessions'].every(key => Array.isArray(value[key]))
    || !value.metrics || !Number.isFinite(value.metrics.n) || !Number.isFinite(value.metrics.model?.brier)
    || !latest.indicators || !Array.isArray(latest.contributions)) throw new Error('Incomplete research payload');
  if (base.innovation) {
    const audit=value.innovation;
    const order=['slope','credit','labor','interaction'];
    if (!audit || audit.version!==base.innovation.version || audit.issueDate!==meta.issueDate || audit.featureDate!==meta.featureDate
      || !audit.latest?.features || !audit.model || JSON.stringify(audit.model.featureOrder)!==JSON.stringify(order)
      || !['means','scales','coefficients'].every(key=>Array.isArray(audit.model[key])&&audit.model[key].length===4&&audit.model[key].every((n:unknown)=>typeof n==='number'&&Number.isFinite(n)))
      || audit.model.scales.some((n:number)=>n<=0) || !Number.isFinite(audit.model.intercept)
      || !order.every(key=>Number.isFinite(audit.latest.features[key])) || !Array.isArray(audit.history)
      || audit.metrics?.n!==value.metrics.n || !Number.isFinite(audit.metrics?.challenger?.brier)) throw new Error('Missing or inconsistent alarm audit');
    const f=audit.latest.features;
    if (Math.abs(f.interaction-Math.max(-f.slope,0)*f.credit)>1e-8
      || keys.some(key=>Math.abs(f[key]-latest.features[key])>1e-8)
      || Math.abs(audit.latest.originalProbability-latest.probability)>1e-8
      || Math.abs(score(f,audit.model).probability-audit.latest.probability)>1e-8) throw new Error('Alarm audit probability or interaction mismatch');
  }
  if (base.ratePath) {
    const trial = value.ratePath, trialLatest = trial?.latest;
    const probability = (p: unknown): p is number => typeof p === 'number' && Number.isFinite(p) && p >= 0 && p <= 1;
    if (!trialLatest || !isMonth(trialLatest.issueDate) || trialLatest.issueDate > meta.issueDate
      || trialLatest.featureDate !== monthOffset(trialLatest.issueDate, -2)
      || trialLatest.forecastStart !== monthOffset(trialLatest.issueDate, 1)
      || trialLatest.forecastEnd !== monthOffset(trialLatest.issueDate, 12)
      || !Array.isArray(trial.history) || !trial.metrics?.all?.models?.recentBlend || !trial.metrics?.recent
      || !probability(trialLatest.rawProbability) || !probability(trialLatest.baselineProbability)
      || !probability(trialLatest.probability)
      || Math.abs(trialLatest.probability - (trialLatest.rawProbability + trialLatest.baselineProbability) / 2) > 1e-8) {
      throw new Error('Missing or inconsistent rate-path research');
    }
    if (trialLatest.recentBlendProbability != null && (!probability(trialLatest.recentBlendProbability)
      || !probability(trialLatest.recentPriorProbability) || !probability(trialLatest.originalProbability)
      || Math.abs(trialLatest.recentBlendProbability - (trialLatest.originalProbability + trialLatest.recentPriorProbability) / 2) > 1e-8)) {
      throw new Error('Invalid recent-base research probability');
    }
    const previous = base.ratePath.prospective?.receipts;
    if (previous?.length) {
      const archive = trial.prospective;
      if (!archive?.chainValid || !Array.isArray(archive.receipts) || archive.receiptCount !== archive.receipts.length
        || previous.some((row: {hash: string}, i: number) => archive.receipts[i]?.hash !== row.hash)) {
        throw new Error('Rate-path forecast record missing or regressive');
      }
    }
  }
  if (base.regimePrior) {
    const trial = value.regimePrior;
    const current = trial?.latest;
    const probability = (p: unknown): p is number => typeof p === 'number' && p >= 0 && p <= 1;
    const matches = (p: unknown, expected: number) => probability(p) && Math.abs(p - expected) < 1e-8;
    if (!current || trial.spec?.id !== base.regimePrior.spec.id || current.issueDate !== latest.issueDate
      || current.featureDate !== latest.featureDate || current.forecastStart !== latest.forecastStart
      || current.forecastEnd !== latest.forecastEnd || !matches(current.originalProbability, latest.probability)
      || !matches(current.fixedBlendProbability, (latest.probability + latest.baselineProbability) / 2)
      || typeof current.available !== 'boolean' || !Array.isArray(trial.history)
      || ![0, 120].includes(trial.metrics?.rolling120?.expectedCalendarMonths)
      || !trial.metrics?.all?.models?.candidate || !trial.metrics?.rolling120?.models?.adaptive) {
      throw new Error('Missing or inconsistent regime research');
    }
    if (current.available) {
      const cell = current.stateMap?.find((row: {id: string}) => row.id === current.state);
      const credit = Number(latest.features.credit.toFixed(10)), labor = Number(latest.features.labor.toFixed(10));
      const state = (credit > 0 ? 'tight-' : 'loose-') + (labor >= .5 ? 'elevated' : 'low');
      const pool = current.recentPriorProbability, alpha = current.regimeWeight;
      if (!cell || current.state !== state || !probability(pool) || !probability(alpha)
        || !Number.isInteger(cell.n) || !Number.isInteger(cell.positiveWindows)
        || cell.n < 0 || cell.positiveWindows < 0 || cell.positiveWindows > cell.n
        || !matches(current.dynamicPriorProbability, (cell.positiveWindows + 24 * pool) / (cell.n + 24))
        || !matches(current.adaptivePriorProbability, pool + alpha * (current.dynamicPriorProbability - pool))
        || !matches(current.probability, (latest.probability + current.dynamicPriorProbability) / 2)
        || !matches(current.adaptiveProbability, (latest.probability + current.adaptivePriorProbability) / 2)) {
        throw new Error('Invalid regime forecast or adaptive weight');
      }
    } else if (current.probability != null || current.adaptiveProbability != null) {
      throw new Error('Unavailable regime forecast has a published probability');
    }
    const previous = base.regimePrior.prospective?.receipts;
    if (previous?.length) {
      const archive = trial.prospective;
      if (!archive?.chainValid || !Array.isArray(archive.receipts) || archive.receiptCount !== archive.receipts.length
        || previous.some((row: {hash: string}, i: number) => archive.receipts[i]?.hash !== row.hash)) {
        throw new Error('Regime forecast record missing or regressive');
      }
    }
  }
  if (base.leadingTrial) {
    const trial = value.leadingTrial, current = trial?.latest;
    const sameProbability = (p: unknown, q: number) => typeof p === 'number' && p >= 0 && p <= 1 && Math.abs(p - q) < 1e-8;
    if (!current || trial.spec?.id !== base.leadingTrial.spec.id || current.issueDate !== latest.issueDate
      || current.featureDate !== latest.featureDate || current.forecastStart !== latest.forecastStart
      || current.forecastEnd !== latest.forecastEnd || !sameProbability(current.originalProbability, latest.probability)
      || !sameProbability(current.baselineProbability, latest.baselineProbability)
      || !sameProbability(current.existingBlendProbability, (latest.probability + latest.baselineProbability) / 2)
      || !Array.isArray(trial.history) || !Array.isArray(trial.diagnostics?.episodes)) {
      throw new Error('Missing or inconsistent leading-indicator research');
    }
    const columns = {
      joint: ['slope','credit','labor','permitGrowth6','claimsGrowth12'],
      permits: ['slope','credit','labor','permitGrowth6'], claims: ['slope','credit','labor','claimsGrowth12'],
      matchedThree: ['slope','credit','labor'],
    };
    const fields = {joint:'probability', permits:'permitsBlendProbability', claims:'claimsBlendProbability', matchedThree:'matchedThreeBlendProbability'};
    if (current.available === true) {
      for (const name of Object.keys(columns) as (keyof typeof columns)[]) {
        const model = trial.currentModels?.[name], keys = columns[name];
        if (!model || JSON.stringify(model.featureOrder) !== JSON.stringify(keys)
          || !keys.every(k => Number.isFinite(current.features?.[k]))
          || !Number.isFinite(model.intercept) || model.refitDate !== current.issueDate
          || !isMonth(model.lastTargetMonth) || model.lastTargetMonth >= current.issueDate
          || !['means','scales','coefficients'].every(k => Array.isArray(model[k]) && model[k].length === keys.length && model[k].every(Number.isFinite))
          || model.scales.some((n:number) => n <= 0)) throw new Error('Invalid leading-indicator parameters');
        const raw = score(current.features, model).probability;
        if (!sameProbability(current[fields[name]], (raw + latest.baselineProbability) / 2)
          || (name === 'joint' && !sameProbability(current.rawProbability, raw))) throw new Error('Invalid leading-indicator forecast');
      }
    } else if (current.available !== false || current.rawProbability != null || Object.values(fields).some(key => current[key] != null)) {
      throw new Error('Incomplete leading-indicator forecast');
    }
    for (const name of ['all', 'rolling120']) {
      const sample = trial.metrics?.[name];
      if (!Number.isInteger(sample?.n) || sample.n !== trial.diagnostics.windows?.[name]?.n
        || !sample.models?.existingBlend || !sample.models?.permitsBlend || !sample.models?.candidate) {
        throw new Error('Inconsistent leading-indicator evaluation months');
      }
    }
    const previous = base.leadingTrial.prospective?.receipts;
    if (previous?.length) {
      const archive = trial.prospective;
      if (!archive?.chainValid || !Array.isArray(archive.receipts) || archive.receiptCount !== archive.receipts.length
        || previous.some((row:{hash:string}, i:number) => archive.receipts[i]?.hash !== row.hash)) {
        throw new Error('Leading-indicator forecast record missing or regressive');
      }
    }
  }
  if (base.weightTrial) {
    const trial = value.weightTrial, current = trial?.latest;
    const lead = value.leadingTrial?.latest;
    const matches = (p: unknown, expected: number) => typeof p === 'number' && p >= 0 && p <= 1 && Math.abs(p - expected) < 1e-8;
    if (!current || !lead || trial.spec?.id !== base.weightTrial.spec.id
      || current.issueDate !== latest.issueDate || current.featureDate !== latest.featureDate
      || current.forecastStart !== latest.forecastStart || current.forecastEnd !== latest.forecastEnd
      || !matches(current.existingBlendProbability,(latest.baselineProbability+latest.probability)/2)
      || typeof current.available !== 'boolean' || !Array.isArray(trial.history) || trial.warnings?.threshold !== .30) {
      throw new Error('Missing or inconsistent adaptive-weight trial');
    }
    if (current.available) {
      const fit = current.fit;
      const credit = Number(latest.features.credit.toFixed(10)), slope = Number(latest.features.slope.toFixed(10));
      const state = slope < 0 || credit > 0 ? 'stress' : 'normal';
      const predicted = (signal: number, weight: number) => latest.baselineProbability + weight*(signal-latest.baselineProbability);
      if (!lead.available || current.state !== state || fit?.refitDate !== current.issueDate
        || fit.trainingCutoff !== monthOffset(current.issueDate,-13)
        || !matches(current.fixedPermitsProbability,lead.permitsBlendProbability)
        || !matches(current.rawPermitsProbability,2*lead.permitsBlendProbability-latest.baselineProbability)
        || !matches(current.permitsWeight,fit.permits?.[state]?.weight)
        || !matches(current.pooledWeight,fit.permits?.pool?.weight)
        || !matches(current.originalWeight,fit.original?.[state]?.weight)
        || !matches(current.fixedRuleWeight,state === 'stress' ? .75 : .25)
        || !matches(current.probability,predicted(current.rawPermitsProbability,current.permitsWeight))
        || !matches(current.fixedRuleProbability,predicted(current.rawPermitsProbability,current.fixedRuleWeight))
        || !matches(current.pooledPermitsProbability,predicted(current.rawPermitsProbability,current.pooledWeight))
        || !matches(current.originalDynamicProbability,predicted(latest.probability,current.originalWeight))) {
        throw new Error('Adaptive-weight forecast disagrees with its inputs or fitted weights');
      }
      for (const arm of [fit.permits, fit.original]) {
        if (!Number.isInteger(fit.trainingN) || fit.trainingN < 0 || fit.warmup !== (fit.trainingN < 60)
          || arm?.pool?.n !== fit.trainingN || arm.normal?.n + arm.stress?.n !== fit.trainingN) {
          throw new Error('Adaptive-weight fit has inconsistent training counts');
        }
        for (const name of ['pool', 'normal', 'stress']) {
          const cell = arm[name], anchor = name === 'pool' ? .5 : arm.pool.weight;
          if (!Number.isInteger(cell.n) || cell.n < 0 || !Number.isFinite(cell.numerator)
            || !Number.isFinite(cell.denominator) || cell.denominator < 0
            || !matches(cell.weight, fit.warmup ? .5 : Math.max(0, Math.min(1, (cell.numerator + anchor) / (cell.denominator + 1))))) {
            throw new Error('Adaptive-weight fit disagrees with its training statistics');
          }
        }
        for (const stat of ['numerator', 'denominator']) {
          if (Math.abs(arm.pool[stat] - arm.normal[stat] - arm.stress[stat]) > 1e-8)
            throw new Error('Adaptive-weight fit disagrees with pooled training statistics');
        }
      }
    } else if (current.probability != null || (!lead.available && [
      current.rawPermitsProbability, current.fixedPermitsProbability, current.fixedRuleProbability, current.pooledPermitsProbability,
    ].some(value => value != null))) throw new Error('Unavailable adaptive-weight forecast has a value');
    for (const key of ['all','rolling120']) {
      const window = trial.metrics?.[key];
      if (!Number.isInteger(window?.n) || window.n !== trial.warnings.windows?.[key]?.n
        || !window.models?.fixedRule || !window.models?.candidate || !window.models?.existingBlend) {
        throw new Error('Adaptive-weight errors and warnings must use the same evaluation months');
      }
    }
    const previous = base.weightTrial.prospective?.receipts;
    if (previous?.length) {
      const archive = trial.prospective;
      if (!archive?.chainValid || !Array.isArray(archive.receipts) || archive.receiptCount !== archive.receipts.length
        || previous.some((row:{hash:string},i:number) => archive.receipts[i]?.hash !== row.hash)) {
        throw new Error('Adaptive-weight forecast record missing or regressive');
      }
    }
  }
  if (base.creditTrial) {
    const trial = value.creditTrial, current = trial?.latest, lead = value.leadingTrial?.latest;
    const near = (x: unknown, y: unknown) => typeof x === 'number' && typeof y === 'number' && Math.abs(x-y) < 1e-8;
    const fields: Record<string,string> = {
      matchedLevel:'matchedLevelProbability', slowOnly:'slowOnlyProbability', shockOnly:'shockOnlyProbability', candidate:'probability',
    };
    if (!current || !lead || trial.spec?.id !== base.creditTrial.spec.id
      || !['issueDate','featureDate','forecastStart','forecastEnd'].every(key => current[key] === latest[key])
      || !near(current.baselineProbability, latest.baselineProbability)
      || !(current.benchmarkProbability === null && lead.permitsBlendProbability === null
        || near(current.benchmarkProbability,lead.permitsBlendProbability))
      || !Array.isArray(trial.history) || trial.warnings?.threshold !== .30 || typeof current.available !== 'boolean') {
      throw new Error('Missing or inconsistent credit dynamics trial');
    }
    if (current.available) {
      if (!lead.available || !['slope','credit','labor','permitGrowth6'].every(k => near(current[k],lead.features[k]))
        || !near(current.credit,current.creditSlow + current.creditShock)
        || typeof current.persistent !== 'boolean' || !Number.isFinite(current.creditSlow) || !Number.isFinite(current.creditShock)
        || !(current.shockThreshold === null ? current.sudden === null
          : Number.isFinite(current.shockThreshold) && current.sudden === (
            Number(current.creditShock.toFixed(12)) > Math.max(0,Number(current.shockThreshold.toFixed(12)))))) {
        throw new Error('Inconsistent credit dynamics signals');
      }
      for (const [arm, field] of Object.entries(fields)) {
        const model = trial.currentModels?.[arm], order = base.creditTrial.spec.models[arm];
        if (!model || JSON.stringify(model.featureOrder) !== JSON.stringify(order)
          || !Number.isFinite(model.intercept) || model.refitDate !== current.issueDate
          || model.trainingCutoff !== monthOffset(current.issueDate,-13)
          || !isMonth(model.trainedThrough) || model.trainedThrough > model.trainingCutoff
          || model.lastTargetMonth !== monthOffset(model.trainedThrough,12)
          || !['means','scales','coefficients'].every(k => Array.isArray(model[k]) && model[k].length === order.length && model[k].every(Number.isFinite))
          || model.scales.some((v:number) => v <= 0)
          || !near(current[field],(score(current,model).probability + current.baselineProbability)/2)) {
          throw new Error('Credit dynamics model parameters or forecasts disagree');
        }
      }
    } else if (Object.values(fields).some(k => current[k] != null)) throw new Error('Unavailable credit dynamics forecast has a value');
    for (const key of ['all','rolling120']) {
      const w = trial.warnings.windows?.[key], s = trial.metrics?.[key], groups = trial.warnings.buckets?.[key];
      if (!w || !s || w.n !== s.n || w.windowStart !== s.windowStart || w.windowEnd !== s.windowEnd
        || !s.models?.benchmark || !s.models?.candidate || !Array.isArray(groups)
        || groups.reduce((sum:number,g:{n:number}) => sum + g.n,0) !== s.n
        || groups.reduce((sum:number,g:{quietN:number}) => sum + g.quietN,0) !== w.quietExpansionN) {
        throw new Error('Credit dynamics reports require common evaluation months');
      }
    }
    const previous = base.creditTrial.prospective?.receipts;
    if (previous?.length) {
      const archive = trial.prospective;
      if (!archive?.chainValid || !Array.isArray(archive.receipts) || archive.receiptCount !== archive.receipts.length
        || previous.some((r:{hash:string},i:number) => archive.receipts[i]?.hash !== r.hash)) {
        throw new Error('Credit dynamics record missing or regressive');
      }
    }
  }
  if (base.expansionTrial) {
    const trial = value.expansionTrial, c = trial?.latest, lead = value.leadingTrial?.latest;
    const near = (a: unknown, b: unknown) => typeof a === 'number' && typeof b === 'number' && Math.abs(a-b) < 1e-8;
    if (!c || !lead || trial.spec?.id !== base.expansionTrial.spec.id || !Array.isArray(trial.history)
      || c.conditionalOnExpansion !== true || typeof c.available !== 'boolean'
      || !['issueDate','featureDate','forecastStart','forecastEnd'].every(k => c[k] === latest[k])
      || !near(c.baselineProbability,latest.baselineProbability)
      || !(c.benchmarkProbability === null && lead.permitsBlendProbability === null
        || near(c.benchmarkProbability,lead.permitsBlendProbability))) {
      throw new Error('Missing or inconsistent expansion-onset trial');
    }
    if (c.available) {
      const model = trial.currentModel, order = ['slope','credit','labor','permitGrowth6'];
      if (!lead.available || !model || JSON.stringify(model.featureOrder) !== JSON.stringify(order)
        || !order.every(k => near(c[k],lead.features[k])) || !Number.isFinite(model.intercept) || model.penalty !== 1
        || !['means','scales','coefficients'].every(k => Array.isArray(model[k]) && model[k].length === order.length && model[k].every(Number.isFinite))
        || model.scales.some((v:number) => v <= 0) || c.refitDate !== c.issueDate
        || c.trainingCutoff !== monthOffset(c.refitDate,-13) || !isMonth(c.trainEnd) || c.trainEnd > c.trainingCutoff
        || c.lastTargetMonth !== monthOffset(c.trainEnd,12) || c.lastTargetMonth >= c.issueDate
        || !['trainingN','trainingPositives','trainingOnsets','refitDate','trainingCutoff','lastTargetMonth'].every(k => model[k] === c[k])
        || model.trainedFrom !== c.trainStart || model.trainedThrough !== c.trainEnd
        || ![c.trainingN,c.trainingPositives,c.trainingOnsets].every(Number.isInteger) || c.trainingN < 100
        || c.trainingOnsets < 1 || c.trainingOnsets > c.trainingPositives || c.trainingPositives >= c.trainingN
        || !near(c.expansionPriorProbability,c.trainingPositives/c.trainingN)
        || !near(c.rawExpansionProbability,score(c,model).probability)
        || !near(c.rawPermitsProbability,2*c.benchmarkProbability-c.baselineProbability)
        || !near(c.probability,(c.rawExpansionProbability+c.expansionPriorProbability)/2)
        || !near(c.signalOnlyChangeProbability,(c.rawExpansionProbability+c.baselineProbability)/2)
        || !near(c.baseOnlyChangeProbability,(c.rawPermitsProbability+c.expansionPriorProbability)/2)) {
        throw new Error('Expansion-onset forecast or training clock disagrees with recorded inputs');
      }
    } else if (c.probability != null || c.signalOnlyChangeProbability != null || c.baseOnlyChangeProbability != null) {
      throw new Error('Unavailable expansion-onset comparison has a published forecast');
    }
    for (const key of ['all','rolling120']) {
      const s = trial.metrics?.[key], w = trial.warnings?.windows?.[key];
      const signalCheck = w?.expansionAtBothDates;
      if (base.expansionTrial.warnings?.windows?.[key]?.expansionAtBothDates && (!signalCheck
        || signalCheck.n + signalCheck.unknownSignalMonths + signalCheck.recessionSignalMonths !== w.n)) {
        throw new Error('Expansion-onset signal-month cohort is inconsistent');
      }
      if (!s || !w || trial.warnings.threshold !== .30 || w.windowStart !== s.windowStart
        || w.windowEnd !== s.windowEnd || w.n !== s.n || w.preOnsetN !== s.positiveWindows
        || w.preOnsetN + w.quietExpansionN !== s.n || w.outcomeScores?.quiet?.n !== w.quietExpansionN
        || w.outcomeScores?.preOnset?.n !== w.preOnsetN || s.expansionN !== s.n + s.missingCandidateMonths
        || s.matureBenchmarkN !== s.expansionN + s.recessionN + s.unknownPhaseN + s.incompleteHorizonN
        || s.expectedCalendarMonths !== s.matureBenchmarkN + s.missingBenchmarkMonths
        || !s.models?.expansionPrior || !s.models?.candidate || !s.models?.benchmark) {
        throw new Error('Expansion-onset evaluation cohorts disagree');
      }
    }
    const previous = base.expansionTrial.prospective, archive = trial.prospective;
    if (previous?.receiptCount || archive) {
      if (!archive?.chainValid || !Array.isArray(archive.receipts) || archive.receipts.length !== archive.receiptCount
        || ![archive.maturedCount,archive.excludedCount,archive.pendingCount].every(n => Number.isInteger(n) && n >= 0)
        || archive.receiptCount !== archive.maturedCount + archive.excludedCount + archive.pendingCount
        || previous?.receipts?.some((r:{hash:string},i:number) => archive.receipts[i]?.hash !== r.hash)) {
        throw new Error('Expansion-onset forecast records missing, inconsistent or regressive');
      }
    }
  }
  if (base.momentumTrial) validateMomentum(value, base.momentumTrial);
  if (base.confirmationTrial) validateConfirmation(value, base.confirmationTrial);
  if (base.curveLegsTrial) validateCurveLegs(value, base.curveLegsTrial);
  if (base.curveStabilityTrial) validateCurveStability(value.curveStabilityTrial,value.curveLegsTrial,base.curveStabilityTrial);
  if (base.jointStressTrial) validateJointStress(value.jointStressTrial, value.expansionTrial, value.momentumTrial, value.curveStabilityTrial, base.jointStressTrial);
  if (base.pathSimulationTrial) validatePathSimulation(value.pathSimulationTrial, value.jointStressTrial, base.pathSimulationTrial);
  if (base.prospective) {
    const archive=value.prospective;
    if (!archive || archive.protocolVersion!==base.prospective.protocolVersion || archive.chainValid!==true
      || !Array.isArray(archive.receipts) || archive.receiptCount!==archive.receipts.length || archive.receiptCount<1
      || !archive.latestReceipt || archive.latestReceipt.issueDate>meta.issueDate
      || !/^[a-f0-9]{64}$/.test(archive.lastHash??'') || archive.lastHash!==archive.latestReceipt.hash
      || !Array.isArray(archive.outcomes) || archive.maturedCount<0 || archive.maturedCount>archive.receiptCount) throw new Error('Missing or inconsistent forecast archive');
  }
  return value;
}

export async function refreshResearchSnapshot(base: MacroSnapshot, now = new Date(), loader: typeof fetch = fetch): Promise<MacroSnapshot> {
  const response = await loader(uncachedResearchUrl(RESEARCH_SNAPSHOT_URL, now.getTime()), { signal: AbortSignal.timeout(5_000), headers: { Accept: 'application/json' }, cache: 'no-store' });
  if (!response.ok) throw new Error(`Research snapshot request failed (${response.status})`);
  const value = structuredClone(validateResearchSnapshot(await response.json(), base, now));
  const checkedAt = now.toISOString();
  const currentMonth = checkedAt.slice(0, 7) + '-01';
  const issueDate = value.latest.issueDate;
  value.meta.refresh = {
    status: 'fresh', checkedAt, lastSuccessfulRefresh: checkedAt,
    sourceUpdatedAt: value.meta.generatedAt, source: 'github-actions', sourceUrl: RESEARCH_SNAPSHOT_URL,
    cacheTtlSeconds: TTL / 1000,
    inputMonthsBehind: (Number(currentMonth.slice(0, 4)) - Number(issueDate.slice(0, 4))) * 12 + Number(currentMonth.slice(5, 7)) - Number(issueDate.slice(5, 7)),
    mode: 'Scheduled research build',
    note: 'A GitHub Actions research job refreshes public FRED data and refits the model on weekdays. This endpoint checks that published build hourly; observation and research-build dates are preserved.'
  };
  return value;
}

export async function getMacroSnapshot(base: MacroSnapshot): Promise<MacroSnapshot> {
  if (cached && Date.now() - cached.at < TTL) return cached.value;
  if (inFlight) return inFlight;
  const known = cached?.value ?? base;
  inFlight = refreshResearchSnapshot(known).catch(() => refreshSnapshot(known)).then(value => {
    cached = { at: Date.now(), value }; return value;
  }).catch((error: unknown) => {
    const failure = error instanceof Error ? error : new Error('Unknown refresh failure');
    console.warn('[HORIZON] Research and FRED refresh unavailable', { name: failure.name, message: failure.message });
    const fallback = structuredClone(cached?.value ?? base);
    fallback.meta = { ...fallback.meta, refresh: { status: 'fallback', checkedAt: new Date().toISOString(), cacheTtlSeconds: 60,
      lastSuccessfulRefresh: cached?.value.meta?.refresh?.lastSuccessfulRefresh ?? null,
      source: cached?.value.meta?.refresh?.source ?? 'bundled-snapshot', sourceUpdatedAt: fallback.meta.generatedAt,
      mode: cached ? 'Last verified research data' : 'Bundled research snapshot',
      note: 'The scheduled research build and direct provider refresh were unavailable. Original observation and model dates are preserved; retry in one minute.' } };
    return fallback;
  }).finally(() => { inFlight = undefined; });
  return inFlight;
}
