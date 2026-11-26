'use client';
import { useState } from 'react';
import type { RegimePriorSnapshot } from '../lib/regime-prior-types';
import { annualOriginScores } from '../lib/regime-annual-check';
import './regime-annual-check.css';

const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const difference = (v: number | null) => (v === null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(5)}`);

export function RegimeAnnualCheck({ trial }: { trial: RegimePriorSnapshot }) {
  const [sample, setSample] = useState<'all' | 'rolling120'>('rolling120');
  const cohort = trial.metrics[sample];
  const rows = annualOriginScores(trial.history, cohort.start, cohort.end);
  const available = rows.filter((row) => row.n);
  const wins = available.filter((row) => row.regimeDelta !== null && row.regimeDelta < 0).length;
  return (
    <details className="regime-annual">
      <summary>Do the results change with the forecast month?</summary>
      <p>
        Choose one issue month per year to get non-overlapping 12-month outcomes within each row. Different
        rows can still contain the same recession.
      </p>
      <label>
        Evaluation period{' '}
        <select value={sample} onChange={(e) => setSample(e.target.value as typeof sample)}>
          <option value="rolling120">Latest 10 years</option>
          <option value="all">Full replay</option>
        </select>
      </label>
      <p aria-live="polite">
        The regime blend has lower Brier error in{' '}
        <strong>
          {wins} of {available.length}
        </strong>{' '}
        calendar-month groups. A negative difference favors the trial.
      </p>
      <div
        className="regime-annual-scroll"
        role="region"
        aria-label="Annual forecast-month comparisons"
        tabIndex={0}
      >
        <table>
          <caption>Mean Brier error by issue month</caption>
          <thead>
            <tr>
              <th>Issue month</th>
              <th>Years</th>
              <th>Positive years</th>
              <th>Existing 50/50</th>
              <th>Regime difference</th>
              <th>Adaptive difference</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.month}>
                <th scope="row">{months[row.month - 1]}</th>
                <td>{row.n}</td>
                <td>{row.positives}</td>
                <td>{row.fixed?.toFixed(5) ?? '—'}</td>
                <td>{difference(row.regimeDelta)}</td>
                <td>{difference(row.adaptiveDelta)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
