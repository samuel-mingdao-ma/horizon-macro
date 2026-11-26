// Each calendar-month cohort issues forecasts exactly one year apart.
export function annualOriginScores(
  history: Record<string, unknown>[],
  start: string | null,
  end: string | null,
) {
  const groups = Array.from({ length: 12 }, (_, i) => ({
    month: i + 1,
    n: 0,
    positives: 0,
    fixed: 0,
    regime: 0,
    adaptive: 0,
  }));
  const probability = (p: unknown): p is number => typeof p === 'number' && p >= 0 && p <= 1;
  const controls = [
    'originalProbability',
    'baselineProbability',
    'recentPriorProbability',
    'recentBlendProbability',
    'expandingBlendProbability',
    'dynamicPriorProbability',
  ];
  const seen = new Set<string>();
  for (const row of history) {
    const { date, target, fixedBlendProbability, probability: regime, adaptiveProbability } = row;
    if (
      !start ||
      !end ||
      typeof date !== 'string' ||
      !/^\d{4}-(0[1-9]|1[0-2])-01$/.test(date) ||
      date < start ||
      date > end ||
      seen.has(date) ||
      (target !== 0 && target !== 1) ||
      !controls.every((key) => probability(row[key])) ||
      !probability(fixedBlendProbability) ||
      !probability(regime) ||
      !probability(adaptiveProbability)
    )
      continue;
    seen.add(date);
    const group = groups[Number(date.slice(5, 7)) - 1];
    group.n++;
    group.positives += target;
    group.fixed += (fixedBlendProbability - target) ** 2;
    group.regime += (regime - target) ** 2;
    group.adaptive += (adaptiveProbability - target) ** 2;
  }
  return groups.map((g) => ({
    month: g.month,
    n: g.n,
    positives: g.positives,
    fixed: g.n ? g.fixed / g.n : null,
    regimeDelta: g.n ? (g.regime - g.fixed) / g.n : null,
    adaptiveDelta: g.n ? (g.adaptive - g.fixed) / g.n : null,
  }));
}
