'use client';

import {useState} from 'react';
import {Download} from 'lucide-react';
import type {JointBounds, JointCalendarPath, JointFlags, JointIssue, JointPeriod, JointRadius, JointStressTrial, JointWindow, JointWitness} from '../lib/joint-stress-types';
import './leading-indicators.css';
import './joint-stress.css';

const may = '2000-05-01';
const feb = '2019-02-01';
const onset2001 = '2001-04-01';
const periods: JointPeriod[] = ['all', 'rolling120'];
const windowNames = {all: 'Full sample', rolling120: 'Latest 10 years'};
const dates = new Intl.DateTimeFormat('en-US', {month: 'short', year: 'numeric', timeZone: 'UTC'});
const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
const month = (date?: string | null) => date ? dates.format(new Date(date.slice(0,7) + '-01T12:00:00Z')) : '—';
const digits = (n: number | null, d = 5) => finite(n) ? n.toFixed(d) : '—';
const percent = (n: number | null) => finite(n) ? (100 * n).toFixed(2) + '%' : '—';
const signed = (n: number | null, d = 2) => finite(n) ? (n < 0 ? '−' : n > 0 ? '+' : '') + Math.abs(n).toFixed(d) : '—';
const pp = (n: number | null) => finite(n) ? signed(100 * n) + ' pp' : '—';
const bp = (n: number | null) => finite(n) ? signed(n, Number.isInteger(n) ? 0 : 2) + ' bp' : '—';
const flag = (v?: boolean | null) => v === true ? 'On' : v === false ? 'Off' : '—';
const count = (v: number | null) => finite(v) ? String(v) : '—';
const radiusName = (r: JointRadius) => r === '0' ? 'Observed' : '±' + r + ' bp';
const bounds = (pair: JointBounds, format: (n: number | null) => string) => pair[0] === pair[1] ? format(pair[0]) : format(pair[0]) + ' to ' + format(pair[1]);
const warning = (f: JointFlags, certified: boolean) => f[0] === null ? 'Unavailable' : f[0] ? 'Always on' : !f[1] ? 'Always off' : certified ? 'Can flip' : 'Unresolved';

function featureMonths(end: string) {
  return [3, 2, 1, 0].map(lag => {
    const d = new Date(end.slice(0,7) + '-01T12:00:00Z');
    d.setUTCMonth(d.getUTCMonth() - lag);
    return dates.format(d);
  });
}

function RiskPath({observed, scenario, labels, range}: {observed: JointWitness; scenario: JointWitness; labels: string[]; range: JointBounds}) {
  const values = [...observed.path, ...scenario.path, ...range].filter(finite);
  if (!values.length) return null;
  const low = Math.max(0, Math.floor(Math.min(...values, 0.29) * 20) / 20);
  const high = Math.min(1, Math.ceil(Math.max(...values, 0.31) * 20) / 20);
  const y = (v: number) => 100 * (high - v) / (high - low);
  const different = scenario.path.some((p,i) => finite(p) && finite(observed.path[i]) && Math.abs(p - observed.path[i]!) > 1e-10);
  const lines = (path: JointWitness['path'], className: string) =>
    path.slice(1).map((v,i) => finite(v) && finite(path[i]) ? <line key={i} className={className}
      x1={100 * i / 3} x2={100 * (i + 1) / 3} y1={y(path[i]!)} y2={y(v)} vectorEffect="non-scaling-stroke"/> : null);
  return <figure className="js-path">
    <figcaption>Next-year onset probability over four signal months</figcaption>
    <div className="js-plot" role="img" aria-label={labels.map((d,i)=>d + ', observed ' + percent(observed.path[i]) + ', example ' + percent(scenario.path[i])).join('. ')}>
      {[high, 0.3, low].map(v => <div className={'js-guide' + (v === 0.3 ? ' js-guide-level' : '')} style={{top:y(v) + '%'}} key={v}>
        <span>{Math.round(100 * v)}%</span></div>)}
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        {different && lines(observed.path, 'js-line-observed')}
        {lines(scenario.path, 'js-line-scenario')}
      </svg>
      {finite(range[0]) && finite(range[1]) && range[0] !== range[1] && <span className="js-whisker" aria-hidden="true"
        style={{top:y(range[1])+'%',height:(y(range[0])-y(range[1]))+'%'}}/>}
      {scenario.path.map((v,i)=>finite(v) && <i key={i} style={{top:y(v)+'%',left:(100*i/3)+'%'}}/>)}
    </div>
    <div className="js-axis" aria-hidden="true">{labels.map(d=><span key={d}>{d}</span>)}</div>
    <div className="js-key"><span><i/>{different ? 'Repriced example' : 'Observed and example coincide'}</span>
      {different && <span><i className="js-observed"/>Observed</span>}<span><i className="js-threshold"/>30% alarm</span>
      {range[0] !== range[1] && <span><i className="js-possible"/>Issue risk range</span>}</div>
  </figure>;
}

function CaseReplay({issue, radius, issueDate}: {issue: JointIssue | null; radius: JointRadius; issueDate: string}) {
  if (!issue) return <p>This issue is unavailable in the current vintage.</p>;
  const sample = issue.radii[radius];
  const original = issue.radii['0'].witnesses;
  const observed = original?.on ?? original?.off;
  const alternative = issue.referenceAlert ? sample.witnesses?.off : sample.witnesses?.extra ?? sample.witnesses?.on;
  const example = alternative ?? sample.witnesses?.steepener ?? sample.witnesses?.on ?? sample.witnesses?.off;
  const labels = featureMonths(issue.featureDate);
  return <>
    <div className="js-case-summary"><p>{issueDate === may ?
      'The next recession began in April 2001. This issue could extend the lead from ten to eleven months.' :
      'No recession began within this issue’s next twelve months. An alert here counts as a false alarm.'}</p>
      <div><span>Warning under {radiusName(radius).toLowerCase()} yields</span><strong>{warning(sample.alert,sample.certified)}</strong></div></div>
    {observed && example && <>
      <div className="js-case-grid">
        <RiskPath observed={observed} scenario={example} labels={labels} range={sample.probability}/>
        <table className="js-case-table">
          <caption>{alternative && radius !== '0' ? 'One path that flips the warning' : 'One admissible yield path'}</caption>
          <thead><tr><th scope="col">Reading</th><th scope="col">Observed</th><th scope="col">Example</th></tr></thead>
          <tbody>{[
            ['Next-year risk', percent(observed.probability), percent(example.probability)],
            ['One-month rise', pp(observed.change1m), pp(example.change1m)],
            ['Three-month rise', pp(observed.change3m), pp(example.change3m)],
            ['Bill move, 3m', bp(observed.shortChangeBp), bp(example.shortChangeBp)],
            ['Ten-year move, 3m', bp(observed.longChangeBp), bp(example.longChangeBp)],
            ['30% alarm', flag(observed.levelAlert), flag(example.levelAlert)],
            ['Pace alarm', flag(observed.quarterAlert), flag(example.quarterAlert)],
            ['Curve-confirmed alarm', flag(observed.referenceAlert), flag(example.referenceAlert)],
          ].map(([label,a,b])=><tr key={label}><th scope="row">{label}</th><td>{a}</td><td>{b}</td></tr>)}</tbody>
        </table>
      </div>
      <details className="js-details"><summary>Yield adjustments behind this example</summary>
        <div className="li-scroll"><table><thead><tr><th scope="col">Source series</th>{labels.map(m=><th scope="col" key={m}>{m}</th>)}</tr></thead>
          <tbody>{['3-month bill','10-year Treasury'].map((label,leg)=><tr key={label}><th scope="row">{label}</th>{example.shocksBp.map((v,i)=><td key={i}>{bp(v[leg])}</td>)}</tr>)}</tbody></table></div>
        <p className="li-note">The same four pairs of rate changes produce every example reading above. One basis point (bp) equals 0.01 percentage point (pp).</p>
      </details>
    </>}
    <p className="li-note">Next-year risk across allowed paths · {bounds(sample.probability,percent)}. Three-month risk change · {bounds(sample.change3m,pp)}.</p>
  </>;
}

function Accuracy({trial,radius}: {trial: JointStressTrial; radius: JointRadius}) {
  const flatterWorsensBoth = periods.every(period=>{
    const w=trial.windows[period], s=w.radii[radius], brier=s.coherentBrier[0], logLoss=s.coherentLogLoss[0];
    return finite(brier) && finite(logLoss) && finite(w.originalBrier) && finite(w.originalLogLoss) &&
      brier>w.originalBrier+1e-10 && logLoss>w.originalLogLoss+1e-10;
  });
  return <section className="li-section"><h2>Probability accuracy</h2>
    <p>{flatterWorsensBoth && <><strong>A persistently flatter spread increases both errors in both samples.</strong> </>}Lower scores mean more accurate forecasts. The last column allows each issue to take its own most favorable or least favorable spread.</p>
    <div className="li-scroll js-table" role="region" aria-label="Repriced probability scores" tabIndex={0}>
      <table><thead><tr>{['Sample','Measure','Observed','Flatter spread','Steeper spread','Full range'].map(h=><th scope="col" key={h}>{h}</th>)}</tr></thead>
        <tbody>{periods.flatMap(period=>{
          const w=trial.windows[period], s=w.radii[radius];
          return (['brier','logLoss'] as const).map(metric=>{
            const isBrier=metric === 'brier',scenarios=isBrier ? s.coherentBrier : s.coherentLogLoss;
            return <tr key={period+metric}><th scope="row">{windowNames[period]}{isBrier && <small>{w.n} issues</small>}</th>
              <td>{isBrier ? 'Brier' : 'Log loss'}</td><td>{digits(isBrier ? w.originalBrier : w.originalLogLoss)}</td>
              <td>{digits(scenarios[0])}</td><td>{digits(scenarios[1])}</td><td>{bounds(s[metric],n=>digits(n))}</td></tr>;
          });
        })}</tbody>
      </table></div>
    <p className="li-note">The flatter path raises every bill reading by {radius} bp and lowers every ten-year reading by {radius} bp. The steeper path reverses both shifts. Each of these two experiments uses one consistent yield history.</p>
  </section>;
}

function ConsistentPaths({trial,period,radius}: {trial: JointStressTrial; period: JointPeriod; radius: JointRadius}) {
  if (!trial.calendarPaths || radius==='0') return null;
  const rows = Object.values(trial.calendarPaths).filter((path): path is JointCalendarPath=>!!path && path.radiusBp<=Number(radius));
  if (!rows.length) return null;
  const changeList = (path: JointCalendarPath) => path.shocks.map(s=>month(s.date)+' ('+bp(s.shortBp)+' bill, '+bp(s.longBp)+' ten-year)').join(' and ');
  return <div className="js-coherent"><h3>One yield history across every issue</h3>
    <p>Each example changes only the observations listed below. Overlapping forecasts share those readings. False-alert counts and accuracy use the selected sample. The 2001 lead uses its full pre-recession year.</p>
    <div className="li-scroll js-table" role="region" aria-label="Consistent yield histories" tabIndex={0}>
      <table><thead><tr>{['Changed history','30% false alarms','Curve-rule false alarms','2001 lead','Brier','Log loss'].map(s=><th key={s} scope="col">{s}</th>)}</tr></thead>
        <tbody>{rows.map(path=>{const w=path.windows[period];return <tr key={path.id}><th scope="row">{month(path.date)} example</th>
          <td>{w.levelQuiet}</td><td>{w.alertQuiet}</td><td>{count(path.lead2001)} mo</td><td>{digits(w.brier)}</td><td>{digits(w.logLoss)}</td></tr>;})}</tbody>
      </table></div>
    {rows.map(path=><p className="li-note" key={path.id}><strong>{month(path.date)}.</strong> {changeList(path)}. Issue risk {percent(path.caseRisk)} · 30% alarm {flag(path.caseLevelAlert).toLowerCase()} · Curve-rule alarm {flag(path.caseAlert).toLowerCase()}.</p>)}
  </div>;
}

function Warnings({window,radius}: {window: JointWindow; radius: JointRadius}) {
  const s = window.radii[radius];
  return <>
    <p>{month(window.windowStart)} – {month(window.windowEnd)} · {window.n} scored expansion issues · {window.quietExpansionN} with no onset in the following year.</p>
    <div className="js-counts">
      <div><span>Observed 30% alarm</span><strong>{window.originalQuiet}</strong><small>False-alert months</small></div>
      <div><span>Repriced 30% alarm</span><strong>{bounds(s.levelQuiet,count)}</strong><small>False-alert months</small></div>
      <div><span>Repriced curve rule</span><strong>{bounds(s.alertQuiet,count)}</strong><small>False-alert months</small></div>
    </div>
    <p><strong>{bounds(s.extraQuiet,count)} additional quiet {s.extraQuiet[1]===1 ? 'month' : 'months'} below 30%.</strong> This comparison applies both rules to the same repriced readings in each issue.</p>
    {s.extraQuietDates.length > 0 && <p className="li-note">Quiet issues where an extra alert can occur{!s.unresolvedN ? '' : ' or cannot be ruled out'} · {s.extraQuietDates.map(month).join(' · ')}.</p>}
    <div className="li-scroll js-table" role="region" aria-label="Lead before each recession" tabIndex={0}>
      <table><caption>Months from first warning to recession onset</caption><thead><tr>
        {['Recession onset','Observed 30%','Repriced 30%','Repriced curve rule'].map(h=><th scope="col" key={h}>{h}</th>)}</tr></thead>
        <tbody>{s.episodes.map(e=><tr key={e.onsetDate}><th scope="row">{month(e.onsetDate)}{e.coverage!=='full' && <small>{e.coverage} coverage</small>}</th>
          <td>{count(e.originalLevelLead)}</td><td>{bounds(e.levelLead,count)}</td><td>{bounds(e.alertLead,count)}</td></tr>)}</tbody>
      </table></div>
    <p className="li-note">The lower bound counts warnings that survive every permitted reading. The upper bound allows a different path in each issue. These overlapping four-month paths can assign different changes to a shared observation.{s.unresolvedN > 0 && <> For {s.unresolvedN} issues the bounds leave some decisions unresolved.</>}</p>
  </>;
}

export default function JointStress({trial}:{trial?:JointStressTrial}) {
  const [radius,setRadius] = useState<JointRadius>('3');
  const [issueDate,setIssueDate] = useState(may);
  const [period,setPeriod] = useState<JointPeriod>('all');
  if (!trial) return <article className="li-research js-view"><h1>Joint yield stress test</h1><p>The repriced research replay is awaiting its first update.</p></article>;
  const w = trial.windows.all, selected = w.radii[radius];
  const lead = selected.episodes.find(e=>e.onsetDate===onset2001);
  const latest = trial.latest, current = latest.radii[radius];
  const mayCase=trial.cases[may], febCase=trial.cases[feb];
  const hasCaseEvidence=mayCase?.radii['3'].alert[0] && mayCase.radii['5'].witnesses?.off && febCase?.radii['3'].witnesses?.extra;
  return <article className="li-research js-view">
    <header className="li-title"><div><h1>Joint yield stress test</h1>
      <p>{hasCaseEvidence ? <>The extra month of warning before the 2001 recession survives ±3 bp in both rates but can disappear at ±5 bp. At ±3 bp, February 2019 can already trigger a false alarm.</> : <>Reprice the chance of a recession starting in the next year and its rate of change as both Treasury yields move.</>}</p></div>
      <a className="li-download" href="/api/download?file=jointstress"><Download size={16} aria-hidden/>Monthly stress CSV</a></header>
    <section className="js-settings"><div><span>Maximum shift per rate, per month</span>
      <div className="li-controls" role="group" aria-label="Maximum change per yield observation">
        {(['0','3','5'] as const).map(r=><button type="button" key={r} aria-pressed={radius===r} onClick={()=>setRadius(r)}>{radiusName(r)}</button>)}
      </div></div>
      <p aria-live="polite">{lead && <>2001 warning lead <strong>{bounds(lead.alertLead,count)} months</strong> · </>}
        Extra quiet-month alerts <strong>{bounds(selected.extraQuiet,count)}</strong> in the full sample.</p>
    </section>
    <section className="li-section js-replay"><div className="li-section-head"><h2>Replay a warning</h2>
      <div className="li-controls" role="group" aria-label="Historical issue">
        {[may,feb].map(date=><button type="button" key={date} aria-pressed={issueDate===date} onClick={()=>setIssueDate(date)}>{month(date)}</button>)}
      </div></div><CaseReplay issue={trial.cases[issueDate]} radius={radius} issueDate={issueDate}/></section>
    <Accuracy trial={trial} radius={radius}/>
    <section className="li-section"><div className="li-section-head"><h2>False alarms and warning lead</h2>
      <div className="li-controls" role="group" aria-label="Warning evaluation sample">{periods.map(p=><button type="button" key={p} aria-pressed={period===p} onClick={()=>setPeriod(p)}>{windowNames[p]}</button>)}</div>
    </div><Warnings window={trial.windows[period]} radius={radius}/><ConsistentPaths trial={trial} period={period} radius={radius}/></section>
    <section className="li-section"><h2>Current issue · {month(latest.issueDate)}</h2>
      {latest.available ? <><p>Conditional on the economy being in expansion, estimated onset risk for {month(latest.forecastStart)} – {month(latest.forecastEnd)} is <strong>{percent(latest.probability)}</strong>. With {radiusName(radius).toLowerCase()} yields the range is <strong>{bounds(current.probability,percent)}</strong>.</p>
        <p className="li-note">Three-month risk change {bounds(current.change3m,pp)} · Curve-confirmed warning {warning(current.alert,current.certified).toLowerCase()}.</p></> : <p>{latest.reason ?? 'The current issue is missing a required risk input.'}</p>}
    </section>
    <section className="li-section"><h2>How the replay works</h2>
      <p>At each issue, the ten-year Treasury and three-month bill can move independently at each of four consecutive signal dates. The spread changes the fitted expansion model’s log odds. Repricing all four probabilities with the issue’s own coefficients and base rate gives new one- and three-month changes.</p>
      <p>At or above 30%, the alarm turns on. Below 30%, risk must reach 20%, rise over one and three months, and reach 30% if the three-month rise repeats. The bill must also rise and the spread narrow. A ten-year move within ±5 bp qualifies as flat. For a larger decline, the bill must rise by at least twice the decline.</p>
      <p className="li-note">The 2:1 rule was selected after inspecting these historical cases. The replay uses revised inputs and retrospective recession dates. The recent decade overlaps the full sample, and several forecast months can refer to one recession. The stress paths are hypothetical.</p>
      <div className="js-links"><a href="#stability">Compare the earlier long-end test</a><a href="/api/download?file=stabilityreceipts">Download frozen issued warnings</a></div>
    </section>
  </article>;
}
