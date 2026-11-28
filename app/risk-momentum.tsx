'use client';

import { useState } from 'react';
import { Download } from 'lucide-react';
import type { MomentumEpisode, MomentumRow, MomentumTrial, MomentumWindow, PaceRule } from '../lib/momentum-types';
import type { WarningResult } from '../lib/weight-types';
import './leading-indicators.css';
import './risk-momentum.css';

const dateFormat = new Intl.DateTimeFormat('en-US', {month: 'short', year: 'numeric', timeZone: 'UTC'});
const month = (date: string | null) => date ? dateFormat.format(new Date(date.slice(0, 7) + '-01T12:00:00Z')) : '—';
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const pct = (v: number | null, digits = 1) => finite(v) ? (100 * v).toFixed(digits) + '%' : '—';
const points = (v: number | null) => finite(v) ? ((v > 0 ? '+' : '') + (100 * v).toFixed(1) + ' pp') : '—';
const score = (v: number | null, digits = 5) => finite(v) ? v.toFixed(digits) : '—';
const count = (v: number, noun: string) => v + ' ' + noun + (v === 1 ? '' : 's');
const alertText = (v: boolean | null) => v === true ? 'On' : v === false ? 'Off' : 'Unavailable';
const ruleNames = {quarter: 'Three-month rule', month: 'One-month rule'};
const periodNames = {all: 'Full history', rolling120: 'Latest 10 years'};
const paceDecision = (row: MomentumRow, rule: PaceRule) => rule === 'quarter' ? row.quarterAlert : row.monthAlert;

function calendarIssue(onset: string, lead: number) {
  const date = new Date(onset.slice(0, 7) + '-01T12:00:00Z');
  date.setUTCMonth(date.getUTCMonth() - lead);
  return date.toISOString().slice(0, 10);
}

function RiskPath({current}: {current: MomentumTrial['latest']}) {
  const path = current.path;
  if (path.length !== 4 || path.some(point => !finite(point.probability))) {
    return <p className="li-note">The four-month path requires four consecutive sets of model inputs.</p>;
  }
  const max = Math.min(1, Math.max(0.4, Math.ceil(10 * Math.max(...path.map(p => p.probability!))) / 10));
  const y = (v: number) => 94 - 84 * v / max;
  const x = (index: number) => 6 + index * 88 / 3;
  const trace = path.map((p, i) => (i ? 'L ' : 'M ') + x(i) + ' ' + y(p.probability!)).join(' ');
  return <figure className="pm-path">
    <figcaption>Four monthly readings at the current fit</figcaption>
    <div className="pm-path-drawing">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img"
        aria-label={'Conditional onset risk. ' + path.map(p => month(p.date) + ', ' + pct(p.probability, 2)).join('. ')}>
        <path className="pm-threshold" d={'M 0 ' + y(.30) + ' H 100'} />
        <path className="pm-trace" d={trace}/>
      </svg>
      <span className="pm-threshold-label" style={{top: y(.30)+'%'}}>30% alert</span>
      {path.map((p, i) => <i key={p.date} className="pm-path-point" style={{left: x(i)+'%', top: y(p.probability!)+'%'}}/>)}
    </div>
    <div className="pm-path-labels" aria-hidden="true">{path.map(p =>
      <div key={p.date}><span>{month(p.date)}</span><b>{pct(p.probability)}</b></div>)}</div>
  </figure>;
}

function Current({trial}: {trial: MomentumTrial}) {
  const c = trial.latest;
  return <section className="li-section pm-current" aria-label="Current conditional recession risk">
    <div><h2>Current onset risk</h2>
      <strong className="pm-reading">{pct(c.probability, 2)}</strong>
      <p>If the U.S. is in expansion in {month(c.issueDate)}, this is its estimated chance of entering recession from {month(c.forecastStart)} through {month(c.forecastEnd)}.</p>
      <p className="pm-change">Three-month change <strong>{points(c.change3m)}</strong></p>
      {!c.available && <p className="li-note">{c.reason || 'Inputs for the current forecast are incomplete.'}</p>}
    </div>
    <div><RiskPath current={c}/>
      <dl className="pm-states" aria-label="Current warning decisions">
        {([['30% baseline', c.levelAlert], ['Three-month rule', c.quarterAlert], ['One-month rule', c.monthAlert]] as const).map(([label, active]) =>
          <div key={label}><dt>{label}</dt><dd data-active={active === true}>{alertText(active)}</dd></div>)}
      </dl>
    </div>
  </section>;
}

function firstAlert(result: WarningResult) {
  if (!result.firstAlertDate || result.leadMonths === null) return 'No observed alert';
  const kind = result.firstAlertKind === 'already-high' ? ', already active'
    : result.firstAlertKind === 'previous-unknown' ? ', prior month unknown' : ', newly active';
  return month(result.firstAlertDate) + ' (' + count(result.leadMonths, 'month') + ' early' + kind + ')';
}

function EpisodeStrip({episode, rows, rule}: {episode: MomentumEpisode; rows: Map<string, MomentumRow>; rule: PaceRule}) {
  const dates = Array.from({length: 12}, (_, index) => calendarIssue(episode.onsetDate, 12 - index));
  const pointsByDate = dates.map(date => {
    const row = rows.get(date);
    return row && row.onsetDate === episode.onsetDate ? row : undefined;
  });
  const firstAdded = pointsByDate.findIndex(row => row && row.levelAlert === false && paceDecision(row, rule) === true);
  const firstAvailable = pointsByDate.findIndex(row => row);
  const [focus, setFocus] = useState(firstAdded >= 0 ? firstAdded : Math.max(0, firstAvailable));
  const selected = pointsByDate[focus];
  return <div className="pm-episode">
    <div className="pm-legend"><span><i className="active"/>30% alert</span><span><i className="added"/>Additional pace alert</span><span><i/>No alert</span><span><i className="missing"/>No scored issue</span></div>
    <div className="pm-strip" role="group" aria-label="Select an issue by months before recession">
      {pointsByDate.map((row, i) => {
        const state = !row ? 'missing' : row.levelAlert ? 'active' : paceDecision(row, rule) ? 'added' : 'off';
        const meaning = {missing: 'no scored issue', active: '30% alert', added: 'additional pace alert', off: 'no alert'}[state];
        return <button type="button" key={dates[i]} className={state} aria-pressed={focus === i}
          aria-label={month(dates[i]) + ', ' + count(12-i, 'month') + ' before onset, ' + meaning}
          onClick={() => setFocus(i)}>{12-i}</button>;
      })}
    </div>
    <div className="pm-strip-axis"><span>Months before recession</span><span>Onset · {month(episode.onsetDate)}</span></div>
    <div className="pm-inspect" aria-live="polite"><strong>{month(dates[focus])}</strong>
      {selected ? <span>Risk <b>{pct(selected.probability, 2)}</b> · Three-month change <b>{points(selected.change3m)}</b> · {ruleNames[rule]} <b>{alertText(paceDecision(selected, rule))}</b></span>
        : <span>No mature, paired expansion forecast for this issue in the selected window.</span>}</div>
    <p>First alert for the 30% baseline was <strong>{firstAlert(episode.methods.level)}</strong>. For the selected rule it was <strong>{firstAlert(episode.methods[rule])}</strong>.</p>
    {episode.coverage !== 'full' && <p className="li-note">This episode has {episode.availableMonths} of its twelve pre-onset months. The mean lead uses complete episodes.</p>}
    <details className="li-details"><summary>First switch from off to on</summary>
      <p>The 30% baseline first switched on in <strong>{month(episode.methods.level.firstCrossDate)}</strong> and the selected rule in <strong>{month(episode.methods[rule].firstCrossDate)}</strong>. A dash means no switch was observed.
        {' '}An alert that was active before this twelve-month window can give early coverage without a new signal in that month.
        {(episode.methods.level.firstCrossUncertain || episode.methods[rule].firstCrossUncertain) && ' An earlier switch is uncertain because a prior decision is missing.'}</p>
    </details>
  </div>;
}

function Replay({trial}: {trial: MomentumTrial}) {
  const [rule, setRule] = useState<PaceRule>('quarter');
  const [period, setPeriod] = useState<MomentumWindow>('all');
  const [episodeDate, setEpisodeDate] = useState('');
  const w = trial.windows[period], baseline = w.summary.level, candidate = w.summary[rule];
  const comparison = rule === 'quarter' ? w.quarterComparison : w.monthComparison;
  const changes = w.changes[rule], gate = trial.gate[rule];
  const rows = new Map(trial.history.filter(r =>
    r.commonMature && w.windowStart && w.windowEnd && r.date >= w.windowStart && r.date <= w.windowEnd
  ).map(row => [row.date, row]));
  const episode = w.episodes.find(e => e.onsetDate === episodeDate) ?? w.episodes.find(e => e.onsetDate.startsWith('2001-')) ?? w.episodes.at(-1);
  const hasEvidence = w.n > 0 && w.completeEpisodes > 0;
  return <>
    <section className="li-section pm-test">
      <div className="li-section-head"><h2>Testing the early warning</h2><div className="li-controls" role="group" aria-label="Pace rule">
        {(['quarter', 'month'] as const).map(k => <button type="button" key={k} aria-pressed={rule===k} onClick={() => setRule(k)}>{ruleNames[k]}</button>)}
      </div></div>
      <p>The baseline alerts at 30%. Below that line, the selected rule also alerts if risk is at least 20%, rose in the latest month, and its average pace over the past three months would take it to 30% within <strong>{rule === 'quarter' ? 'three months' : 'one month'}</strong>.</p>
      <div className="pm-window"><div><h3>Historical replay</h3><p className="li-note">{month(w.windowStart)} – {month(w.windowEnd)} · {count(w.n, 'scored expansion month')}</p></div>
        <div className="li-controls" role="group" aria-label="Historical window">{(['all', 'rolling120'] as const).map(k =>
          <button type="button" key={k} aria-pressed={period===k} onClick={() => setPeriod(k)}>{periodNames[k]}</button>)}</div></div>
      {hasEvidence && <p className="pm-result" aria-live="polite">The selected rule warned earlier for <strong>{comparison.earlier} of {count(w.completeEpisodes, 'recession')}</strong> and added alerts in <strong>{count(changes.quietDates.length, 'quiet month')}</strong>.</p>}
      <div className="li-scroll pm-table" role="region" aria-label="Warning policy comparison" tabIndex={0}><table><thead><tr><th scope="col">Measure</th><th scope="col">30% baseline</th><th scope="col">{ruleNames[rule]}</th></tr></thead><tbody>
        <tr><th scope="row">Quiet months alerted</th><td>{baseline.quietAlerts} / {w.quietExpansionN}</td><td>{candidate.quietAlerts} / {w.quietExpansionN}</td></tr>
        <tr><th scope="row">Pre-onset months alerted</th><td>{baseline.preOnsetAlerts} / {w.preOnsetN}</td><td>{candidate.preOnsetAlerts} / {w.preOnsetN}</td></tr>
        <tr><th scope="row">Mean lead, months</th><td>{score(baseline.meanLeadMonths, 2)}</td><td>{score(candidate.meanLeadMonths, 2)}</td></tr>
        <tr><th scope="row">Complete recessions flagged</th><td>{baseline.completeHits} / {w.completeEpisodes}</td><td>{candidate.completeHits} / {w.completeEpisodes}</td></tr>
      </tbody></table></div>
      <p className="li-note">A quiet month is an expansion issue followed by twelve months without a recession onset. Each alerted issue counts once. Average lead gives missed recessions zero months.
        {comparison.baselineAtCeiling && ' The baseline was already active at the maximum twelve-month lead in every complete episode here.'}</p>
      <details className="li-details"><summary>Additional alert dates · {count(changes.quietDates.length + changes.preOnsetDates.length, 'month')}</summary>
        <dl className="pm-dates">{(['quietDates','preOnsetDates'] as const).map(key => <div key={key}>
          <dt>{key==='quietDates' ? 'During quiet expansions' : 'Before a recession onset'} ({changes[key].length})</dt>
          <dd>{changes[key].length > 0 ? changes[key].map(month).join(' · ') : 'None'}</dd></div>)}</dl>
        <p className="li-note">These issues triggered only the selected pace rule. A repeat alert can add coverage within a recession’s lead-up even when its first warning date stays the same.</p>
      </details>
      {trial.windows.all.completeEpisodes > 0 && trial.windows.rolling120.completeEpisodes > 0 &&
        <p className="pm-verdict"><strong>{gate.passed ? 'The rule met the joint test.' : 'The rule fell short of the joint test.'}</strong>{' '}
          The test requires an earlier alert for at least one complete recession, no later alerts or missed detections, and zero extra quiet-month alerts in both samples.
          {' '}{gate.earlierBoth ? 'Mean lead improved in both samples.' : 'Mean lead did not improve in both samples.'}</p>}
    </section>
    <section className="li-section">
      <div className="li-section-head"><h2>Inside a recession’s warning window</h2>
        {episode && <label className="li-select pm-select">Recession onset<select value={episode.onsetDate} onChange={e => setEpisodeDate(e.target.value)}>
          {w.episodes.map(e => <option key={e.onsetDate} value={e.onsetDate}>{month(e.onsetDate)}{e.coverage === 'full' ? '' : ' · ' + e.coverage}</option>)}</select></label>}</div>
      {episode ? <EpisodeStrip key={period + rule + episode.onsetDate} episode={episode} rows={rows} rule={rule}/> : <p>No recession lead-up is available in this sample.</p>}
    </section>
  </>;
}

function CaseComparison({trial}: {trial: MomentumTrial}) {
  const full = trial.windows.all, diagnostic = full.caseComparison;
  const hit = trial.history.find(row => row.date === diagnostic.date);
  const quiet = diagnostic.matches.find(row => row.date === '2019-02-01') ?? diagnostic.matches[0];
  if (!diagnostic.available || !hit || !hit.onsetDate || !quiet) return null;
  const nextOnset = full.episodes.find(e => e.onsetDate > quiet.date)?.onsetDate;
  function lead(issue: string, onset: string) {
    const when = new Date(onset), issued = new Date(issue);
    return 12 * (when.getUTCFullYear() - issued.getUTCFullYear()) + when.getUTCMonth() - issued.getUTCMonth();
  }
  return <section className="li-section"><h2>Why one early warning came with a false alarm</h2>
    <p>In {month(quiet.date)}, risk and both measures of its rise were at least as high as in {month(hit.date)}. The forecast year following {month(hit.date)} contained a recession onset. The year following {month(quiet.date)} stayed in expansion.</p>
    <div className="li-scroll pm-case" role="region" aria-label="Matched pre-recession warning and quiet-month false alarm" tabIndex={0}><table>
      <thead><tr><th scope="col">At issue</th><th scope="col">{month(hit.date)}</th><th scope="col">{month(quiet.date)}</th></tr></thead><tbody>
        <tr><th scope="row">12-month risk</th><td>{pct(hit.probability, 2)}</td><td>{pct(quiet.probability, 2)}</td></tr>
        <tr><th scope="row">Latest one-month rise</th><td>{points(hit.change1m)}</td><td>{points(quiet.change1m)}</td></tr>
        <tr><th scope="row">Three-month rise</th><td>{points(hit.change3m)}</td><td>{points(quiet.change3m)}</td></tr>
        <tr><th scope="row">Time to next onset</th><td>{count(lead(hit.date, hit.onsetDate), 'month')}</td><td>{nextOnset ? count(lead(quiet.date, nextOnset), 'month') : 'Beyond 12 months'}</td></tr>
      </tbody></table></div>
    <p>Any rule using only these three readings that becomes more willing to alert as each rises must flag {month(quiet.date)} if it flags {month(hit.date)}. Raising the cutoffs alone cannot distinguish these two issues on a twelve-month horizon.</p>
    <p className="li-note">This retrospective comparison uses quiet, below-threshold issues with complete risk paths.</p>
  </section>;
}

function Accuracy({trial}: {trial: MomentumTrial}) {
  return <section className="li-section"><h2>Probability accuracy</h2>
    <p>All three rules use the expansion model’s original twelve-month probability. Only the decision to raise an alert changes, so each rule earns the same scores on the same monthly forecasts.</p>
    <div className="li-scroll pm-table" role="region" aria-label="Probability accuracy across both evaluation windows" tabIndex={0}>
      <table><thead><tr><th scope="col">Scored expansion issues</th><th scope="col">Brier error</th><th scope="col">Log loss</th><th scope="col">AUC</th></tr></thead>
        <tbody>{(['all','rolling120'] as const).map(k => {
          const w = trial.windows[k], s = w.probabilityScores;
          return <tr key={k}><th scope="row">{periodNames[k]} ({w.n})</th><td>{score(s.brier)}</td><td>{score(s.logLoss)}</td><td>{score(s.auc, 3)}</td></tr>;
        })}</tbody></table></div>
    <p className="li-note">The latest decade is part of the full history. Adjacent twelve-month outcomes overlap. Lower Brier error and log loss indicate more accurate probabilities. AUC measures how well forecasts rank subsequent outcomes.</p>
  </section>;
}

export default function RiskMomentum({trial}: {trial?: MomentumTrial}) {
  if (!trial) return <article className="li-research pm-view"><h1>How fast is recession risk rising?</h1><p>The scheduled research build is awaiting the warning replay.</p></article>;
  const f = trial.prospective;
  const full = trial.windows.all, recent = trial.windows.rolling120;
  const known = full.episodes.find(episode => episode.onsetDate.startsWith('2001-'));
  const recovered = known && (known.methods.quarter.leadMonths ?? 0) > (known.methods.level.leadMonths ?? 0);
  return <article className="li-research pm-view"><header className="li-title"><div><h1>How fast is recession risk rising?</h1>
    <p>{recovered ? <>The three-month rule moved the first warning for the 2001 recession from <strong>{month(known.methods.level.firstAlertDate)}</strong> to <strong>{month(known.methods.quarter.firstAlertDate)}</strong>. It added alerts in {count(full.changes.quarter.quietDates.length, 'quiet month')}, including {recent.changes.quarter.quietDates.length} in the latest decade.</> : <>Can a rising probability give the expansion model more time to warn of recession without adding false alarms?</>}</p></div>
    <a className="li-download" href="/api/download?file=momentum"><Download size={16} aria-hidden="true"/>Monthly replay CSV</a></header>
    <p className="li-note"><a href="#confirmation">Compare the economic signals behind the May 2000 and February 2019 warnings.</a></p>
    <Current trial={trial}/><Replay trial={trial}/><CaseComparison trial={trial}/><Accuracy trial={trial}/>
    <section className="li-section li-method"><h2>How the pace is measured</h2>
      <p>For each issue, the model scores four consecutive months of inputs using one set of coefficients and one expansion base rate. That holds the model fixed while the economic readings change. Earlier points in each path are reconstructed at the issue’s fit. Inputs carry the model’s two-month lag.</p>
      <p>The three-month change is measured in percentage points. Continuing this pace gives a hypothetical time to the 30% line. The twelve-month recession forecast remains the current fitted probability. Incomplete paths can still trigger the 30% rule.</p>
      <p className="li-note">Both pace rules were specified before this replay. The 2001 delay was already known when the experiment was designed. Historical inputs use revised data and recession months are dated retrospectively.
        {' '}<a href="#onset">Expansion-model evidence</a> · <a href="https://www.nber.org/research/business-cycle-dating">NBER business cycle dating</a></p>
    </section>
    <section className="li-section"><div className="li-section-head"><h2>Warnings frozen at issue</h2>{!!f?.receiptCount &&
      <a className="li-download" href="/api/download?file=momentumreceipts"><Download size={16} aria-hidden="true"/>Forecast records</a>}</div>
      {f?.receiptCount ? <p><strong>{f.receiptCount} recorded · {f.maturedCount} scored · {f.excludedCount} excluded · {f.pendingCount} pending.</strong>
        {f.latestReceipt && <> Latest issue {month(f.latestReceipt.issueDate)}.</>}</p> : <p>The first eligible monthly record is awaiting capture.</p>}
      <p className="li-note">Each record freezes the risk path and all three decisions before the forecast year begins. Scoring requires an expansion in the issue month and a complete year of outcome labels.</p>
    </section>
  </article>;
}
