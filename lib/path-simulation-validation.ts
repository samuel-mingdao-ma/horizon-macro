import type { MacroSnapshot } from './live-data';

type Row = MacroSnapshot;
const windows = ['all','rolling120'] as const;
const designs: Record<string,[number|null,number]> = {empirical:[null,6],cap3:[3,6],cap5:[5,6],iid:[null,1]};
const close = (x: number, y: number, tolerance = 2e-10) => Number.isFinite(x) && Math.abs(x-y) <= tolerance;
function check(value: unknown, reason: string): asserts value {
  if (!value) throw new Error('Yield path simulation ' + reason);
}
function rate(value: Row, n: number) {
  check(value?.n === n && Number.isInteger(value.passed) && value.passed >= 0 && value.passed <= n &&
    close(value.rate,value.passed/n), 'has an invalid trial count or rate');
  const z = 1.959963984540054, p = value.passed/n, denom = 1+z*z/n;
  const center = (p+z*z/(2*n))/denom, half = z*Math.sqrt(p*(1-p)/n+z*z/(4*n*n))/denom;
  check(value.interval?.length === 2 && close(value.interval[0],Math.max(0,center-half),2e-6) &&
    close(value.interval[1],Math.min(1,center+half),2e-6), 'has a mismatched simulation interval');
}
function quantiles(nums: unknown, lo: number, hi: number) {
  check(Array.isArray(nums) && nums.length===3 && nums.every(n => Number.isFinite(n) && n >= lo && n <= hi) &&
    nums[0] <= nums[1] && nums[1] <= nums[2], 'has invalid simulated quantiles');
}
function nextMonth(date: string, step: number) {
  const d = new Date(date);
  d.setUTCMonth(d.getUTCMonth()+step);
  return d.toISOString().slice(0,10);
}
function validateGateCounts(s: Row) {
  const g = s.gates, n = s.draws;
  for (const key of ['lead','brierBoth','logLossBoth','quietMatched','quietObserved','quietBoth','joint','jointStrict',
    'jointMatched','jointObserved','brierAll','brierRecent','quietAll','quietRecent','mayAlert','febAlert','mayExtra','febExtra']) rate(g?.[key],n);
  for (const [name,left,right] of [
    ['brierBoth','brierAll','brierRecent'], ['quietBoth','quietAll','quietRecent'], ['quietBoth','quietMatched','quietObserved'],
    ['joint','jointMatched','jointObserved'], ['jointStrict','joint','logLossBoth'],
  ]) {
    const a = g[left].passed, b = g[right].passed;
    check(g[name].passed <= Math.min(a,b) && g[name].passed >= Math.max(0,a+b-n), 'has inconsistent joint counts');
  }
  check(g.mayExtra.passed<=g.mayAlert.passed && g.febExtra.passed<=g.febAlert.passed && g.lead.passed <= g.mayAlert.passed && g.joint.passed <= Math.min(g.lead.passed,g.brierBoth.passed,g.quietBoth.passed),
    'uses incompatible warning and score decisions');
  const stages = ['allPaths','lead','brierBoth','quietBoth','jointStrict'];
  check(s.funnel?.length === stages.length && s.funnel.every((v: Row,i: number) => v.gate === stages[i] &&
    Number.isInteger(v.count) && v.count >= 0 && v.count <= (i ? s.funnel[i-1].count : n)) &&
    s.funnel[0].count === n && s.funnel[1].count === g.lead.passed && s.funnel[2].count <= g.brierBoth.passed &&
    s.funnel[3].count === g.joint.passed && s.funnel[4].count === g.jointStrict.passed, 'lost the same-path funnel');
  check(Array.isArray(s.leadHistogram) && s.leadHistogram.every((h: Row) =>
    (h.lead === null || Number.isInteger(h.lead) && h.lead >= 1 && h.lead <= 12) && Number.isInteger(h.count) && h.count>=0) &&
    s.leadHistogram.reduce((a: number,h: Row) => a+h.count,0) === n,'has an inconsistent lead distribution');
}
function validateExamples(s: Row, baseline: Row) {
  check(Array.isArray(s.examples) && s.examples.length>0,'lost its example paths');
  for (const e of s.examples) {
    check(Number.isInteger(e.draw) && e.draw>=1 && e.draw<=s.draws, 'has an unknown example path');
    let eligible = e.mayAlert && e.lead2001>=11 && e.lead2001>(e.levelLead2001 ?? 0);
    for (const w of windows) {
      const m = e[w], b = baseline[w];
      check(Number.isInteger(m?.ruleQuiet) && Number.isInteger(m.levelQuiet) && m.ruleQuiet>=m.levelQuiet &&
        m.ruleQuiet<=b.quietN && m.levelQuiet>=0 && Number.isFinite(m.brier) && m.brier>=0 && m.brier<=1 &&
        Number.isFinite(m.logLoss) && m.logLoss>=0, 'has invalid example outcomes');
      eligible = eligible && m.brier<=b.brier+1e-12 && m.ruleQuiet<=Math.min(b.quietAlerts,m.levelQuiet);
    }
    check(Boolean(eligible) === e.passed, 'mislabels an example path');
    for (const [field,date] of [['mayPath','2000-05-01'],['febPath','2019-02-01']]) {
      check(e[field]?.length===4 && e[field].every((p: Row,i: number) => p.date===nextMonth(date,i-5) &&
        [p.longBp,p.shortBp].every((v: number) => Number.isFinite(v) && (s.capBp===null || Math.abs(v)<=s.capBp))),
        'changed the dates or magnitude of a case shock');
    }
  }
}
export function validatePathSimulation(t: Row, parent: Row, previous: Row) {
  const spec = t?.spec, base = t?.baseline;
  check(spec?.id === previous.spec.id && spec.parentId === parent.spec.id && spec.seed===5342001 && spec.draws===20000 &&
    spec.primary==='empirical' && spec.bandBp===5 && spec.ratio===2 && spec.threshold===.3 && spec.blockMonths===6,
    'changed its registered design');
  check(t.latest && ['issueDate','featureDate','forecastStart','forecastEnd','refitDate','available','probability']
    .every(k=>t.latest[k]===parent.latest[k]), 'changed its live forecast vintage');
  for (const k of windows) {
    const w = parent.windows[k], b = base?.[k];
    check(b && b.n===w.n && b.quietN===w.quietExpansionN && b.quietAlerts===w.originalQuiet && b.windowStart===w.windowStart &&
      b.windowEnd===w.windowEnd && close(b.brier,w.originalBrier) && close(b.logLoss,w.originalLogLoss),'changed the scored baseline');
  }
  const original = parent.windows.all.radii['0'].episodes.find((e: Row)=>e.onsetDate==='2001-04-01');
  check(original && base.levelLead2001===original.originalLevelLead && base.ruleLead2001===original.alertLead[0],
    'changed the observed lead');
  const c = t.calibration, source = c?.source;
  check(source?.series?.join(',') === 'DTB3,DGS10' && source.dailyStart < source.dailyEnd && source.donorEnd<=source.dailyEnd &&
    Number.isInteger(source.pairedDays) && Number.isInteger(source.donorMonths) && source.pairedDays>=source.donorMonths,
    'lost historical Treasury source coverage');
  for (const [name,cutoff] of [['first',spec.observationStart],['may2000','2000-03-01'],['latest',t.latest.featureDate]]) {
    const p = c[name];
    check(p && p.cutoff===cutoff && p.start<=p.end && p.end<p.cutoff && p.n>=6 && p.n<=source.donorMonths &&
      Number.isFinite(p.shortSdBp) && p.shortSdBp>0 && Number.isFinite(p.longSdBp) && p.longSdBp>0 &&
      Math.abs(p.correlation)<=1 && close(p.covarianceBp2,p.correlation*p.shortSdBp*p.longSdBp,1e-8) &&
      p.within3>=0 && p.within3<=p.within5 && p.within5<=1, 'changed its chronological calibration');
  }
  check(Array.isArray(t.scenarios) && t.scenarios.length===4 && new Set(t.scenarios.map((s: Row)=>s.id)).size===4,
    'lost a sensitivity scenario');
  for (const s of t.scenarios) {
    const design = designs[s.id];
    check(design && s.capBp===design[0] && s.blockMonths===design[1] && s.draws===spec.draws, 'changed a sampling scenario');
    validateGateCounts(s);
    validateExamples(s,base);
    for (const k of windows) {
      const b=base[k], w=s.windows?.[k];
      check(w,'lost period statistics');
      for (const m of ['levelQuiet','ruleQuiet','extraQuiet']) quantiles(w[m],0,b.quietN);
      for (const m of ['brier','logLoss']) {
        quantiles(w[m],0,m==='brier'?1:Infinity);
        quantiles(w[m+'Delta'],-Infinity,Infinity);
        check(w[m].every((v:number,i:number)=>close(v-b[m],w[m+'Delta'][i])), 'has an incorrect proper-score difference');
      }
    }
    if (t.latest.available) {
      quantiles(s.latest?.probability,0,1);
      rate(s.latest.warning,s.draws);
    } else check(s.latest===null,'retains a simulation for an unavailable current forecast');
  }
}
