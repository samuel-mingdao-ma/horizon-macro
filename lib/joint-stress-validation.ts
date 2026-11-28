import type { MacroSnapshot } from './live-data';

type Row = MacroSnapshot;
type Risk = number | null;
const radii = [0, 3, 5];
const unit = 1e12;
const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const close = (a: unknown, b: Risk) => b === null ? a === null : typeof a === 'number' && Math.abs(a-b) < 1e-9;
function requireValue(test: unknown, message: string): asserts test {
  if (!test) throw new Error('Joint yield stress ' + message);
}

// Convert the four risks back to their logistic signal components. This cross-check
// uses the published risk path independently from the Python feature-vector replay.
function reprice(p: Risk, fit: Row | null, spreadBp: number): Risk {
  if (p === null || !fit) return null;
  if (spreadBp === 0) return p;
  const signal = 2*p - fit.trainingPrevalence;
  const i = fit.featureOrder.indexOf('slope');
  const oddsMultiplier = Math.exp(fit.coefficients[i] / fit.scales[i] * spreadBp / 100);
  return (fit.trainingPrevalence + signal * oddsMultiplier / (1-signal + signal * oddsMultiplier)) / 2;
}
function range(a: Risk, b: Risk) {
  return a === null || b === null ? [null, null] : [Math.min(a,b), Math.max(a,b)];
}
function difference(a: Risk, b: Risk) {
  return a === null || b === null ? null : (Math.round(a*unit) - Math.round(b*unit)) / unit;
}
function checkPair(found: unknown, expected: Risk[], label: string) {
  requireValue(Array.isArray(found) && found.length === 2 && expected.every((n,i) => close(found[i],n)), label);
}
function checkIssue(row: Row, pace: Row, curve: Row, fit: Row | null, live: boolean) {
  const dateKey = live ? 'issueDate' : 'date';
  requireValue(row && [dateKey,'featureDate','refitDate','probability','change1m','change3m','levelAlert',
    ...(live ? ['available','forecastStart','forecastEnd'] : ['commonMature','target','onsetDate'])].every(k => row[k] === pace[k]),
    'changed a forecast vintage, score or matching outcome');
  if (row.probability !== null)
    requireValue(fit?.refitDate === row.refitDate && row.refitDate <= row[dateKey], 'lost the as-of model');
  const s = curve.shortChange === null ? null : Math.round(curve.shortChange*unit);
  const l = curve.longChange === null ? null : Math.round(curve.longChange*unit);
  const reference = row.levelAlert === null ? null : row.levelAlert || !!(pace.quarterAlert && s !== null && l !== null &&
    s > 0 && s > l && l <= .05*unit && (l >= -.05*unit || 2*l >= -s));
  requireValue(row.referenceAlert === reference, 'changed the observed 5 bp, 2:1 rule');
  const path = [pace.lag3Probability, pace.lag2Probability, pace.lag1Probability, pace.probability];
  for (const h of radii) {
    const r = row.radii?.[h];
    requireValue(r && typeof r.certified === 'boolean', 'lost a stress radius or certification status');
    const p = path.map(v => range(reprice(v,fit,-2*h),reprice(v,fit,2*h)));
    checkPair(r.probability,p[3],'has an incorrect repriced probability interval');
    checkPair(r.change1m,[difference(p[3][0],p[2][1]),difference(p[3][1],p[2][0])],'has an incorrect one-month change');
    checkPair(r.change3m,path.some(v => v === null) ? [null,null] :
      [difference(p[3][0],p[0][1]),difference(p[3][1],p[0][0])],'has an incorrect three-month change');
    const flags = p[3].map(v => v === null ? null : Math.round(v*unit) >= .3*unit);
    requireValue(equal(r.level,flags), 'changed the stressed 30% benchmark');
    for (const [key, actual] of [['alert',reference], ['extra', reference === null ? null : reference && !row.levelAlert]] as const) {
      const pair = r[key];
      requireValue(Array.isArray(pair) && pair.length === 2 && (actual === null ? equal(pair,[null,null]) :
        pair.every(v => typeof v === 'boolean') && (!pair[0] || actual) && (pair[1] || !actual) &&
        (h > 0 || equal(pair,[actual,actual]))), 'has inconsistent decision bounds');
    }
  }
}
function checkWindow(w: Row, parent: Row, history: Row[], models: Map<string,Row>) {
  requireValue(w && ['windowStart','windowEnd','n','quietExpansionN','preOnsetN'].every(k => w[k] === parent[k]) &&
    w.originalQuiet === parent.levelQuiet && close(w.originalBrier,parent.probabilityScores.brier) &&
    close(w.originalLogLoss,parent.probabilityScores.logLoss), 'changed the baseline window');
  const rows = history.filter(r => r.commonMature && r.date >= w.windowStart && r.date <= w.windowEnd);
  const quiet = rows.filter(r => r.target === 0);
  requireValue(rows.length === w.n && quiet.length === w.quietExpansionN, 'has a mismatched scored population');
  for (const h of radii) {
    const s = w.radii?.[h];
    requireValue(s && s.unresolvedN === rows.filter(r => !r.radii[h].certified).length, 'changed the unresolved count');
    const brier = [0,0], loss = [0,0], coherentBrier = [0,0], coherentLogLoss = [0,0];
    for (const row of rows) {
      const path = row.radii[h].probability;
      const fit = models.get(row.refitDate)!;
      const y: number = row.target;
      for (const j of [0,1]) {
        const p = path[y === 1 ? 1-j : j];
        const coherent = reprice(row.probability,fit,2*h*(j === 0 ? -1 : 1))!;
        brier[j] += (p-y)**2;
        loss[j] -= Math.log(y === 1 ? p : 1-p);
        coherentBrier[j] += (coherent-y)**2;
        coherentLogLoss[j] -= Math.log(y === 1 ? coherent : 1-coherent);
      }
    }
    for (const [key, totals] of Object.entries({brier,logLoss:loss,coherentBrier,coherentLogLoss}))
      checkPair(s[key],totals.map(n => n / rows.length),'has an incorrect ' + key + ' score');
    for (const k of ['level','alert','extra']) {
      const expected = [0,1].map(j => quiet.filter(r => r.radii[h][k][j]).length);
      requireValue(equal(s[k+'Quiet'],expected), 'changed the paired quiet-month counts');
    }
    requireValue(equal(s.extraQuietDates,quiet.filter(r => r.radii[h].extra[1]).map(r => r.date)),
      'changed the additional quiet months');
    requireValue(s.episodes?.length === parent.episodes.length, 'changed recession coverage');
    parent.episodes.forEach((ep: Row, i: number) => {
      const cohort = rows.filter(r => r.target === 1 && r.onsetDate === ep.onsetDate);
      const e = s.episodes[i];
      requireValue(e.onsetDate === ep.onsetDate && e.coverage === ep.coverage && e.originalLevelLead === ep.levelLead,
        'changed an episode or its observed lead');
      const month = (d: string) => Number(d.slice(0,4))*12 + Number(d.slice(5,7));
      for (const k of ['level','alert']) {
        const leads = [0,1].map(j => {
          const first = cohort.find(r => r.radii[h][k][j]);
          return first ? month(ep.onsetDate)-month(first.date) : null;
        });
        requireValue(equal(e[k+'Lead'],leads), 'changed a stressed lead time');
      }
    });
  }
}
function moveMonth(date: string, offset: number) {
  const d = new Date(date);
  d.setUTCMonth(d.getUTCMonth() + offset);
  return d.toISOString().slice(0,10);
}
function scenario(pace: Row, curve: Row, fit: Row | null, shocks: number[][]) {
  const path = [pace.lag3Probability,pace.lag2Probability,pace.lag1Probability,pace.probability]
    .map((p,i) => reprice(p,fit,shocks[i][1]-shocks[i][0]));
  const k = path.map(v => v === null ? null : Math.round(v*unit));
  const [start,middle,previous,end] = k;
  const level = end === null ? null : end >= .3*unit;
  const three = start !== null && middle !== null && previous !== null && end !== null;
  const quarter = level === null || end === null ? null : level || three && end >= .2*unit && end > previous &&
    end > start && 2*end-start >= .3*unit;
  const bill = curve.shortChange === null ? null : Math.round((curve.shortChange+(shocks[3][0]-shocks[0][0])/100)*unit);
  const ten = curve.longChange === null ? null : Math.round((curve.longChange+(shocks[3][1]-shocks[0][1])/100)*unit);
  const ok = bill !== null && ten !== null && bill > 0 && bill > ten && ten <= .05*unit && (ten >= -.05*unit || 2*ten >= -bill);
  return {path, probability:path[3], levelAlert:level, quarterAlert:quarter, referenceAlert:level === null ? null : level || (quarter && ok),
    change1m:difference(path[3],path[2]), change3m:three ? difference(path[3],path[0]) : null,
    shortChangeBp:bill === null ? null : bill / 1e10, longChangeBp:ten === null ? null : ten / 1e10};
}
function validateExamples(row: Row, pace: Row, curve: Row, fit: Row | null) {
  for (const h of radii) {
    const r = row.radii[h], witnesses = r.witnesses;
    requireValue(witnesses && ['on','off','extra'].every(k => Object.prototype.hasOwnProperty.call(witnesses,k)), 'lost its example paths');
    for (const [name, raw] of Object.entries(witnesses)) {
      const w = raw as Row | null;
      if (!w) {
        if (r.certified && row.probability !== null && ['on','extra','off'].includes(name))
          requireValue(name === 'on' ? !r.alert[1] : name === 'extra' ? !r.extra[1] : r.alert[0], 'lost a feasible example');
        continue;
      }
      requireValue(Array.isArray(w.shocksBp) && w.shocksBp.length === 4 &&
        w.shocksBp.every((p: unknown) => Array.isArray(p) && p.length === 2 && p.every(v => Number.isFinite(v) && Math.abs(v)<=h)),
        'shows an inadmissible example');
      const v = scenario(pace,curve,fit,w.shocksBp);
      requireValue(Array.isArray(w.path) && w.path.length === 4 && v.path.every((p,i) => close(w.path[i],p)) &&
        (['levelAlert','quarterAlert','referenceAlert'] as const).every(k => w[k] === v[k]) &&
        (['probability','change1m','change3m','shortChangeBp','longChangeBp'] as const).every(k => close(w[k],v[k])) &&
        (name === 'off' ? v.referenceAlert === false : name === 'on' ? v.referenceAlert === true :
          name !== 'extra' || v.referenceAlert === true && v.levelAlert === false), 'shows an inconsistent example');
    }
  }
}
function checkCalendarPaths(trial: Row, pace: Row, stability: Row, models: Map<string,Row>, previous: Row) {
  for (const id of ['february2019','may2000']) {
    const c = trial.calendarPaths?.[id], registered = previous.calendarPaths?.[id];
    requireValue(c && registered && c.date === registered.date && c.radiusBp === registered.radiusBp &&
      equal(c.shocks,registered.shocks), 'changed its registered calendar examples');
    const moves = new Map<string,number[]>(c.shocks.map((x: Row) => [x.date,[x.shortBp,x.longBp]]));
    const replay = pace.history.map((r: Row,i: number) => {
      const shocks = [-5,-4,-3,-2].map(lag => moves.get(moveMonth(r.date,lag)) ?? [0,0]);
      return {...r, ...scenario(r,stability.history[i],models.get(r.refitDate) ?? null,shocks)};
    });
    const example = replay.find((r: Row) => r.date === c.date);
    requireValue(example && close(c.caseRisk,example.probability) && close(c.change1m,example.change1m) &&
      close(c.change3m,example.change3m) && c.caseAlert === example.referenceAlert && c.caseLevelAlert === example.levelAlert,
      'changed the case on its fixed calendar path');
    const onset = '2001-04-01';
    const first = replay.find((r: Row) => r.commonMature && r.onsetDate === onset && r.target === 1 && r.referenceAlert);
    requireValue(first ? Number.isInteger(c.lead2001) && moveMonth(first.date,c.lead2001) === onset : c.lead2001 === null,
      'changed the calendar example lead');
    for (const window of ['all','rolling120']) {
      const w = trial.windows[window], v = c.windows?.[window];
      const paired: Row[] = replay.filter((r: Row) => r.commonMature && r.date >= w.windowStart && r.date <= w.windowEnd);
      const quiet = paired.filter(r => r.target === 0);
      const extra = quiet.filter(r => r.referenceAlert && !r.levelAlert).map(r => r.date);
      requireValue(v && v.alertQuiet === quiet.filter(r => r.referenceAlert).length &&
        v.levelQuiet === quiet.filter(r => r.levelAlert).length && equal(v.extraDates,extra) &&
        (window !== 'all' || equal(c.extraDates,extra)) &&
        close(v.brier,paired.reduce((t,r) => t+(r.target-r.probability)**2,0)/paired.length) &&
        close(v.logLoss,paired.reduce((t,r) => t-Math.log(r.target ? r.probability : 1-r.probability),0)/paired.length),
        'changed its coherent calendar counts or scores');
    }
  }
}
export function validateJointStress(trial: Row, expansion: Row, pace: Row, stability: Row, previous: Row) {
  const spec = trial?.spec;
  requireValue(spec?.id === previous.spec.id && spec.parentId === stability.spec.id && equal(spec.radiiBp,radii) &&
    spec.bandBp === 5 && spec.ratio === 2 && spec.threshold === .3 && spec.floor === .2,
    'changed the registered sensitivity design');
  const models = new Map<string,Row>(expansion.folds.map((f: Row) => [f.refitDate,f.models.candidate]));
  const history: Row[] = trial.history;
  requireValue(Array.isArray(history) && history.length === pace.history.length, 'lost the historical forecast path');
  history.forEach((row,i) => checkIssue(row,pace.history[i],stability.history[i],models.get(row.refitDate) ?? null,false));
  checkIssue(trial.latest,pace.latest,stability.latest,expansion.currentModel,true);
  validateExamples(trial.latest,pace.latest,stability.latest,expansion.currentModel);
  for (const d of ['2000-05-01','2019-02-01']) {
    const i = history.findIndex(r => r.date === d), r = history[i], c = trial.cases?.[d];
    if (!r) { requireValue(c === null,'references a missing case'); continue; }
    requireValue(c?.date === d && c.probability === r.probability && c.referenceAlert === r.referenceAlert, 'changed a case origin');
    validateExamples(c,pace.history[i],stability.history[i],models.get(r.refitDate) ?? null);
    for (const h of radii) for (const k of ['probability','change1m','change3m','level','alert','extra','certified'])
      requireValue(equal(c.radii[h][k],r.radii[h][k]), 'changed a case interval');
  }
  checkCalendarPaths(trial,pace,stability,models,previous);
  for (const window of ['all','rolling120']) checkWindow(trial.windows?.[window],stability.windows[window],history,models);
}
