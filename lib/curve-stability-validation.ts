import type { MacroSnapshot } from './live-data';

const bands = [0,2,5,10], ratios = [1.5,1.75,2,2.25,2.5], modes = ['actual','guaranteed','possible'] as const;
const caseDate = '2000-05-01', caseOnset = '2001-04-01', bpUnit = 1e10;
const sameList = (a: unknown,b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const fail = (reason: string): never => { throw new Error('Curve stability ' + reason); };

function decision(row: MacroSnapshot, band: number, ratio: number) {
  const short = row.shortChange === null ? null : Math.round(row.shortChange * 1e12);
  const long = row.longChange === null ? null : Math.round(row.longChange * 1e12);
  const hasRange = short !== null && short > 0;
  // Multiplication by four makes every ratio an integer at the registered grid points.
  const num = 4 * ratio;
  const lo = -Math.max(band * bpUnit * num,(short ?? 0) * 4);
  const hi = Math.min(band * bpUnit,short ?? 0) * num;
  const inclusive = hasRange ? band * bpUnit < short : null;
  const below = (x: number) => inclusive ? x <= hi : x < hi;
  const inside = (x: number) => x >= lo && below(x);
  const applies = hasRange && long !== null;
  const centre = (long ?? 0) * num, left = centre - 3 * bpUnit * num, right = centre + 3 * bpUnit * num;
  const alarm = (test: boolean) => row.levelAlert === null ? null : Boolean(row.levelAlert || row.quarterAlert && applies && test);
  return {
    actual:alarm(inside(centre)), minus3:alarm(inside(left)), plus3:alarm(inside(right)),
    guaranteed:alarm(inside(left) && inside(right)), possible:alarm(right >= lo && below(left)),
    lowerBp:hasRange ? lo/(num * bpUnit) : null, upperBp:hasRange ? hi/(num * bpUnit) : null, upperInclusive:inclusive,
  };
}

function checkResult(expected: ReturnType<typeof decision>, actual: MacroSnapshot) {
  if (!actual || !Object.entries(expected).every(([k,v]) => actual[k] === v ||
      (typeof v === 'number' && typeof actual[k] === 'number' && Math.abs(actual[k]-v) < 1e-9)))
    fail('decisions or long-yield interval disagree with the frozen rule');
}

function leadMonths(onset: string,first: string|null) {
  const index = (d: string) => Number(d.slice(0,4))*12 + Number(d.slice(5,7));
  return first ? index(onset)-index(first) : null;
}

export function validateCurveStability(trial: MacroSnapshot, parent: MacroSnapshot, previous: MacroSnapshot) {
  const spec = trial?.spec, live = trial?.latest;
  if (!live || !parent || spec?.id !== previous.spec.id || spec.parentId !== parent.spec.id || spec.stressBp !== 3
    || spec.referenceId !== 'd5-r2' || spec.originalId !== 'd0-r2' || !sameList(spec.bandsBp,bands) || !sameList(spec.ratios,ratios)
    || !Array.isArray(trial.cells) || trial.cells.length !== bands.length*ratios.length
    || !Array.isArray(trial.history) || trial.history.length !== parent.history.length) fail('has an incomplete or changed design');
  const inputs = ['featureDate','lagFeatureDate','probability','shortChange','longChange','levelAlert','quarterAlert','mixedTwoToOneAlert'];
  if (![...inputs,'issueDate','refitDate','forecastStart','forecastEnd','available'].every(k => live[k] === parent.latest[k]))
    fail('changed the current parent forecast or its rates');
  const history: MacroSnapshot[] = trial.history;
  const copied = [...inputs,'date','commonMature','issuePhase','target','onsetDate'];
  if (history.some((r,i) => !copied.every(k => r[k] === parent.history[i][k]))) fail('changed the dated evaluation cohort');
  const may = history.find(r => r.date === caseDate);
  const cells = new Map(trial.cells.map((c: MacroSnapshot) => [c.id,c] as const));
  for (const band of bands) for (const ratio of ratios) {
    const id = 'd'+band+'-r'+ratio, cell = cells.get(id) as MacroSnapshot|undefined;
    if (!cell || cell.ratio !== ratio || cell.bandBp !== band) throw new Error('Curve stability grid is missing ' + id);
    checkResult(decision(live,band,ratio),live.results?.[id]);
    for (const d of [caseDate,'2019-02-01']) {
      const row = history.find(r => r.date === d);
      if (row) checkResult(decision(row,band,ratio),cell.cases?.[d]);
      else if (cell.cases?.[d] !== null) fail('uses a missing case');
    }
    const verdicts = {pointPassed:true,stressPassed:true};
    for (const name of ['all','rolling120']) {
      const w = trial.windows?.[name], p = parent.windows[name], v = cell.windows?.[name];
      if (!v || !w || !['windowStart','windowEnd','n','quietExpansionN','preOnsetN','completeEpisodes'].every(k => w[k] === p[k])
        || !['brier','logLoss','auc'].every(k => w.probabilityScores?.[k] === p.probabilityScores[k])
        || w.levelQuiet !== p.summary.level.quietAlerts || w.levelPre !== p.summary.level.preOnsetAlerts || w.levelHits !== p.summary.level.completeHits
        || !Array.isArray(w.episodes) || w.episodes.length !== p.episodes.length
        || !Array.isArray(v.episodes) || v.episodes.length !== w.episodes.length) fail('changed baseline counts or probability scores');
      const paired = history.filter(r => r.commonMature && w.windowStart <= r.date && r.date <= w.windowEnd);
      const extras = paired.filter(r => r.quarterAlert && !r.levelAlert).map(row => ({row,flags:decision(row,band,ratio)}));
      for (const mode of modes) {
        const alerted = new Set(extras.filter(x => x.flags[mode]).map(x => x.row.date));
        for (const [suffix,y] of [['QuietDates',0],['PreDates',1]] as const) {
          const dates = paired.filter(r => r.target === y && alerted.has(r.date)).map(r => r.date);
          if (!sameList(v[mode+suffix],dates)) fail('extra months disagree with their outcomes and decision intervals');
        }
        w.episodes.forEach((ep: MacroSnapshot,i: number) => {
          const e = v.episodes[i], baseEp = p.episodes[i];
          const first = paired.find(r => r.onsetDate === ep.onsetDate && (r.levelAlert || alerted.has(r.date)))?.date ?? null;
          if (!e || !['onsetDate','coverage','availableMonths'].every(k => ep[k] === baseEp[k]) || e.onsetDate !== ep.onsetDate
            || ep.levelFirstDate !== baseEp.methods.level.firstAlertDate || ep.levelLead !== baseEp.methods.level.leadMonths
            || e[mode+'FirstDate'] !== first || e[mode+'Lead'] !== leadMonths(e.onsetDate,first)) fail('episode timing disagrees with monthly decisions');
        });
      }
      const event = w.episodes.findIndex((ep: MacroSnapshot) => ep.onsetDate === caseOnset && ep.coverage === 'full');
      for (const [verdict,hit,quiet] of [['pointPassed','actual','actual'],['stressPassed','guaranteed','possible']] as const) {
        if (!w.quietExpansionN || !w.completeEpisodes || v[quiet+'QuietDates'].length ||
          (name === 'all' && (event < 0 || !may?.commonMature || may.onsetDate !== caseOnset || may.levelAlert || !may.quarterAlert
          || !cell.cases[caseDate]?.[hit] || v.episodes[event][hit+'Lead'] < 11 || v.episodes[event][hit+'Lead'] <= w.episodes[event].levelLead)))
          verdicts[verdict] = false;
      }
    }
    if (cell.pointPassed !== verdicts.pointPassed || cell.stressPassed !== verdicts.stressPassed) fail('has an inconsistent pass decision');
  }
  const a = trial.prospective;
  if (a || previous.prospective?.receiptCount) {
    if (!a?.chainValid || !Array.isArray(a.receipts) || a.receiptCount !== a.receipts.length
      || ![a.pendingCount,a.maturedCount,a.excludedCount].every(n => Number.isInteger(n) && n >= 0)
      || a.receiptCount !== a.pendingCount + a.maturedCount + a.excludedCount
      || previous.prospective?.receipts?.some((r: MacroSnapshot,i: number) => r.hash !== a.receipts[i]?.hash))
      fail('has missing or regressive prospective records');
  }
}
