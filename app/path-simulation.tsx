'use client';

import {useState} from 'react';
import {Download} from 'lucide-react';
import type {PassRate, PathSimulationTrial, Quantiles, SimulationExample, SimulationPeriod, SimulationScenario} from '../lib/path-simulation-types';
import './leading-indicators.css';
import './path-simulation.css';

const periods: SimulationPeriod[] = ['all','rolling120'];
const names = {all: 'Full sample', rolling120: 'Recent 10 years'};
const dates = new Intl.DateTimeFormat('en-US',{month:'short',year:'numeric',timeZone:'UTC'});
const whole = new Intl.NumberFormat('en-US');
const month = (d: string | null) => d ? dates.format(new Date(d.slice(0,7)+'-01T12:00:00Z')) : '—';
const fixed = (v: number | null | undefined, d = 2) => typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
const pct = (v: number | null | undefined, d = 1) => typeof v === 'number' && Number.isFinite(v) ? (v * 100).toFixed(d)+'%' : '—';
const interval = (g: PassRate) => pct(g.interval[0],2)+'–'+pct(g.interval[1],2);
const signed = (v: number | null, d=2) => v===null ? '—' : (v < 0 ? '−' : v > 0 ? '+' : '')+Math.abs(v).toFixed(d);
const byScenario: Record<string,string> = {empirical:'Historical blocks',cap3:'Blocks capped at ±3 bp',cap5:'Blocks capped at ±5 bp',iid:'Independent months'};
const nameFor = (s: SimulationScenario) => byScenario[s.id] ?? s.label;
const yes = (v:boolean) => v ? 'On' : 'Off';

function PassFunnel({scenario}:{scenario:SimulationScenario}) {
  const labels: Record<string,string> = {
    allPaths:'All simulated histories', lead:'Keep the 2001 lead',
    brierBoth:'Also maintain Brier in both samples', quietBoth:'Also meet both false-alarm limits', jointStrict:'Also maintain log loss in both samples',
  };
  return <figure className="ps-funnel">
    <figcaption>Paths left after each requirement</figcaption>
    <ol>{scenario.funnel.filter(f=>f.gate!=='jointStrict').map(f=><li key={f.gate}>
      <div className="ps-funnel-row"><span>{labels[f.gate] ?? f.gate}</span><strong>{whole.format(f.count)}</strong></div>
      <div className="ps-track" aria-hidden="true"><i style={{width:100*f.count/scenario.draws+'%'}}/></div>
    </li>)}</ol>
  </figure>;
}

function GateSummary({s}:{s:SimulationScenario}) {
  const gates = s.gates;
  const rows = [
    ['2001 warning keeps its extra month',gates.lead],
    ['Brier holds in both samples',gates.brierBoth],
    ['False alarms stay within the repriced 30% counts in both samples',gates.quietMatched],
    ['False alarms stay within the observed 30% counts in both samples',gates.quietObserved],
    ['False alarms meet both limits in both samples',gates.quietBoth],
    ['Lead and Brier held, with false alarms capped at the repriced 30% counts',gates.jointMatched],
    ['Lead and Brier held, with false alarms capped at the observed 30% counts',gates.jointObserved],
    ['All primary conditions',gates.joint],
    ['All primary conditions and log loss holds in both samples',gates.jointStrict],
  ] as const;
  return <details className="ps-details"><summary>Individual conditions and Monte Carlo intervals</summary>
    <div className="li-scroll" role="region" aria-label="Pass rates by requirement" tabIndex={0}>
      <table><thead><tr><th scope="col">Requirement</th><th scope="col">Passing paths</th><th scope="col">Share</th><th scope="col">95% interval</th></tr></thead>
        <tbody>{rows.map(([label,g])=><tr key={label}><th scope="row">{label}</th><td>{whole.format(g.passed)}</td><td>{pct(g.rate,2)}</td><td>{interval(g)}</td></tr>)}</tbody></table>
    </div>
    <p className="li-note">Each row counts paths meeting its own requirement. The joint result counts the intersection on the same paths.</p>
  </details>;
}

function Sensitivity({trial,scenario,onSelect}:{trial:PathSimulationTrial;scenario:SimulationScenario;onSelect:(s:string)=>void}) {
  return <section className="li-section">
    <h2>How much do the assumptions matter?</h2>
    <p>The primary replay keeps the sizes of historical paired changes and samples contiguous six-month blocks. The capped versions limit each rate adjustment separately. Independent monthly sampling keeps the historical pairs and removes the block structure.</p>
    <div className="li-scroll" role="region" aria-label="Sampling assumption comparison" tabIndex={0}>
      <table><thead><tr><th scope="col">Path model</th><th scope="col">2001 lead held</th><th scope="col">Brier held in both</th>
        <th scope="col">False-alarm limits met</th><th scope="col">All conditions</th></tr></thead>
        <tbody>{trial.scenarios.map(s=><tr className={scenario.id===s.id ? 'ps-active' : undefined} key={s.id}>
          <th scope="row"><button type="button" className="ps-row-link" aria-pressed={scenario.id===s.id} onClick={()=>onSelect(s.id)}>{nameFor(s)}</button></th>
          {[s.gates.lead,s.gates.brierBoth,s.gates.quietBoth,s.gates.joint].map((g,i)=><td key={i}>{pct(g.rate,2)}</td>)}
        </tr>)}</tbody></table>
    </div>
  </section>;
}

function SampleOutcomes({trial,s}:{trial:PathSimulationTrial;s:SimulationScenario}) {
  const [period,setPeriod] = useState<SimulationPeriod>('all');
  const w=s.windows[period], base=trial.baseline[period];
  const rows: [string,number,Quantiles,number][] = [
    ['Brier error',base.brier,w.brier,5],['Log loss',base.logLoss,w.logLoss,5],
    ['30% false-alert months',base.quietAlerts,w.levelQuiet,0],['Curve-rule false-alert months',base.quietAlerts,w.ruleQuiet,0],
  ];
  return <section className="li-section">
    <div className="li-section-head"><h2>Errors and false alarms</h2>
      <div className="li-controls" role="group" aria-label="Evaluation window">{periods.map(k=><button type="button" key={k} aria-pressed={k===period} onClick={()=>setPeriod(k)}>{names[k]}</button>)}</div></div>
    <p>{month(base.windowStart)}–{month(base.windowEnd)} · {base.n} mature forecasts issued during expansions, including {base.quietN} months with no recession onset in the following year. Lower values are better. A quiet issue counts once per warning rule.</p>
    <div className="li-scroll" role="region" aria-label="Error and alarm distributions" tabIndex={0}>
      <table><thead><tr>{['Metric','Observed reference','5th percentile','Median','95th percentile'].map(t=><th scope="col" key={t}>{t}</th>)}</tr></thead>
        <tbody>{rows.map(([label,value,q,d])=><tr key={label}><th scope="row">{label}</th><td>{fixed(value,d)}</td>{q.map((n,i)=><td key={i}>{fixed(n,d)}</td>)}</tr>)}</tbody></table></div>
    <p><strong>{pct(s.gates.quietMatched.rate)}</strong> of paths pass the false-alarm test in both samples against a repriced 30% benchmark. Using the original observed totals, <strong>{pct(s.gates.quietObserved.rate)}</strong> pass in both samples.</p>
    <p className="li-note">For false alarms, the observed reference is the original 30% rule. The main test also compares the curve rule to the 30% rule recalculated on each simulated history. The table gives marginal percentiles across paths.</p>
  </section>;
}

function Example({example,period}:{example:SimulationExample;period:SimulationPeriod}) {
  const [which,setWhich] = useState<'mayPath'|'febPath'>('mayPath');
  const scores=example[period], alert=which==='mayPath'?example.mayAlert:example.febAlert;
  return <>
    <p>In draw {whole.format(example.draw)}, the 2001 warning lead was <strong>{example.lead2001===null ? 'unavailable' : example.lead2001+' months'}</strong> against {example.levelLead2001===null ? 'no warning' : example.levelLead2001+' months'} for the repriced 30% rule.
      {' '}{names[period]} Brier was <strong>{fixed(scores.brier,5)}</strong>. The curve rule produced <strong>{scores.ruleQuiet}</strong> quiet-month alerts against <strong>{scores.levelQuiet}</strong> for the 30% rule on the same path.</p>
    <div className="ps-compare">
      <div><div className="li-controls ps-controls-inline" role="group" aria-label="Example forecast month">
        {(['mayPath','febPath'] as const).map(k=><button key={k} type="button" aria-pressed={which===k} onClick={()=>setWhich(k)}>{k==='mayPath'?'May 2000':'Feb 2019'}</button>)}</div>
        <p className="li-note">Curve-confirmed warning <strong>{yes(alert)}</strong>. {which==='mayPath' ? 'An April 2001 recession onset fell within this issue’s twelve-month horizon.' : 'The March 2020 onset lay outside this issue’s twelve-month horizon.'}</p></div>
      <div className="li-scroll" role="region" aria-label="Calendar shifts in the selected simulation" tabIndex={0}>
        <table><thead><tr><th scope="col">Observation</th><th scope="col">3m bill, bp</th><th scope="col">10y yield, bp</th></tr></thead>
          <tbody>{example[which].map(o=><tr key={o.date}><th scope="row">{month(o.date)}</th><td>{signed(o.shortBp)}</td><td>{signed(o.longBp)}</td></tr>)}</tbody></table>
      </div></div>
  </>;
}

function Examples({s}:{s:SimulationScenario}) {
  const [index,setIndex]=useState(0);
  const [period,setPeriod]=useState<SimulationPeriod>('all');
  const example=s.examples[index] ?? s.examples[0];
  if (!example) return null;
  return <section className="li-section"><h2>Inspect a simulated history</h2>
    <p>The curve rule fires in <strong>{pct(s.gates.mayAlert.rate)}</strong> of draws in May 2000 and <strong>{pct(s.gates.febAlert.rate)}</strong> in February 2019. A February warning counts as false because the March 2020 recession began thirteen months later.{s.gates.febExtra && <> It is an extra warning below the repriced 30% line in {pct(s.gates.febExtra.rate,2)} of all draws.</>}</p>
    <div className="ps-controls ps-example-controls"><label htmlFor="ps-example">Example draw</label>
      <select id="ps-example" value={example.draw} onChange={e=>setIndex(s.examples.findIndex(x=>x.draw===Number(e.target.value)))}>
        {s.examples.map(x=><option value={x.draw} key={x.draw}>Draw {whole.format(x.draw)} · {x.passed?'Pass':'Fail'}</option>)}</select>
      <label htmlFor="ps-example-window">Sample</label><select id="ps-example-window" value={period} onChange={e=>setPeriod(e.target.value as SimulationPeriod)}>
        {periods.map(k=><option key={k} value={k}>{names[k]}</option>)}</select></div>
    <Example example={example} period={period}/>
  </section>;
}

function Calibration({trial}:{trial:PathSimulationTrial}) {
  const keys=['first','may2000','latest'] as const;
  const [key,setKey]=useState<(typeof keys)[number]>('may2000');
  const c=trial.calibration[key], source=trial.calibration.source;
  const rows=[
    ['Mean signed shift, bp',signed(c.shortMeanBp),signed(c.longMeanBp)],
    ['Standard deviation, bp',fixed(c.shortSdBp),fixed(c.longSdBp)],
    ['Median absolute shift, bp',fixed(c.shortMedianAbsBp),fixed(c.longMedianAbsBp)],
    ['90th percentile absolute shift, bp',fixed(c.shortP90AbsBp),fixed(c.longP90AbsBp)],
    ['One-month autocorrelation',fixed(c.shortLag1,3),fixed(c.longLag1,3)],
  ];
  return <section className="li-section"><h2>Where the yield shifts come from</h2>
    <p>Move a monthly averaging window one trading session earlier. Replace its last paired daily quote with the preceding month’s last paired quote, keeping the number of trading sessions fixed. Repeating that calculation for both rates gives a signed pair of monthly adjustments.</p>
    <div className="li-controls ps-controls-inline" role="group" aria-label="Calibration history cutoff">{keys.map(k=><button key={k} type="button"
      aria-pressed={k===key} onClick={()=>setKey(k)}>{k==='first'?'Start of replay':k==='may2000'?'May 2000 issue':'Latest issue'}</button>)}</div>
    <p><strong>{whole.format(c.n)}</strong> paired historical months from {month(c.start)} through {month(c.end)}. Bill and ten-year shifts had a Pearson correlation of <strong>{fixed(c.correlation,3)}</strong>. Both shifts were within ±3 bp in <strong>{pct(c.within3)}</strong> of months and within ±5 bp in <strong>{pct(c.within5)}</strong>.</p>
    <div className="li-scroll ps-calibration" role="region" aria-label="Historical input distribution" tabIndex={0}>
      <table><thead><tr><th scope="col">Historical shift</th><th scope="col">3m bill</th><th scope="col">10y Treasury</th></tr></thead>
        <tbody>{rows.map(([t,a,b])=><tr key={t}><th scope="row">{t}</th><td>{a}</td><td>{b}</td></tr>)}</tbody></table></div>
    <p className="li-note">Daily records span {month(source.dailyStart)}–{month(source.dailyEnd)} across {whole.format(source.pairedDays)} common trading dates. Each block comes from consecutive historical months ending before its first simulated observation. Overlapping forecasts use the same pair whenever they share an observation date. The signed changes keep the historical relationship between the two rates.</p>
    <div className="ps-links">{source.series.map(id=><a key={id} href={'https://fred.stlouisfed.org/series/'+encodeURIComponent(id)}>{id==='DTB3'?'Daily three-month bill':'Daily ten-year Treasury'} · {id}</a>)}</div>
  </section>;
}

export default function PathSimulation({trial}:{trial?:PathSimulationTrial}) {
  const [selected,setSelected]=useState<string|null>(null);
  if (!trial?.scenarios?.length) return <article className="li-research ps-view"><h1>Recession warning simulation</h1><p>The first calibrated simulation is awaiting a complete research update.</p></article>;
  const s=trial.scenarios.find(v=>v.id===(selected ?? trial.spec.primary)) ?? trial.scenarios[0];
  const g=s.gates.joint, baseline=trial.baseline;
  return <article className="li-research ps-view">
    <header className="li-title"><div><h1>Recession warning simulation</h1>
      <p>How often can small, historically calibrated Treasury moves preserve the earlier 2001 warning, maintain forecast accuracy and keep false alarms within the 30% benchmark?</p></div>
      <a className="li-download" href="/api/download?file=pathsimulation"><Download size={16} aria-hidden="true"/>Simulated paths CSV</a></header>
    <div className="ps-controls"><label htmlFor="ps-scenario">Simulated yield history</label>
      <select id="ps-scenario" value={s.id} onChange={e=>setSelected(e.target.value)}>{trial.scenarios.map(v=><option key={v.id} value={v.id}>{nameFor(v)}</option>)}</select></div>
    <section className="ps-overview" aria-live="polite"><div className="ps-result"><h2>Paths passing all conditions</h2>
      <strong>{pct(g.rate,2)}</strong><span>{whole.format(g.passed)} of {whole.format(g.n)} simulated histories</span>
      <p className="li-note">95% Monte Carlo interval {interval(g)}.</p></div><PassFunnel scenario={s}/></section>
    <section className="li-section"><h2>What counts as a pass?</h2>
      <p>Keep the May 2000 warning, with at least eleven months’ lead before the recession and at least one extra month versus the repriced 30% rule. On observed yields the two leads were {baseline.ruleLead2001} and {baseline.levelLead2001} months. Require Brier error to stay at or below its observed value in <strong>both</strong> samples.</p>
      <p>In each sample, the curve rule must produce no more false alerts than either the scenario’s 30% rule or the original 30% count ({baseline.all.quietAlerts} full sample, {baseline.rolling120.quietAlerts} recent). Adding the requirement that log loss also holds in both samples leaves <strong>{pct(s.gates.jointStrict.rate,2)}</strong> of draws.</p>
      {s.gates.lead.passed>0 && <p className="li-note">Among paths that keep the early warning, {pct(g.passed/s.gates.lead.passed,2)} also hold both Brier scores and satisfy the false-alarm limits.</p>}
      <GateSummary s={s}/></section>
    <Sensitivity trial={trial} scenario={s} onSelect={setSelected}/>
    <SampleOutcomes trial={trial} s={s}/>
    <Examples key={s.id} s={s}/>
    <Calibration trial={trial}/>
    {s.latest && trial.latest.available && <section className="li-section"><h2>Current issue · {month(trial.latest.issueDate)}</h2>
      <p>Conditional on expansion at issue, the observed forecast assigns <strong>{pct(trial.latest.probability,2)}</strong> to a recession starting from {month(trial.latest.forecastStart)} through {month(trial.latest.forecastEnd)}. The middle 90% of simulated estimates span {pct(s.latest.probability[0],2)}–{pct(s.latest.probability[2],2)}. The warning fires in {pct(s.latest.warning.rate,2)} of draws.</p>
    </section>}
    <section className="li-section"><h2>Interpreting the frequency</h2>
      <p>Each draw reprices the four monthly feature vectors using that issue’s fitted model, economic prior and two-month data lag. Both warning rules use the same risk path. The probability scores compare recalculated forecasts with the observed recession outcomes. The two samples overlap.</p>
      <p>The simulated frequency is conditional on a one-session change in quote timing, a sampling scheme and revised historical data. The yield shifts approximate timing sensitivity. The 95% Wilson interval measures random sampling error across simulated histories. Calibration uncertainty and future changes in the economy fall outside that interval. The 2:1 warning rule was originally chosen after inspecting historical cases.</p>
      <p className="li-note">Random seed {trial.spec.seed}{' · '}{whole.format(s.draws)} paths per specification.</p>
      <div className="ps-links"><a href="#jointstress">Inspect the earlier ±3 and ±5 bp stress bounds</a></div>
    </section></article>;
}
