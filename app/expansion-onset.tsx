'use client';

import { useState } from 'react';
import { Download } from 'lucide-react';
import type { ExpansionEpisode, ExpansionMethod, ExpansionRow, ExpansionTrial, ExpansionWindow } from '../lib/expansion-types';
import type { WarningResult } from '../lib/weight-types';
import './leading-indicators.css';
import './expansion-onset.css';

const windows: ExpansionWindow[] = ['all', 'rolling120'];
const names = { all: 'Full history', rolling120: 'Latest 10 years' };
const methods: [ExpansionMethod, string][] = [
  ['benchmark', 'Published permits benchmark'],
  ['signalOnlyChange', 'Expansion signal + original base rate'],
  ['baseOnlyChange', 'Original signal + expansion base rate'],
  ['candidate', 'Expansion signal + expansion base rate'],
  ['expansionPrior', 'Expansion base rate alone'],
];
const monthFormat = new Intl.DateTimeFormat('en-US', {month:'short',year:'numeric',timeZone:'UTC'});
const month = (date: string | null) => date ? monthFormat.format(new Date(date.slice(0,7) + '-01T12:00:00Z')) : '—';
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const num = (v: number | null | undefined, digits: number) => finite(v) ? v.toFixed(digits) : '—';
const pct = (v: number | null | undefined, digits = 1) => finite(v) ? (100*v).toFixed(digits) + '%' : '—';
const fraction = (n: number, total: number) => total ? n + ' / ' + total : '—';
const count = (n: number, noun: string) => n + ' ' + noun + (n === 1 ? '' : 's');

function Current({trial}:{trial:ExpansionTrial}) {
  const l = trial.latest;
  return <section className="li-section on-current">
    <div>
      <h2>If the U.S. is currently in expansion</h2>
      <p>Estimated chance of entering recession during {month(l.forecastStart)} – {month(l.forecastEnd)}.</p>
      <p className="on-note">Issued {month(l.issueDate)} with inputs through {month(l.featureDate)}. The current business-cycle phase is an assumption. NBER dates turning points retrospectively.</p>
    </div>
    <div className="on-now"><span>Expansion-onset model</span><strong>{pct(l.probability,2)}</strong>
      <span>Published permits benchmark <b>{pct(l.benchmarkProbability,2)}</b></span>
      <small>The benchmark estimates the chance of at least one recession month in the next year.</small>
      {!l.available && <small>{l.reason || 'A dated model input is unavailable.'}</small>}
    </div>
  </section>;
}

function Accuracy({trial}:{trial:ExpansionTrial}) {
  const threshold = trial.warnings.threshold;
  const recent = trial.metrics.rolling120;
  const recentRows = trial.history.filter(r => r.commonMature && recent.windowStart && recent.windowEnd && recent.windowStart <= r.date && r.date <= recent.windowEnd);
  const priorAlerts = recentRows.filter(r => finite(r.expansionPriorProbability) && r.expansionPriorProbability >= threshold).length;
  const quieter = windows.every(k=>{
    const {summary,quietExpansionN} = trial.warnings.windows[k];
    return quietExpansionN>0 && summary.candidate.quietAlerts<summary.benchmark.quietAlerts;
  });
  return <section className="li-section on-performance">
    <h2>Forecasts issued during expansions</h2>
    <p>{trial.gate.passed && quieter && <><strong>Probability error and false alarms fell in both windows.</strong>{' '}</>}
      Both models are scored on the same months later identified as expansions. Each alert requires a probability of at least {pct(threshold,0)}.</p>
    <div className="on-pair">{windows.map(k => {
      const m = trial.metrics[k], w = trial.warnings.windows[k], b = w.summary.benchmark, c = w.summary.candidate;
      return <div className="on-period" key={k}><h3>{names[k]}</h3>
        <p className="on-dateline">{month(m.windowStart)} – {month(m.windowEnd)} · {m.n} expansion months</p>
        <table aria-label={names[k] + ' model comparison'}><thead><tr><th scope="col">Measure</th><th scope="col">Permits 50/50</th><th scope="col">Onset model</th></tr></thead>
          <tbody>
            <tr><th scope="row">Brier error</th><td>{num(m.models.benchmark.brier,5)}</td><td>{num(m.models.candidate.brier,5)}</td></tr>
            <tr><th scope="row">Quiet months alerted</th><td>{fraction(b.quietAlerts,w.quietExpansionN)}</td><td>{fraction(c.quietAlerts,w.quietExpansionN)}</td></tr>
            <tr><th scope="row">Mean lead, months</th><td>{num(b.meanLeadMonths,1)}</td><td>{num(c.meanLeadMonths,1)}</td></tr>
            <tr><th scope="row">Recessions flagged</th><td>{fraction(b.completeHits,w.completeEpisodes)}</td><td>{fraction(c.completeHits,w.completeEpisodes)}</td></tr>
          </tbody>
        </table>
      </div>;
    })}</div>
    <p><strong>{trial.warnings.jointGate.passed ? 'The onset model met all three objectives in both windows.' : 'The onset model fell short of the joint test across both windows.'}</strong>{' '}
      The test requires lower probability error, fewer false alarms and a longer mean lead with at least as many recessions detected in each window.</p>
    {finite(recent.models.baseOnlyChange.brier) && <p>In the latest decade, changing only the benchmark’s base rate gave a Brier error of <strong>{num(recent.models.baseOnlyChange.brier,5)}</strong>.
      Refitting the signal as well gave <strong>{num(recent.models.candidate.brier,5)}</strong>. The expansion base rate alone scored <strong>{num(recent.models.expansionPrior.brier,5)}</strong> and raised {count(priorAlerts,'alert')} in {recent.n} expansion months.</p>}
    <p className="on-note">Lower Brier error indicates better probability estimates. Quiet expansions are followed by twelve months with no recession onset. The mean lead uses complete episodes and assigns a missed recession zero months.</p>
  </section>;
}

type EpisodeMonth = { lead: number; row?: ExpansionRow };
function EpisodePlot({data, threshold}:{data:EpisodeMonth[];threshold:number}) {
  const [focus,setFocus] = useState(() => Math.max(0,data.findIndex(p=>p.row)));
  const item = data[focus];
  const bounds = Math.max(threshold,...data.flatMap(p=>[p.row?.probability,p.row?.benchmarkProbability].filter(finite)));
  const maxY = Math.min(1, Math.max(.5, Math.ceil((bounds+.015)*10)/10));
  const x = (i:number) => i/11*100;
  const y = (v:number) => 100*(1-v/maxY);
  function trace(field:'probability'|'benchmarkProbability') {
    let connected=false;
    return data.map((point,i)=>{
      const value=point.row?.[field];
      if(!finite(value)){connected=false;return '';}
      const command=connected?'L':'M'; connected=true;
      return command+x(i).toFixed(2)+','+y(value).toFixed(2);
    }).join(' ');
  }
  return <figure className="on-figure"><figcaption>
    <span><i className="on-swatch on-signal"/>Onset model</span>
    <span><i className="on-swatch on-benchmark"/>Permits 50/50</span>
    <span><i className="on-swatch on-threshold"/>{pct(threshold,0)} alert threshold</span>
  </figcaption>
    <div className="on-chart">
      <div className="on-axis"><span>{pct(maxY,0)}</span><span>0%</span></div>
      <div className="on-lines" onPointerMove={e=>{
        const rect=e.currentTarget.getBoundingClientRect();
        if(rect.width>0)setFocus(Math.min(11,Math.max(0,Math.round((e.clientX-rect.left)/rect.width*11))));
      }}>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Forecast probabilities in the twelve expansion months before the selected recession. Inspect individual months with the slider.">
          <path d={'M0,'+y(threshold)+' H100'} className="on-reference"/>
          <path d={trace('benchmarkProbability')} className="on-bench-path"/>
          <path d={trace('probability')} className="on-model-path"/>
        </svg>
        <span className="on-cursor" style={{left:x(focus)+'%'}}/>
        {(['probability','benchmarkProbability'] as const).map(field=>{
          const v=item.row?.[field];
          return finite(v) && <span key={field} className={'on-dot '+(field==='probability'?'model':'bench')} style={{left:x(focus)+'%',top:y(v)+'%'}}/>;
        })}
      </div>
    </div>
    <div className="on-axis-x"><span>12 months before</span><span>1 month before</span></div>
    <div className="on-inspector"><label>Months before onset
      <input type="range" min="0" max="11" value={focus} aria-label="Inspect months before onset" aria-valuetext={count(item.lead,'month')+' before onset'} onChange={e=>setFocus(Number(e.target.value))}/>
      <strong>{item.lead}</strong></label>
      <div aria-live="polite">{item.row ? <><strong>{month(item.row.date)}</strong> · Permits {pct(item.row.benchmarkProbability,2)} · Onset model {pct(item.row.probability,2)}</> : <>No paired expansion issue at this lead in the selected window.</>}</div>
    </div>
  </figure>;
}

function EpisodeView({episode,trial,period}:{episode:ExpansionEpisode;trial:ExpansionTrial;period:ExpansionWindow}) {
  const metric=trial.metrics[period], threshold=trial.warnings.threshold;
  const byLead = new Map<number,ExpansionRow>();
  for(const row of trial.history) {
    if(row.commonMature && row.onsetDate===episode.onsetDate && row.monthsToOnset!=null &&
       metric.windowStart && metric.windowEnd && metric.windowStart<=row.date && row.date<=metric.windowEnd)
      byLead.set(row.monthsToOnset,row);
  }
  const data=Array.from({length:12},(_,i)=>({lead:12-i,row:byLead.get(12-i)}));
  function first(m:WarningResult) {
    if (!m.firstAlertDate) return 'No observed alert';
    const note=m.firstAlertKind==='new-crossing'?'new crossing':m.firstAlertKind==='already-high'?'already active':'prior month unknown';
    return month(m.firstAlertDate)+' · '+count(m.leadMonths!,'month')+' · '+note;
  }
  function crossing(m:WarningResult) {
    const note=m.firstCrossUncertain?' (earlier crossing uncertain)':'';
    return (m.firstCrossDate?month(m.firstCrossDate)+' · '+count(m.crossLeadMonths!,'month'):'None observed')+note;
  }
  return <>
    <p className="on-dateline">{count(episode.availableMonths,'paired expansion month')} in the twelve months before {month(episode.onsetDate)}.{episode.coverage!=='full' && ' This incomplete episode is excluded from the mean lead.'}</p>
    <EpisodePlot key={episode.onsetDate+period} data={data} threshold={threshold}/>
    <div className="on-scroll" role="region" aria-label="Warning dates for the selected recession" tabIndex={0}><table className="on-left"><thead><tr><th scope="col">Forecast</th><th scope="col">First alert in window</th><th scope="col">First new crossing</th></tr></thead>
      <tbody>{(['benchmark','candidate'] as const).map(k=><tr key={k}><th scope="row">{k==='benchmark'?'Permits 50/50':'Onset model'}</th><td>{first(episode.methods[k])}</td><td>{crossing(episode.methods[k])}</td></tr>)}</tbody>
    </table></div>
    <p className="on-note">An alert can already be active at the start of the twelve-month window. A new crossing requires a forecast below the threshold in the preceding calendar month.</p>
  </>;
}

function Evidence({trial}:{trial:ExpansionTrial}) {
  const [period,setPeriod]=useState<ExpansionWindow>('all'), [chosen,setChosen]=useState('');
  const m=trial.metrics[period], w=trial.warnings.windows[period], changes=w.alertChanges;
  const episode = w.episodes.find(e=>e.onsetDate===chosen)
    ?? w.episodes.find(e=>e.coverage==='full' && e.methods.benchmark.leadMonths!==e.methods.candidate.leadMonths)
    ?? w.episodes.at(-1);
  return <section className="li-section on-evidence">
    <div className="li-section-head"><h2>Before each recession</h2><div className="li-controls" role="group" aria-label="Evaluation window">{windows.map(k=>
      <button key={k} type="button" aria-pressed={k===period} onClick={()=>setPeriod(k)}>{names[k]}</button>)}</div></div>
    <p>Among {count(w.completeEpisodes,'fully observed recession')}, the onset model warned earlier in <strong>{w.comparison.earlier}</strong>,
      at the same time in <strong>{w.comparison.tied}</strong>, and later in <strong>{w.comparison.later}</strong>.
      {w.comparison.baselineAtCeiling && ' The benchmark already reached the twelve-month limit in every complete episode.'}</p>
    {episode ? <><label className="on-select">Recession start<select value={episode.onsetDate} onChange={e=>setChosen(e.target.value)}>
      {w.episodes.map(e=><option value={e.onsetDate} key={e.onsetDate}>{month(e.onsetDate)}{e.coverage==='full'?'':' · '+e.coverage}</option>)}</select></label>
      <EpisodeView episode={episode} trial={trial} period={period}/></> : <p>No recession start falls within the available forecast coverage.</p>}
    <h3 className="on-sub">Which warnings changed?</h3>
    <div className="on-scroll" tabIndex={0} role="region" aria-label="Changes in alert decisions"><table><thead><tr><th scope="col">Expansion issues</th><th scope="col">Scored</th><th scope="col">Alerts removed</th><th scope="col">Alerts added</th></tr></thead><tbody>
      <tr><th scope="row">No recession in the following year</th><td>{w.quietExpansionN}</td><td>{changes.quietRemoved}</td><td>{changes.quietAdded}</td></tr>
      <tr><th scope="row">Before a recession onset</th><td>{w.preOnsetN}</td><td>{changes.preOnsetRemoved}</td><td>{changes.preOnsetAdded}</td></tr>
    </tbody></table></div>
    <div className="on-scroll" role="region" aria-label="Risk estimates by realized outcome" tabIndex={0}><table><thead><tr><th scope="col">Realized outcome</th><th scope="col">Mean permits risk</th><th scope="col">Mean onset risk</th><th scope="col">Permits Brier</th><th scope="col">Onset Brier</th></tr></thead>
      <tbody>{(['quiet','preOnset'] as const).map(group=>{
        const r=w.outcomeScores[group];
        return <tr key={group}><th scope="row">{group==='quiet'?'Continued expansion':'Recession began'} ({r.n})</th><td>{pct(r.benchmark.meanRisk)}</td><td>{pct(r.candidate.meanRisk)}</td><td>{num(r.benchmark.brier,4)}</td><td>{num(r.candidate.brier,4)}</td></tr>;
      })}</tbody></table></div>
    <p className="on-note">These groups use the outcome known a year later. They show where probabilities gained or lost accuracy. Calibration requires grouping by the probability known at issue.</p>
    <details className="li-details"><summary>Evaluation months and model controls</summary>
      <p>{m.matureBenchmarkN} mature benchmark issues in this window of {count(m.expectedCalendarMonths,'calendar month')}. {m.recessionN} originated in recessions.
        {m.missingBenchmarkMonths>0 && <> {count(m.missingBenchmarkMonths,'calendar month')} lacked a mature benchmark forecast.</>}
        {m.unknownPhaseN>0 && <> The issue-month phase was unknown for {count(m.unknownPhaseN,'forecast')}.</>}
        {m.incompleteHorizonN>0 && <> The twelve-month horizon lacked complete labels for {count(m.incompleteHorizonN,'expansion issue')}.</>}
        {' '}Of {m.expansionN} eligible expansion issues, {m.n} have paired forecasts and {m.missingCandidateMonths} are missing a candidate. {m.positiveWindows} positive windows cover {count(m.distinctOnsets,'distinct onset')}.</p>
      {w.expansionAtBothDates && <p>Signals arrive with a two-month lag. In {w.expansionAtBothDates.recessionSignalMonths} of the {m.n} expansion-origin forecasts, the signal month itself was in recession.
        {w.expansionAtBothDates.unknownSignalMonths > 0 && <> The signal-month phase was unavailable for {w.expansionAtBothDates.unknownSignalMonths} further issues.</>}
        {' '}Restricting scoring to the {w.expansionAtBothDates.n} issues in expansion at both dates gives a Brier error of {num(w.expansionAtBothDates.benchmark,5)} for the benchmark and {num(w.expansionAtBothDates.candidate,5)} for the onset model. Both forecasts use the original training rule.</p>}
      <div className="on-scroll" tabIndex={0} role="region" aria-label="Model and base rate controls"><table><thead><tr><th scope="col">Forecast components</th><th scope="col">Brier error</th><th scope="col">Log loss</th><th scope="col">AUC</th></tr></thead>
        <tbody>{methods.map(([k,label])=><tr key={k}><th scope="row">{label}</th><td>{num(m.models[k].brier,5)}</td><td>{num(m.models[k].logLoss,5)}</td><td>{num(m.models[k].auc,3)}</td></tr>)}</tbody></table></div>
      <p className="on-note">Each blended forecast assigns half its weight to the signal and half to the base rate. Changing one component at a time shows which part accounts for a change in probability error.</p>
    </details>
  </section>;
}

export default function ExpansionOnset({trial}:{trial?:ExpansionTrial}) {
  if (!trial) return <article className="li-research on-research"><h1>From expansion to recession</h1><p>The scheduled research build is awaiting this comparison.</p></article>;
  const f=trial.prospective, l=trial.latest;
  return <article className="li-research on-research"><header className="li-title"><div><h1>From expansion to recession</h1>
    <p>Can building permits, the yield curve, credit and labor conditions warn of a new U.S. recession when the model learns only from expansion months?</p></div>
    <a className="li-download" href="/api/download?file=expansion"><Download size={16} aria-hidden="true"/>Monthly replay CSV</a></header>
    <Current trial={trial}/><Accuracy trial={trial}/><Evidence trial={trial}/>
    <section className="li-section"><h2>How the onset forecast works</h2>
      <p>The benchmark combines the published permits signal and the historical frequency of a recession month in the following year.
        The onset model fits the same four signals on expansion months and estimates its base rate from those same months. A positive outcome means at least one expansion-to-recession transition in months one through twelve after the forecast.</p>
      {l.available && <p>For the {month(l.issueDate)} fit, {count(l.trainingPositives,'positive training window')} among {l.trainingN} expansion issues covered {count(l.trainingOnsets,'distinct recession start')}.
        The fitted signal gave {pct(l.rawExpansionProbability,2)} and the expansion base rate was {pct(l.expansionPriorProbability,2)}.</p>}
      <p>Historical fits use an expanding training sample and update each January. Every training outcome ends before the refit, and economic inputs lag the forecast month by two months. The live model refits monthly.
        All dated issues receive a conditional estimate when their inputs are available. Later business-cycle dating determines which forecasts can be scored.</p>
      <p className="on-note">Economic data are revised. The monthly horizons overlap and one recession can generate twelve positive windows. The recent decade is part of the full replay.
        {' '}<a href="https://fred.stlouisfed.org/series/USREC">Monthly recession indicator</a> · <a href="https://www.nber.org/research/data/us-business-cycle-expansions-and-contractions">NBER turning points</a></p>
    </section>
    <section className="li-section"><div className="li-section-head"><h2>Forecasts frozen at issue</h2>
      {f && f.receiptCount>0 && <a className="li-download" href="/api/download?file=expansionreceipts"><Download size={16} aria-hidden="true"/>Forecast records</a>}</div>
      {f && f.receiptCount>0 ? <><p><strong>{f.receiptCount} recorded · {f.maturedCount} scored · {f.excludedCount} excluded · {f.pendingCount} pending.</strong></p>
        {f.latestReceipt && <p>The {month(f.latestReceipt.issueDate)} record gives a conditional onset probability of {pct(f.latestReceipt.predictions.candidate,2)}. Its published permits benchmark was {pct(f.latestReceipt.predictions.benchmark,2)}.</p>}
        {f.maturedCount>0 && <p>Frozen Brier error is {num(f.metrics?.candidate?.brier,5)} for the onset model and {num(f.metrics?.benchmark?.brier,5)} for the benchmark.</p>}</> : <p>The first eligible issue is awaiting capture.</p>}
      <p className="on-note">Monthly forecasts are recorded before their forecast windows start. Evaluation requires expansion at issue and a complete outcome year. Issues subsequently dated within recessions are counted separately.</p>
    </section>
  </article>;
}
