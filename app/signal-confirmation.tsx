'use client';

import { useState } from 'react';
import { Download } from 'lucide-react';
import type {
  ConfirmationPeriod, ConfirmationReading, ConfirmationRule, ConfirmationTrial, ConfirmationWindow,
} from '../lib/confirmation-types';
import type { WarningResult } from '../lib/weight-types';
import './leading-indicators.css';
import './signal-confirmation.css';

const ruleNames = {pressure: 'All three pressures', direction: 'All three worsening', breadth: 'Two of three pressures'};
const ruleFields = {pressure: 'pressureAlert', direction: 'directionAlert', breadth: 'breadthAlert'} as const;
const rules: ConfirmationRule[] = ['pressure', 'direction', 'breadth'];
const periods: ConfirmationWindow[] = ['all', 'rolling120'];
const periodNames = {all: 'Full history', rolling120: 'Latest 10 years'};
const calendar = new Intl.DateTimeFormat('en-US', {month: 'short', year: 'numeric', timeZone: 'UTC'});
const month = (date: string | null) => date ? calendar.format(new Date(date.slice(0, 7) + '-01T12:00:00Z')) : '—';
const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
const fixed = (n: number | null, digits: number) => finite(n) ? n.toFixed(digits) : '—';
const pct = (n: number | null) => finite(n) ? fixed(n * 100, 2) + '%' : '—';
const signed = (n: number | null, digits: number, unit = '') => finite(n) ? (n > 0 ? '+' : '') + n.toFixed(digits) + unit : '—';
const delta = (now: number | null, before: number | null) => finite(now) && finite(before) ? now - before : null;
const state = (decision: boolean | null) => decision === true ? 'On' : decision === false ? 'Off' : 'Unavailable';
const voteCount = (row: ConfirmationReading, rule: ConfirmationRule) => rule === 'direction' ? row.directionVotes : row.pressureVotes;

type Signal = {name: string; test: string; votes: (r: ConfirmationReading) => boolean | null; reading: (r: ConfirmationReading) => string};
function signals(rule: ConfirmationRule): Signal[] {
  const directional = rule === 'direction';
  return [
    {name: 'Housing permits', test: directional ? 'Six-month growth slowed' : 'Six-month growth below zero',
      votes: r => directional ? r.permitsSlowing : r.permitsNegative,
      reading: r => directional ? signed(delta(r.permitGrowth6, r.lagPermitGrowth6), 2, ' pp') : signed(r.permitGrowth6, 2, '%')},
    {name: 'Initial jobless claims', test: directional ? 'Yearly growth accelerated' : 'Yearly growth above zero',
      votes: r => directional ? r.claimsRising : r.claimsPositive,
      reading: r => directional ? signed(delta(r.claimsGrowth12, r.lagClaimsGrowth12), 2, ' pp') : signed(r.claimsGrowth12, 2, '%')},
    {name: 'Credit conditions', test: 'Subindex rose in three months', votes: r => r.creditTightening,
      reading: r => signed(delta(r.credit, r.lagCredit), 3)},
  ];
}

function Vote({value}: {value: boolean | null}) {
  return <span className="cf-vote" data-vote={value === true ? 'yes' : value === false ? 'no' : 'missing'}>
    {value === true ? 'Yes' : value === false ? 'No' : 'Missing'}</span>;
}

function Cases({trial, rule}: {trial: ConfirmationTrial; rule: ConfirmationRule}) {
  const rows = ['2000-05-01', '2019-02-01'].map(date => trial.history.find(row => row.date === date));
  if (!rows[0] || !rows[1]) return <p>The two case months need complete historical coverage.</p>;
  const cases = [rows[0], rows[1]];
  const first = trial.caseAttribution[cases[0].date], second = trial.caseAttribution[cases[1].date];
  const effects = [['slope','Yield curve'], ['credit','Credit conditions'], ['labor','Unemployment gap'], ['permitGrowth6','Permits growth']] as const;
  return <>
    <div className="li-scroll cf-cases" role="region" tabIndex={0} aria-label="May 2000 and February 2019 signal comparison">
      <table><thead><tr><th scope="col">Forecast issue</th>{cases.map(r => <th key={r.date} scope="col">{month(r.date)}</th>)}</tr></thead>
      <tbody>
        <tr className="cf-case-risk"><th scope="row">12-month onset risk</th>{cases.map(r => <td key={r.date}>{pct(r.probability)}</td>)}</tr>
        {signals(rule).map(s => <tr key={s.name}><th scope="row">{s.name}<small>{s.test}</small></th>
          {cases.map(r => <td key={r.date}><strong>{s.reading(r)}</strong> <Vote value={s.votes(r)}/></td>)}</tr>)}
        <tr className="cf-decision"><th scope="row">Confirmed warning</th>{cases.map(r => <td key={r.date}>
          <strong>{state(r[ruleFields[rule]])}</strong><small>{voteCount(r, rule) ?? '—'} of 3 votes</small></td>)}</tr>
        <tr><th scope="row">Following 12 months</th>{cases.map(r => <td key={r.date}>
          {r.commonMature && r.target === 1 ? 'Onset in ' + month(r.onsetDate) : r.commonMature && r.target === 0 ? 'No onset' : 'Unscored'}</td>)}</tr>
      </tbody></table>
    </div>
    <p className="li-note">The inputs for these issues end in {month(cases[0].featureDate)} and {month(cases[1].featureDate)} respectively.
      Changes compare readings three calendar months apart. Both cases were known before the confirmation rules were set.</p>
    {first && second && [first, second].every(a => a.effects.slope > 0 && a.effects.slope === Math.max(...Object.values(a.effects))) &&
      <p>The yield curve contributed the largest increase in both model readings. It added <strong>{signed(100 * first.effects.slope, 2, ' pp')}</strong> in {month(cases[0].date)} and <strong>{signed(100 * second.effects.slope, 2, ' pp')}</strong> in {month(cases[1].date)}.</p>}
    {first && second && <details className="li-details cf-attribution"><summary>What drove the three-month rise in risk?</summary>
      <div className="li-scroll cf-table" role="region" tabIndex={0} aria-label="Model contributions to the three-month risk changes">
        <table><thead><tr><th scope="col">Risk contribution</th>{cases.map(r => <th scope="col" key={r.date}>{month(r.date)}</th>)}</tr></thead>
        <tbody>{effects.map(([key, label]) => <tr key={key}><th scope="row">{label}</th>
          <td>{signed(100 * first.effects[key], 2, ' pp')}</td><td>{signed(100 * second.effects[key], 2, ' pp')}</td></tr>)}
          <tr><th scope="row">Total risk change</th><td>{signed(100 * first.change, 2, ' pp')}</td><td>{signed(100 * second.change, 2, ' pp')}</td></tr>
        </tbody></table></div>
      <p className="li-note">The calculation holds each issue’s model and base rate fixed and moves all four inputs together in a straight line from their earlier to later readings. Negative contributions offset increases. These figures describe statistical associations within the fitted model. Jobless claims cast a confirmation vote while the unemployment gap enters the probability model.</p>
    </details>}
  </>;
}

function Current({trial, rule}: {trial: ConfirmationTrial; rule: ConfirmationRule}) {
  const c = trial.latest;
  return <section className="li-section">
    <div className="cf-current">
      <div><h2>Current risk and confirmation</h2><strong className="cf-risk">{pct(c.probability)}</strong>
        <p>If {month(c.issueDate)} is an expansion month, this is the estimated chance of recession starting from {month(c.forecastStart)} through {month(c.forecastEnd)}.</p>
        {!c.available && <p className="li-note">{c.reason || 'Inputs for this forecast are incomplete.'}</p>}</div>
      <div><p className="cf-observed">Economic readings through {month(c.featureDate)}</p>
        <dl className="cf-signals">{signals(rule).map(s => <div key={s.name}><dt>{s.name}</dt>
          <dd>{s.reading(c)} <Vote value={s.votes(c)}/></dd></div>)}</dl>
        <p className="li-note">30% alert <b>{state(c.levelAlert)}</b> · Pace alert <b>{state(c.quarterAlert)}</b> · Confirmed alert <b>{state(c[ruleFields[rule]])}</b></p>
      </div>
    </div>
  </section>;
}

function EpisodeDate({value}: {value: WarningResult}) {
  return value.firstAlertDate ? <>{month(value.firstAlertDate)}<small>{value.leadMonths} months early{value.firstAlertKind === 'already-high' ? ' · already on' : ''}</small></> : <>No observed alert</>;
}

function Replay({window: w, period, rule, onPeriod}: {window: ConfirmationPeriod; period: ConfirmationWindow; rule: ConfirmationRule; onPeriod: (p: ConfirmationWindow) => void}) {
  const policies = ['level', 'quarter', rule] as const;
  const titles = ['30% baseline', 'Pace alone', 'Confirmed'];
  const exceeded = w.changes[rule].quietDates.length;
  return <section className="li-section">
    <div className="li-section-head"><h2>Early warnings and false alarms</h2>
      <div className="li-controls" role="group" aria-label="Historical window">{periods.map(key => <button key={key} type="button" aria-pressed={period === key}
        onClick={() => onPeriod(key)}>{periodNames[key]}</button>)}</div></div>
    <p>{month(w.windowStart)} – {month(w.windowEnd)} · {w.n} scored expansion months. The confirmation rule added <strong>{exceeded} false-alert {exceeded === 1 ? 'month' : 'months'}</strong> to the 30% baseline.</p>
    <div className="li-scroll cf-table" role="region" tabIndex={0} aria-label="Paired alert outcomes"><table>
      <thead><tr><th scope="col">Measure</th>{titles.map(name => <th key={name} scope="col">{name}</th>)}</tr></thead><tbody>
        <tr><th scope="row">Quiet months alerted</th>{policies.map(k => <td key={k}>{w.summary[k].quietAlerts} / {w.quietExpansionN}</td>)}</tr>
        <tr><th scope="row">Pre-onset months alerted</th>{policies.map(k => <td key={k}>{w.summary[k].preOnsetAlerts} / {w.preOnsetN}</td>)}</tr>
        <tr><th scope="row">Mean lead in months</th>{policies.map(k => <td key={k}>{fixed(w.summary[k].meanLeadMonths, 2)}</td>)}</tr>
        <tr><th scope="row">Complete episodes detected</th>{policies.map(k => <td key={k}>{w.summary[k].completeHits} / {w.completeEpisodes}</td>)}</tr>
      </tbody></table></div>
    <h3 className="cf-subheading">First alert before each recession</h3>
    <div className="li-scroll cf-table" role="region" tabIndex={0} aria-label="First warning date and lead by recession"><table>
      <thead><tr><th scope="col">Recession onset</th>{titles.map(name => <th key={name} scope="col">{name}</th>)}</tr></thead>
      <tbody>{w.episodes.map(e => <tr key={e.onsetDate}><th scope="row">{month(e.onsetDate)}{e.coverage !== 'full' && <small>{e.availableMonths} / 12 months observed</small>}</th>
        {policies.map(k => <td key={k}><EpisodeDate value={e.methods[k]}/></td>)}</tr>)}</tbody>
    </table></div>
    <p className="li-note">A quiet issue is an expansion month followed by twelve months without an onset. Mean lead counts complete episodes, with zero for a miss.
      Early coverage can include an alert already active when the twelve-month window opened.</p>
  </section>;
}

function Audit({trial, period, rule}: {trial: ConfirmationTrial; period: ConfirmationWindow; rule: ConfirmationRule}) {
  const w = trial.windows[period];
  const rows = trial.history.filter(r => r.commonMature && !r.levelAlert && r.quarterAlert && w.windowStart && w.windowEnd && w.windowStart <= r.date && r.date <= w.windowEnd);
  const [issue, setIssue] = useState('2000-05-01');
  const selected = rows.find(r => r.date === issue) ?? rows[0];
  const checks = signals(rule);
  return <section className="li-section"><div className="li-section-head"><h2>Inspect an extra pace alert</h2>
    {selected && <label className="li-select">Forecast issue<select value={selected.date} onChange={e => setIssue(e.target.value)}>{rows.map(r =>
      <option key={r.date} value={r.date}>{month(r.date)} · {r.target === 1 ? 'pre-onset' : 'quiet'}</option>)}</select></label>}
    </div>
    {!selected ? <p>No scored extra pace alerts in this window.</p> : <>
      <p>{rows.length} issues in this window triggered the sub-30% pace alert. At the {month(selected.date)} issue, risk was <strong>{pct(selected.probability)}</strong>.
        The selected rule {selected[ruleFields[rule]] ? 'confirmed' : 'withheld'} the warning. {selected.target === 1
          ? 'A recession began in ' + month(selected.onsetDate) + '.' : 'The following twelve months contained no recession onset.'}</p>
      <div className="li-scroll cf-table" role="region" aria-label="Signal readings used at selected issue" tabIndex={0}><table>
        <thead><tr><th scope="col">Indicator</th><th scope="col">{month(selected.lagFeatureDate)}</th>
          <th scope="col">{month(selected.featureDate)}</th><th scope="col">Vote</th></tr></thead><tbody>
          <tr><th scope="row">Six-month permits growth</th><td>{signed(selected.lagPermitGrowth6, 2, '%')}</td><td>{signed(selected.permitGrowth6, 2, '%')}</td><td><Vote value={checks[0].votes(selected)}/></td></tr>
          <tr><th scope="row">Yearly claims growth</th><td>{signed(selected.lagClaimsGrowth12, 2, '%')}</td><td>{signed(selected.claimsGrowth12, 2, '%')}</td><td><Vote value={checks[1].votes(selected)}/></td></tr>
          <tr><th scope="row">Credit subindex</th><td>{signed(selected.lagCredit, 3)}</td><td>{signed(selected.credit, 3)}</td><td><Vote value={checks[2].votes(selected)}/></td></tr>
        </tbody></table></div>
      <details className="li-details"><summary>All {rows.length} extra pace alerts and their votes</summary>
        <div className="li-scroll cf-audit" role="region" aria-label="All additional pace alerts in selected window" tabIndex={0}><table>
          <thead><tr>{['Issue', 'Outcome', 'Permits', 'Claims', 'Credit', 'Confirmed'].map(s => <th key={s} scope="col">{s}</th>)}</tr></thead>
          <tbody>{rows.map(r => <tr key={r.date}><th scope="row">{month(r.date)}</th><td>{r.target === 1 ? 'Pre-onset' : 'Quiet'}</td>
            {checks.map(check => <td key={check.name}><Vote value={check.votes(r)}/></td>)}<td>{state(r[ruleFields[rule]])}</td></tr>)}</tbody>
        </table></div></details>
    </>}
  </section>;
}

function Accuracy({trial}: {trial: ConfirmationTrial}) {
  return <section className="li-section"><h2>Probability accuracy</h2>
    <p>Each rule reuses the issued expansion-model probability for every month. Brier error and log loss are therefore identical across the alarm policies.</p>
    <div className="li-scroll cf-table" role="region" aria-label="Shared probability scores" tabIndex={0}><table>
      <thead><tr>{['Expansion issues', 'Brier error', 'Log loss', 'AUC'].map(name => <th key={name} scope="col">{name}</th>)}</tr></thead>
      <tbody>{periods.map(k => { const w = trial.windows[k], scores = w.probabilityScores;
        return <tr key={k}><th scope="row">{periodNames[k]} · {w.n}</th><td>{fixed(scores.brier, 5)}</td>
          <td>{fixed(scores.logLoss, 5)}</td><td>{fixed(scores.auc, 3)}</td></tr>; })}</tbody>
    </table></div><p className="li-note">The latest decade is contained in the full sample. Twelve-month outcomes overlap, and the same recession can account for several pre-onset months.</p>
  </section>;
}

export default function SignalConfirmation({trial}: {trial?: ConfirmationTrial}) {
  const [rule, setRule] = useState<ConfirmationRule>('pressure');
  const [period, setPeriod] = useState<ConfirmationWindow>('all');
  if (!trial) return <article className="li-research cf-view"><h1>Do the economic signals confirm the warning?</h1><p>The scheduled research build is awaiting the confirmation replay.</p></article>;
  const f = trial.prospective, w = trial.windows[period], g = trial.gate[rule];
  const enough = trial.windows.all.completeEpisodes > 0 && trial.windows.rolling120.completeEpisodes > 0;
  const may = trial.history.find(r => r.date === '2000-05-01');
  const allQuiet = trial.windows.all.changes.pressure.quietDates.length;
  const recentQuiet = trial.windows.rolling120.changes.pressure.quietDates.length;
  return <article className="li-research cf-view">
    <header className="li-title"><div><h1>Do the economic signals confirm the warning?</h1>
      <p>{may && may.commonMature && may.quarterAlert && !may.levelAlert
        ? <>Requiring all three pressure signals {may.pressureAlert ? 'kept' : 'withheld'} the May 2000 warning. It added {allQuiet} false-alert {allQuiet === 1 ? 'month' : 'months'} over the full replay and {recentQuiet} in the latest decade.</>
        : <>Can housing, labor and credit corroborate an early recession warning before risk reaches 30%?</>}</p></div>
      <a className="li-download" href="/api/download?file=confirmation"><Download size={16} aria-hidden="true"/>Monthly replay CSV</a></header>
    <section className="li-section cf-compare">
      <div className="li-section-head"><h2>May 2000 versus February 2019</h2><label className="li-select">Confirmation rule
        <select value={rule} onChange={e => setRule(e.target.value as ConfirmationRule)}>{rules.map(k => <option key={k} value={k}>{ruleNames[k]}</option>)}</select></label></div>
      <p>{rule === 'direction' ? 'This rule looks for worsening conditions across all three signals over the past quarter.'
        : (rule === 'pressure' ? 'All three signals must agree.' : 'At least two signals must agree.') + ' The votes are falling permits, rising jobless claims and tighter credit.'}
        {' '}Confirmation applies only when the pace rule would add a warning below 30%.</p>
      <Cases trial={trial} rule={rule}/>
      {enough && <p className="cf-verdict" aria-live="polite"><strong>{g.passed ? 'Met the historical test.' : 'Fell short of the historical test.'}</strong>{' '}
        {g.mayRetained ? 'Kept the extra month before 2001.' : 'Lost the extra month before 2001.'}{' '}
        {g.allNoAddedFalse && g.rolling120NoAddedFalse ? 'Matched the baseline false-alert count in both periods.' :
          'Added ' + trial.windows.all.changes[rule].quietDates.length + ' false-alert months in the full history and ' + trial.windows.rolling120.changes[rule].quietDates.length + ' in the latest decade.'}</p>}
    </section>
    <Current trial={trial} rule={rule}/>
    <Replay window={w} period={period} rule={rule} onPeriod={setPeriod}/>
    <Audit trial={trial} period={period} rule={rule}/>
    <Accuracy trial={trial}/>
    <section className="li-section li-method"><h2>How confirmation works</h2>
      <p>Risk at or above 30% always triggers an alert. Below 30%, the pace rule first requires risk of at least 20%, a monthly rise and a positive three-month change fast enough to reach 30% within another quarter. The selected confirmation rule then checks the economic readings.</p>
      <p>Permit growth compares the three-month average of building permits with the same measure six months earlier. Claims growth compares the three-month average of initial unemployment insurance claims with a year earlier. A rise in the Chicago Fed credit subindex indicates tighter financial conditions. The directional rule compares each of these readings with its value three calendar months earlier.</p>
      <p>Each forecast uses economic inputs dated two months before the issue. A missing required vote prevents an additional warning. The conditional model uses permits, the yield curve, credit and unemployment, so the votes can share information with the risk estimate. The replay uses revised economic observations and retrospectively dated recessions.</p>
      <p className="li-note"><a href="#curvelegs">See which Treasury yield drove the May 2000 and February 2019 risk increases</a> · <a href="#momentum">Risk momentum</a> · <a href="https://fred.stlouisfed.org/series/PERMIT">Building permits</a> · <a href="https://fred.stlouisfed.org/series/ICSA">Initial claims</a> · <a href="https://fred.stlouisfed.org/series/NFCICREDIT">Credit conditions</a> · <a href="https://fred.stlouisfed.org/series/USREC">Recession dates</a></p>
    </section>
    <section className="li-section"><div className="li-section-head"><h2>Decisions frozen at issue</h2>
      {!!f?.receiptCount && <a className="li-download" href="/api/download?file=confirmationreceipts"><Download size={16} aria-hidden="true"/>Forecast records</a>}</div>
      {f?.receiptCount ? <p><strong>{f.receiptCount} recorded · {f.maturedCount} scored · {f.excludedCount} excluded · {f.pendingCount} pending.</strong>
        {f.latestReceipt && <> Latest issue {month(f.latestReceipt.issueDate)}.</>}</p> : <p>The first eligible monthly issue is awaiting capture.</p>}
      <p className="li-note">The monthly record preserves the probability, votes and warning decisions before the forecast window opens. Scoring requires a full outcome year after an expansion issue.</p>
    </section>
  </article>;
}
