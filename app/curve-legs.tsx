'use client';

import {useState} from 'react';
import {Download} from 'lucide-react';
import type {CurveLegsTrial, CurveReading, CurveRow, CurveRule, CurveWindow} from '../lib/curve-legs-types';
import './leading-indicators.css';
import './curve-legs.css';

const rules: CurveRule[] = ['shortLead', 'bear', 'sustained', 'mixedTwoToOne'];
const periods: CurveWindow[] = ['all', 'rolling120'];
const periodName = {all: 'Full history', rolling120: 'Latest 10 years'};
const ruleName = {shortLead: 'Short end leads', bear: 'Long yield holds or rises', sustained: 'Three consecutive bill increases', mixedTwoToOne: '2:1 split · exploratory'};
const alertField = {shortLead:'shortLeadAlert', bear:'bearAlert', sustained:'sustainedAlert', mixedTwoToOne:'mixedTwoToOneAlert'} as const;
const conditions = {
  shortLead: 'The curve flattens and the rising bill yield contributes more than the long end. An equal split gives no extra alert.',
  bear: 'The short end leads the flattening and the ten-year yield finishes level or higher.',
  sustained: 'The short end leads the flattening and the bill yield rises in each of the three monthly steps.',
  mixedTwoToOne: 'The bill rises, the ten-year yield is flat or falling, and the bill rise is at least twice the size of the long-yield fall. This threshold and sign test were chosen after inspecting both historical windows.',
};
const drivers: Record<CurveReading['driver'],string> = {
  'short-led':'Short end led', 'long-led':'Long end led', equal:'Equal contributions',
  'no-flattening':'No flattening', unavailable:'Inputs incomplete',
};
const patterns: Record<CurveReading['pattern'],string> = {
  'both-flatten':'Both ends contributed.', 'short-only':'The long yield held steady.',
  'long-only':'The bill yield held steady.', 'long-rise-offset':'A rise in the long yield offset part of the bill move.',
  'short-fall-offset':'A fall in the bill yield offset part of the long-end move.',
  'no-flattening':'The spread held steady or widened.', unavailable:'At least one endpoint yield is missing.',
};
const dateFormat = new Intl.DateTimeFormat('en-US',{month:'short',year:'numeric',timeZone:'UTC'});
const month = (value: string|null) => value ? dateFormat.format(new Date(value.slice(0,7)+'-01T12:00:00Z')) : '—';
const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
const numeric = (n: number|null, places = 2) => finite(n) ? n.toFixed(places) : '—';
const yieldPct = (x: number|null) => finite(x) ? numeric(x) + '%' : '—';
const risk = (x: number|null) => finite(x) ? yieldPct(100*x) : '—';
function bp(x: number|null) {
  if (!finite(x)) return '—';
  const n = Math.round(x*10000)/100;
  return (n>0 ? '+' : n<0 ? '−' : '') + Math.abs(n).toLocaleString('en-US',{maximumFractionDigits:2}) + ' bp';
}
const negative = (x: number|null) => finite(x) ? -x : null;
const on = (x: boolean|null) => x === null ? 'Unavailable' : x ? 'On' : 'Off';
const outcome = (r: CurveRow) => !r.commonMature ? 'Unscored' : r.target === 1 ? 'Pre-onset' : 'Quiet';

function Leg({label, from, to, effect, bound, tenor}: {label:string; from:number|null; to:number|null; effect:number|null; bound:number; tenor:'short'|'long'}) {
  const width = finite(effect) ? 50*Math.abs(effect)/bound : 0;
  return <div className="cl-leg">
    <div className="cl-leg-label"><span>{label}</span><span>{yieldPct(from)} <span aria-label="to">→</span> {yieldPct(to)}</span></div>
    <div className="cl-leg-reading"><span className="cl-track" aria-hidden="true"><i className={'cl-fill cl-'+tenor}
      style={{left:(finite(effect) && effect<0 ? 50-width : 50)+'%', width:width+'%'}}/></span>
      <strong>{bp(effect)}</strong></div>
  </div>;
}

function Cases({trial, rule}: {trial:CurveLegsTrial;rule:CurveRule}) {
  const cases = ['2000-05-01','2019-02-01'].map(d=>trial.history.find(r=>r.date===d));
  const bound = Math.max(.01,...cases.flatMap(r=>r ? [r.shortChange,r.longChange].filter(finite).map(Math.abs) : []));
  const may=cases[0];
  const excluded=trial.history.filter(r=>['2006-02-01','2022-09-01'].includes(r.date) && r.commonMature && r.target===0 && !r.levelAlert && r.shortLeadAlert && !r.mixedTwoToOneAlert && finite(r.longChange) && r.longChange>0);
  return <section className="li-section cl-compare">
    <div className="li-section-head"><h2>Two flattenings, three months each</h2></div>
    <p>Each bar shows one yield’s contribution to narrowing the ten-year minus three-month spread. Right of zero narrows the spread. Left of zero offsets the narrowing. Both cases use the same scale.</p>
    <div className="cl-pair">{cases.map((r,i) => r ? <figure className="cl-case" key={r.date}>
      <figcaption><h3>{month(r.date)} issue</h3><span>{month(r.lagFeatureDate)} – {month(r.featureDate)} observations</span></figcaption>
      <div className="cl-net"><strong>{bp(r.flattening)}</strong><span>net flattening</span></div>
      <Leg label="3-month bill" from={r.shortStart} to={r.shortEnd} effect={r.shortChange} bound={bound} tenor="short"/>
      <Leg label="10-year Treasury" from={r.longStart} to={r.longEnd} effect={negative(r.longChange)} bound={bound} tenor="long"/>
      <p className="cl-explain"><strong>{drivers[r.driver]}.</strong> {patterns[r.pattern]}</p>
      <dl className="cl-kv"><div><dt>12-month onset risk</dt><dd>{risk(r.probability)}</dd></div>
        <div><dt>Selected curve alert</dt><dd>{on(r[alertField[rule]])}</dd></div>
        <div><dt>Outcome in 12 months</dt><dd>{!r.commonMature?'Unscored':r.target===1?'Onset · '+month(r.onsetDate):'No onset'}</dd></div></dl>
    </figure> : <p key={i}>This issue is outside the available replay.</p>)}</div>
    {rule==='mixedTwoToOne' && <div className="cl-shadow-note">
      {excluded.length>0 && <p>Other short-led false alerts also had rising ten-year yields. {excluded.map(r=>month(r.date)+' ('+bp(r.longChange)+')').join(' and ')} fell outside the exploratory rule.</p>}
      {may?.mixedTwoToOneAlert && finite(may.longChange) && Math.round(100*may.longChange)===-2 &&
        <p>The May result is sensitive to the long-yield cutoff. A ten-year ending yield 3 bp higher would turn a 2 bp fall into a 1 bp rise and switch this filter off. This check holds the existing pace alert fixed.</p>}
    </div>}
    <details className="li-details"><summary>How much did each end contribute to model risk?</summary>
      <div className="li-scroll cl-table" role="region" aria-label="Yield-curve contribution to the fitted risk change" tabIndex={0}><table>
        <thead><tr><th scope="col">Contribution to risk</th>{cases.map((r,i)=><th scope="col" key={i}>{r?month(r.date):'Unavailable'}</th>)}</tr></thead>
        <tbody>{([['shortEffect','3-month bill'],['longEffect','10-year Treasury'],['curveEffect','Total yield curve']] as const).map(([key,label])=><tr key={key}><th scope="row">{label}</th>
          {cases.map((r,i)=>{const part=r?trial.caseEffects[r.date]:null;const v=part?.[key];return <td key={i}>{finite(v)?(v>0?'+':'')+(100*v).toFixed(2)+' pp':'—'}</td>;})}</tr>)}</tbody></table></div>
      <p className="li-note">These figures are percentage points of conditional recession risk. The model uses the yield spread. Its fitted curve contribution is split in proportion to each end’s signed contribution to the spread change.</p>
    </details>
    <p className="li-note">Net flattening in basis points equals the bill yield change minus the ten-year yield change. A falling ten-year yield therefore has a positive bar. One basis point is 0.01 percentage point of yield. The observation window ends two months before the issue.</p>
  </section>;
}

function Replay({trial,rule,period,setPeriod}: {trial:CurveLegsTrial;rule:CurveRule;period:CurveWindow;setPeriod:(k:CurveWindow)=>void}) {
  const w = trial.windows[period], g = trial.gate[rule];
  const policies = ['level','quarter',rule] as const, names = ['30% baseline','Pace alone','With curve rule'];
  const added = w.changes[rule].quietDates.length;
  return <section className="li-section"><div className="li-section-head"><h2>Early warning versus false alerts</h2>
    <div className="li-controls" role="group" aria-label="Historical window">{periods.map(k=><button type="button" key={k} aria-pressed={k===period}
      onClick={()=>setPeriod(k)}>{periodName[k]}</button>)}</div></div>
    <p>{month(w.windowStart)} – {month(w.windowEnd)} · {w.n} scored expansion issues. <strong>{added} additional false-alert {added===1?'month':'months'}</strong> with the selected rule.</p>
    <div className="li-scroll cl-table" role="region" tabIndex={0} aria-label="Warning performance by policy"><table><thead><tr><th scope="col">Measure</th>{names.map(name=><th scope="col" key={name}>{name}</th>)}</tr></thead>
      <tbody><tr><th scope="row">Quiet months alerted</th>{policies.map(k=><td key={k}>{w.summary[k].quietAlerts} / {w.quietExpansionN}</td>)}</tr>
        <tr><th scope="row">Pre-onset months alerted</th>{policies.map(k=><td key={k}>{w.summary[k].preOnsetAlerts} / {w.preOnsetN}</td>)}</tr>
        <tr><th scope="row">Complete episodes detected</th>{policies.map(k=><td key={k}>{w.summary[k].completeHits} / {w.completeEpisodes}</td>)}</tr>
        <tr><th scope="row">Mean lead, months</th>{policies.map(k=><td key={k}>{numeric(w.summary[k].meanLeadMonths)}</td>)}</tr></tbody></table></div>
    <p className="cl-verdict" aria-live="polite"><strong>{rule==='mixedTwoToOne' ? (g.passed?'Matched both criteria in the design sample.':'Missed the criteria in the design sample.') : g.passed?'Met the joint test.':'Fell short of the joint test.'}</strong>{' '}
      {g.mayRetained?'Retained the May 2000 warning.':'Did not retain the May 2000 advance.'} The selected rule added {trial.windows.all.changes[rule].quietDates.length} quiet months in full history and {trial.windows.rolling120.changes[rule].quietDates.length} in the latest decade.{rule==='mixedTwoToOne' && ' These observations informed the rule and cannot independently validate it.'}</p>
    <h3>First alert before each recession</h3>
    <div className="li-scroll cl-table" role="region" tabIndex={0} aria-label="First recession warnings"><table><thead><tr><th scope="col">Onset</th>{names.map(name=><th key={name} scope="col">{name}</th>)}</tr></thead>
      <tbody>{w.episodes.map(e=><tr key={e.onsetDate}><th scope="row">{month(e.onsetDate)}{e.coverage!=='full'&&<small>{e.availableMonths} of 12 months observed</small>}</th>
        {policies.map(k=>{const alert=e.methods[k];return <td key={k}>{alert.firstAlertDate?<>{month(alert.firstAlertDate)}<small>{alert.leadMonths} months early{alert.firstAlertKind==='already-high'?' · already on':''}</small></>:'No observed warning'}</td>;})}</tr>)}</tbody></table></div>
    <p className="li-note">Each quiet month is an expansion issue followed by a full year without recession onset. Lead averages cover complete episodes, counting zero for a miss. An alert can already be active at the start of the twelve-month window.</p>
  </section>;
}

function Audit({trial,rule,period}: {trial:CurveLegsTrial;rule:CurveRule;period:CurveWindow}) {
  const w=trial.windows[period], [issue,setIssue]=useState('2000-05-01');
  const rows=trial.history.filter(r=>r.quarterAlert&&!r.levelAlert&&r.commonMature&&w.windowStart&&r.date>=w.windowStart&&w.windowEnd&&r.date<=w.windowEnd);
  const selected=rows.find(r=>r.date===issue)??rows[0];
  return <section className="li-section"><div className="li-section-head"><h2>Inspect the extra pace alerts</h2>
    {selected&&<label className="li-select">Forecast issue<select value={selected.date} onChange={e=>setIssue(e.target.value)}>{rows.map(r=><option value={r.date} key={r.date}>{month(r.date)} · {outcome(r)}</option>)}</select></label>}</div>
    {selected ? <><p>For {month(selected.date)}, the bill yield moved <strong>{bp(selected.shortChange)}</strong> and the ten-year yield moved <strong>{bp(selected.longChange)}</strong>. The short rate rose in {selected.shortRiseCount??'—'} of three monthly steps.
      The selected rule {selected[alertField[rule]]?'kept':'withheld'} the extra alert.</p>
      <details className="li-details"><summary>All {rows.length} sub-30% pace alerts in this window</summary>
        <div className="li-scroll cl-audit" role="region" tabIndex={0} aria-label="All extra pace alerts and their curve drivers"><table><thead><tr>
          {['Issue','Bill change','10-year change','Flattening','Driver','Curve alert','Outcome'].map(name=><th scope="col" key={name}>{name}</th>)}</tr></thead>
          <tbody>{rows.map(r=><tr key={r.date}><th scope="row">{month(r.date)}</th><td>{bp(r.shortChange)}</td><td>{bp(r.longChange)}</td><td>{bp(r.flattening)}</td>
            <td>{drivers[r.driver]}</td><td>{on(r[alertField[rule]])}</td><td>{outcome(r)}</td></tr>)}</tbody></table></div></details></> : <p>No scored extra pace alert in this period.</p>}
  </section>;
}

function Current({trial,rule}: {trial:CurveLegsTrial;rule:CurveRule}) {
  const c=trial.latest;
  return <section className="li-section"><div className="cl-current"><div><h2>Current issue</h2>
    <strong className="cl-risk">{risk(c.probability)}</strong>
    <p>Estimated chance of entering recession from {month(c.forecastStart)} through {month(c.forecastEnd)}, conditional on expansion in {month(c.issueDate)}.</p>
    {!c.available&&<p className="li-note">{c.reason??'The probability inputs are incomplete.'}</p>}</div>
    <div><dl className="cl-kv">
      <div><dt>Bill yield change</dt><dd>{bp(c.shortChange)}</dd></div><div><dt>Ten-year yield change</dt><dd>{bp(c.longChange)}</dd></div>
      <div><dt>Net flattening</dt><dd>{bp(c.flattening)}</dd></div><div><dt>Curve driver</dt><dd>{drivers[c.driver]}</dd></div>
    </dl><p className="li-note">30% baseline <b>{on(c.levelAlert)}</b> · Pace <b>{on(c.quarterAlert)}</b> · Selected rule <b>{on(c[alertField[rule]])}</b></p></div></div>
    <details className="li-details"><summary>Monthly yields behind this issue</summary>
      <div className="li-scroll cl-table" role="region" tabIndex={0} aria-label="Current issue Treasury observations"><table><thead><tr><th scope="col">Month</th><th scope="col">3-month bill</th><th scope="col">10-year Treasury</th></tr></thead>
        <tbody>{c.yieldPath.map(p=><tr key={p.date}><th scope="row">{month(p.date)}</th><td>{yieldPct(p.shortYield)}</td><td>{yieldPct(p.longYield)}</td></tr>)}</tbody></table></div></details>
  </section>;
}

function Accuracy({trial}: {trial:CurveLegsTrial}) {
  return <section className="li-section"><h2>Probability accuracy</h2><p>Every policy issues the same expansion-model probability on the same dates. Changing the alarm decision leaves these probability scores identical across policies.</p>
    <div className="li-scroll cl-table" role="region" tabIndex={0} aria-label="Probability scores for both windows"><table><thead><tr>
      {['Expansion issues','Brier error','Log loss','AUC'].map(k=><th key={k} scope="col">{k}</th>)}</tr></thead>
      <tbody>{periods.map(k=>{const w=trial.windows[k],p=w.probabilityScores;return <tr key={k}><th scope="row">{periodName[k]} · {w.n}</th>
        <td>{numeric(p.brier,5)}</td><td>{numeric(p.logLoss,5)}</td><td>{numeric(p.auc,3)}</td></tr>;})}</tbody></table></div>
    <p className="li-note">Monthly outcomes overlap. The latest decade is part of the full replay and contains {trial.windows.rolling120.completeEpisodes} complete recession {trial.windows.rolling120.completeEpisodes===1?'episode':'episodes'}.</p>
  </section>;
}

export default function CurveLegs({trial}: {trial?:CurveLegsTrial}) {
  const [rule,setRule]=useState<CurveRule>('shortLead');
  const [period,setPeriod]=useState<CurveWindow>('all');
  if (!trial) return <article className="li-research cl-view"><h1>Which end flattened the yield curve?</h1><p>The curve replay is awaiting a research update.</p></article>;
  const base=trial.gate.shortLead, candidate=trial.gate.mixedTwoToOne, f=trial.prospective;
  const measured=trial.windows.all.completeEpisodes>0&&trial.windows.rolling120.completeEpisodes>0;
  return <article className="li-research cl-view">
    <header className="li-title"><div><h1>Which end flattened the yield curve?</h1>
      <p>{measured ? <>The short-end rule {base.mayRetained?'kept':'missed'} May 2000’s early signal and added {trial.windows.all.changes.shortLead.quietDates.length} false-alert months in full history.
        {' '}{candidate.passed?'An exploratory 2:1 rule kept the early signal and matched the baseline false-alert count in both windows. It was designed after reviewing those months.':'The exploratory 2:1 rule was designed after reviewing both historical windows.'}</>
        : 'Trace each change in recession risk back to the three-month bill and ten-year Treasury yields.'}</p></div>
      <a className="li-download" href="/api/download?file=curvelegs"><Download size={16} aria-hidden="true"/>Monthly replay CSV</a></header>
    <div className="cl-toolbar"><label className="li-select">Curve confirmation rule<select value={rule} onChange={e=>setRule(e.target.value as CurveRule)}>
      {rules.map(k=><option value={k} key={k}>{ruleName[k]}</option>)}</select></label>
      <p aria-live="polite">{conditions[rule]} All rules retain the 30% alarm and screen only extra pace warnings.</p></div>
    <Cases trial={trial} rule={rule}/>
    <Replay trial={trial} rule={rule} period={period} setPeriod={setPeriod}/>
    <Audit trial={trial} rule={rule} period={period}/>
    <Current trial={trial} rule={rule}/>
    <Accuracy trial={trial}/>
    <section className="li-section li-method"><h2>Measurement and timing</h2>
      <p>Monthly FRED readings use the ten-year constant-maturity Treasury yield and the three-month Treasury bill secondary-market discount rate. The model uses the quoted spread without converting the bill to a bond-equivalent yield. Observed changes in these rates can reflect policy expectations, term premia and other influences.</p>
      <p>The pace alarm below 30% requires at least 20% risk, a one-month rise and a three-month rise large enough to reach 30% within another quarter at the same pace. The curve rules keep the probability and its two-month observation lag. Missing endpoints prevent an extra curve alert. The consecutive-increases rule also needs the two intermediate bill readings.</p>
      <p>The 2000 and 2019 cases were known at the start. Three tests were specified before the full replay. The fourth, the exploratory 2:1 split, was developed using the replay outcomes. Historical inputs include revisions and recession dates are assigned retrospectively.</p>
      <p className="li-note"><a href="#stability">Test nearby yield thresholds and a three-basis-point change</a> · <a href="#confirmation">Economic-signal comparison</a> · <a href="#momentum">Pace rule</a> · <a href="https://fred.stlouisfed.org/series/TB3MS">Three-month bill</a> · <a href="https://fred.stlouisfed.org/series/GS10">Ten-year Treasury</a> · <a href="https://fred.stlouisfed.org/series/USREC">Recession dates</a></p>
    </section>
    <section className="li-section"><div className="li-section-head"><h2>Decisions frozen at issue</h2>
      {!!f?.receiptCount&&<a className="li-download" href="/api/download?file=curvelegsreceipts"><Download size={16} aria-hidden="true"/>Forecast records</a>}</div>
      {f?.receiptCount?<p><strong>{f.receiptCount} recorded · {f.maturedCount} scored · {f.excludedCount} excluded · {f.pendingCount} pending.</strong>{f.latestReceipt&&<> Latest issue {month(f.latestReceipt.issueDate)}.</>}</p>:<p>The first eligible monthly issue is awaiting capture.</p>}
      <p className="li-note">The monthly record freezes the common probability, the two yield paths and the decisions before the forecast year starts. Only expansion issues with twelve subsequent outcome months enter the score.</p>
    </section>
  </article>;
}
