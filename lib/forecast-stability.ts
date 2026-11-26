export type TrialIssue = {
  date: string;
  target: number | null;
  existingBlendProbability: number | null;
  probability: number | null;
  recentBlendProbability?: number | null;
};

export type TrialVariant = 'probability' | 'recentBlendProbability';
const WINDOW = 24;
const finiteProbability = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;

/** Remove one complete calendar block at a time and recompute the paired mean loss difference. */
export function forecastStability(
  rows: TrialIssue[],
  start: string | null,
  end: string | null,
  variant: TrialVariant,
) {
  if (!start || !end) return null;
  const sample = rows
    .flatMap((row) => {
      const candidate = row[variant],
        incumbent = row.existingBlendProbability;
      if (
        row.date < start ||
        row.date > end ||
        (row.target !== 0 && row.target !== 1) ||
        !finiteProbability(candidate) ||
        !finiteProbability(incumbent) ||
        !finiteProbability(row.probability) ||
        !finiteProbability(row.recentBlendProbability)
      )
        return [];
      return [
        {
          date: row.date,
          month: Number(row.date.slice(0, 4)) * 12 + Number(row.date.slice(5, 7)),
          gain: (incumbent - row.target) ** 2 - (candidate - row.target) ** 2,
        },
      ];
    })
    .sort((a, b) => a.month - b.month);
  if (sample.length <= WINDOW || sample.some((r, i) => i > 0 && r.month === sample[i - 1].month)) return null;
  const prefix = [0];
  for (const row of sample) prefix.push(prefix[prefix.length - 1] + row.gain);
  const total = prefix[sample.length],
    remainder = sample.length - WINDOW;
  let lowest = Infinity,
    highest = -Infinity,
    n = 0;
  for (let i = 0; i + WINDOW <= sample.length; i++) {
    if (sample[i + WINDOW - 1].month - sample[i].month !== WINDOW - 1) continue;
    const gain = (total - (prefix[i + WINDOW] - prefix[i])) / remainder;
    lowest = Math.min(lowest, gain);
    highest = Math.max(highest, gain);
    n++;
  }
  return n ? { lowest, highest, n, full: total / sample.length } : null;
}
