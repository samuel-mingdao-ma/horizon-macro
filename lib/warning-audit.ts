/** Pure retrospective warning audit. No dates or outcomes are inferred. */
export type WarningRuleId = 'original' | 'curve' | 'challenger' | 'blend' | 'base' | 'gate';
export const WARNING_RULES: readonly WarningRuleId[] = ['original', 'curve', 'challenger', 'blend', 'base', 'gate'];
export type WarningRuleMetrics = {
  n: number; positiveWindows: number; auc: number | null; brier: number | null; logLoss: number | null;
  tp: number; fp: number; fn: number; tn: number; alertMonths: number; missingScoreCount: number;
};
export type WarningCohort = {
  n: number; positiveWindows: number; recessionIssueCount: number; unknownRegimeCount: number;
  start: string | null; end: string | null; rules: Record<WarningRuleId, WarningRuleMetrics>;
};
export type EpisodeWarning = {
  availableMonths: number; expectedMonths: 12; coverage: 'complete' | 'partial';
  alertMonths: number; alertDates: string[]; firstAlertDate: string | null; leadMonths: number | null; hit: boolean;
};
export type WarningEpisode = {
  start: string; end: string | null; availableMonths: number; expectedMonths: 12; coverage: 'complete' | 'partial';
  rules: Record<WarningRuleId, EpisodeWarning>;
};
export type WarningEpisodeAggregate = {
  totalEpisodes: number; completeEpisodes: number; hitEpisodes: number; partialEpisodes: number;
  hitRate: number | null; meanFirstAlertLeadMonths: number | null;
};
export type WarningAudit = {
  threshold: number; disclosure: string; cohorts: { all: WarningCohort; expansion: WarningCohort };
  episodes: WarningEpisode[]; episodeAggregate: Record<WarningRuleId, WarningEpisodeAggregate>;
};
type ObjectRow = Record<string, unknown>;
type PreparedRow = {
  date: string; month: number; target: 0 | 1 | null; recession: 0 | 1 | null;
  credit: number | null; labor: number | null; scores: Record<Exclude<WarningRuleId, 'gate'>, number | null>;
};
const object = (value: unknown): ObjectRow => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as ObjectRow : {};
const rows = (value: unknown): ObjectRow[] => Array.isArray(value) ? value.map(object) : [];
const finite = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null;
const probability = (value: unknown): number | null => { const p = finite(value); return p !== null && p >= 0 && p <= 1 ? p : null; };
const binary = (value: unknown): 0 | 1 | null => value === 0 || value === 1 ? value : null;

/** Month arithmetic is UTC-calendar integer arithmetic, with no locale or Date parsing. */
function monthNumber(value: unknown): number | null {
  if (typeof value !== 'string') return null;
  const match = /^(\d{4})-(\d{2})-01(?:T.*)?$/.exec(value);
  if (!match) return null;
  const year = Number(match[1]), month = Number(match[2]);
  return month >= 1 && month <= 12 ? year * 12 + month - 1 : null;
}
function monthString(value: number): string {
  return `${String(Math.floor(value / 12)).padStart(4, '0')}-${String(value % 12 + 1).padStart(2, '0')}-01`;
}
function prepare(snapshot: ObjectRow): PreparedRow[] {
  const base = new Map<number, ObjectRow>(), experimental = new Map<number, ObjectRow>();
  for (const [input, output] of [[rows(snapshot.history), base], [rows(object(snapshot.innovation).history), experimental]] as const) {
    for (const row of input) { const month = monthNumber(row.date); if (month !== null) output.set(month, row); }
  }
  const result: PreparedRow[] = [];
  for (const month of [...new Set([...base.keys(), ...experimental.keys()])].sort((a, b) => a - b)) {
    const ordinary = base.get(month), extra = experimental.get(month) ?? {};
    // Existing base labels, including explicit unknowns, are authoritative.
    const labels = ordinary ?? extra;
    const original = probability(extra.originalProbability) ?? probability(ordinary?.probability);
    const baseline = probability(extra.baseline) ?? probability(ordinary?.baseline);
    const blend = probability(extra.blendProbability) ?? probability(ordinary?.blendProbability)
      ?? (original !== null && baseline !== null ? .5 * original + .5 * baseline : null);
    result.push({ date: monthString(month), month, target: binary(labels.target), recession: binary(labels.recession),
      credit: finite(extra.credit) ?? finite(ordinary?.credit), labor: finite(extra.labor) ?? finite(ordinary?.labor),
      scores: { original, curve: probability(extra.curveProbability) ?? probability(ordinary?.curveProbability),
        challenger: probability(extra.challengerProbability), blend, base: baseline } });
  }
  return result;
}
function alert(row: PreparedRow, rule: WarningRuleId, threshold: number): boolean | null {
  if (rule !== 'gate') { const p = row.scores[rule]; return p === null ? null : p >= threshold; }
  const curve = row.scores.curve;
  if (curve === null) return null;
  if (curve < threshold) return false;
  if ((row.credit !== null && row.credit > 0) || (row.labor !== null && row.labor >= .5)) return true;
  return row.credit === null || row.labor === null ? null : false;
}
function rankedAuc(input: { target: 0 | 1; probability: number }[]): number | null {
  const positives = input.reduce((n, row) => n + row.target, 0), negatives = input.length - positives;
  if (!positives || !negatives) return null;
  const sorted = [...input].sort((a, b) => a.probability - b.probability);
  let positiveRankSum = 0;
  for (let begin = 0; begin < sorted.length;) {
    let end = begin + 1;
    while (end < sorted.length && sorted[end].probability === sorted[begin].probability) end++;
    const averageRank = (begin + 1 + end) / 2;
    for (let i = begin; i < end; i++) if (sorted[i].target === 1) positiveRankSum += averageRank;
    begin = end;
  }
  return (positiveRankSum - positives * (positives + 1) / 2) / (positives * negatives);
}
function cohort(input: PreparedRow[], threshold: number): WarningCohort {
  const mature = input.filter((row): row is PreparedRow & { target: 0 | 1 } => row.target !== null);
  const rules = {} as Record<WarningRuleId, WarningRuleMetrics>;
  for (const rule of WARNING_RULES) {
    const available = mature.filter(row => alert(row, rule, threshold) !== null);
    let tp = 0, fp = 0, fn = 0, tn = 0, brier = 0, logLoss = 0;
    const scored: { target: 0 | 1; probability: number }[] = [];
    for (const row of available) {
      const signal = alert(row, rule, threshold)!;
      if (signal && row.target === 1) tp++; else if (signal) fp++; else if (row.target === 1) fn++; else tn++;
      if (rule !== 'gate') {
        const p = row.scores[rule]!;
        scored.push({ target: row.target, probability: p });
        brier += (p - row.target) ** 2;
        const clipped = Math.max(1e-12, Math.min(1 - 1e-12, p));
        logLoss -= row.target * Math.log(clipped) + (1 - row.target) * Math.log(1 - clipped);
      }
    }
    rules[rule] = { n: available.length, positiveWindows: tp + fn,
      auc: rule === 'gate' ? null : rankedAuc(scored),
      brier: scored.length ? brier / scored.length : null, logLoss: scored.length ? logLoss / scored.length : null,
      tp, fp, fn, tn, alertMonths: tp + fp, missingScoreCount: mature.length - available.length };
  }
  return { n: mature.length, positiveWindows: mature.reduce((n, row) => n + row.target, 0),
    recessionIssueCount: mature.filter(row => row.recession === 1).length,
    unknownRegimeCount: mature.filter(row => row.recession === null).length,
    start: mature[0]?.date ?? null, end: mature.at(-1)?.date ?? null, rules };
}

export function deriveWarningAudit(snapshot: unknown, threshold = .30): WarningAudit {
  if (typeof threshold !== 'number' || !Number.isFinite(threshold) || threshold < 0 || threshold > 1)
    throw new RangeError('Warning threshold must be a finite probability between 0 and 1.');
  const source = object(snapshot), prepared = prepare(source);
  const episodes: WarningEpisode[] = [], seen = new Set<number>();
  for (const period of rows(source.recessions).sort((a, b) => (monthNumber(a.start) ?? -1) - (monthNumber(b.start) ?? -1))) {
    const onset = monthNumber(period.start);
    if (onset === null || seen.has(onset)) continue;
    seen.add(onset);
    const eligible = prepared.filter(row => row.month >= onset - 12 && row.month < onset && row.recession === 0 && row.target !== null);
    const rules = {} as Record<WarningRuleId, EpisodeWarning>;
    for (const rule of WARNING_RULES) {
      const available = eligible.filter(row => alert(row, rule, threshold) !== null);
      const alerts = available.filter(row => alert(row, rule, threshold));
      rules[rule] = { availableMonths: available.length, expectedMonths: 12, coverage: available.length === 12 ? 'complete' : 'partial',
        alertMonths: alerts.length, alertDates: alerts.map(row => row.date), firstAlertDate: alerts[0]?.date ?? null,
        leadMonths: alerts.length ? onset - alerts[0].month : null, hit: alerts.length > 0 };
    }
    // Exclude episodes outside this dataset's time span, rather than padding them with zero warnings.
    const firstMonth = prepared[0]?.month, lastMonth = prepared.at(-1)?.month;
    if (firstMonth === undefined || lastMonth === undefined || onset <= firstMonth || onset > lastMonth + 1) continue;
    episodes.push({ start: monthString(onset), end: typeof period.end === 'string' ? period.end : null,
      availableMonths: eligible.length, expectedMonths: 12, coverage: eligible.length === 12 ? 'complete' : 'partial', rules });
  }
  const episodeAggregate = {} as Record<WarningRuleId, WarningEpisodeAggregate>;
  for (const rule of WARNING_RULES) {
    const complete = episodes.filter(episode => episode.rules[rule].coverage === 'complete');
    const hits = complete.filter(episode => episode.rules[rule].hit);
    episodeAggregate[rule] = { totalEpisodes: episodes.length, completeEpisodes: complete.length, hitEpisodes: hits.length,
      partialEpisodes: episodes.length - complete.length, hitRate: complete.length ? hits.length / complete.length : null,
      meanFirstAlertLeadMonths: hits.length ? hits.reduce((n, episode) => n + episode.rules[rule].leadMonths!, 0) / hits.length : null };
  }
  return { threshold,
    disclosure: 'Latest-vintage retrospective audit using revised history and retrospective USREC labels. Expansion-issued means issue-month USREC equals 0 in today’s history, not a regime known in real time. The model retains its original any-recession-month-in-the-next 12 months target; it is not onset-trained. Monthly targets overlap. Gate is a supplementary alarm policy, so probability scores are undefined for it. Episode hits count only strictly pre-onset expansion issues with known targets; incomplete 12-month coverage is excluded from complete-episode hit rates.',
    cohorts: { all: cohort(prepared, threshold), expansion: cohort(prepared.filter(row => row.recession === 0), threshold) },
    episodes, episodeAggregate };
}
