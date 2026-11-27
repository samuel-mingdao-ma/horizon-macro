'use client';

import { useState } from 'react';
import { Download } from 'lucide-react';
import type { CreditMethod, CreditSignals, CreditState, CreditTrial, CreditWindow } from '../lib/credit-types';
import type { WarningResult } from '../lib/weight-types';
import './leading-indicators.css';
import './credit-dynamics.css';

const periods: CreditWindow[] = ['all', 'rolling120'];
const periodName = { all: 'Full history', rolling120: 'Latest 10 years' };
const stateName: Record<CreditState, string> = {
  persistent: 'Persistent tightness only', sudden: 'Sudden deterioration only', both: 'Both conditions',
  neither: 'Neither condition', unknown: 'Incomplete history',
};
const modelName: Record<CreditMethod, string> = {
  benchmark: 'Published permits benchmark', matchedLevel: 'Credit level on matched training months',
  slowOnly: 'Prior average only', shockOnly: 'Recent change only', candidate: 'Prior average and recent change',
};
const isNumber = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x);
const num = (x: number | null, digits = 5) => isNumber(x) ? x.toFixed(digits) : '—';
const pct = (x: number | null, digits = 1) => isNumber(x) ? (100 * x).toFixed(digits) + '%' : '—';
const signed = (x: number | null) => isNumber(x) ? (x > 0 ? '+' : '') + x.toFixed(3) : '—';
const dateFormat = new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' });
const month = (date: string | null) => date ? dateFormat.format(new Date(date.slice(0, 7) + '-01T12:00:00Z')) : '—';
const ordinal = (d: string) => 12 * Number(d.slice(0, 4)) + Number(d.slice(5, 7));
const count = (a: number, b: number) => b ? a + ' / ' + b : '—';

function stateOf(s: CreditSignals): CreditState {
  if (s.persistent == null || s.sudden == null) return 'unknown';
  if (s.persistent && s.sudden) return 'both';
  if (s.persistent) return 'persistent';
  return s.sudden ? 'sudden' : 'neither';
}

function Scorecard({ trial }: { trial: CreditTrial }) {
  const comparable = periods.every(k => isNumber(trial.metrics[k].models.benchmark.brier)
    && isNumber(trial.metrics[k].models.candidate.brier));
  const wins = periods.filter(k => trial.metrics[k].models.candidate.brier! < trial.metrics[k].models.benchmark.brier!);
  const nearlyTied = periods.filter(k => {
    const { benchmark, candidate } = trial.metrics[k].models;
    return isNumber(candidate.brier) && isNumber(benchmark.brier) && Math.abs(benchmark.brier - candidate.brier) < 1e-6;
  });
  const result = wins.length === 2 ? 'both periods' : wins.length === 1 ? 'the ' + (wins[0] === 'all' ? 'full sample' : 'latest decade') + ' only' : 'neither period';
  return <section className="li-section cd-score">
    <h2>Forecast performance</h2>
    <p>{comparable ? <>Splitting credit lowers Brier error in <strong>{result}</strong>.</> : 'Probability scores require mature forecasts in both periods.'}{' '}
      {nearlyTied.map(k => {
        const scores = trial.metrics[k].models;
        return <span key={k}>{periodName[k]} is effectively tied, with an absolute Brier difference of {num(Math.abs(scores.benchmark.brier! - scores.candidate.brier!), 8)}. </span>;
      })}Each comparison uses identical forecast months and the same {pct(trial.warnings.threshold, 0)} alert threshold.</p>
    <div className="cd-pair">{periods.map(k => {
      const m = trial.metrics[k], w = trial.warnings.windows[k], b = w.summary.benchmark, c = w.summary.candidate;
      return <div key={k} className="cd-period">
        <h3>{periodName[k]}</h3>
        <div className="cd-caption">{month(m.windowStart)} – {month(m.windowEnd)} · {m.n} scored months</div>
        <table aria-label={periodName[k] + ' paired forecast performance'}><thead><tr><th scope="col">Measure</th><th scope="col">Benchmark</th><th scope="col">Split credit</th></tr></thead>
          <tbody>
            <tr><th scope="row">Brier error</th><td>{num(m.models.benchmark.brier)}</td><td>{num(m.models.candidate.brier)}</td></tr>
            <tr><th scope="row">Quiet months with alerts</th><td>{count(b.quietAlerts, w.quietExpansionN)}</td><td>{count(c.quietAlerts, w.quietExpansionN)}</td></tr>
            <tr><th scope="row">Mean warning lead <small>(months)</small></th><td>{num(b.meanLeadMonths, 1)}</td><td>{num(c.meanLeadMonths, 1)}</td></tr>
            <tr><th scope="row">Recessions flagged</th><td>{count(b.completeHits, w.completeEpisodes)}</td><td>{count(c.completeHits, w.completeEpisodes)}</td></tr>
          </tbody>
        </table>
      </div>;
    })}</div>
    <p>{trial.warnings.jointGate.passed ? 'Split credit met' : 'Split credit fell short of'} the joint test across both periods.
      It requires lower Brier error, fewer quiet-month alerts and an earlier mean warning with at least as many recessions flagged.</p>
    <p className="cd-note">Lower Brier error means more accurate probabilities. Quiet months are expansion months followed by twelve recession-free months. Lead times use complete pre-recession windows and count misses as zero.</p>
  </section>;
}

type Point = CreditSignals & { date: string };
type PlotField = 'credit' | 'creditSlow' | 'creditShock' | 'shockThreshold';
function CreditChart({ points, mode }: { points: Point[]; mode: 'level' | 'change' }) {
  const fields: [PlotField, PlotField] = mode === 'level' ? ['credit', 'creditSlow'] : ['creditShock', 'shockThreshold'];
  const first = ordinal(points[0].featureDate), last = ordinal(points[points.length - 1].featureDate);
  const values = [0, ...points.flatMap(p => fields.map(f => p[f]).filter(isNumber))];
  const top = Math.max(...values), bottom = Math.min(...values);
  const pad = Math.max((top - bottom) * 0.08, .005), max = top + pad, min = bottom - pad;
  const x = (p: Point) => 2 + 996 * (ordinal(p.featureDate) - first) / Math.max(1, last - first);
  const y = (v: number) => 100 * (1 - (v - min) / (max - min));
  function line(field: PlotField) {
    let previous = -Infinity;
    return points.map(p => {
      const value = p[field], time = ordinal(p.featureDate);
      if (!isNumber(value)) return '';
      const cmd = time === previous + 1 ? 'L' : 'M';
      previous = time;
      return cmd + x(p).toFixed(2) + ',' + y(value).toFixed(2);
    }).join(' ');
  }
  const labels = mode === 'level' ? ['Monthly credit index', 'Prior three-month average'] : ['Recent change', 'Prior five-year 90th percentile'];
  const end = points[points.length - 1], lastValue = end[fields[0]];
  return <figure className="cd-figure">
    <figcaption><span><i aria-hidden="true" />{labels[0]}</span><span><i aria-hidden="true" />{labels[1]}</span></figcaption>
    <div className="cd-chart">
      <div className="cd-y" aria-hidden="true"><span>{signed(max)}</span><span>{signed(min)}</span></div>
      <div className="cd-drawing">
        <svg viewBox="0 0 1000 100" preserveAspectRatio="none" role="img" aria-label={labels.join(' and ') + ' from ' + month(points[0].featureDate) + ' through ' + month(end.featureDate) + ', in index points.'}>
          <path d={'M0,' + y(0) + 'H1000'} className="cd-zero" />
          <path d={line(fields[1])} className="cd-reference" />
          <path d={line(fields[0])} className="cd-series" />
        </svg>
        {isNumber(lastValue) && <span className="cd-marker" aria-hidden="true" style={{left: x(end) / 10 + '%', top: y(lastValue) + '%'}} />}
      </div>
    </div>
    <div className="cd-x"><span>{month(points[0].featureDate)}</span><span>{month(end.featureDate)}</span></div>
  </figure>;
}

function SignalHistory({ trial }: { trial: CreditTrial }) {
  const [selected, setSelected] = useState<string | null>(null);
  const [mode, setMode] = useState<'level' | 'change'>('change');
  const latest = trial.latest, live = { ...latest, date: latest.issueDate };
  const rows = [...trial.history.filter(r => r.date < live.date), live];
  const index = selected ? rows.findIndex(r => r.date === selected) : -1;
  const active = index >= 0 ? index : rows.length - 1;
  const row = rows[active], isCurrent = row.date === latest.issueDate;
  const years = [...new Set(rows.map(r => r.date.slice(0, 4)))];
  const range = rows.slice(0, active + 1).filter(r => ordinal(r.featureDate) > ordinal(row.featureDate) - 36);
  function jump(year: string) {
    const candidates = rows.filter(r => r.date.startsWith(year));
    const offset = Number(row.date.slice(5, 7));
    const nearest = candidates.reduce((best, r) => Math.abs(Number(r.date.slice(5, 7)) - offset) < Math.abs(Number(best.date.slice(5, 7)) - offset) ? r : best);
    setSelected(nearest.date);
  }
  return <section className="li-section">
    <div className="li-section-head"><h2>Credit at the forecast date</h2>
      <div className="li-controls" role="group" aria-label="Credit chart series">{(['change', 'level'] as const).map(v =>
        <button type="button" key={v} aria-pressed={v === mode} onClick={() => setMode(v)}>{v === 'change' ? 'Recent change' : 'Index level'}</button>
      )}</div>
    </div>
    <p>Credit observations end two months before each issue. The chart follows the last three years of available observations up to the selected signal month.</p>
    <CreditChart points={range} mode={mode} />
    <div className="cd-scrub">
      <label>Issue year<select value={row.date.slice(0, 4)} onChange={e => jump(e.target.value)}>{years.map(y => <option key={y}>{y}</option>)}</select></label>
      <label>Issue month<input aria-label="Inspect forecast issue month" aria-valuetext={month(row.date)} type="range" min={0} max={rows.length - 1} value={active} onChange={e => setSelected(rows[Number(e.target.value)].date)} /></label>
      {!isCurrent && <button type="button" className="cd-reset" onClick={() => setSelected(null)}>Latest issue</button>}
    </div>
    <div className="cd-inspect">
      <div className="cd-inspect-title"><h3>{month(row.date)}</h3><span>{isCurrent ? 'Current monthly refit' : 'Historical January refit'} · {month(row.featureDate)} credit data</span></div>
      <p className="cd-state">{stateName[stateOf(row)]}</p>
      <dl className="cd-readings">
        <div><dt>Monthly index</dt><dd>{signed(row.credit)}</dd></div>
        <div><dt>Prior average</dt><dd>{signed(row.creditSlow)}</dd></div>
        <div><dt>Recent change</dt><dd>{signed(row.creditShock)}</dd></div>
        <div><dt>Shock cutoff</dt><dd>{signed(row.shockThreshold)}</dd></div>
      </dl>
      <p>One-year risk <strong>{pct(row.probability, 2)}</strong> with split credit and <strong>{pct(row.benchmarkProbability, 2)}</strong> with the permits benchmark.
        {isCurrent && <> Forecast window {month(latest.forecastStart)} – {month(latest.forecastEnd)}.</>}{isCurrent && !latest.available && <> {latest.reason}</>}</p>
    </div>
  </section>;
}

function firstWarning(r: WarningResult) {
  if (!r.firstAlertDate) return 'No observed alert';
  const kind = r.firstAlertKind === 'new-crossing' ? 'new crossing'
    : r.firstAlertKind === 'already-high' ? 'already above threshold' : 'previous month unknown';
  return month(r.firstAlertDate) + ' · ' + r.leadMonths + ' mo · ' + kind;
}

function crossing(r: WarningResult) {
  if (r.firstCrossDate) return (r.firstCrossUncertain ? 'Earliest confirmed ' : '') + month(r.firstCrossDate) + ' · ' + r.crossLeadMonths + ' mo';
  return r.firstCrossUncertain ? 'Uncertain · missing previous month' : 'No new crossing observed';
}

function Audit({ trial, period, setPeriod }: { trial: CreditTrial; period: CreditWindow; setPeriod: (k: CreditWindow) => void }) {
  const w = trial.warnings.windows[period], m = trial.metrics[period];
  const buckets = trial.warnings.buckets[period];
  const [onset, setOnset] = useState<string | null>(null);
  const episode = w.episodes.find(e => e.onsetDate === onset) ?? w.episodes[w.episodes.length - 1];
  const changes = w.alertChanges;
  const changedMonths = trial.history.filter(r =>
    r.commonMature && m.windowStart && m.windowEnd && r.date >= m.windowStart && r.date <= m.windowEnd &&
    isNumber(r.probability) && isNumber(r.benchmarkProbability) &&
    (r.probability >= trial.warnings.threshold) !== (r.benchmarkProbability >= trial.warnings.threshold));
  const both = buckets.find(b => b.state === 'both');
  return <section className="li-section">
    <div className="li-section-head"><h2>What followed each credit state?</h2>
      <div className="li-controls" role="group" aria-label="Credit evidence period">{periods.map(k =>
        <button type="button" aria-pressed={k === period} key={k} onClick={() => setPeriod(k)}>{periodName[k]}</button>
      )}</div>
    </div>
    <p><strong>Persistent tightness</strong> means each of the three preceding observation months had a positive index.
      A <strong>sudden deterioration</strong> means the current index exceeds its prior three-month average by a positive amount above the 90th percentile of the previous 60 monthly changes. Both conditions can occur together.</p>
    <div className="cd-scroll" role="region" aria-label="Credit states, outcomes and false alerts" tabIndex={0}>
      <table><thead><tr><th scope="col">Credit state</th><th scope="col">Scored months</th><th scope="col">Recession outcomes</th><th scope="col">Observed rate</th><th scope="col">Benchmark risk¹</th><th scope="col">Split risk¹</th><th scope="col">Quiet alerts²</th></tr></thead>
        <tbody>{buckets.filter(b => b.state !== 'unknown' || b.n > 0).map(b => <tr key={b.state}><th scope="row">{stateName[b.state]}</th>
          <td>{b.n}</td><td>{b.positives}</td><td>{pct(b.observedRate)}</td><td>{pct(b.benchmarkMean)}</td><td>{pct(b.candidateMean)}</td>
          <td>{b.quietN ? b.benchmarkQuietAlerts + ' → ' + b.candidateQuietAlerts + ' of ' + b.quietN : '—'}</td></tr>)}</tbody>
      </table>
    </div>
    <p className="cd-note">¹ Mean forecast probability in each state. ² Benchmark to split-credit alerts, among quiet expansion months only. A positive outcome means at least one of the next twelve months is in recession. Adjacent forecasts can share that outcome.</p>
    {both && both.positives > 0 && isNumber(both.recessionIssuedPositiveN) && (
      <p>When both conditions held, <strong>{both.recessionIssuedPositiveN} of {both.positives}</strong> positive forecasts were issued during an ongoing recession.
        {isNumber(both.preOnsetN) && <> Another {both.preOnsetN} came during the expansion before onset.</>}</p>
    )}
    <h3 className="cd-subtitle">Which alarms changed?</h3>
    <p>Across {w.quietExpansionN} quiet months, split credit cleared <strong>{changes.quietRemoved}</strong> benchmark alerts and added <strong>{changes.quietAdded}</strong>.
      In the twelve months before recession starts, it cleared {changes.preOnsetRemoved} and added {changes.preOnsetAdded}.</p>
    <details className="li-details"><summary>Months where the {pct(trial.warnings.threshold, 0)} alert changed ({changedMonths.length})</summary>
      {changedMonths.length ? <div className="cd-scroll" role="region" aria-label="Changed alert months" tabIndex={0}>
        <table><thead><tr><th scope="col">Issue month</th><th scope="col">Economic phase</th><th scope="col">Benchmark</th><th scope="col">Split credit</th><th scope="col">Alert change</th></tr></thead>
          <tbody>{changedMonths.map(r => <tr key={r.date}><th scope="row">{month(r.date)}</th><td>{({
            'expansion-no-recession': 'Quiet expansion', 'pre-onset': 'Before recession', 'recession-issued': 'Already in recession',
          } as Record<string, string>)[r.issuePhase ?? ''] ?? 'Unclassified'}</td><td>{pct(r.benchmarkProbability, 2)}</td><td>{pct(r.probability, 2)}</td>
            <td>{r.probability! >= trial.warnings.threshold ? 'Added' : 'Cleared'}</td></tr>)}</tbody>
        </table>
      </div> : <p>Both models gave the same alert decision in all {m.n} scored months in this period.</p>}
    </details>
    <div className="cd-episodes">
      <div className="li-section-head"><h3>Recession warning dates</h3>
        {episode && <label className="cd-select">Recession start<select value={episode.onsetDate} onChange={e => setOnset(e.target.value)}>
          {w.episodes.map(e => <option key={e.onsetDate} value={e.onsetDate}>{month(e.onsetDate)}</option>)}
        </select></label>}
      </div>
      <p>{w.completeEpisodes} complete pre-recession {w.completeEpisodes === 1 ? 'window' : 'windows'} in {periodName[period].toLowerCase()}.
        {w.comparison.sufficient && <> Split credit warned earlier in {w.comparison.earlier}, at the same time in {w.comparison.tied}, and later in {w.comparison.later}.</>}
        {w.comparison.baselineAtCeiling && <> The benchmark was already at the twelve-month limit for every fully observed recession in this period.</>}</p>
      {episode && <><p className="cd-note">{month(episode.onsetDate)} · {episode.availableMonths} of 12 preceding expansion months observed.
        {episode.coverage !== 'full' && <> This incomplete episode is excluded from mean warning lead.</>}</p>
        <div className="cd-scroll" role="region" aria-label="First alerts and new threshold crossings" tabIndex={0}>
          <table className="cd-table-left"><thead><tr><th scope="col">Forecast</th><th scope="col">First observed alert</th><th scope="col">First new crossing</th></tr></thead>
            <tbody>{(['benchmark', 'candidate'] as const).map(k => <tr key={k}><th scope="row">{k === 'benchmark' ? 'Permits benchmark' : 'Split credit'}</th>
              <td>{firstWarning(episode.methods[k])}</td><td>{crossing(episode.methods[k])}</td></tr>)}</tbody></table>
        </div>
        <p className="cd-note">A new crossing requires a forecast below the threshold in the preceding calendar month. An alert already active when the window opens can qualify for lead time.</p>
      </>}
    </div>
    <details className="li-details"><summary>Model controls for {periodName[period].toLowerCase()}</summary>
      <div className="cd-scroll" tabIndex={0} role="region" aria-label="Ablations and matched credit level">
        <table><thead><tr><th scope="col">Credit input</th><th scope="col">Brier error</th><th scope="col">Log loss</th><th scope="col">AUC</th></tr></thead>
          <tbody>{(Object.keys(modelName) as CreditMethod[]).map(k => <tr key={k}><th scope="row">{modelName[k]}</th><td>{num(m.models[k].brier)}</td><td>{num(m.models[k].logLoss)}</td><td>{num(m.models[k].auc, 3)}</td></tr>)}</tbody>
        </table>
      </div>
      <p className="cd-note">All five forecasts share the same {m.n} mature evaluation months, including {m.positiveWindows} positive outcomes. {m.missingCandidateMonths} mature benchmark months have no paired candidate. The matched-level control isolates changes in training coverage. Lower Brier error and log loss favor better probabilities. Higher AUC favors better ranking.</p>
    </details>
  </section>;
}

export function CreditDynamics({ trial }: { trial?: CreditTrial }) {
  const [period, setPeriod] = useState<CreditWindow>('rolling120');
  if (!trial) return <article className="li-research cd-research"><h1>Credit persistence and shocks</h1><p>The scheduled research build is awaiting the credit comparison.</p></article>;
  const record = trial.prospective;
  return <article className="li-research cd-research">
    <header className="li-title"><div><h1>Credit persistence and shocks</h1>
      <p>Does the path of credit conditions improve the one-year U.S. recession forecast? The benchmark puts half its weight on the building-permits model and half on the historical recession rate.</p>
    </div><a className="li-download" href="/api/download?file=creditdynamics"><Download size={16} aria-hidden="true" />Monthly replay CSV</a></header>
    <Scorecard trial={trial} />
    <SignalHistory trial={trial} />
    <Audit trial={trial} period={period} setPeriod={setPeriod} />
    <section className="li-section"><h2>How the comparison works</h2>
      <p>The benchmark uses the monthly credit level. The split-credit model replaces that input with the preceding three-month average and the latest deviation from it. Their sum recovers the monthly level. The fitted model can give a persistent move and a recent jump different coefficients. Both models retain building permits, the Treasury slope, the labor signal and the fixed 50/50 blend.</p>
      <p>The candidate and its three fitted controls use the same eligible training months and a common ridge penalty. Each January refit uses only outcomes whose entire forecast year has ended. The current forecast is refit monthly. The two state flags describe the data in the tables. The probability model uses the continuous readings.</p>
      <p className="cd-note">The replay uses revised economic observations and retrospectively dated U.S. recessions. Recent forecasts overlap and a decade may contain only one downturn. The credit subindex measures conditions relative to its historical average. <a href="https://fred.stlouisfed.org/series/NFCICREDIT">Chicago Fed credit subindex via FRED</a>. <a href="#onset">Inspect forecasts trained on expansion months.</a></p>
    </section>
    <section className="li-section"><div className="li-section-head"><h2>Forecasts frozen at issue</h2>
      {record && record.receiptCount > 0 && <a className="li-download" href="/api/download?file=creditreceipts"><Download size={16} aria-hidden="true" />Forecast records</a>}
    </div>
      {record?.receiptCount ? <p><strong>{record.receiptCount} recorded · {record.maturedCount} matured.</strong>{' '}
        {record.latestReceipt && <>The {month(record.latestReceipt.issueDate)} record puts split-credit risk at {pct(record.latestReceipt.predictions.candidate, 2)} and benchmark risk at {pct(record.latestReceipt.predictions.benchmark, 2)}.</>}
        {record.maturedCount > 0 && record.metrics?.candidate && record.metrics.benchmark && <> Frozen Brier errors are {num(record.metrics.candidate.brier)} and {num(record.metrics.benchmark.brier)}, respectively.</>}
      </p> : <p>The first eligible monthly forecast is awaiting capture.</p>}
      <p className="cd-note">Each monthly record preserves the inputs and forecasts available before the prediction window opens. Outcomes enter the prospective score after all twelve months are available.</p>
    </section>
  </article>;
}

export default CreditDynamics;
