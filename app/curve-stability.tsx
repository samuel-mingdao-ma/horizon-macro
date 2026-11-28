'use client';

import {useState} from 'react';
import {Check, Download, X} from 'lucide-react';
import type {CurveStabilityTrial, StabilityCell, StabilityPeriod, StabilityResult, StabilityRow} from '../lib/curve-stability-types';
import './leading-indicators.css';
import './curve-stability.css';

const may = '2000-05-01';
const feb = '2019-02-01';
const recession2001 = '2001-04-01';
const periods: StabilityPeriod[] = ['all','rolling120'];
const periodName = {all:'Full history', rolling120:'Latest 10 years'};
const formatMonth = new Intl.DateTimeFormat('en-US',{month:'short',year:'numeric',timeZone:'UTC'});
const month = (v: string | null) => v ? formatMonth.format(new Date(v.slice(0,7)+'-01T12:00:00Z')) : '—';
const finite = (v: unknown): v is number => typeof v==='number' && Number.isFinite(v);
const number = (v: number|null|undefined, digits=2) => finite(v) ? v.toLocaleString('en-US',{maximumFractionDigits:digits}) : '—';
const score = (v: number|null, digits=5) => finite(v) ? v.toFixed(digits) : '—';
const signed = (v: number|null) => finite(v) ? (v>0?'+':v<0?'−':'')+number(Math.abs(v)) : '—';
const bp = (v: number|null) => finite(v) ? signed(v)+' bp' : '—';
const bpChange = (v: number|null) => finite(v) ? Math.round(v*1e12)/1e10 : null;
const prob = (v: number|null) => finite(v) ? (100*v).toFixed(2)+'%' : '—';
const flag = (v: boolean|null|undefined) => v===true?'On':v===false?'Off':'Unavailable';
const band = (v:number) => v===0?'0 bp':'±'+v+' bp';
const plural = (n:number,one:string,many=one+'s') => n===1?one:many;

function why(cell: StabilityCell, stressed: boolean) {
  const passed = stressed ? cell.stressPassed : cell.pointPassed;
  if (passed) return 'Pass';
  const w = cell.windows.all;
  const kept = stressed ? cell.cases[may]?.guaranteed : cell.cases[may]?.actual;
  const added = (stressed ? w.possibleQuietDates : w.actualQuietDates).length;
  if (kept===false && added) return 'Both';
  if (kept===false) return 'May';
  if (added) return 'False';
  return 'Other';
}

function Matrix({trial,cell,select,stressed,setStressed}:{trial:CurveStabilityTrial;cell:StabilityCell;select:(s:string)=>void;stressed:boolean;setStressed:(v:boolean)=>void}) {
  const {bandsBp,ratios,stressBp}=trial.spec;
  const passed=trial.cells.filter(c=>stressed?c.stressPassed:c.pointPassed).length;
  return <section className="li-section cs-matrix-section" aria-labelledby="cs-map-label">
    <div className="li-section-head"><h2 id="cs-map-label">Which settings hold?</h2>
      <div className="li-controls" role="group" aria-label="Matrix test">
        <button type="button" aria-pressed={!stressed} onClick={()=>setStressed(false)}>Observed</button>
        <button type="button" aria-pressed={stressed} onClick={()=>setStressed(true)}>±{stressBp} bp stress</button>
      </div></div>
    <p aria-live="polite"><strong>{passed} of {trial.cells.length} settings pass</strong>{stressed
      ? ' when each month’s ten-year yield change can move independently anywhere within ±'+stressBp+' bp of its reading.'
      : ' at the observed monthly yields.'} A pass keeps the extra month before the 2001 recession, preserves the baseline’s recession detections and adds zero quiet-month alerts in both samples.</p>
    <table className="cs-matrix" aria-label="Select a flat band and minimum bill-rise to long-fall ratio">
      <caption>Rows set the ten-year moves treated as flat. Columns set the bill rise required per basis point of ten-year decline outside that band.</caption>
      <thead><tr><th scope="col">Flat band</th>{ratios.map(r=><th scope="col" key={r}>{r}×</th>)}</tr></thead>
      <tbody>{bandsBp.map(d=><tr key={d}><th scope="row">{band(d)}</th>{ratios.map(r=>{
        const c=trial.cells.find(x=>x.bandBp===d&&x.ratio===r);
        if (!c) return <td key={r}>—</td>;
        const label=why(c,stressed), passes=label==='Pass';
        return <td key={r}><button type="button" className={passes?'cs-pass':'cs-fail'} aria-pressed={c.id===cell.id}
          aria-label={band(d)+' flat band, '+r+' to 1 ratio, '+(passes?'pass':label==='May'?'May warning fails':label==='False'?'extra false alerts':label==='Both'?'May warning fails and extra false alerts':'gate unmet')}
          onClick={()=>select(c.id)}>{passes?<Check size={14} aria-hidden/>:<X size={13} aria-hidden/>}<span>{label}</span></button></td>;
      })}</tr>)}</tbody>
    </table>
    <p className="li-note cs-key"><span><b>May</b> loses the extra month.</span><span><b>False</b> adds a quiet-month alert.</span><span><b>Both</b> misses both tests.</span></p>
  </section>;
}

function IssuedCase({row,result,title,shift}: {row?:StabilityRow;result:StabilityResult|null;title:string;shift:number}) {
  if (!row || !result) return <div><h3>{title}</h3><p>Case unavailable in this vintage.</p></div>;
  const short=bpChange(row.shortChange), long=bpChange(row.longChange);
  const {lowerBp:lo,upperBp:hi,upperInclusive}=result;
  const hasBounds=finite(lo)&&finite(hi);
  const moved=finite(long)?long+shift:null;
  const adjusted=row.levelAlert===null?null:row.levelAlert || !!(row.quarterAlert&&finite(moved)&&hasBounds&&moved>=lo&&(upperInclusive?moved<=hi:moved<hi));
  let edge='';
  if (hasBounds && finite(long)) {
    if (long < lo) edge='A '+bp(lo-long)+' shift reaches the lower cutoff and admits the reading.';
    else if (long <= hi) edge='The upper cutoff is '+bp(hi-long)+' above this reading. '+(upperInclusive?'Equality qualifies.':'Equality is outside the filter.');
    else edge='The reading is '+bp(long-hi)+' above the upper cutoff.';
  }
  const verdict=row.target===1&&row.onsetDate?'Onset in '+month(row.onsetDate):row.target===0?'No onset within 12 months':'Outcome unavailable';
  return <article className="cs-case"><h3>{title}</h3><p className="li-note">{month(row.lagFeatureDate)} – {month(row.featureDate)} observations</p>
    <dl><div><dt>Three-month bill move</dt><dd>{bp(short)}</dd></div>
      <div><dt>Observed ten-year move</dt><dd>{bp(long)}</dd></div>
      <div><dt>Accepted ten-year moves</dt><dd>{hasBounds?<>{bp(lo)} to {bp(hi)}{!upperInclusive?' (upper bound excluded)':''}</>:'None'}</dd></div>
      <div><dt>Observed alert</dt><dd>{flag(result.actual)}</dd></div>
      <div className="cs-shift-result"><dt>With a {bp(shift)} shift</dt><dd>{bp(moved)} · {flag(adjusted)}</dd></div></dl>
    <p className="cs-edge">{edge}</p><p className="li-note">{verdict}</p>
  </article>;
}

function Cases({trial,cell}:{trial:CurveStabilityTrial;cell:StabilityCell}) {
  const stress=trial.spec.stressBp;
  const [shift,setShift]=useState(stress);
  return <section className="li-section"><h2>Move the long-end reading</h2>
    <p>For the selected {band(cell.bandBp)} flat band and {cell.ratio}:1 ratio, move the ten-year yield change while the bill move and the issued pace warning stay fixed.</p>
    <label className="cs-slider"><span>Shift to the observed ten-year move</span>
      <input type="range" min={-stress} max={stress} step={0.5} value={shift} onChange={e=>setShift(Number(e.target.value))}/>
      <output>{bp(shift)}</output></label>
    <div className="cs-cases" aria-live="polite">{([may,feb] as const).map(date=><IssuedCase key={date} title={month(date)+' issue'}
      row={trial.history.find(r=>r.date===date)} result={cell.cases[date]} shift={shift}/>)}</div>
  </section>;
}

function Evidence({trial,cell,period,setPeriod}:{trial:CurveStabilityTrial;cell:StabilityCell;period:StabilityPeriod;setPeriod:(p:StabilityPeriod)=>void}) {
  const selected=cell.windows[period],w=trial.windows[period];
  const gained=selected.possibleQuietDates.filter(d=>!selected.actualQuietDates.includes(d));
  const complete=selected.episodes.filter(e=>w.episodes.find(b=>b.onsetDate===e.onsetDate)?.coverage==='full');
  const earlier=complete.filter(e=>{
    const l=w.episodes.find(b=>b.onsetDate===e.onsetDate)?.levelLead;
    return finite(e.guaranteedLead) && e.guaranteedLead>(l??0);
  }).length;
  const numLead=(n:number|null|undefined)=>finite(n)?n+' mo':'—';
  return <section className="li-section"><div className="li-section-head"><h2>Warnings in the replay</h2>
    <div className="li-controls" role="group" aria-label="Evaluation window">{periods.map(p=><button key={p} type="button" aria-pressed={p===period}
      onClick={()=>setPeriod(p)}>{periodName[p]}</button>)}</div></div>
    <p>{month(w.windowStart)} – {month(w.windowEnd)} · {w.n} scored expansion issues · {band(cell.bandBp)} flat band · {cell.ratio}:1 ratio</p>
    <div className="li-scroll cs-table" role="region" tabIndex={0} aria-label="Selected rule versus original 30 percent alarm"><table>
      <thead><tr><th scope="col">Warning months</th><th scope="col">30% baseline</th><th scope="col">Observed rule</th><th scope="col">Under ±{trial.spec.stressBp} bp</th></tr></thead>
      <tbody><tr><th scope="row">Quiet alerts</th><td>{w.levelQuiet} / {w.quietExpansionN}</td><td>{w.levelQuiet+selected.actualQuietDates.length} / {w.quietExpansionN}</td>
        <td>Up to {w.levelQuiet+selected.possibleQuietDates.length} / {w.quietExpansionN}</td></tr>
        <tr><th scope="row">Pre-onset alerts</th><td>{w.levelPre} / {w.preOnsetN}</td><td>{w.levelPre+selected.actualPreDates.length} / {w.preOnsetN}</td>
          <td>At least {w.levelPre+selected.guaranteedPreDates.length} / {w.preOnsetN}</td></tr></tbody>
    </table></div>
    <dl className="cs-dates"><div><dt>Extra quiet alerts at observed yields</dt><dd>{selected.actualQuietDates.map(month).join(' · ')||'None'}</dd></div>
      <div><dt>Extra quiet alerts possible only under stress</dt><dd>{gained.map(month).join(' · ')||'None'}</dd></div>
      <div><dt>Extra pre-onset alerts guaranteed under stress</dt><dd>{selected.guaranteedPreDates.map(month).join(' · ')||'None'}</dd></div></dl>
    <h3>Lead before each recession</h3>
    <p className="li-note">Across {w.completeEpisodes} complete {plural(w.completeEpisodes,'episode')}, {earlier} {earlier===1?'gets':'get'} an earlier first warning even at the least favorable reading in each issue.</p>
    <div className="li-scroll cs-table" role="region" aria-label="Recession episode lead in months" tabIndex={0}><table><thead><tr>
      {['Recession onset','30% baseline','Observed lead','Guaranteed lead'].map(k=><th scope="col" key={k}>{k}</th>)}</tr></thead>
      <tbody>{w.episodes.map(e=>{
        const c=selected.episodes.find(x=>x.onsetDate===e.onsetDate);
        return <tr key={e.onsetDate}><th scope="row">{month(e.onsetDate)}{e.coverage!=='full'&&<small>{e.availableMonths} / 12 issues observed</small>}</th>
          <td>{numLead(e.levelLead)}</td><td>{numLead(c?.actualLead)}</td><td>{numLead(c?.guaranteedLead)}</td></tr>;
      })}</tbody></table></div>
  </section>;
}

function Scores({trial}: {trial:CurveStabilityTrial}) {
  return <section className="li-section"><h2>Probability accuracy</h2><p>The grid changes warning decisions on the same expansion-origin forecasts. Each setting and stress test uses the same issued twelve-month probabilities.</p>
    <div className="li-scroll cs-table" role="region" aria-label="Probability scores" tabIndex={0}><table><thead><tr>
      {['Scored expansion issues','Brier error','Log loss','AUC'].map(k=><th scope="col" key={k}>{k}</th>)}</tr></thead>
      <tbody>{periods.map(p=>{const w=trial.windows[p],s=w.probabilityScores;return <tr key={p}><th scope="row">{periodName[p]} · {w.n}</th>
        <td>{score(s.brier)}</td><td>{score(s.logLoss)}</td><td>{score(s.auc,3)}</td></tr>;})}</tbody></table></div>
    <p className="li-note">The recent decade overlaps the full replay. Twelve monthly issue windows can refer to the same recession onset.</p>
  </section>;
}

export default function CurveStability({trial}:{trial?:CurveStabilityTrial}) {
  const [selected,setSelected]=useState<string|null>(null);
  const [stressed,setStressed]=useState(true),[period,setPeriod]=useState<StabilityPeriod>('all');
  const cell=trial?.cells.find(c=>c.id===(selected??trial.spec.referenceId));
  if (!trial || !cell) return <article className="li-research cs-view"><h1>How stable is the 2:1 warning?</h1><p>The sensitivity replay is awaiting a research update.</p></article>;
  const c=trial.latest,f=trial.prospective;
  const original=trial.cells.find(x=>x.id===trial.spec.originalId),ref=trial.cells.find(x=>x.id===trial.spec.referenceId);
  const episode=cell.windows.all.episodes.find(e=>e.onsetDate===recession2001);
  const lead=trial.windows.all.episodes.find(e=>e.onsetDate===recession2001)?.levelLead;
  const current=c.results[cell.id];
  return <article className="li-research cs-view"><header className="li-title"><div><h1>How stable is the 2:1 warning?</h1>
    <p>{ref?.stressPassed&&original&&!original.stressPassed
      ? <>At {ref.ratio}:1, a +{trial.spec.stressBp} bp change to the ten-year reading {original.cases[may]?.plus3===false ? 'silences the original May 2000 warning' : 'tests the original May 2000 warning'}. With a {band(ref.bandBp)} flat band, the early warning survives every shift and adds no false-alert months in either sample under the same stress.</>
      : <>Test the May 2000 warning across small changes in the ten-year yield and neighboring bill-to-bond ratios.</>}</p></div>
    <a className="li-download" href="/api/download?file=stability"><Download size={16} aria-hidden/>Monthly grid CSV</a></header>
    <p className="li-note">This test holds the risk estimate fixed. <a href="#jointstress">Recalculate risk and momentum when both Treasury yields move.</a></p>
    <Matrix trial={trial} cell={cell} select={setSelected} stressed={stressed} setStressed={setStressed}/>
    <section className="cs-selection" aria-live="polite"><div><h2>{band(cell.bandBp)} flat band · {cell.ratio}:1</h2>
      <p>May 2000 at observed yields <b>{flag(cell.cases[may]?.actual)}</b>. At a +{trial.spec.stressBp} bp shift <b>{flag(cell.cases[may]?.plus3)}</b>.</p></div>
      <p>2001 lead <b>{number(lead,0)} months</b> at 30%, <b>{number(episode?.actualLead,0)} observed</b>, <b>{number(episode?.guaranteedLead,0)} guaranteed</b>.</p></section>
    <Cases trial={trial} cell={cell}/><Evidence trial={trial} cell={cell} period={period} setPeriod={setPeriod}/><Scores trial={trial}/>
    <section className="li-section"><h2>Current issue</h2><div className="cs-current"><div><strong className="cs-risk">{prob(c.probability)}</strong>
      <p>Chance of entering recession from {month(c.forecastStart)} through {month(c.forecastEnd)}, conditional on expansion in {month(c.issueDate)}.</p>
      {!c.available&&<p className="li-note">{c.reason??'Current risk inputs are incomplete.'}</p>}</div>
      <dl><div><dt>Bill change</dt><dd>{bp(bpChange(c.shortChange))}</dd></div><div><dt>Ten-year change</dt><dd>{bp(bpChange(c.longChange))}</dd></div>
        <div><dt>30% alarm / pace alarm</dt><dd>{flag(c.levelAlert)} / {flag(c.quarterAlert)}</dd></div>
        <div><dt>Selected rule at observed yields</dt><dd>{flag(current?.actual)}</dd></div></dl></div></section>
    <section className="li-section"><h2>What the test changes</h2>
      <p>The flat band treats a ten-year yield change inside ±{cell.bandBp} bp as zero for the sign and ratio tests, including the endpoints. Outside the band, the ten-year yield must fall and the bill must rise by at least {cell.ratio} times that fall. The original quoted spread must narrow and the bill must rise in both cases. Each screen applies only to an extra pace alarm below 30%.</p>
      <p>Stress moves the long-end change continuously by up to {trial.spec.stressBp} bp in either direction. A guaranteed alert survives every allowed reading. The displayed cutoffs are rounded to two decimals. Decisions use the exact bounds. A possible alert needs only one. Different months can take different shifts, so the false-alert bound counts every quiet month that could trigger. The issued forecast, original pace alarm and short yield stay fixed.</p>
      <p className="li-note">The original 2:1 rule was chosen after inspecting the replay. This grid was fixed for a sensitivity check of those already-known cases. Revised data, overlapping horizons and few recessions limit what it can establish about future warnings. <a href="#curvelegs">Original yield-curve decomposition</a></p>
    </section>
    <section className="li-section"><div className="li-section-head"><h2>Rules frozen at issue</h2>{!!f?.receiptCount&&<a className="li-download" href="/api/download?file=stabilityreceipts"><Download size={16} aria-hidden/>Forecast records</a>}</div>
      {f?.receiptCount?<p><strong>{f.receiptCount} recorded · {f.maturedCount} scored · {f.excludedCount} excluded · {f.pendingCount} pending.</strong> Latest issue {month(f.latestReceipt?.issueDate??null)}.</p>:<p>The first eligible monthly record is awaiting capture.</p>}
    </section>
  </article>;
}
