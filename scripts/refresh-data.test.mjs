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
