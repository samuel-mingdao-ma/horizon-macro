/** Consecutive annual-replay alarms, with explicit gaps, outcomes and censoring. */
import { warningReplayRows, type WarningReplayRow } from './warning-audit.ts';
export type AlarmSpellRule = 'original' | 'curve' | 'challenger' | 'gate';
export type AlarmSpellClassification = 'positive' | 'false' | 'mixed' | 'pending';
export type AlarmBoundary =
  | 'observed-non-alarm'
  | 'dataset-boundary'
  | 'missing-date'
  | 'missing-signal'
  | 'observed-positive'
  | 'pending-outcome';
export type AlarmMonth = {
  date: string;
  probability: number | null;
  curveProbability: number | null;
  alarm: boolean | null;
  target: 0 | 1 | null;
  status: 'positive' | 'false' | 'pending' | 'quiet' | 'missing';
  spellId: string | null;
};
export type AlarmSpell = {
  id: string;
  start: string;
  end: string;
  months: number;
  classification: AlarmSpellClassification;
  falseMonths: number;
  positiveMonths: number;
  pendingMonths: number;
  leftCensored: boolean;
  rightCensored: boolean;
  leftBoundary: AlarmBoundary;
  rightBoundary: AlarmBoundary;
};
export type FalseWarningStreak = {
  start: string;
  end: string;
  months: number;
  leftCensored: boolean;
  rightCensored: boolean;
  leftBoundary: AlarmBoundary;
  rightBoundary: AlarmBoundary;
};
export type AlarmSpellAudit = {
  version: '1.0';
  rule: AlarmSpellRule;
  threshold: number;
  disclosure: string;
  scoreMeaning: string;
  coverage: {
    start: string | null;
    end: string | null;
    calendarMonths: number;
    observedMonths: number;
    scoredMonths: number;
    missingCalendarMonths: number;
    missingSignalMonths: number;
    pendingOutcomeMonths: number;
    gaps: { start: string; end: string; months: number; reason: 'missing-date' | 'missing-signal' }[];
  };
  stats: {
    matureScoredMonths: number;
    alarmMonths: number;
    allAlarmMonths: number;
    falseAlarmMonths: number;
    positiveAlarmMonths: number;
    pendingAlarmMonths: number;
    alarmShare: number | null;
    falseAlarmShare: number | null;
    positiveAlarmShare: number | null;
    falseShareOfMatureAlarms: number | null;
    spellCount: number;
    longestAlarmMonths: number;
    longestFalseStreakMonths: number;
  };
  spells: AlarmSpell[];
  monthlyRows: AlarmMonth[];
  longestFalseStreak: FalseWarningStreak | null;
};
const RULES: readonly AlarmSpellRule[] = ['original', 'curve', 'challenger', 'gate'];
const monthString = (value: number) =>
  `${String(Math.floor(value / 12)).padStart(4, '0')}-${String((value % 12) + 1).padStart(2, '0')}-01`;
const censored = (boundary: AlarmBoundary) =>
  ['dataset-boundary', 'missing-date', 'missing-signal', 'pending-outcome'].includes(boundary);
/** An annual experiment owns its dates. Live/monthly refits cannot fill its gaps. */
function annualReplaySource(snapshot: unknown): unknown {
  const object = (value: unknown): Record<string, unknown> =>
    value !== null && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  const source = object(snapshot),
    experiment = object(source.innovation);
  const asRows = (value: unknown) => (Array.isArray(value) ? value.map(object) : []);
  const annual = (row: Record<string, unknown>) =>
    row.forecastType === undefined || row.forecastType === 'annual-walk-forward';
  const baseRows = asRows(source.history).filter(annual);
  const candidateRows = asRows(experiment.history);
  if (!candidateRows.length) return { history: baseRows };
  const eligible = candidateRows.filter(annual),
    baseByDate = new Map(baseRows.map((row) => [row.date, row]));
  const mapped = eligible.map((row) => {
    const previous = baseByDate.get(row.date) ?? {};
    return {
      ...previous,
      ...row,
      probability: Object.hasOwn(row, 'originalProbability') ? row.originalProbability : previous.probability,
    };
  });
  return { history: mapped, innovation: { history: eligible } };
}

export function deriveAlarmSpells(
  snapshot: unknown,
  options: { rule?: AlarmSpellRule; threshold?: number } = {},
): AlarmSpellAudit {
  const rule = options.rule === undefined ? 'original' : options.rule,
    threshold = options.threshold === undefined ? 0.3 : options.threshold;
  if (!RULES.includes(rule)) throw new RangeError('Unsupported alarm spell rule');
  const replay = warningReplayRows(annualReplaySource(snapshot), threshold),
    first = replay[0]?.month,
    last = replay.at(-1)?.month;
  const byMonth = new Map(replay.map((row) => [row.month, row]));
  const monthlyRows: AlarmMonth[] = [],
    gaps: AlarmSpellAudit['coverage']['gaps'] = [];
  const index = (month: number): WarningReplayRow | undefined => byMonth.get(month);
  const boundary = (month: number, falseStreak = false): AlarmBoundary => {
    if (first === undefined || last === undefined || month < first || month > last) return 'dataset-boundary';
    const row = index(month);
    if (!row) return 'missing-date';
    if (row.signals[rule] === null) return 'missing-signal';
    if (row.signals[rule] === false) return 'observed-non-alarm';
    if (falseStreak && row.target === null) return 'pending-outcome';
    if (falseStreak && row.target === 1) return 'observed-positive';
    return 'observed-non-alarm'; // Adjacent known alarms are joined before this function is called.
  };
  let missingDates = 0,
    missingSignals = 0,
    pendingOutcomes = 0,
    scored = 0;
  if (first !== undefined && last !== undefined)
    for (let month = first; month <= last; month++) {
      const row = index(month),
        signal = row?.signals[rule] ?? null;
      const missing = !row ? 'missing-date' : signal === null ? 'missing-signal' : null;
      if (!row) missingDates++;
      else if (signal === null) missingSignals++;
      if (row && row.target === null) pendingOutcomes++;
      if (signal !== null) scored++;
      if (missing) {
        const prior = gaps.at(-1);
        if (prior && prior.reason === missing && prior.end === monthString(month - 1)) {
          prior.end = monthString(month);
          prior.months++;
        } else gaps.push({ start: monthString(month), end: monthString(month), months: 1, reason: missing });
      }
      const target = row?.target ?? null;
      const status: AlarmMonth['status'] =
        signal === null
          ? 'missing'
          : target === null
            ? 'pending'
            : !signal
              ? 'quiet'
              : target === 1
                ? 'positive'
                : 'false';
      monthlyRows.push({
        date: monthString(month),
        probability: row && rule !== 'gate' ? row.scores[rule] : null,
        curveProbability: row?.scores.curve ?? null,
        alarm: signal,
        target,
        status,
        spellId: null,
      });
    }
  const spells: AlarmSpell[] = [];
  let run: { start: number; end: number; rows: AlarmMonth[] } | null = null;
  const finish = () => {
    if (!run) return;
    const falseMonths = run.rows.filter((row) => row.target === 0).length;
    const positiveMonths = run.rows.filter((row) => row.target === 1).length;
    const pendingMonths = run.rows.length - falseMonths - positiveMonths;
    const classification = pendingMonths
      ? 'pending'
      : falseMonths && positiveMonths
        ? 'mixed'
        : positiveMonths
          ? 'positive'
          : 'false';
    const leftBoundary = boundary(run.start - 1),
      rightBoundary = boundary(run.end + 1);
    const id = `${rule}-${monthString(run.start)}`;
    spells.push({
      id,
      start: monthString(run.start),
      end: monthString(run.end),
      months: run.rows.length,
      classification,
      falseMonths,
      positiveMonths,
      pendingMonths,
      leftBoundary,
      rightBoundary,
      leftCensored: censored(leftBoundary),
      rightCensored: censored(rightBoundary),
    });
    for (const row of run.rows) row.spellId = id;
    run = null;
  };
  for (let offset = 0; offset < monthlyRows.length; offset++) {
    const row = monthlyRows[offset],
      month = first! + offset;
    if (row.alarm !== true) {
      finish();
      continue;
    }
    if (!run) run = { start: month, end: month, rows: [] };
    run.end = month;
    run.rows.push(row);
  }
  finish();
  let falseRun: { start: number; end: number; months: number } | null = null;
  let longestFalseStreak: FalseWarningStreak | null = null;
  const finishFalse = () => {
    if (!falseRun) return;
    if (!longestFalseStreak || falseRun.months > longestFalseStreak.months) {
      const leftBoundary = boundary(falseRun.start - 1, true),
        rightBoundary = boundary(falseRun.end + 1, true);
      longestFalseStreak = {
        start: monthString(falseRun.start),
        end: monthString(falseRun.end),
        months: falseRun.months,
        leftBoundary,
        rightBoundary,
        leftCensored: censored(leftBoundary),
        rightCensored: censored(rightBoundary),
      };
    }
    falseRun = null;
  };
  for (let offset = 0; offset < monthlyRows.length; offset++) {
    const row = monthlyRows[offset],
      month = first! + offset;
    if (row.alarm !== true || row.target !== 0) {
      finishFalse();
      continue;
    }
    if (!falseRun) falseRun = { start: month, end: month, months: 0 };
    falseRun.end = month;
    falseRun.months++;
  }
  finishFalse();
  const mature = monthlyRows.filter((row) => row.alarm !== null && row.target !== null);
  const falseAlarms = mature.filter((row) => row.alarm && row.target === 0).length;
  const positiveAlarms = mature.filter((row) => row.alarm && row.target === 1).length;
  const alarmMonths = falseAlarms + positiveAlarms,
    pendingAlarms = monthlyRows.filter((row) => row.alarm && row.target === null).length;
  const ratio = (numerator: number, denominator: number) => (denominator ? numerator / denominator : null);
  const scoreMeaning =
    rule === 'gate'
      ? 'Confirmation gate is a policy, not a probability; curveProbability records its input score.'
      : rule === 'challenger'
        ? 'Post-hoc interaction candidate probability'
        : rule === 'curve'
          ? 'Curve-only model probability'
          : 'Original model probability';
  return {
    version: '1.0',
    rule,
    threshold,
    scoreMeaning,
    disclosure:
      'Latest-vintage retrospective annual historical replay. Annual experiment dates are authoritative; live fixed-model or monthly-refit rows never fill missing annual replay dates. The target is any recession month in the next twelve months, not onset alone. A positive alarm month has target 1, not necessarily a recession in its issue month. Consecutive calendar signals form spells; missing dates or scores break them and censor adjacent boundaries. Pending outcomes take precedence over known outcome classifications. Shares use only mature scored months; pending alarms are separate. The longest false-warning streak is measured independently inside or across outcome-mixed spells. Censoring concerns observed run boundaries, not confidence intervals. Monthly targets overlap; spell counts are not independent evidence of predictive skill.',
    coverage: {
      start: first === undefined ? null : monthString(first),
      end: last === undefined ? null : monthString(last),
      calendarMonths: monthlyRows.length,
      observedMonths: replay.length,
      scoredMonths: scored,
      missingCalendarMonths: missingDates,
      missingSignalMonths: missingSignals,
      pendingOutcomeMonths: pendingOutcomes,
      gaps,
    },
    stats: {
      matureScoredMonths: mature.length,
      alarmMonths,
      allAlarmMonths: alarmMonths + pendingAlarms,
      falseAlarmMonths: falseAlarms,
      positiveAlarmMonths: positiveAlarms,
      pendingAlarmMonths: pendingAlarms,
      alarmShare: ratio(alarmMonths, mature.length),
      falseAlarmShare: ratio(falseAlarms, mature.length),
      positiveAlarmShare: ratio(positiveAlarms, mature.length),
      falseShareOfMatureAlarms: ratio(falseAlarms, alarmMonths),
      spellCount: spells.length,
      longestAlarmMonths: Math.max(0, ...spells.map((spell) => spell.months)),
      longestFalseStreakMonths: (longestFalseStreak as FalseWarningStreak | null)?.months ?? 0,
    },
    spells,
    monthlyRows,
    longestFalseStreak,
  };
}

/** Deterministic monthly evidence, optionally restricted to one spell. */
export function alarmSpellsCsv(audit: AlarmSpellAudit, spellId?: string): string {
  if (spellId !== undefined && !audit.spells.some((spell) => spell.id === spellId))
    throw new RangeError('Unknown alarm spell');
  const header = [
    'version',
    'rule',
    'threshold',
    'audit_start',
    'audit_end',
    'date',
    'model_probability',
    'curve_probability',
    'alarm',
    'target',
    'status',
    'spell_id',
    'spell_classification',
    'spell_start',
    'spell_end',
    'spell_months',
    'false_months',
    'positive_months',
    'pending_months',
    'left_censored',
    'right_censored',
    'left_boundary',
    'right_boundary',
    'target_definition',
    'label_vintage',
  ];
  const byId = new Map(audit.spells.map((spell) => [spell.id, spell]));
  const quote = (value: unknown) =>
    value === null || value === undefined ? '' : '"' + String(value).replaceAll('"', '""') + '"';
  const records = audit.monthlyRows
    .filter((row) => spellId === undefined || row.spellId === spellId)
    .map((row) => {
      const spell = row.spellId ? byId.get(row.spellId) : undefined;
      return [
        audit.version,
        audit.rule,
        audit.threshold,
        audit.coverage.start,
        audit.coverage.end,
        row.date,
        row.probability,
        row.curveProbability,
        row.alarm,
        row.target,
        row.status,
        row.spellId,
        spell?.classification,
        spell?.start,
        spell?.end,
        spell?.months,
        spell?.falseMonths,
        spell?.positiveMonths,
        spell?.pendingMonths,
        spell?.leftCensored,
        spell?.rightCensored,
        spell?.leftBoundary,
        spell?.rightBoundary,
        'Any recession month in the following 12 calendar months; continuation included',
        'Latest-vintage retrospective labels',
      ]
        .map(quote)
        .join(',');
    });
  return [header.join(','), ...records].join('\n') + '\n';
}
