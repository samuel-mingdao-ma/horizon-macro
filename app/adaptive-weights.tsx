'use client';

import { useState } from 'react';
import { Download } from 'lucide-react';
import type { Snapshot } from '../lib/types';
import type {
  WeightTrial,
  WeightWindow,
  WeightMethod,
  WarningMethod,
  WarningResult,
  WarningSlice,
} from '../lib/weight-types';
import './leading-indicators.css';
import './adaptive-weights.css';

const windows: WeightWindow[] = ['all', 'rolling120'];
const windowName = { all: 'Full history', rolling120: 'Latest 10 years' };
const alertModels: [WarningMethod, string][] = [
  ['existingBlend', 'Existing 50/50'],
  ['fixedPermits', 'Permits at 50/50'],
  ['candidate', 'Learned weights'],
  ['fixedRule', '75/25 rule'],
];
const errorModels: [WeightMethod, string][] = [
  ...alertModels,
  ['pooledPermits', 'Permits with one fitted weight'],
  ['originalDynamic', 'Original signals with adaptive weights'],
];
const valid = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
const number = (n: number | null | undefined, digits = 5) => (valid(n) ? n.toFixed(digits) : '—');
const percent = (n: number | null | undefined, digits = 1) =>
  valid(n) ? (100 * n).toFixed(digits) + '%' : '—';
const dateFormat = new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' });
const month = (date: string | null | undefined) =>
  date ? dateFormat.format(new Date(date.slice(0, 7) + '-01T12:00:00Z')) : '—';
const stateName = (s: string | null) =>
  s === 'stress' ? 'Stress' : s === 'normal' ? 'Normal' : 'Unavailable';

function Scorecard({ trial }: { trial: WeightTrial }) {
  const wins = windows.filter(
    (k) =>
      trial.metrics[k].n &&
      trial.metrics[k].models.candidate.brier! < trial.metrics[k].models.existingBlend.brier!,
  );
  const weightWins = windows.filter(
    (k) =>
      trial.metrics[k].n &&
      trial.metrics[k].models.candidate.brier! < trial.metrics[k].models.fixedPermits.brier!,
  );
  const available = windows.every(
    (k) =>
      trial.metrics[k].n &&
      ['candidate', 'existingBlend', 'fixedPermits'].every((id) =>
        valid(trial.metrics[k].models[id as WeightMethod].brier),
      ),
  );
  const describe = (keys: WeightWindow[]) =>
    keys.length === 2
      ? 'both periods'
      : keys.length === 1
        ? windowName[keys[0]].toLowerCase() + ' only'
        : 'neither period';
  return (
    <section className="aw-section aw-score">
      <h2>Probability accuracy</h2>
      <p>
        {available ? (
          <>
            {wins.length ? (
              <>
                Learned weights lower Brier error relative to the existing 50/50 in{' '}
                <strong>{describe(wins)}</strong>.
              </>
            ) : (
              <>
                The existing 50/50 matches or beats learned weights in <strong>both periods</strong>.
              </>
            )}{' '}
            {weightWins.length ? (
              <>Holding the permits signal fixed, changing its weight helps in {describe(weightWins)}.</>
            ) : (
              <>Keeping the permits model at 50% also fares at least as well in both periods.</>
            )}
          </>
        ) : (
          'The comparisons require mature forecasts in both evaluation windows.'
        )}{' '}
        Lower Brier error means the probabilities were closer to the outcomes.
      </p>
      <div className="aw-score-grid" role="table" aria-label="Brier error by model and evaluation window">
        <div role="row" className="aw-score-row aw-score-head">
          <span role="columnheader">Evaluation period</span>
          {alertModels.map(([k, name]) => (
            <span role="columnheader" key={k}>
              {name}
            </span>
          ))}
        </div>
        {windows.map((k) => {
          const s = trial.metrics[k];
          return (
            <div role="row" className="aw-score-row" key={k}>
              <div role="rowheader">
                <b>{windowName[k]}</b>
                <small>
                  {month(s.windowStart)} – {month(s.windowEnd)} · {s.n} matched issues
                </small>
              </div>
              {alertModels.map(([id, name]) => (
                <div role="cell" data-label={name} key={id}>
                  {number(s.models[id].brier)}
                </div>
              ))}
            </div>
          );
        })}
      </div>
      <p className="li-note">
        The learned weights are the primary experiment. The later 75/25 rule gives the permits signal a preset
        75% in stress and 25% in normal conditions.
      </p>
      {trial.warnings && (
        <p className="aw-gate">
          At the {percent(trial.warnings.threshold, 0)} alert threshold,{' '}
          {trial.warnings.gate.passed
            ? 'both periods also clear the early-warning test.'
            : 'the early-warning test clears ' +
              describe(windows.filter((k) => trial.warnings!.windows[k].comparison.passes)) +
              '.'}{' '}
          The test requires more lead time, at least as many downturns detected and an equal or lower
          quiet-expansion false alarm rate.
        </p>
      )}
    </section>
  );
}

function Current({ trial }: { trial: WeightTrial }) {
  const c = trial.latest,
    fit = c.fit;
  return (
    <section className="aw-section">
      <h2>
        Risk for {month(c.forecastStart)} – {month(c.forecastEnd)}
      </h2>
      <p>
        Issued {month(c.issueDate)} using {month(c.featureDate)} signals. The target is at least one U.S.
        recession month during the following year.
      </p>
      <div className="aw-values">
        <div>
          <span>Learned weights</span>
          <strong>{percent(c.probability, 2)}</strong>
        </div>
        <div>
          <span>Permits at 50/50</span>
          <strong>{percent(c.fixedPermitsProbability, 2)}</strong>
        </div>
        <div>
          <span>Existing 50/50</span>
          <strong>{percent(c.existingBlendProbability, 2)}</strong>
        </div>
      </div>
      {c.available && valid(c.permitsWeight) ? (
        <>
          <p>
            The <strong>{stateName(c.state).toLowerCase()}</strong> state gives the permits model{' '}
            <strong>{percent(c.permitsWeight)}</strong> weight. Its raw forecast is{' '}
            {percent(c.rawPermitsProbability)}. The remaining {percent(1 - c.permitsWeight)} goes to the
            historical base of {percent(c.baselineProbability)}.
          </p>
          <dl className="aw-facts">
            <div>
              <dt>Treasury slope</dt>
              <dd>{number(c.slope, 2)} pp</dd>
            </div>
            <div>
              <dt>Credit index</dt>
              <dd>{number(c.credit, 3)}</dd>
            </div>
            <div>
              <dt>Normal-state weight</dt>
              <dd>
                {percent(fit.permits.normal.weight)} <small>· {fit.permits.normal.n} issues</small>
              </dd>
            </div>
            <div>
              <dt>Stress-state weight</dt>
              <dd>
                {percent(fit.permits.stress.weight)} <small>· {fit.permits.stress.n} issues</small>
              </dd>
            </div>
          </dl>
        </>
      ) : (
        <p>The adaptive estimate is unavailable for this issue. {c.reason}</p>
      )}
      <p className="li-note">
        The weight fit used {fit.trainingN} previously issued forecasts.{' '}
        {fit.lastTargetMonth && <>Their last outcome month was {month(fit.lastTargetMonth)}. </>}
        The 75/25 rule currently gives {percent(c.fixedRuleWeight)} weight to the signal and implies{' '}
        {percent(c.fixedRuleProbability, 2)} risk.{' '}
        {fit.warmup ? (
          'The warm-up rule uses 50/50.'
        ) : (
          <>The pooled permits-model weight is {percent(fit.permits.pool.weight)}.</>
        )}
      </p>
    </section>
  );
}

type WeightHistoryRow = WeightTrial['history'][number];
const serial = (date: string) => Number(date.slice(0, 4)) * 12 + Number(date.slice(5, 7)) - 1;
function weightPath(rows: WeightHistoryRow[], x: (r: WeightHistoryRow) => number) {
  let path = '',
    previousMonth = -Infinity;
  for (const row of rows) {
    if (!valid(row.permitsWeight)) {
      previousMonth = -Infinity;
      continue;
    }
    const m = serial(row.date),
      py = (1 - row.permitsWeight) * 100;
    path += (m === previousMonth + 1 ? 'H' + x(row) + 'V' : 'M' + x(row) + ' ') + py + ' ';
    previousMonth = m;
  }
  return path;
}
function WeightHistory({ trial }: { trial: WeightTrial }) {
  const rows = trial.history;
  const [inspection, setInspection] = useState('');
  if (!rows.length) return null;
  const found = inspection ? rows.findIndex((r) => r.date === inspection) : -1;
  const index = found >= 0 ? found : rows.length - 1;
  const selected = rows[index];
  const years = Array.from(new Set(rows.map((r) => r.date.slice(0, 4))));
  const first = serial(rows[0].date),
    span = Math.max(1, serial(rows[rows.length - 1].date) - first);
  const x = (r: WeightHistoryRow) => ((serial(r.date) - first) * 100) / span;
  const choose = (i: number) => setInspection(rows[i].date);
  return (
    <section className="aw-section">
      <div className="li-section-head">
        <div>
          <h2>How the signal weight moved</h2>
          <p>
            A negative Treasury slope or a positive credit index selects the stress weight. All other observed
            combinations use the normal weight.
          </p>
        </div>
        <label className="li-select">
          Jump to issue year
          <select
            value={selected.date.slice(0, 4)}
            onChange={(e) => {
              const yr = e.target.value;
              setInspection(
                (
                  rows.find((r) => r.date.startsWith(yr + selected.date.slice(4, 7))) ??
                  rows.find((r) => r.date.startsWith(yr))!
                ).date,
              );
            }}
          >
            {years.map((y) => (
              <option key={y}>{y}</option>
            ))}
          </select>
        </label>
      </div>
      <figure className="aw-figure">
        <div className="aw-chart-key">
          <span>
            <i /> Applied permits-model weight
          </span>
          <span>
            <i /> Fixed 50%
          </span>
          <span>
            <i /> Stress at issue
          </span>
        </div>
        <div className="aw-plot">
          <div className="aw-axis">
            <span>100%</span>
            <span>50%</span>
            <span>0%</span>
          </div>
          <div className="aw-plot-inner">
            <svg
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
              role="img"
              aria-label="Historical signal weight, fixed 50 percent reference and stress periods. The month slider provides exact values."
              onClick={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const target = first + Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)) * span;
                const nearest = rows.reduce(
                  (best, r, i) =>
                    Math.abs(serial(r.date) - target) < Math.abs(serial(rows[best].date) - target) ? i : best,
                  0,
                );
                choose(nearest);
              }}
            >
              {rows
                .filter((r) => r.state === 'stress')
                .map((r) => (
                  <rect
                    key={r.date}
                    x={Math.max(0, x(r) - 50 / span)}
                    y="0"
                    width={Math.min(100 / span, 100 - x(r) + 50 / span)}
                    height="100"
                    fill="var(--aw-state)"
                  />
                ))}
              <path className="aw-mid" d="M0 50H100" />
              <path className="aw-trajectory" d={weightPath(rows, x)} />
              <path className="aw-cursor" d={`M${x(selected)} 0V100`} />
            </svg>
            {valid(selected.permitsWeight) && (
              <i
                className="aw-point"
                style={{ left: x(selected) + '%', top: (1 - selected.permitsWeight) * 100 + '%' }}
              />
            )}
          </div>
        </div>
        <div className="aw-x-axis">
          <span>{month(rows[0].date)}</span>
          <span>{month(rows[rows.length - 1].date)}</span>
        </div>
      </figure>
      <label className="aw-range">
        Inspect issue{' '}
        <input
          type="range"
          min={0}
          max={rows.length - 1}
          value={index}
          aria-valuetext={month(selected.date)}
          onChange={(e) => choose(Number(e.target.value))}
        />
      </label>
      <div className="aw-inspection" aria-live="polite">
        <div>
          <small>Annual replay issue</small>
          <strong>{month(selected.date)}</strong>
        </div>
        <div>
          <small>{stateName(selected.state)} · signal weight</small>
          <strong>{percent(selected.permitsWeight)}</strong>
        </div>
        <div>
          <small>Adaptive risk</small>
          <strong>{percent(selected.probability)}</strong>
        </div>
        <div>
          <small>Fixed permits risk</small>
          <strong>{percent(selected.fixedPermitsProbability)}</strong>
        </div>
      </div>
      <p className="li-note">
        Inputs {month(selected.featureDate)} · January fit {month(selected.refitDate)} · {selected.trainingN}{' '}
        eligible past forecasts. The 75/25 rule applied {percent(selected.fixedRuleWeight, 0)} weight and gave{' '}
        {percent(selected.fixedRuleProbability)} risk.{' '}
        {selected.trainingN < 60
          ? 'The first 60 eligible outcomes are required to learn the weights.'
          : 'State weights stay fixed within that replay year. The monthly state determines which weight applies.'}
      </p>
    </section>
  );
}

function warningLabel(a: WarningResult) {
  if (!a.firstAlertDate || !valid(a.leadMonths)) return 'No observed alert';
  return month(a.firstAlertDate) + ' · ' + a.leadMonths + ' mo';
}
function crossingLabel(a: WarningResult) {
  if (a.firstCrossDate)
    return (
      month(a.firstCrossDate) +
      ' · ' +
      a.crossLeadMonths +
      ' mo' +
      (a.firstCrossUncertain ? ' (earlier crossing uncertain)' : '')
    );
  if (a.firstAlertKind === 'already-high') return 'Already high at the first alert';
  if (a.firstAlertKind === 'previous-unknown') return 'Previous month unavailable';
  return 'No observed upward crossing';
}
function WarningTable({ s }: { s: WarningSlice }) {
  return (
    <>
      <div
        className="aw-scroll"
        role="region"
        aria-label="Early warnings and quiet-expansion false alarms"
        tabIndex={0}
      >
        <table>
          <thead>
            <tr>
              <th>Forecast</th>
              <th>Complete cycles detected</th>
              <th>Mean lead</th>
              <th>Quiet-month false alerts</th>
              <th>Quiet false alarm rate</th>
            </tr>
          </thead>
          <tbody>
            {alertModels.map(([k, name]) => {
              const m = s.summary[k];
              return (
                <tr key={k}>
                  <th scope="row">{name}</th>
                  <td>
                    {m.completeHits} / {s.completeEpisodes}
                  </td>
                  <td>{number(m.meanLeadMonths, 1)} mo</td>
                  <td>
                    {m.quietAlerts} / {s.quietExpansionN}
                  </td>
                  <td>{percent(m.quietRate)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p>
        Relative to the existing 50/50, the learned weights warned earlier in{' '}
        <strong>{s.comparison.earlier}</strong> complete {s.comparison.earlier === 1 ? 'cycle' : 'cycles'},
        tied in <strong>{s.comparison.tied}</strong>, and warned later in{' '}
        <strong>{s.comparison.later}</strong>.
      </p>
      <p className="li-note">
        Mean lead includes only cycles with all twelve pre-onset issues. A missed cycle contributes zero
        months. False alerts count expansion issues followed by twelve recession-free months. An alert that
        stayed above threshold can span many months.
      </p>
    </>
  );
}
function WarningAudit({
  trial,
  period,
  setPeriod,
}: {
  trial: WeightTrial;
  period: WeightWindow;
  setPeriod: (k: WeightWindow) => void;
}) {
  const warnings = trial.warnings;
  const [method, setMethod] = useState<WarningMethod>('candidate');
  if (!warnings)
    return (
      <section className="aw-section">
        <h2>Early warning</h2>
        <p>Episode-level warning evidence is unavailable in this research build.</p>
      </section>
    );
  const s = warnings.windows[period];
  const m = trial.metrics[period];
  const scored = trial.history.filter(
    (r) =>
      r.commonMature && !!m.windowStart && !!m.windowEnd && m.windowStart <= r.date && r.date <= m.windowEnd,
  );
  const stressRows = scored.filter(
    (r) =>
      r.state === 'stress' && valid(r.probability) && valid(r.existingBlendProbability) && valid(r.target),
  );
  const stressMean = (key: 'target' | 'probability' | 'existingBlendProbability') =>
    stressRows.length ? stressRows.reduce((total, r) => total + r[key]!, 0) / stressRows.length : null;
  return (
    <section className="aw-section">
      <div className="li-section-head">
        <div>
          <h2>Did the alarm sound earlier?</h2>
          <p>
            The alarm starts at {percent(warnings.threshold, 0)} risk. Each recession can contribute up to
            twelve months of advance warning.
          </p>
        </div>
        <div className="aw-tabs" role="group" aria-label="Warning evaluation period">
          {windows.map((k) => (
            <button type="button" key={k} aria-pressed={period === k} onClick={() => setPeriod(k)}>
              {windowName[k]}
            </button>
          ))}
        </div>
      </div>
      <p className="li-note">
        {month(s.windowStart)} – {month(s.windowEnd)} · {s.n} paired issues · {s.completeEpisodes} fully
        observed, {s.partialEpisodes} partly observed and {s.unavailableEpisodes} unobserved pre-onset
        windows.
      </p>
      <WarningTable s={s} />
      {s.comparison.baselineAtCeiling && (
        <p className="li-note">
          The existing 50/50 already flagged every fully observed cycle at the twelve-month limit of this
          test.
        </p>
      )}
      {stressRows.length > 0 && (
        <p>
          Among the {stressRows.length} matched stress-state issues in this period,{' '}
          {percent(stressMean('target'))} were followed by a recession month. The learned model averaged{' '}
          <strong>{percent(stressMean('probability'))}</strong> risk and the existing 50/50 averaged{' '}
          <strong>{percent(stressMean('existingBlendProbability'))}</strong>.
        </p>
      )}
      <details className="aw-detail">
        <summary>First alert and first new crossing by recession</summary>
        <p>
          First alert means the earliest observed expansion issue at or above threshold within the
          twelve-month window. A new crossing also requires the preceding calendar month to be observed below
          threshold. An alarm may already be active as the window opens.
        </p>
        <label className="li-select aw-model-select">
          Forecast to inspect
          <select value={method} onChange={(e) => setMethod(e.target.value as WarningMethod)}>
            {alertModels.map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <div className="aw-scroll" tabIndex={0} role="region" aria-label="Observed alert and crossing dates">
          <table>
            <thead>
              <tr>
                <th>Recession start</th>
                <th>Months observed</th>
                <th>First alert · lead</th>
                <th>Upward crossing</th>
              </tr>
            </thead>
            <tbody>
              {s.episodes.map((e) => {
                const a = e.methods[method];
                return (
                  <tr key={e.onsetDate}>
                    <th scope="row">{month(e.onsetDate)}</th>
                    <td>
                      {e.availableMonths} / 12 · {e.coverage}
                    </td>
                    <td>
                      {e.availableMonths ? warningLabel(a) : 'Unavailable'}
                      {a.firstAlertKind === 'already-high' && (
                        <small className="aw-cell-note">Above threshold the previous month</small>
                      )}
                      {a.firstAlertKind === 'new-crossing' && (
                        <small className="aw-cell-note">Newly above threshold</small>
                      )}
                    </td>
                    <td>{e.availableMonths ? crossingLabel(a) : 'Unavailable'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {!s.episodes.length && (
          <p>No recession starts fall within this period’s observable forecast horizons.</p>
        )}
      </details>
      <details className="aw-detail">
        <summary>How confident were the warnings?</summary>
        <p>
          Threshold counts treat all alarms alike. Brier error also measures how far each probability was from
          the outcome. These rows cover all matched issues, including those issued during recessions.
        </p>
        <div className="aw-scroll" tabIndex={0} role="region" aria-label="Forecast error by realized outcome">
          <table>
            <thead>
              <tr>
                <th>Next twelve months</th>
                <th>Issues</th>
                <th>Existing 50/50</th>
                <th>Learned weights</th>
              </tr>
            </thead>
            <tbody>
              {[0, 1].map((y) => {
                const rows = scored.filter(
                  (r) => r.target === y && valid(r.probability) && valid(r.existingBlendProbability),
                );
                const err = (key: 'probability' | 'existingBlendProbability') =>
                  rows.length
                    ? rows.reduce((sum, r) => sum + ((r[key] as number) - y) ** 2, 0) / rows.length
                    : null;
                return (
                  <tr key={y}>
                    <th scope="row">{y ? 'At least one recession month' : 'No recession month'}</th>
                    <td>{rows.length}</td>
                    <td>{number(err('existingBlendProbability'))}</td>
                    <td>{number(err('probability'))}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

function Methods({ trial, period }: { trial: WeightTrial; period: WeightWindow }) {
  const s = trial.metrics[period];
  return (
    <section className="aw-section">
      <h2>How the weights are learned</h2>
      <p>
        Each January the model fits weights using earlier annual-replay forecasts whose full twelve-month
        outcomes ended before that January. The live issue uses a monthly refit. Signals at each issue are two
        months old.
      </p>
      <p>
        The fitted weight minimizes squared probability error. A penalty of one pulls the pooled weight toward
        50% and each state weight toward the pooled weight. All weights stay between 0% and 100%. The first 60
        mature forecasts are required for fitting. An empty state uses the pooled weight.
      </p>
      <p>
        The 75/25 rule was specified after inspecting the learned model’s scores. It assigns 75% to the
        permits model in stress and 25% in normal conditions. Both approaches use the same historical base
        rate.
      </p>
      <details className="aw-detail">
        <summary>Model controls and scoring details</summary>
        <p>
          {windowName[period]} · {s.n} matched issues · {s.positiveWindows} positive outcomes ·{' '}
          {s.missingCandidateMonths} mature incumbent issues without a paired candidate. The latest-decade
          window spans 120 calendar issue months through the latest mature incumbent issue.
        </p>
        <div className="aw-scroll" tabIndex={0} role="region" aria-label="Probabilistic model controls">
          <table>
            <thead>
              <tr>
                <th>Forecast</th>
                <th>Brier error</th>
                <th>Log loss</th>
                <th>AUC</th>
              </tr>
            </thead>
            <tbody>
              {errorModels.map(([k, label]) => (
                <tr key={k}>
                  <th scope="row">{label}</th>
                  <td>{number(s.models[k]?.brier)}</td>
                  <td>{number(s.models[k]?.logLoss)}</td>
                  <td>{number(s.models[k]?.auc, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="li-note">
          Lower Brier and log loss favor more accurate probabilities. Higher AUC favors better ranking. The
          pooled permits control learns one shared weight across states. The original-signal control fits
          state weights to the three-signal model.
        </p>
      </details>
      <p className="li-note">
        The replay uses revised economic data and retrospective recession dates. Twelve-month targets overlap.
        The two time periods share observations, and a single downturn can generate many positive forecasts.{' '}
        <a href="#leading">Inspect the earlier permits experiment.</a>
      </p>
    </section>
  );
}

export default function AdaptiveWeights({ data }: { data: Snapshot }) {
  const trial = data.weightTrial;
  const [period, setPeriod] = useState<WeightWindow>('rolling120');
  if (!trial)
    return (
      <article className="li-research aw-research">
        <h1>State-dependent forecast weights</h1>
        <p>The current research build is awaiting the weight experiment.</p>
      </article>
    );
  const record = trial.prospective,
    latestRecord = record?.latestReceipt;
  return (
    <article className="li-research aw-research">
      <header className="li-title">
        <div>
          <h1>When should the signal carry more weight?</h1>
          <p>
            Credit conditions and the Treasury curve determine how much of the one-year U.S. recession
            forecast comes from the permits model and how much comes from the historical base rate.
          </p>
        </div>
        <a href="/api/download?file=weights" className="li-download">
          <Download size={16} aria-hidden />
          Download replay data
        </a>
      </header>
      <Scorecard trial={trial} />
      <WarningAudit trial={trial} period={period} setPeriod={setPeriod} />
      <Current trial={trial} />
      <WeightHistory trial={trial} />
      <Methods trial={trial} period={period} />
      <section className="aw-section">
        <div className="li-section-head">
          <h2>Frozen forecasts</h2>
          <a className="li-download" href="/api/download?file=weightreceipts">
            <Download size={16} aria-hidden />
            Download records
          </a>
        </div>
        {record ? (
          <>
            <p>
              <strong>
                {record.receiptCount} recorded · {record.maturedCount} matured.
              </strong>{' '}
              {latestRecord && (
                <>
                  The latest record was issued for {month(latestRecord.issueDate)}. It put risk at{' '}
                  {percent(latestRecord.predictions.candidate, 2)} with learned weights and{' '}
                  {percent(latestRecord.predictions.existingBlend, 2)} under the existing 50/50. The
                  exploratory rule gave {percent(latestRecord.predictions.fixedRule, 2)}.
                </>
              )}
            </p>
            {record.maturedCount > 0 && record.metrics && (
              <p>
                Prospective Brier error is {number(record.metrics.candidate?.brier)} for learned weights and{' '}
                {number(record.metrics.existingBlend?.brier)} for the existing 50/50.
              </p>
            )}
          </>
        ) : (
          <p>The first eligible monthly forecast is awaiting capture.</p>
        )}
        <p className="li-note">
          Each issue is frozen before its forecast window begins. Its outcome enters the record after all
          twelve monthly recession labels are available.
        </p>
      </section>
    </article>
  );
}
