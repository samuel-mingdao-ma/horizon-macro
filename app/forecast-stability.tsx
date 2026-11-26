import { forecastStability, type TrialIssue, type TrialVariant } from '../lib/forecast-stability';

const variants = [
  ['probability', 'Rate-path blend'],
  ['recentBlendProbability', '15-year base-rate blend'],
] as const satisfies readonly (readonly [TrialVariant, string])[];

function signed(value: number) {
  if (Math.abs(value) < 0.00005) return '0.0000';
  return (value > 0 ? '+' : '−') + Math.abs(value).toFixed(4);
}

export function ForecastStability({
  rows,
  start,
  end,
}: {
  rows: TrialIssue[];
  start: string | null;
  end: string | null;
}) {
  return (
    <details className="forecast-stability">
      <summary>Does the result depend on one two-year stretch?</summary>
      <p>
        Remove each complete run of 24 consecutive forecast months in turn. The figures show the reduction in
        average Brier error versus the existing 50/50 blend on the months left in this period. Positive values
        favor the trial.
      </p>
      <dl>
        {variants.map(([key, name]) => {
          const result = forecastStability(rows, start, end, key);
          return (
            <div key={key}>
              <dt>{name}</dt>
              <dd>
                {result ? (
                  <>
                    Full period <strong>{signed(result.full)}</strong>. After omitting a block,{' '}
                    <strong>
                      {signed(result.lowest)} to {signed(result.highest)}
                    </strong>{' '}
                    across {result.n} possible blocks.
                  </>
                ) : (
                  'Insufficient common history for this check.'
                )}
              </dd>
            </div>
          );
        })}
      </dl>
      <p>
        Models keep their original fitted weights. The range describes sensitivity to the evaluation period.
        Overlapping windows and the small number of downturns limit inference about future accuracy.
      </p>
    </details>
  );
}
