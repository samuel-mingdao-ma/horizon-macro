/** Live public-data inference. Fitting and validation stay in research/build_model.py. */
export type Observation = { date: string; value: number };
export type MacroSnapshot = Record<string, any>;
const IDS = ['GS10', 'TB3MS', 'NFCICREDIT', 'UNRATE', 'CPIAUCSL', 'FEDFUNDS', 'GS1', 'GS2', 'GS5', 'GS30'];
const TTL = 60 * 60 * 1000;
export const RESEARCH_SNAPSHOT_URL = 'https://raw.githubusercontent.com/samuel-mingdao-ma/horizon-macro/main/public/data/snapshot.json';
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
  return value;
}

export async function refreshResearchSnapshot(base: MacroSnapshot, now = new Date(), loader: typeof fetch = fetch): Promise<MacroSnapshot> {
  const response = await loader(RESEARCH_SNAPSHOT_URL, { signal: AbortSignal.timeout(5_000), headers: { Accept: 'application/json' }, cache: 'no-store' });
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
