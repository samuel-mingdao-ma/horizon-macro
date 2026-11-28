import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import { parseFredCsv, monthlyMean, monthOffset, featureVector, score, refreshSnapshot } from '../lib/live-data.ts';

const snapshot = JSON.parse(await readFile(new URL('../data/snapshot.json', import.meta.url), 'utf8'));
const rawIds = ['GS10', 'TB3MS', 'NFCICREDIT', 'UNRATE', 'CPIAUCSL', 'FEDFUNDS', 'GS1', 'GS2', 'GS5', 'GS30'];
const rows = Object.fromEntries(await Promise.all(rawIds.map(async id => {
  const csv = await readFile(new URL(`../research/raw/${id}.csv`, import.meta.url), 'utf8');
  return [id, parseFredCsv(csv)];
})));

test('calendar offsets and monthly averaging preserve observation-month semantics', () => {
  assert.equal(monthOffset('2026-01-01', -2), '2025-11-01');
  assert.deepEqual([...monthlyMean([{ date: '2026-01-02', value: 1 }, { date: '2026-01-09', value: 3 }, { date: '2026-02-01', value: 10 }], '2026-02-01')], [['2026-01-01', 2]]);
  assert.deepEqual(parseFredCsv('observation_date,X\n2020-01-01,.\n2020-02-01,0\n'), [{ date: '2020-02-01', value: 0 }]);
});

test('browser-compatible feature and score calculation reproduces Python snapshot', () => {
  const maps = Object.fromEntries(Object.entries(rows).map(([id, data]) => [id, monthlyMean(data, monthOffset(snapshot.latest.issueDate, 1))]));
  const features = featureVector(maps, snapshot.latest.featureDate);
  for (const key of snapshot.model.featureOrder) assert.ok(Math.abs(features[key] - snapshot.latest.features[key]) < 1e-8, `feature ${key}`);
  const result = score(features, snapshot.model);
  assert.ok(Math.abs(result.probability - snapshot.latest.probability) < 1e-8, 'model score parity');
  const rawLogit = snapshot.model.rawIntercept + snapshot.model.featureOrder.reduce((sum, key, i) => sum + snapshot.model.rawCoefficients[i] * features[key], 0);
  assert.ok(Math.abs(1 / (1 + Math.exp(-rawLogit)) - result.probability) < 1e-8, 'raw and standardized scoring parity');
});

test('live inference preserves research metrics and complete aligned dates', async () => {
  const result = await refreshSnapshot(snapshot, new Date(snapshot.latest.issueDate + 'T12:00:00Z'), async id => rows[id]);
  assert.equal(result.latest.featureDate, snapshot.latest.featureDate);
  assert.ok(Math.abs(result.latest.probability - snapshot.latest.probability) < 1e-8);
  assert.deepEqual(result.metrics, snapshot.metrics);
  assert.deepEqual(result.history, snapshot.history);
  assert.equal(result.meta.refresh.status, 'fresh');
});

test('incomplete provider data cannot produce a live forecast', async () => {
  await assert.rejects(refreshSnapshot(snapshot, new Date(snapshot.latest.issueDate + 'T12:00:00Z'), async id => {
    if (id === 'UNRATE') throw new Error('offline');
    return rows[id];
  }));
});


test('new issue months extend the live history without rewriting the evaluated backtest', async () => {
  const nextIssue = monthOffset(snapshot.latest.issueDate, 1);
  const neededFeatureMonth = monthOffset(nextIssue, -2);
  // Simulate the next release even when a real run occurs before that release.
  const releasedRows = Object.fromEntries(Object.entries(rows).map(([id, data]) => {
    const exists = data.some(row => row.date.slice(0, 7) === neededFeatureMonth.slice(0, 7));
    return [id, exists ? data : [...data, { date: neededFeatureMonth, value: data.at(-1).value }]];
  }));
  const result = await refreshSnapshot(snapshot, new Date(nextIssue + 'T12:00:00Z'), async id => releasedRows[id]);
  assert.equal(result.latest.issueDate, nextIssue);
  assert.equal(result.history.at(-1).date, nextIssue);
  assert.equal(result.history.at(-1).forecastType, 'live-fixed-model');
  assert.equal(result.history.at(-1).target, null);
  assert.deepEqual(result.metrics, snapshot.metrics);
  assert.deepEqual(result.history.slice(0, snapshot.history.length), snapshot.history);
});

test('scheduled research snapshot preserves vintage dates and verifies model math', async () => {
  const { refreshResearchSnapshot } = await import('../lib/live-data.ts');
  const now = new Date(snapshot.meta.generatedAt);
  const result = await refreshResearchSnapshot(snapshot, now, async () => Response.json(snapshot));
  assert.equal(result.meta.refresh.source, 'github-actions');
  assert.equal(result.meta.refresh.sourceUpdatedAt, snapshot.meta.generatedAt);
  assert.equal(result.meta.generatedAt, snapshot.meta.generatedAt);
  assert.equal(result.latest.issueDate, snapshot.latest.issueDate);
  const currentMonth = now.toISOString().slice(0, 7) + '-01';
  const expectedDelay = (Number(currentMonth.slice(0, 4)) - Number(snapshot.latest.issueDate.slice(0, 4))) * 12 + Number(currentMonth.slice(5, 7)) - Number(snapshot.latest.issueDate.slice(5, 7));
  assert.equal(result.meta.refresh.inputMonthsBehind, expectedDelay);
});

test('remote builds cannot regress the research vintage or issue future forecasts', async () => {
  const { validateResearchSnapshot } = await import('../lib/live-data.ts');
  const now = new Date(snapshot.meta.generatedAt);
  const older = structuredClone(snapshot);
  older.meta.generatedAt = new Date(now.getTime() - 86_400_000).toISOString();
  assert.throws(() => validateResearchSnapshot(older, snapshot, now), /Stale/);
  const badScore = structuredClone(snapshot);
  badScore.latest.probability += 0.01;
  assert.throws(() => validateResearchSnapshot(badScore, snapshot, now), /probability/);
  const future = structuredClone(snapshot);
  future.latest.issueDate = monthOffset(snapshot.latest.issueDate, 1);
  assert.throws(() => validateResearchSnapshot(future, snapshot, now), /dates/);
  const badModel = structuredClone(snapshot);
  badModel.model.scales[0] = 0;
  assert.throws(() => validateResearchSnapshot(badModel, snapshot, now), /parameters/);
  assert.throws(() => validateResearchSnapshot({ meta: { version: '99' } }, snapshot, now), /version/);
});


test('research fetches bypass stale branch CDN entries while keeping canonical provenance', async () => {
  const { refreshResearchSnapshot, RESEARCH_SNAPSHOT_URL } = await import('../lib/live-data.ts');
  const checkedAt = new Date(snapshot.meta.generatedAt);
  const requests = [];
  const loader = async (input, options) => {
    requests.push({ url: new URL(String(input)), options });
    return Response.json(snapshot);
  };
  const first = await refreshResearchSnapshot(snapshot, checkedAt, loader);
  await refreshResearchSnapshot(snapshot, new Date(checkedAt.getTime() + 1000), loader);
  const canonical = new URL(RESEARCH_SNAPSHOT_URL);
  for (const { url, options } of requests) {
    assert.equal(url.origin + url.pathname, canonical.origin + canonical.pathname);
    assert.deepEqual([...url.searchParams.keys()], ['_horizon_refresh']);
    assert.match(url.searchParams.get('_horizon_refresh'), /^\d+$/);
    assert.equal(options.cache, 'no-store');
  }
  assert.equal(requests[0].url.searchParams.get('_horizon_refresh'), String(checkedAt.getTime()));
  assert.notEqual(requests[0].url.href, requests[1].url.href);
  assert.equal(first.meta.refresh.sourceUrl, RESEARCH_SNAPSHOT_URL);
});


test('new research builds retain a mathematically consistent alarm audit', async () => {
  const {validateResearchSnapshot}=await import('../lib/live-data.ts');
  if(!snapshot.innovation) return;
  const now=new Date(snapshot.meta.generatedAt);
  const missing=structuredClone(snapshot);delete missing.innovation;
  assert.throws(()=>validateResearchSnapshot(missing,snapshot,now),/alarm audit/);
  const wrongInteraction=structuredClone(snapshot);wrongInteraction.innovation.latest.features.interaction+=1;
  assert.throws(()=>validateResearchSnapshot(wrongInteraction,snapshot,now),/interaction/);
  const wrongScore=structuredClone(snapshot);wrongScore.innovation.latest.probability+=.01;
  assert.throws(()=>validateResearchSnapshot(wrongScore,snapshot,now),/probability/);
});

test('research refresh cannot drop or regress its prospective archive',async()=>{
  const {validateResearchSnapshot}=await import('../lib/live-data.ts');
  if(!snapshot.prospective)return;
  const now=new Date(snapshot.meta.generatedAt);
  const missing=structuredClone(snapshot);delete missing.prospective;
  assert.throws(()=>validateResearchSnapshot(missing,snapshot,now),/forecast archive/);
  const future=structuredClone(snapshot);future.prospective.latestReceipt.issueDate=monthOffset(snapshot.latest.issueDate,1);
  assert.throws(()=>validateResearchSnapshot(future,snapshot,now),/forecast archive/);
  const badHash=structuredClone(snapshot);badHash.prospective.lastHash='a'.repeat(64);
  assert.throws(()=>validateResearchSnapshot(badHash,snapshot,now),/forecast archive/);
});

test('refreshes retain the new trial and verify each published blend formula', async () => {
  const {validateResearchSnapshot} = await import('../lib/live-data.ts');
  const now = new Date(snapshot.meta.generatedAt);
  const missing = structuredClone(snapshot);
  delete missing.ratePath;
  assert.throws(() => validateResearchSnapshot(missing, snapshot, now), /rate-path research/);
  const corrupt = structuredClone(snapshot);
  corrupt.ratePath.latest.recentBlendProbability = corrupt.ratePath.latest.recentBlendProbability === 1 ? 0 : 1;
  assert.throws(() => validateResearchSnapshot(corrupt, snapshot, now), /recent-base research/);
  const empty = structuredClone(snapshot);
  empty.ratePath.prospective = {chainValid: true, receiptCount: 0, receipts: []};
  if (snapshot.ratePath.prospective?.receiptCount > 0)
    assert.throws(() => validateResearchSnapshot(empty, snapshot, now), /record missing or regressive/);
});

test('remote updates preserve regime records and reproduce the conditional and adaptive probabilities', async () => {
  const {validateResearchSnapshot} = await import('../lib/live-data.ts');
  const now = new Date(snapshot.meta.generatedAt);
  const missing = structuredClone(snapshot);
  delete missing.regimePrior;
  assert.throws(() => validateResearchSnapshot(missing, snapshot, now), /regime research/);
  for (const key of ['state', 'dynamicPriorProbability', 'adaptiveProbability']) {
    const wrong = structuredClone(snapshot);
    wrong.regimePrior.latest[key] = key === 'state' ? 'unknown' : null;
    assert.throws(() => validateResearchSnapshot(wrong, snapshot, now), /regime forecast/);
  }
  if (snapshot.regimePrior.prospective?.receiptCount) {
    const truncated = structuredClone(snapshot);
    truncated.regimePrior.prospective.receipts = [];
    assert.throws(() => validateResearchSnapshot(truncated, snapshot, now), /Regime forecast record/);
  }
});

test('leading-indicator refresh preserves both the current comparisons and their common outcome months', async () => {
  const {validateResearchSnapshot} = await import('../lib/live-data.ts');
  const now = new Date(snapshot.meta.generatedAt);
  for (const change of [
    data => {delete data.leadingTrial;},
    data => {data.leadingTrial.diagnostics.windows.all.n += 1;},
    data => {data.leadingTrial.latest.existingBlendProbability = null;},
  ]) {
    const changed = structuredClone(snapshot);
    change(changed);
    assert.throws(() => validateResearchSnapshot(changed, snapshot, now), /leading-indicator/i);
  }
  if (snapshot.leadingTrial.latest.available) {
    const changed = structuredClone(snapshot);
    changed.leadingTrial.latest.permitsBlendProbability = null;
    assert.throws(() => validateResearchSnapshot(changed, snapshot, now), /leading-indicator forecast/);
    const unavailable = structuredClone(snapshot);
    Object.assign(unavailable.leadingTrial.latest, {
      available:false,probability:null,matchedThreeBlendProbability:null,permitsBlendProbability:null,
      claimsBlendProbability:null,rawProbability:null,
    });
    if (unavailable.weightTrial) {
      assert.throws(() => validateResearchSnapshot(unavailable, snapshot, now), /adaptive-weight/i);
      Object.assign(unavailable.weightTrial.latest, {
        available:false, rawPermitsProbability:null, fixedPermitsProbability:null, probability:null,
        pooledPermitsProbability:null, fixedRuleProbability:null,
      });
    }
    if (unavailable.creditTrial) {
      Object.assign(unavailable.creditTrial.latest, {available:false,benchmarkProbability:null,
        probability:null,matchedLevelProbability:null,slowOnlyProbability:null,shockOnlyProbability:null});
    }
    if (unavailable.expansionTrial) {
      Object.assign(unavailable.expansionTrial.latest, {available:false, benchmarkProbability:null,
        rawPermitsProbability:null, probability:null, signalOnlyChangeProbability:null, baseOnlyChangeProbability:null});
    }
    if (unavailable.momentumTrial) {
      const c = unavailable.momentumTrial.latest;
      Object.assign(c,{available:false,probability:null,levelAlert:null,quarterAlert:null,monthAlert:null,
        paceAvailable:false,change1m:null,change3m:null});
      c.path[3].probability = null;
    }
    if (unavailable.confirmationTrial) {
      Object.assign(unavailable.confirmationTrial.latest,{available:false,probability:null,change1m:null,change3m:null,
        levelAlert:null,quarterAlert:null,pressureAlert:null,directionAlert:null,breadthAlert:null});
    }
    if (unavailable.curveLegsTrial) {
      Object.assign(unavailable.curveLegsTrial.latest,{available:false,probability:null,change1m:null,change3m:null,levelAlert:null,
        quarterAlert:null,shortLeadAlert:null,bearAlert:null,sustainedAlert:null,mixedTwoToOneAlert:null});
    }
    if (unavailable.curveStabilityTrial) {
      const live = unavailable.curveStabilityTrial.latest;
      Object.assign(live,{available:false,probability:null,levelAlert:null,quarterAlert:null,mixedTwoToOneAlert:null});
      for (const result of Object.values(live.results)) {
        Object.assign(result,{actual:null,guaranteed:null,possible:null,minus3:null,plus3:null});
      }
    }
    assert.doesNotThrow(() => validateResearchSnapshot(unavailable, snapshot, now));
  }
  if (snapshot.leadingTrial.prospective?.receiptCount) {
    const truncated = structuredClone(snapshot);
    truncated.leadingTrial.prospective.receipts = [];
    assert.throws(() => validateResearchSnapshot(truncated, snapshot, now), /record missing or regressive/);
  }
});

test('adaptive weights require consistent forecast components, paired warning dates and archived history', async () => {
  const {validateResearchSnapshot} = await import('../lib/live-data.ts');
  const now = new Date(snapshot.meta.generatedAt);
  const drop = structuredClone(snapshot);
  delete drop.weightTrial;
  assert.throws(() => validateResearchSnapshot(drop,snapshot,now),/adaptive-weight/i);
  if (snapshot.weightTrial.latest.available) {
    for (const field of ['state','probability','permitsWeight','fixedRuleProbability']) {
      const changed = structuredClone(snapshot);
      changed.weightTrial.latest[field]=null;
      assert.throws(() => validateResearchSnapshot(changed,snapshot,now),/Adaptive-weight forecast/);
    }
    const inconsistent = structuredClone(snapshot);
    inconsistent.weightTrial.latest.fit.permits.pool.numerator += 2;
    assert.throws(() => validateResearchSnapshot(inconsistent,snapshot,now), /Adaptive-weight fit/);
  }
  const mismatched = structuredClone(snapshot);
  mismatched.weightTrial.warnings.windows.all.n++;
  assert.throws(() => validateResearchSnapshot(mismatched,snapshot,now),/same evaluation months/);
  if (snapshot.weightTrial.prospective?.receiptCount) {
    const missing=structuredClone(snapshot);
    missing.weightTrial.prospective.receipts=[];
    assert.throws(() => validateResearchSnapshot(missing,snapshot,now),/record missing or regressive/);
  }
});

test('credit dynamics remote updates retain paired evidence and reproduce the issued forecasts', async () => {
  const {validateResearchSnapshot} = await import('../lib/live-data.ts');
  const now = new Date(snapshot.meta.generatedAt);
  for (const mutate of [
    d => { delete d.creditTrial; },
    d => { d.creditTrial.warnings.buckets.all[0].n++; },
    d => { d.creditTrial.latest.benchmarkProbability = -1; },
    ...(snapshot.creditTrial.latest.available ? [
      d => { d.creditTrial.latest.creditShock += .2; },
      d => { d.creditTrial.latest.probability = -1; },
      d => { d.creditTrial.latest.sudden = !d.creditTrial.latest.sudden; },
    ] : []),
    ...(snapshot.creditTrial.prospective?.receiptCount ? [d => { d.creditTrial.prospective.receipts = []; }] : []),
  ]) {
    const invalid = structuredClone(snapshot);
    mutate(invalid);
    assert.throws(() => validateResearchSnapshot(invalid,snapshot,now), /credit dynamics/i);
  }
});

test('expansion-onset research keeps comparable expansion cohorts and validates the conditional probability', async () => {
  const {validateResearchSnapshot} = await import('../lib/live-data.ts');
  const now = new Date(snapshot.meta.generatedAt);
  const corruptions = [
    d => { delete d.expansionTrial; },
    d => { d.expansionTrial.latest.conditionalOnExpansion = false; },
    d => { d.expansionTrial.metrics.rolling120.recessionN++; },
    ...(snapshot.expansionTrial.latest.available ? [
      d => { d.expansionTrial.latest.rawExpansionProbability += .05; },
      d => { d.expansionTrial.latest.trainingPositives++; },
      d => { d.expansionTrial.latest.baseOnlyChangeProbability = -1; },
    ] : []),
    ...(snapshot.expansionTrial.prospective?.receiptCount ? [
      d => { d.expansionTrial.prospective.receipts = []; },
      d => { d.expansionTrial.prospective.excludedCount++; },
    ] : []),
  ];
  for (const mutate of corruptions) {
    const invalid = structuredClone(snapshot);
    mutate(invalid);
    assert.throws(() => validateResearchSnapshot(invalid,snapshot,now), /expansion-onset/i);
  }
});

test('risk momentum preserves dated risk paths, decisions and comparable quiet months', async () => {
  const {validateResearchSnapshot} = await import('../lib/live-data.ts');
  const corruptions = [
    d => { delete d.momentumTrial; },
    d => { d.momentumTrial.spec.projectionMonths.month = 3; },
    d => { d.momentumTrial.latest.path[0].date = d.momentumTrial.latest.issueDate; },
    d => { d.momentumTrial.history[0].levelAlert = !d.momentumTrial.history[0].levelAlert; },
    d => { d.momentumTrial.windows.all.probabilityScores.brier += .01; },
    d => { d.momentumTrial.windows.all.caseComparison.matches.push({date:'1900-01-01'}); },
    d => { d.momentumTrial.windows.rolling120.changes.quarter.quietDates.push('2000-05-01'); },
    ...(snapshot.momentumTrial.prospective?.receiptCount ? [d => { d.momentumTrial.prospective.receipts = []; }] : []),
  ];
  for (const mutate of corruptions) {
    const invalid = structuredClone(snapshot);
    mutate(invalid);
    assert.throws(() => validateResearchSnapshot(invalid,snapshot,new Date(snapshot.meta.generatedAt)), /risk momentum/i);
  }
});

test('signal confirmation verifies votes, decisions, case attributions, cohorts and frozen records', async () => {
  const {validateResearchSnapshot} = await import('../lib/live-data.ts');
  const corruptions = [
    d => { delete d.confirmationTrial; },
    d => { d.confirmationTrial.latest.creditTightening = !d.confirmationTrial.latest.creditTightening; },
    d => { d.confirmationTrial.history[55].pressureAlert = !d.confirmationTrial.history[55].pressureAlert; },
    d => { d.confirmationTrial.history[55].lagFeatureDate = d.confirmationTrial.history[55].featureDate; },
    d => { d.confirmationTrial.windows.all.changes.breadth.quietDates.push('2000-05-01'); },
    d => { d.confirmationTrial.windows.rolling120.probabilityScores.brier += .01; },
    d => { d.confirmationTrial.gate.pressure.passed = !d.confirmationTrial.gate.pressure.passed; },
    ...(snapshot.confirmationTrial.caseAttribution['2000-05-01'] ? [
      d => { d.confirmationTrial.caseAttribution['2000-05-01'].effects.slope += .01; },
    ]: []),
    ...(snapshot.confirmationTrial.prospective?.receiptCount ? [d => { d.confirmationTrial.prospective.receipts = []; }] : []),
  ];
  for (const mutate of corruptions) {
    const invalid = structuredClone(snapshot);
    mutate(invalid);
    assert.throws(() => validateResearchSnapshot(invalid,snapshot,new Date(snapshot.meta.generatedAt)), /signal confirmation/i);
  }
});

test('Treasury yield legs preserve input dates, signed changes, advance declarations and held-out receipts', async () => {
  const {validateResearchSnapshot} = await import('../lib/live-data.ts');
  for (const mutate of [
    d => { delete d.curveLegsTrial; },
    d => { d.curveLegsTrial.spec.postHocRules = []; },
    d => { d.curveLegsTrial.latest.yieldPath[0].date = d.latest.issueDate; },
    d => { d.curveLegsTrial.history[77].shortStart += .01; },
    d => { d.curveLegsTrial.history[77].mixedTwoToOneAlert = !d.curveLegsTrial.history[77].mixedTwoToOneAlert; },
    d => { d.curveLegsTrial.windows.all.probabilityScores.brier += .01; },
    d => { d.curveLegsTrial.windows.rolling120.changes.shortLead.quietDates.push('2000-05-01'); },
    d => { d.curveLegsTrial.gate.mixedTwoToOne.passed = !d.curveLegsTrial.gate.mixedTwoToOne.passed; },
    ...(snapshot.curveLegsTrial.caseEffects['2000-05-01'] ? [d => { d.curveLegsTrial.caseEffects['2000-05-01'].shortEffect += .02; }] : []),
    ...(snapshot.curveLegsTrial.prospective?.receiptCount ? [d => { d.curveLegsTrial.prospective.receipts=[]; }] : []),
  ]) {
    const invalid = structuredClone(snapshot);
    mutate(invalid);
    assert.throws(() => validateResearchSnapshot(invalid,snapshot,new Date(snapshot.meta.generatedAt)), /yield curve legs/i);
  }
});

test('curve stability preserves the grid, issue clock, stress bounds, cohort and archive', async () => {
  const {validateResearchSnapshot} = await import('../lib/live-data.ts');
  for (const mutate of [
    d => { delete d.curveStabilityTrial; },
    d => { d.curveStabilityTrial.spec.stressBp = 2; },
    d => { d.curveStabilityTrial.cells[3] = d.curveStabilityTrial.cells[2]; },
    d => { d.curveStabilityTrial.latest.results['d5-r2'].possible = !d.curveStabilityTrial.latest.results['d5-r2'].possible; },
    d => { d.curveStabilityTrial.history[12].probability = -1; },
    d => { d.curveStabilityTrial.windows.all.probabilityScores.brier += .01; },
    d => { d.curveStabilityTrial.cells[0].windows.rolling120.possibleQuietDates.push('2000-05-01'); },
    d => { d.curveStabilityTrial.cells[0].stressPassed = !d.curveStabilityTrial.cells[0].stressPassed; },
    ...(snapshot.curveStabilityTrial.prospective?.receiptCount ? [d => { d.curveStabilityTrial.prospective.receipts=[]; }] : []),
  ]) {
    const invalid = structuredClone(snapshot);
    mutate(invalid);
    assert.throws(() => validateResearchSnapshot(invalid,snapshot,new Date(snapshot.meta.generatedAt)), /curve stability/i);
  }
});
