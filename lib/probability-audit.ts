/** Post-hoc, prequential least-squares shrinkage experiment on annual replay only. */
export type ProbabilityMethod = 'original' | 'prequential' | 'base' | 'fixedBlend';
export const PROBABILITY_METHODS: readonly ProbabilityMethod[] = [
  'original',
  'prequential',
  'base',
  'fixedBlend',
];
export const PROBABILITY_MIN_TRAINING_MONTHS = 60;
export type ProbabilityFold = {
  year: number;
  refitDate: string;
  trainingCutoff: string;
  trainStart: string | null;
  trainEnd: string | null;
  lastTargetMonth: string | null;
  trainingN: number;
  weight: number | null;
  unconstrainedWeight: number | null;
  numerator: number | null;
  denominator: number | null;
  identified: boolean;
  status: 'fit' | 'degenerate-base' | 'insufficient-history';
};
export type ProbabilityAuditRow = {
  date: string;
  target: 0 | 1 | null;
  originalProbability: number;
  baselineProbability: number;
  prequentialProbability: number;
  fixedBlendProbability: number;
  evaluated: boolean;
  foldYear: number;
  weight: number;
  trainingCutoff: string;
  trainingN: number;
  trainEnd: string;
  lastTargetMonth: string;
};
export type ProbabilityBin = {
  id: number;
  lower: number;
  upper: number;
  upperInclusive: boolean;
  n: number;
  positiveWindows: number;
  meanPredicted: number | null;
  observedRate: number | null;
  brier: number | null;
};
export type ProbabilityScore = {
  brier: number | null;
  totalBrierLoss: number;
};
export type ProbabilityAudit = {
  version: '1.0';
  status:
    | 'post-hoc prequential research replay'
    | 'unavailable-no-annual-replay'
    | 'unavailable-missing-source-date';
  disclosure: string;
  minimumTrainingMonths: 60;
  coverage: {
    sourceRows: number;
    acceptedRows: number;
    invalidDateRows: number;
    futureDateRows: number;
    duplicateDateRows: number;
    duplicateMonths: number;
    nonAnnualRows: number;
    missingProbabilityRows: number;
    unknownTargetRows: number;
    maskedFutureTargetRows: number;
    excludedWarmupMatureRows: number;
    sourceIssueDate: string | null;
    labelCutoff: string | null;
  };
  folds: ProbabilityFold[];
  rows: ProbabilityAuditRow[];
  metrics: {
    n: number;
    start: string | null;
    end: string | null;
    positiveWindows: number;
    original: ProbabilityScore;
    prequential: ProbabilityScore;
    base: ProbabilityScore;
    fixedBlend: ProbabilityScore;
    pairedImprovement: {
      vsOriginal: {
        mean: number | null;
        total: number;
      };
      vsBase: {
        mean: number | null;
        total: number;
      };
      vsFixedBlend: {
        mean: number | null;
        total: number;
      };
    };
  };
  bins: Record<ProbabilityMethod, ProbabilityBin[]>;
  current: {
    status: 'available' | 'unavailable';
    issueDate: string | null;
    featureDate: string | null;
    originalProbability: number | null;
    baselineProbability: number | null;
    prequentialProbability: number | null;
    fixedBlendProbability: number | null;
    weight: number | null;
    foldYear: number | null;
    foldRefitDate: string | null;
    trainingCutoff: string | null;
    trainingN: number;
    note: string;
  };
};
type ObjectRow = Record<string, unknown>;
type SourceRow = {
  date: string;
  month: number;
  target: 0 | 1 | null;
  originalProbability: number;
  baselineProbability: number;
};
export type ProbabilityTrainingRow = {
  target: 0 | 1;
  originalProbability: number;
  baselineProbability: number;
};
const object = (value: unknown): ObjectRow =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as ObjectRow) : {};
const probability = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1 ? value : null;
const binary = (value: unknown): 0 | 1 | null => (value === 0 || value === 1 ? value : null);
function monthIndex(value: unknown, firstDay = true): number | null {
  if (typeof value !== 'string') return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:T.*)?$/.exec(value);
  if (!match) return null;
  const year = Number(match[1]),
    month = Number(match[2]),
    day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || (firstDay && day !== 1)) return null;
  const days = [
    31,
    year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ];
  return day <= days[month - 1] ? year * 12 + month - 1 : null;
}
const monthString = (value: number) =>
  `${String(Math.floor(value / 12)).padStart(4, '0')}-${String((value % 12) + 1).padStart(2, '0')}-01`;
const blend = (p: number, b: number, w: number) => (w === 0 ? b : w === 1 ? p : b + w * (p - b));
/** Exact convex-combination least squares; a zero denominator deterministically uses base. */
export function fitProbabilityWeight(training: readonly ProbabilityTrainingRow[]) {
  let numerator = 0,
    denominator = 0;
  for (const row of training) {
    if (
      binary(row.target) === null ||
      probability(row.originalProbability) === null ||
      probability(row.baselineProbability) === null
    )
      throw new RangeError('Weight fitting requires finite probabilities and known binary labels');
    const difference = row.originalProbability - row.baselineProbability;
    numerator += difference * (row.target - row.baselineProbability);
    denominator += difference * difference;
  }
  const identified = denominator !== 0;
  const unconstrainedWeight = identified ? numerator / denominator : null;
  const weight = identified ? Math.max(0, Math.min(1, unconstrainedWeight!)) : 0;
  return { weight, unconstrainedWeight, numerator, denominator, identified };
}
function foldForYear(year: number, source: SourceRow[]): ProbabilityFold {
  const refit = year * 12;
  const eligible = source.filter(
    (
      row,
    ): row is SourceRow & {
      target: 0 | 1;
    } => row.target !== null && row.month + 12 < refit,
  );
  const trainingN = eligible.length,
    first = eligible[0],
    last = eligible.at(-1);
  const common = {
    year,
    refitDate: monthString(refit),
    trainingCutoff: monthString(refit - 13),
    trainStart: first?.date ?? null,
    trainEnd: last?.date ?? null,
    lastTargetMonth: last ? monthString(last.month + 12) : null,
    trainingN,
  };
  if (trainingN < PROBABILITY_MIN_TRAINING_MONTHS)
    return {
      ...common,
      weight: null,
      unconstrainedWeight: null,
      numerator: null,
      denominator: null,
      identified: false,
      status: 'insufficient-history',
    };
  const fitted = fitProbabilityWeight(eligible);
  return { ...common, ...fitted, status: fitted.identified ? 'fit' : 'degenerate-base' };
}
const methodValue = (row: ProbabilityAuditRow, method: ProbabilityMethod) =>
  method === 'original'
    ? row.originalProbability
    : method === 'base'
      ? row.baselineProbability
      : method === 'fixedBlend'
        ? row.fixedBlendProbability
        : row.prequentialProbability;
const binId = (value: number) => Math.min(4, Math.floor(value * 5));
export function deriveProbabilityAudit(snapshot: unknown): ProbabilityAudit {
  const root = object(snapshot),
    experiment = object(root.innovation),
    latest = object(root.latest),
    meta = object(root.meta);
  const raw = Array.isArray(experiment.history) ? experiment.history.map(object) : [];
  // The experiment's own dated build bounds its replay; live dates cannot extend it.
  const ceiling = monthIndex(experiment.issueDate);
  const labelDates = [
    monthIndex(object(meta.dataRefresh).labelCutoff),
    ...(Array.isArray(root.sources) ? root.sources.map(object) : [])
      .filter((row) => row.id === 'USREC')
      .map((row) => monthIndex(row.lastDate)),
  ].filter((value): value is number => value !== null);
  const labelCeiling = ceiling === null ? null : Math.min(ceiling, ...labelDates);
  const coverage: ProbabilityAudit['coverage'] = {
    sourceRows: raw.length,
    acceptedRows: 0,
    invalidDateRows: 0,
    futureDateRows: 0,
    duplicateDateRows: 0,
    duplicateMonths: 0,
    nonAnnualRows: 0,
    missingProbabilityRows: 0,
    unknownTargetRows: 0,
    maskedFutureTargetRows: 0,
    excludedWarmupMatureRows: 0,
    sourceIssueDate: ceiling === null ? null : monthString(ceiling),
    labelCutoff: labelCeiling === null ? null : monthString(labelCeiling),
  };
  const dated = new Map<number, ObjectRow[]>();
  for (const row of raw) {
    if (row.forecastType !== 'annual-walk-forward') {
      coverage.nonAnnualRows++;
      continue;
    }
    const month = monthIndex(row.date);
    if (month === null) {
      coverage.invalidDateRows++;
      continue;
    }
    if (ceiling === null || month > ceiling) {
      coverage.futureDateRows++;
      continue;
    }
    const group = dated.get(month) ?? [];
    group.push(row);
    dated.set(month, group);
  }
  const source: SourceRow[] = [];
  for (const [month, records] of [...dated.entries()].sort((a, b) => a[0] - b[0])) {
    if (records.length !== 1) {
      coverage.duplicateDateRows += records.length;
      coverage.duplicateMonths++;
      continue;
    }
    const row = records[0],
      p = probability(row.originalProbability),
      b = probability(row.baseline);
    if (p === null || b === null) {
      coverage.missingProbabilityRows++;
      continue;
    }
    const reportedTarget = binary(row.target);
    const matureHorizon = labelCeiling !== null && month + 12 <= labelCeiling;
    const target = matureHorizon ? reportedTarget : null;
    if (!matureHorizon && reportedTarget !== null) coverage.maskedFutureTargetRows++;
    if (target === null) coverage.unknownTargetRows++;
    source.push({ date: monthString(month), month, target, originalProbability: p, baselineProbability: b });
  }
  coverage.acceptedRows = source.length;
  const issue = monthIndex(latest.issueDate) ?? monthIndex(meta.issueDate),
    issueYear = issue === null ? null : Math.floor(issue / 12);
  const years = new Set(source.map((row) => Math.floor(row.month / 12))); // A live issue cannot create a new replay fold.
  const folds = [...years].sort((a, b) => a - b).map((year) => foldForYear(year, source));
  const byYear = new Map(folds.map((fold) => [fold.year, fold]));
  const rows: ProbabilityAuditRow[] = [];
  for (const row of source) {
    const fold = byYear.get(Math.floor(row.month / 12))!;
    if (fold.weight === null) {
      if (row.target !== null) coverage.excludedWarmupMatureRows++;
      continue;
    }
    rows.push({
      date: row.date,
      target: row.target,
      originalProbability: row.originalProbability,
      baselineProbability: row.baselineProbability,
      prequentialProbability: blend(row.originalProbability, row.baselineProbability, fold.weight),
      fixedBlendProbability: 0.5 * (row.originalProbability + row.baselineProbability),
      evaluated: row.target !== null,
      foldYear: fold.year,
      weight: fold.weight,
      trainingCutoff: fold.trainingCutoff,
      trainingN: fold.trainingN,
      trainEnd: fold.trainEnd!,
      lastTargetMonth: fold.lastTargetMonth!,
    });
  }
  const mature = rows.filter(
    (
      row,
    ): row is ProbabilityAuditRow & {
      target: 0 | 1;
    } => row.target !== null,
  );
  const scores = {} as Record<ProbabilityMethod, ProbabilityScore>,
    bins = {} as Record<ProbabilityMethod, ProbabilityBin[]>;
  for (const method of PROBABILITY_METHODS) {
    const totalBrierLoss = mature.reduce((sum, row) => sum + (methodValue(row, method) - row.target) ** 2, 0);
    scores[method] = { brier: mature.length ? totalBrierLoss / mature.length : null, totalBrierLoss };
    bins[method] = Array.from({ length: 5 }, (_, id) => {
      const group = mature.filter((row) => binId(methodValue(row, method)) === id);
      return {
        id,
        lower: id / 5,
        upper: (id + 1) / 5,
        upperInclusive: id === 4,
        n: group.length,
        positiveWindows: group.reduce((sum, row) => sum + row.target, 0),
        meanPredicted: group.length
          ? group.reduce((sum, row) => sum + methodValue(row, method), 0) / group.length
          : null,
        observedRate: group.length ? group.reduce((sum, row) => sum + row.target, 0) / group.length : null,
        brier: group.length
          ? group.reduce((sum, row) => sum + (methodValue(row, method) - row.target) ** 2, 0) / group.length
          : null,
      };
    });
  }
  const improvement = (method: ProbabilityMethod) => {
    const total = mature.reduce(
      (sum, row) =>
        sum + (methodValue(row, method) - row.target) ** 2 - (row.prequentialProbability - row.target) ** 2,
      0,
    );
    return { total, mean: mature.length ? total / mature.length : null };
  };
  const currentFold = issueYear === null ? undefined : byYear.get(issueYear);
  const p = probability(latest.probability),
    b = probability(latest.baselineProbability);
  const available =
    currentFold?.weight !== null && currentFold?.weight !== undefined && p !== null && b !== null;
  return {
    version: '1.0',
    status: !raw.length
      ? 'unavailable-no-annual-replay'
      : ceiling === null
        ? 'unavailable-missing-source-date'
        : 'post-hoc prequential research replay',
    disclosure:
      'A post-hoc prequential research experiment, not untouched holdout validation. Each January fits one constrained least-squares weight q=b+w(p−b) using only annual-replay issues whose full 12-month targets end strictly before that January, with at least 60 eligible months. Weight remains frozen for that issue year. A zero denominator uses w=0 (base) because weight is unidentified. Comparisons use the exact same post-warmup mature months; fixed 50/50 is an existing post-hoc comparator. Empty bins stay empty and 100% belongs to the final band. Revised histories, retrospective NBER labels, announcement delays and overlapping targets remain limitations; this calendar rule does not reconstruct true historical release vintages.',
    minimumTrainingMonths: 60,
    coverage,
    folds,
    rows,
    metrics: {
      n: mature.length,
      start: mature[0]?.date ?? null,
      end: mature.at(-1)?.date ?? null,
      positiveWindows: mature.reduce((sum, row) => sum + row.target, 0),
      ...scores,
      pairedImprovement: {
        vsOriginal: improvement('original'),
        vsBase: improvement('base'),
        vsFixedBlend: improvement('fixedBlend'),
      },
    },
    bins,
    current: {
      status: available ? 'available' : 'unavailable',
      issueDate: issue === null ? null : monthString(issue),
      featureDate: typeof latest.featureDate === 'string' ? latest.featureDate : null,
      originalProbability: p,
      baselineProbability: b,
      prequentialProbability: available ? blend(p!, b!, currentFold!.weight!) : null,
      fixedBlendProbability: p !== null && b !== null ? 0.5 * (p + b) : null,
      weight: currentFold?.weight ?? null,
      foldYear: issueYear,
      foldRefitDate: currentFold?.refitDate ?? null,
      trainingCutoff: currentFold?.trainingCutoff ?? null,
      trainingN: currentFold?.trainingN ?? 0,
      note: !currentFold
        ? 'Unavailable: the annual research replay has no fold for this live issue year. A previous-year weight is not extrapolated, and live inputs cannot create a new fold. Refresh the annual research replay before using a weight in this year.'
        : 'Illustrative application of the current issue-year January weight to the latest live original probability and current expanding base rate. The weight was fitted to annual-replay forecasts; the live original may instead be a monthly refit or fixed-model refresh. This current illustration is separate from the historical evaluated rows. No previous-year weight is carried forward when this year cannot be fitted.',
    },
  };
}
/** Default export is the common mature comparison sample; pending rows require opt-in. */
export function probabilityAuditCsv(
  audit: ProbabilityAudit,
  options: {
    method?: ProbabilityMethod;
    bin?: number;
    includePending?: boolean;
  } = {},
): string {
  const method = options.method ?? 'prequential';
  if (!PROBABILITY_METHODS.includes(method)) throw new RangeError('Unknown probability method');
  if (options.bin !== undefined && (!Number.isInteger(options.bin) || options.bin < 0 || options.bin > 4))
    throw new RangeError('Probability bin must be an integer 0 through 4');
  const filtered = audit.rows.filter(
    (row) =>
      (options.includePending || row.evaluated) &&
      (options.bin === undefined || binId(methodValue(row, method)) === options.bin),
  );
  const header = [
    'experiment',
    'method',
    'selected_bin',
    'issue_date',
    'target',
    'evaluated',
    'selected_probability',
    'probability_bin',
    'original_probability',
    'prequential_probability',
    'base_probability',
    'fixed_blend_probability',
    'fold_year',
    'weight',
    'training_cutoff',
    'training_n',
    'train_end',
    'last_training_target_month',
    'source_issue_date',
    'target_definition',
  ];
  const quote = (value: unknown) =>
    value === null || value === undefined ? '' : '"' + String(value).replaceAll('"', '""') + '"';
  const records = filtered.map((row) =>
    [
      audit.status,
      method,
      options.bin,
      row.date,
      row.target,
      row.evaluated,
      methodValue(row, method),
      binId(methodValue(row, method)),
      row.originalProbability,
      row.prequentialProbability,
      row.baselineProbability,
      row.fixedBlendProbability,
      row.foldYear,
      row.weight,
      row.trainingCutoff,
      row.trainingN,
      row.trainEnd,
      row.lastTargetMonth,
      audit.coverage.sourceIssueDate,
      'Any recession month in the following 12 calendar months; continuation included',
    ]
      .map(quote)
      .join(','),
  );
  return [header.join(','), ...records].join('\n') + '\n';
}
