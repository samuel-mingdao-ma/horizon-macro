import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import {
  deriveProbabilityAudit,
  fitProbabilityWeight,
  probabilityAuditCsv,
  PROBABILITY_METHODS,
} from '../lib/probability-audit.ts';
const month = (value) => `${Math.floor(value / 12)}-${String((value % 12) + 1).padStart(2, '0')}-01`;
const history = (n = 120) =>
  Array.from({ length: n }, (_, i) => ({
    date: month(2000 * 12 + i),
    target: i % 2 === 0 ? 1 : 0,
    originalProbability: 0.8,
    baseline: 0.2,
    forecastType: 'annual-walk-forward',
  }));
function snapshot(rows = history(), issue = rows.at(-1)?.date ?? '2009-12-01') {
  return {
    innovation: { issueDate: issue, history: rows },
    latest: { issueDate: issue, featureDate: '2009-10-01', probability: 0.7, baselineProbability: 0.2 },
    meta: { issueDate: issue },
    sources: [{ id: 'USREC', lastDate: issue }],
  };
}
const close = (a, b, tolerance = 1e-12) => assert.ok(Math.abs(a - b) < tolerance, `${a} differs from ${b}`);
test('closed form recovers perfect, endpoint-constrained, fractional and unidentified weights', () => {
  close(
    fitProbabilityWeight([
      { target: 1, originalProbability: 1, baselineProbability: 0 },
      { target: 0, originalProbability: 0, baselineProbability: 1 },
    ]).weight,
    1,
  );
  close(fitProbabilityWeight([{ target: 0, originalProbability: 1, baselineProbability: 0 }]).weight, 0);
  close(
    fitProbabilityWeight(
      [1, 0, 0, 0].map((target) => ({ target, originalProbability: 1, baselineProbability: 0 })),
    ).weight,
    0.25,
  );
  const degenerate = fitProbabilityWeight([
    { target: 1, originalProbability: 0.5, baselineProbability: 0.5 },
  ]);
  assert.equal(degenerate.weight, 0);
  assert.equal(degenerate.identified, false);
  assert.equal(degenerate.unconstrainedWeight, null);
  assert.throws(
    () => fitProbabilityWeight([{ target: null, originalProbability: 0.5, baselineProbability: 0.3 }]),
    RangeError,
  );
});
test('January eligibility purges twelve-month targets and requires sixty valid earlier issue months', () => {
  const audit = deriveProbabilityAudit(snapshot());
  const before = audit.folds.find((f) => f.year === 2005),
    first = audit.folds.find((f) => f.year === 2006);
  assert.equal(before.trainingN, 48);
  assert.equal(before.weight, null);
  assert.equal(first.trainingN, 60);
  assert.equal(first.trainingCutoff, '2004-12-01');
  assert.equal(first.trainEnd, '2004-12-01');
  assert.equal(first.lastTargetMonth, '2005-12-01');
  assert.equal(audit.rows[0].date, '2006-01-01');
  assert.ok(audit.folds.every((f) => f.weight === null || f.lastTargetMonth < f.refitDate));
});
test('ineligible boundary outcomes cannot alter January weights and each year remains frozen', () => {
  const rows = history(),
    initial = deriveProbabilityAudit(snapshot(rows));
  const changed = structuredClone(rows);
  changed.find((r) => r.date === '2005-01-01').target = 0;
  const next = deriveProbabilityAudit(snapshot(changed));
  close(initial.folds.find((f) => f.year === 2006).weight, next.folds.find((f) => f.year === 2006).weight);
  assert.notEqual(
    initial.folds.find((f) => f.year === 2007).weight,
    next.folds.find((f) => f.year === 2007).weight,
  );
  const year = initial.rows.filter((r) => r.foldYear === 2006);
  assert.equal(year.length, 12);
  assert.equal(new Set(year.map((r) => r.weight)).size, 1);
  assert.equal(new Set(year.map((r) => r.trainingN)).size, 1);
});
test('unknown, invalid and not-yet-complete target horizons stay unscored and out of weight denominators', () => {
  const rows = history();
  rows[5].target = null;
  rows[6].target = 2;
  const s = snapshot(rows);
  s.sources[0].lastDate = '2009-06-01';
  const audit = deriveProbabilityAudit(s);
  assert.equal(audit.folds.find((f) => f.year === 2006).trainingN, 58);
  assert.ok(audit.rows.filter((r) => r.date > '2008-06-01').every((r) => r.target === null && !r.evaluated));
  assert.ok(audit.coverage.maskedFutureTargetRows >= 18);
  assert.ok(audit.metrics.end <= '2008-06-01');
  const missing = snapshot();
  delete missing.sources;
  const withCeiling = deriveProbabilityAudit(missing);
  assert.ok(withCeiling.rows.filter((r) => r.date > '2008-12-01').every((r) => r.target === null));
});
test('duplicate dates are all rejected, dates must be valid month starts, and no live refits fill replay gaps', () => {
  const rows = history();
  rows.push({ ...rows[0] });
  rows.push({
    date: '2004-02-30',
    target: 1,
    originalProbability: 0.9,
    baseline: 0.2,
    forecastType: 'annual-walk-forward',
  });
  rows.push({
    date: '2010-01-01',
    target: 1,
    originalProbability: 0.9,
    baseline: 0.2,
    forecastType: 'annual-walk-forward',
  });
  rows.push({ ...rows[2], forecastType: 'current-month-refit' });
  const s = snapshot(rows, '2009-12-01');
  s.history = [{ date: '2000-01-01', probability: 0.99, target: 1 }];
  const audit = deriveProbabilityAudit(s);
  assert.equal(audit.coverage.duplicateDateRows, 2);
  assert.equal(audit.coverage.duplicateMonths, 1);
  assert.equal(audit.coverage.invalidDateRows, 1);
  assert.equal(audit.coverage.futureDateRows, 1);
  assert.equal(audit.coverage.nonAnnualRows, 1);
  assert.equal(audit.coverage.acceptedRows, 119);
  assert.equal(audit.folds.find((f) => f.year === 2006).trainingN, 59);
  const noReplay = deriveProbabilityAudit({ history: s.history });
  assert.equal(noReplay.rows.length, 0);
  const missingDate = snapshot();
  delete missingDate.innovation.issueDate;
  assert.equal(deriveProbabilityAudit(missingDate).status, 'unavailable-missing-source-date');
  assert.equal(deriveProbabilityAudit(missingDate).coverage.acceptedRows, 0);
});
test('twenty-point bins include100percent, retain empty bands, and all methods share exactly the scored sample', () => {
  const rows = history();
  const probabilities = [0, 0.2, 0.4, 0.6, 0.8, 1];
  rows.forEach((r, i) => {
    r.originalProbability = probabilities[i % 6];
    r.baseline = 0.25;
  });
  const audit = deriveProbabilityAudit(snapshot(rows));
  const last = audit.bins.original[4];
  assert.equal(last.upperInclusive, true);
  assert.equal(audit.bins.original.length, 5);
  const ones = audit.rows.filter((r) => r.evaluated && r.originalProbability === 1).length;
  assert.ok(ones > 0);
  assert.ok(last.n >= ones);
  for (const method of PROBABILITY_METHODS) {
    assert.equal(
      audit.bins[method].reduce((n, b) => n + b.n, 0),
      audit.metrics.n,
    );
  }
  const empty = audit.bins.base.find((b) => b.n === 0);
  assert.equal(empty.meanPredicted, null);
  assert.equal(empty.observedRate, null);
  assert.equal(empty.brier, null);
});
test('current same-year live application is illustrative and never constructs a future-year fold', () => {
  const s = snapshot(),
    a = deriveProbabilityAudit(s);
  assert.equal(a.current.status, 'available');
  close(a.current.prequentialProbability, 0.2 + a.current.weight * (0.7 - 0.2));
  const changed = structuredClone(s);
  changed.latest.issueDate = '2010-01-01';
  changed.latest.probability = 0.95;
  const future = deriveProbabilityAudit(changed);
  assert.equal(future.current.status, 'unavailable');
  assert.equal(future.current.weight, null);
  assert.equal(future.current.prequentialProbability, null);
  assert.equal(future.current.foldRefitDate, null);
  assert.ok(!future.folds.some((f) => f.year === 2010));
  assert.match(future.current.note, /not extrapolated/);
  const sameYear = structuredClone(s);
  sameYear.latest.issueDate = '2009-11-01';
  close(deriveProbabilityAudit(sameYear).current.weight, a.current.weight);
  assert.match(a.current.note, /monthly refit/);
});
test('CSV defaults to common mature rows; bin filters, fold attribution and values reproduce band counts', () => {
  const audit = deriveProbabilityAudit(snapshot());
  const csv = probabilityAuditCsv(audit);
  assert.equal(csv.trim().split('\n').length, audit.metrics.n + 1);
  assert.equal(csv, probabilityAuditCsv(audit));
  assert.match(csv, /training_cutoff,training_n,train_end,last_training_target_month/);
  for (const method of PROBABILITY_METHODS)
    for (let bin = 0; bin < 5; bin++) {
      assert.equal(
        probabilityAuditCsv(audit, { method, bin }).trim().split('\n').length,
        audit.bins[method][bin].n + 1,
      );
    }
  assert.equal(
    probabilityAuditCsv(audit, { includePending: true }).trim().split('\n').length,
    audit.rows.length + 1,
  );
  assert.throws(() => probabilityAuditCsv(audit, { bin: 5 }), RangeError);
  assert.throws(() => probabilityAuditCsv(audit, { method: 'winner' }), RangeError);
});
test('real replay paired losses independently match CSV rows and no fixed calendar denominator is assumed', async () => {
  const s = JSON.parse(await readFile(new URL('../data/snapshot.json', import.meta.url), 'utf8'));
  const before = JSON.stringify(s),
    audit = deriveProbabilityAudit(s),
    csv = probabilityAuditCsv(audit);
  assert.equal(JSON.stringify(s), before);
  const lines = csv.trim().split('\n');
  const header = lines[0].split(',');
  const records = lines
    .slice(1)
    .map((line) =>
      Object.fromEntries(line.split(',').map((value, i) => [header[i], value.replace(/^"|"$/g, '')])),
    );
  assert.equal(records.length, audit.metrics.n);
  const map = {
    original: 'original_probability',
    prequential: 'prequential_probability',
    base: 'base_probability',
    fixedBlend: 'fixed_blend_probability',
  };
  for (const method of PROBABILITY_METHODS) {
    const sum = records.reduce(
      (total, row) => total + (Number(row[map[method]]) - Number(row.target)) ** 2,
      0,
    );
    close(sum, audit.metrics[method].totalBrierLoss, 1e-9);
    close(sum / records.length, audit.metrics[method].brier, 1e-10);
  }
  close(
    audit.metrics.pairedImprovement.vsOriginal.total,
    audit.metrics.original.totalBrierLoss - audit.metrics.prequential.totalBrierLoss,
    1e-9,
  );
  for (const row of records) {
    assert.ok(row.last_training_target_month < `${row.fold_year}-01-01`);
    assert.ok(Number(row.training_n) >= 60);
  }
});
