'use client';

import { useState } from 'react';
import { Download } from 'lucide-react';
import type { Snapshot } from '../lib/types';
import type {
  LeadEpisode,
  LeadEpisodeRow,
  LeadGroupKey,
  LeadingMethod,
  LeadingTrial,
  LeadingWindow,
} from '../lib/leading-types';
import './leading-indicators.css';

const periods: LeadingWindow[] = ['all', 'rolling120'];
const periodLabels = { all: 'Full history', rolling120: 'Latest 10 years' };
const methods: [LeadingMethod, string][] = [
  ['existingBlend', 'Existing 50/50'],
  ['matchedThreeBlend', 'Three original signals on matched training data'],
  ['permitsBlend', 'Original signals + building permits'],
  ['claimsBlend', 'Original signals + initial claims'],
  ['candidate', 'Original signals + both leading indicators'],
  ['rawFive', 'Five-signal forecast before blending'],
];
const phases: [LeadGroupKey, string][] = [
  ['pre7to12', '7–12 months before onset'],
  ['pre4to6', '4–6 months before onset'],
  ['pre1to3', '1–3 months before onset'],
  ['recessionIssued', 'Issued during a recession'],
  ['quietExpansion', 'Expansion with no recession in the next year'],
];
const valid = (x: number | null | undefined): x is number => typeof x === 'number' && Number.isFinite(x);
const pct = (x: number | null | undefined) => (valid(x) ? (100 * x).toFixed(1) + '%' : '—');
const dec = (x: number | null | undefined, digits = 5) => (valid(x) ? x.toFixed(digits) : '—');
const change = (x: number | null | undefined) => (valid(x) ? (x > 0 ? '+' : '') + x.toFixed(1) + '%' : '—');
const monthFormatter = new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' });
const month = (s?: string | null) =>
  s ? monthFormatter.format(new Date(s.slice(0, 7) + '-01T12:00:00Z')) : '—';
const labelId = (k: LeadingWindow) => (k === 'all' ? 'Full history' : 'Latest 120 issue months');

function Scorecard({ trial }: { trial: LeadingTrial }) {
  const { allPassed, rolling120Passed } = trial.gate;
  const verdict = !periods.every((p) => trial.metrics[p].n > 0)
    ? 'The comparison is awaiting mature forecasts.'
    : allPassed && rolling120Passed
      ? 'Both periods favor the five-signal blend.'
      : allPassed
        ? 'The five-signal blend improves the full replay only.'
        : rolling120Passed
          ? 'The five-signal blend improves the latest decade only.'
          : 'The existing 50/50 matches or beats the five-signal blend in both periods.';
  const controlsAvailable = periods.every(
    (k) =>
      valid(trial.metrics[k].models.permitsBlend.brier) && valid(trial.metrics[k].models.existingBlend.brier),
  );
  const wins = periods.filter(
    (k) => trial.metrics[k].models.permitsBlend.brier! < trial.metrics[k].models.existingBlend.brier!,
  );
  const recent = trial.metrics.rolling120.models;
  return (
    <section className="li-score">
      <h2>{controlsAvailable && wins.length === 2 && !trial.gate.passed ? 'Building permits improve both historical scores.' : verdict}</h2>
      <p>
        {controlsAvailable && wins.length === 2 && !trial.gate.passed ? verdict + ' ' : ''}
        Each forecast assigns half its weight to the same historical base rate. Lower Brier error is better.
      </p>
      <div className="li-score-grid" role="table" aria-label="Comparison with the existing forecast">
        <div className="li-score-row li-score-head" role="row">
          <span role="columnheader">Evaluation period</span>
          <span role="columnheader">Existing 50/50</span>
          <span role="columnheader">Add permits</span>
          <span role="columnheader">Add permits + claims</span>
        </div>
        {periods.map((key) => {
          const s = trial.metrics[key],
            incumbent = s.models.existingBlend.brier,
            candidate = s.models.candidate.brier;

          return (
            <div key={key} className="li-score-row" role="row">
              <div role="rowheader">
                <strong>{labelId(key)}</strong>
                <small>
                  {month(s.windowStart)} – {month(s.windowEnd)} · {s.n} scored
                </small>
              </div>
              <div role="cell" data-label="Existing 50/50">
                {dec(incumbent)}
              </div>
              <div role="cell" data-label="Add permits">
                {dec(s.models.permitsBlend.brier)}
              </div>
              <div role="cell" data-label="Add both">
                {dec(candidate)}
              </div>
            </div>
          );
        })}
      </div>
      {controlsAvailable && (
        <p className="li-permit-verdict">
          <strong>Adding only permits</strong> improves the original model’s Brier error{' '}
          {wins.length === 2
            ? 'in both periods'
            : wins.length === 1
              ? 'in the ' + (wins[0] === 'all' ? 'full replay only' : 'latest decade only')
              : 'in neither period'}
          . The latest-decade difference versus the existing 50/50 is{' '}
          <strong>{dec(recent.permitsBlend.brier! - recent.existingBlend.brier!)}</strong>. This
          single-indicator control was specified alongside the primary two-indicator test.
        </p>
      )}
      <p className="li-note">
        Each row uses identical mature issue months for all three forecasts. The recent window ends at the
        latest mature issue of the existing model.
      </p>
    </section>
  );
}

const leads = Array.from({ length: 12 }, (_, i) => 12 - i);
type PlotKey = 'existingBlendProbability' | 'permitsBlendProbability' | 'probability';
const lineKeys: PlotKey[] = ['existingBlendProbability', 'permitsBlendProbability', 'probability'];
function episodePath(points: (LeadEpisodeRow | undefined)[], key: PlotKey) {
  let path = '',
    connected = false;
  for (let i = 0; i < points.length; i++) {
    const value = points[i]?.[key];
    if (valid(value)) {
      path += (connected ? 'L' : 'M') + ' ' + (100 * i) / 11 + ' ' + (100 - 100 * value) + ' ';
      connected = true;
    } else connected = false;
  }
  return path;
}

function EpisodeChart({ episodes }: { episodes: LeadEpisode[] }) {
  const [chosen, setChosen] = useState('');
  const [lead, setLead] = useState(1);
  const event = episodes.find((e) => e.onsetDate === chosen) ?? episodes.at(-1);
  if (!event) return <p>Episode histories will appear when comparable forecasts are available.</p>;
  const points = leads.map((m) => event.rows.find((r) => r.monthsToOnset === m)),
    readout = points[12 - lead];
  return (
    <section className="li-section li-episode">
      <div className="li-section-head">
        <div>
          <h2>The twelve forecasts before a recession</h2>
          <p>
            Choose the first recession month, then move through the preceding issue months. Each point is a
            forecast for its own next twelve months.
          </p>
        </div>
        <label className="li-select">
          First recession month
          <select value={event.onsetDate} onChange={(e) => setChosen(e.target.value)}>
            {episodes.map((e) => (
              <option key={e.onsetDate} value={e.onsetDate}>
                {month(e.onsetDate)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <figure>
        <div className="li-legend">
          <span>
            <i className="li-base-mark" />
            Existing 50/50
          </span>
          <span>
            <i className="li-permit-mark" />
            Add permits
          </span>
          <span>
            <i className="li-trial-mark" />
            Add permits + claims
          </span>
        </div>
        <div className="li-chart">
          <div className="li-y-axis" aria-hidden="true">
            {[100, 75, 50, 25, 0].map((v) => (
              <span key={v} style={{ top: 100 - v + '%' }}>
                {v}%
              </span>
            ))}
          </div>
          <div
            className="li-plot"
            onPointerDown={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              if (r.width > 0)
                setLead(12 - Math.min(11, Math.max(0, Math.round((11 * (e.clientX - r.left)) / r.width))));
            }}
          >
            {[100, 75, 50, 25, 0].map((v) => (
              <i key={v} className="li-gridline" style={{ top: v + '%' }} />
            ))}
            <div className="li-cursor" style={{ left: (100 * (12 - lead)) / 11 + '%' }} />
            <svg
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
              role="img"
              aria-label={
                'Existing, permits-only and five-signal probabilities before ' +
                month(event.onsetDate) +
                '. Read individual values in the chart data table.'
              }
            >
              {lineKeys.map((key, i) => (
                <path
                  key={key}
                  className={['li-old-line', 'li-permit-line', 'li-joint-line'][i]}
                  d={episodePath(points, key)}
                  vectorEffect="non-scaling-stroke"
                  fill="none"
                />
              ))}
            </svg>
            {lineKeys.map((key, i) =>
              points.map((r, j) =>
                valid(r?.[key]) ? (
                  <i
                    key={key + j}
                    aria-hidden="true"
                    className={
                      'li-dot ' +
                      ['li-old-point', 'li-permit-point', 'li-joint-point'][i] +
                      (j === 12 - lead ? ' li-point-selected' : '')
                    }
                    style={{ left: (100 * j) / 11 + '%', top: 100 - 100 * r[key]! + '%' }}
                  />
                ) : null,
              ),
            )}
          </div>
          <div className="li-x-axis" aria-hidden="true">
            {[12, 9, 6, 3, 1].map((m) => (
              <span key={m} style={{ left: (100 * (12 - m)) / 11 + '%' }}>
                {m}
              </span>
            ))}
          </div>
        </div>
        <figcaption>Months before the first recession month. Gaps show unavailable forecasts.</figcaption>
      </figure>
      <div className="li-scrub">
        <label htmlFor="li-lead">Inspect forecast</label>
        <input
          id="li-lead"
          type="range"
          min="1"
          max="12"
          step="1"
          value={13 - lead}
          onChange={(e) => setLead(13 - Number(e.target.value))}
          aria-valuetext={lead + (lead === 1 ? ' month' : ' months') + ' before onset'}
        />
      </div>
      <div className="li-readout" aria-live="polite">
        <div>
          <strong>
            {lead} {lead === 1 ? 'month' : 'months'} before onset
          </strong>
          <small>
            {readout
              ? 'Issued ' + month(readout.date) + ' · signals ' + month(readout.featureDate)
              : 'Forecast unavailable'}
          </small>
        </div>
        <div>
          <span>Existing 50/50</span>
          <b>{pct(readout?.existingBlendProbability)}</b>
        </div>
        <div>
          <span>Add permits</span>
          <b>{pct(readout?.permitsBlendProbability)}</b>
        </div>
        <div>
          <span>Add both</span>
          <b>{pct(readout?.probability)}</b>
        </div>
      </div>
      {readout && (
        <p className="li-note">
          In {month(readout.date)}, the raw three-signal forecast was {pct(readout.originalProbability)} and
          its historical base rate was {pct(readout.baselineProbability)}. The latest usable unemployment gap
          was {dec(readout.labor, 2)} percentage points.
        </p>
      )}
      <details className="li-details">
        <summary>View the monthly forecasts and signals</summary>
        <div className="li-scroll" tabIndex={0} role="region" aria-label="Forecast and signal history">
          <table>
            <thead>
              <tr>
                {[
                  'Months before onset',
                  'Issue month',
                  'Existing 50/50',
                  'Add permits',
                  'Add both',
                  'Permits, 6m',
                  'Claims, 12m',
                ].map((t) => (
                  <th key={t}>{t}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {points.map((r, i) => (
                <tr key={leads[i]}>
                  <th scope="row">{leads[i]}</th>
                  <td>{month(r?.date)}</td>
                  <td>{pct(r?.existingBlendProbability)}</td>
                  <td>{pct(r?.permitsBlendProbability)}</td>
                  <td>{pct(r?.probability)}</td>
                  <td>{change(r?.permitGrowth6)}</td>
                  <td>{change(r?.claimsGrowth12)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

function Diagnostics({ trial, window }: { trial: LeadingTrial; window: LeadingWindow }) {
  const [model, setModel] = useState<'incumbent' | 'candidate'>('incumbent');
  const d = trial.diagnostics?.windows[window];
  if (!d) return null;
  const before = d.groups.preOnset,
    expansion = d.groups.allExpansion;
  return (
    <div className="li-diagnosis">
      <h3>What kept the forecast low?</h3>
      <p>
        Across {before.n} expansion issues within a year of a later onset, the original three-signal model
        averaged <strong>{pct(before.rawMean)}</strong>. The historical base rate averaged{' '}
        <strong>{pct(before.baseMean)}</strong>. Blending them equally yielded{' '}
        <strong>{pct(before.incumbentMean)}</strong>. The same issues averaged{' '}
        <strong>{pct(before.candidateMean)}</strong> after adding permits and claims.
      </p>
      {before.n > 0 && (
        <p>
          The base rate pulled the forecast below the raw model in{' '}
          <strong>
            {before.incumbentBelowRawN} of {before.n}
          </strong>{' '}
          pre-onset issues. With signals observed two months before the forecast, the unemployment gap was
          below 0.50 percentage points in <strong>{before.laborBelowHalfN}</strong> of them. A delayed labor
          signal and averaging with the base rate help explain why the warnings were muted.
        </p>
      )}
      <div className="li-scroll" tabIndex={0} role="region" aria-label="Forecasts by business-cycle phase">
        <table>
          <thead>
            <tr>
              <th>Lead time or phase</th>
              <th>Issues</th>
              <th>Mean existing</th>
              <th>Mean with permits</th>
              <th>Mean with both</th>
              <th>Realized frequency</th>
            </tr>
          </thead>
          <tbody>
            {phases.map(([id, label]) => {
              const g = d.groups[id];
              return (
                <tr key={id}>
                  <th scope="row">{label}</th>
                  <td>{g.n}</td>
                  <td>{pct(g.incumbentMean)}</td>
                  <td>{pct(g.permitsMean)}</td>
                  <td>{pct(g.candidateMean)}</td>
                  <td>{pct(g.observedRate)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="li-note">
        Onset dates use the first USREC month coded 1. The lead-time groups show how forecasts behaved before
        known downturns. Monthly windows overlap, and several can describe the same downturn.
      </p>
      <p>
        Across {expansion.n} expansion issues, the existing forecast averaged{' '}
        <strong>{pct(expansion.incumbentMean)}</strong>, the five-signal blend averaged{' '}
        <strong>{pct(expansion.candidateMean)}</strong> and <strong>{pct(expansion.observedRate)}</strong> of
        windows contained a recession. This comparison includes expansions followed by a recession-free year.
      </p>
      <details className="li-details">
        <summary>See calibration by forecast probability</summary>
        <div className="li-controls" role="group" aria-label="Forecast used for calibration bands">
          {(['incumbent', 'candidate'] as const).map((k) => (
            <button key={k} type="button" aria-pressed={model === k} onClick={() => setModel(k)}>
              {k === 'incumbent' ? 'Existing 50/50' : 'Five-signal blend'}
            </button>
          ))}
        </div>
        <div className="li-scroll" tabIndex={0} role="region" aria-label="Calibration by probability band">
          <table>
            <thead>
              <tr>
                <th>Forecast band</th>
                <th>Issues</th>
                <th>Mean forecast</th>
                <th>Realized frequency</th>
              </tr>
            </thead>
            <tbody>
              {d.calibration[model].map((b) => (
                <tr key={b.lower}>
                  <th scope="row">
                    {Math.round(100 * b.lower)}–{Math.round(100 * b.upper)}%
                  </th>
                  <td>{b.n}</td>
                  <td>{pct(model === 'incumbent' ? b.incumbentMean : b.candidateMean)}</td>
                  <td>{pct(b.observedRate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

function PermitErrors({ trial, window }: { trial: LeadingTrial; window: LeadingWindow }) {
  const period = trial.metrics[window];
  const split = [
    { n: 0, existing: 0, permit: 0 },
    { n: 0, existing: 0, permit: 0 },
  ];
  const byOrigin = Array.from({ length: 12 }, () => ({ n: 0, delta: 0 }));
  for (const r of trial.history) {
    if (
      !r.commonMature ||
      !period.windowStart ||
      !period.windowEnd ||
      r.date < period.windowStart ||
      r.date > period.windowEnd ||
      (r.target !== 0 && r.target !== 1) ||
      !valid(r.permitsBlendProbability) ||
      !valid(r.existingBlendProbability)
    )
      continue;
    const origin = byOrigin[Number(r.date.slice(5, 7)) - 1];
    const sum = split[r.target];
    sum.n++;
    const incumbentLoss = (r.existingBlendProbability - r.target) ** 2,
      permitsLoss = (r.permitsBlendProbability - r.target) ** 2;
    sum.existing += incumbentLoss;
    sum.permit += permitsLoss;
    origin.n++;
    origin.delta += permitsLoss - incumbentLoss;
  }
  if (!split.every((s) => s.n > 0)) return null;
  const pre = trial.diagnostics?.windows[window].groups.preOnset;
  const origins = byOrigin.filter((g) => g.n);
  return (
    <div className="li-permit-read">
      <h3>Where does the permits-only score come from?</h3>
      {pre && pre.n > 0 && valid(pre.permitsBrier) && (
        <p>
          For the {pre.n} issues strictly before a recession began, mean risk moved from{' '}
          <strong>{pct(pre.incumbentMean)}</strong> to <strong>{pct(pre.permitsMean)}</strong> with permits.
          Brier error for those early warnings moved from <strong>{dec(pre.incumbentBrier)}</strong> to{' '}
          <strong>{dec(pre.permitsBrier)}</strong>.
        </p>
      )}
      <p>
        In {split[0].n} windows with no recession month, adding permits took average squared error from{' '}
        <strong>{dec(split[0].existing / split[0].n)}</strong> to{' '}
        <strong>{dec(split[0].permit / split[0].n)}</strong>. In the {split[1].n} windows that contained a
        recession month, it went from <strong>{dec(split[1].existing / split[1].n)}</strong> to{' '}
        <strong>{dec(split[1].permit / split[1].n)}</strong>. The overall Brier score weights each issue month
        equally.
      </p>
      <p className="li-note">
        Checking each issue month separately, the permits-only blend had lower Brier error in{' '}
        <strong>
          {origins.filter((g) => g.delta < 0).length} of {origins.length}
        </strong>{' '}
        calendar-month groups. Each group uses one forecast per year, so its 12-month horizons are disjoint.
        Different groups can include the same recession.
      </p>
    </div>
  );
}

export default function LeadingIndicators({ data }: { data: Snapshot }) {
  const [window, setWindow] = useState<LeadingWindow>('rolling120');
  const trial = data.leadingTrial;
  if (!trial)
    return (
      <div className="li-research">
        <h1>Leading indicators</h1>
        <p>This research snapshot has no leading-indicator trial.</p>
      </div>
    );
  const latest = trial.latest,
    s = trial.metrics[window];
  const receipt = trial.prospective?.latestReceipt;
  const diag = trial.diagnostics?.windows[window];
  return (
    <div className="li-research">
      <header className="li-title">
        <div>
          <h1>Can permits and claims give earlier warning?</h1>
          <p>
            Housing authorizations track plans to build. Initial unemployment claims track new layoffs. We
            tested whether they improved a one-year recession forecast built from the yield curve, credit and
            unemployment.
          </p>
        </div>
        <a className="li-download" href="/api/download?file=leading">
          <Download size={16} aria-hidden="true" />
          Download monthly data
        </a>
      </header>
      <Scorecard trial={trial} />
      <section className="li-section li-current">
        <div className="li-section-head">
          <div>
            <h2>
              Risk for {month(latest.forecastStart)} – {month(latest.forecastEnd)}
            </h2>
            <p>
              Issued {month(latest.issueDate)} using signals through {month(latest.featureDate)}.
            </p>
          </div>
        </div>
        <div className="li-current-values">
          <div>
            <span>Existing 50/50</span>
            <strong>{pct(latest.existingBlendProbability)}</strong>
          </div>
          <div>
            <span>Add permits</span>
            <strong>{pct(latest.permitsBlendProbability)}</strong>
          </div>
          <div>
            <span>Add permits + claims</span>
            <strong>{pct(latest.probability)}</strong>
          </div>
        </div>
        {latest.available ? (
          <p>
            Smoothed permits changed <strong>{change(latest.features.permitGrowth6)}</strong> over six months.
            Smoothed initial claims changed <strong>{change(latest.features.claimsGrowth12)}</strong> over
            twelve months.
          </p>
        ) : (
          <p>The new forecast is unavailable for this issue. Missing readings are shown as dashes.</p>
        )}
      </section>
      {trial.diagnostics && <EpisodeChart episodes={trial.diagnostics.episodes} />}
      <section className="li-section">
        <div className="li-section-head">
          <div>
            <h2>Which forecasts changed?</h2>
            <p>Compare the models and the business-cycle phases on the same set of months.</p>
          </div>
          <div className="li-controls" role="group" aria-label="Evaluation period">
            {periods.map((k) => (
              <button key={k} type="button" aria-pressed={window === k} onClick={() => setWindow(k)}>
                {periodLabels[k]}
              </button>
            ))}
          </div>
        </div>
        <p className="li-period-caption" aria-live="polite">
          {month(s.windowStart)} – {month(s.windowEnd)} · {s.n} paired issues · {s.positiveWindows} positive
          windows
          {diag
            ? ' · ' + diag.episodeCount + ' recession ' + (diag.episodeCount === 1 ? 'episode' : 'episodes')
            : ''}
        </p>
        <Diagnostics trial={trial} window={window} />
        <PermitErrors trial={trial} window={window} />
        <details className="li-details">
          <summary>Compare all signal combinations and scores</summary>
          <p>
            All added-signal models use the same training rows and the incumbent’s expanding base rate. The
            matched three-signal model isolates changes from training coverage. Brier error and log loss favor
            lower scores. AUC favors higher scores.
          </p>
          <div className="li-scroll" tabIndex={0} role="region" aria-label="Model scores on paired forecasts">
            <table>
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Brier</th>
                  <th>Log loss</th>
                  <th>AUC</th>
                </tr>
              </thead>
              <tbody>
                {methods.map(([k, name]) => (
                  <tr key={k}>
                    <th scope="row">{name}</th>
                    <td>{dec(s.models[k].brier)}</td>
                    <td>{dec(s.models[k].logLoss)}</td>
                    <td>{dec(s.models[k].auc, 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="li-note">
            {s.incumbentN} mature incumbent issues in this calendar window. {s.missingCandidateMonths} lack a
            paired candidate score.
          </p>
        </details>
      </section>
      <section className="li-section li-forward">
        <div className="li-section-head">
          <div>
            <h2>Forecasts on record</h2>
            <p>
              Each monthly record freezes the forecast before its twelve-month window begins. Outcomes can be
              scored once the full window has published recession labels.
            </p>
          </div>
          <a className="li-download" href="/api/download?file=leadingreceipts">
            <Download size={16} aria-hidden="true" />
            Download forecast records
          </a>
        </div>
        {trial.prospective ? (
          <p>
            <strong>
              {trial.prospective.receiptCount} recorded · {trial.prospective.maturedCount} matured.
            </strong>
            {receipt && (
              <>
                {' '}
                Most recent issue {month(receipt.issueDate)} covers {month(receipt.forecastStart)} –{' '}
                {month(receipt.forecastEnd)}. Its frozen estimates were{' '}
                {pct(receipt.predictions.existingBlend)} for the existing 50/50,{' '}
                {pct(receipt.predictions.permitsBlend)} with permits, and {pct(receipt.predictions.candidate)}{' '}
                with both signals.
              </>
            )}
          </p>
        ) : (
          <p>Prospective records have not been loaded for this research snapshot.</p>
        )}
      </section>
      <details className="li-details li-method">
        <summary>Indicator definitions, validation and sources</summary>
        <p>
          <strong>Housing.</strong> PERMIT counts authorized new privately owned housing units, in thousands
          at a seasonally adjusted annual rate. The signal compares the latest three-month mean with the
          three-month mean six months earlier.{' '}
          <a href="https://fred.stlouisfed.org/series/PERMIT">Building permits on FRED</a>
        </p>
        <p>
          <strong>Layoffs.</strong> ICSA counts seasonally adjusted initial unemployment insurance claims each
          week. A month needs every scheduled weekly observation. The signal compares the latest three-month
          mean of monthly averages with its value twelve months earlier.{' '}
          <a href="https://fred.stlouisfed.org/series/ICSA">Initial claims on FRED</a>
        </p>
        <p>
          <strong>Historical replay.</strong> Each January the logistic models are fit using only issues whose
          full target windows ended before the fit. The current issue uses a monthly refit. Signals are lagged
          two calendar months. Seasonal revisions and retrospective recession dating remain in the historical
          data. Even a good historical result across these few downturns needs new forecast outcomes to
          establish reliability.{' '}
          <a href="https://fred.stlouisfed.org/series/USREC">Recession chronology on FRED</a>
        </p>
      </details>
    </div>
  );
}
