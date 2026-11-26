import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import { deriveAlarmSpells, alarmSpellsCsv } from '../lib/alarm-spells.ts';
import { deriveWarningAudit } from '../lib/warning-audit.ts';
const row = (date, options = {}) => ({
  date,
  probability: 0.8,
  curveProbability: 0.8,
  baseline: 0.2,
  target: 0,
  recession: 0,
  credit: 0.1,
  labor: 0,
  ...options,
});

test('calendar gaps and missing scores break spells and censor both adjoining boundaries', () => {
  const history = [
    row('2020-01-01'),
    row('2020-02-01'),
    row('2020-04-01'),
    row('2020-05-01', { probability: null }),
    row('2020-06-01'),
    row('2020-07-01', { probability: 0.1 }),
  ];
  const audit = deriveAlarmSpells({ history });
  assert.deepEqual(
    audit.spells.map((s) => s.months),
    [2, 1, 1],
  );
  assert.equal(audit.coverage.calendarMonths, 7);
  assert.equal(audit.coverage.observedMonths, 6);
  assert.equal(audit.coverage.missingCalendarMonths, 1);
  assert.equal(audit.coverage.missingSignalMonths, 1);
  assert.deepEqual(
    audit.coverage.gaps.map((g) => [g.start, g.reason]),
    [
      ['2020-03-01', 'missing-date'],
      ['2020-05-01', 'missing-signal'],
    ],
  );
  assert.equal(audit.spells[0].leftBoundary, 'dataset-boundary');
  assert.equal(audit.spells[0].leftCensored, true);
  assert.equal(audit.spells[0].rightBoundary, 'missing-date');
  assert.equal(audit.spells[1].leftCensored, true);
  assert.equal(audit.spells[1].rightBoundary, 'missing-signal');
  assert.equal(audit.spells[2].leftBoundary, 'missing-signal');
  assert.equal(audit.spells[2].rightBoundary, 'observed-non-alarm');
  assert.equal(audit.spells[2].rightCensored, false);
  assert.equal(audit.monthlyRows[2].alarm, null);
  assert.equal(audit.monthlyRows[2].target, null);
});

test('real-time and monthly-refit rows cannot fill annual replay gaps or extend its timeline', () => {
  const history = [
    row('2020-01-01', { forecastType: 'annual-walk-forward' }),
    row('2020-02-01', { forecastType: 'current-month-refit' }),
    row('2020-03-01', { forecastType: 'annual-walk-forward' }),
    row('2020-04-01', { forecastType: 'live-fixed-model' }),
  ];
  const innovation = {
    history: [
      { ...row('2020-01-01'), originalProbability: 0.8, forecastType: 'annual-walk-forward' },
      { ...row('2020-03-01'), originalProbability: 0.8, forecastType: 'annual-walk-forward' },
    ],
  };
  const audit = deriveAlarmSpells({ history, innovation });
  assert.equal(audit.coverage.end, '2020-03-01');
  assert.equal(audit.coverage.missingCalendarMonths, 1);
  assert.equal(audit.monthlyRows[1].status, 'missing');
  assert.equal(audit.monthlyRows[1].alarm, null);
  assert.deepEqual(
    audit.spells.map((spell) => spell.months),
    [1, 1],
  );
  const legacy = deriveAlarmSpells({ history });
  assert.equal(legacy.coverage.end, '2020-03-01');
  assert.equal(legacy.coverage.missingCalendarMonths, 1);
});

test('pending outcome takes precedence over mixed known outcomes without inferring a positive', () => {
  const audit = deriveAlarmSpells({
    history: [row('2020-01-01', { target: 1 }), row('2020-02-01'), row('2020-03-01', { target: null })],
  });
  const spell = audit.spells[0];
  assert.equal(spell.classification, 'pending');
  assert.equal(spell.positiveMonths, 1);
  assert.equal(spell.falseMonths, 1);
  assert.equal(spell.pendingMonths, 1);
  assert.equal(spell.rightCensored, true);
  assert.equal(audit.stats.matureScoredMonths, 2);
  assert.equal(audit.stats.alarmMonths, 2);
  assert.equal(audit.stats.allAlarmMonths, 3);
  assert.equal(audit.stats.pendingAlarmMonths, 1);
  assert.equal(audit.stats.alarmShare, 1);
  assert.equal(audit.stats.falseAlarmShare, 0.5);
});

test('mixed spells expose their own longest contiguous false-warning streak', () => {
  const history = [
    row('2020-01-01', { probability: 0.1 }),
    row('2020-02-01', { target: 1 }),
    row('2020-03-01'),
    row('2020-04-01'),
    row('2020-05-01', { target: 1 }),
    row('2020-06-01', { probability: 0.1 }),
  ];
  const audit = deriveAlarmSpells({ history });
  assert.equal(audit.spells.length, 1);
  assert.equal(audit.spells[0].classification, 'mixed');
  assert.equal(audit.spells[0].months, 4);
  assert.deepEqual(audit.longestFalseStreak, {
    start: '2020-03-01',
    end: '2020-04-01',
    months: 2,
    leftBoundary: 'observed-positive',
    rightBoundary: 'observed-positive',
    leftCensored: false,
    rightCensored: false,
  });
});

test('false streaks stop at pending labels and mark that outcome boundary as censored', () => {
  const audit = deriveAlarmSpells({
    history: [
      row('2020-01-01', { probability: 0.1 }),
      row('2020-02-01'),
      row('2020-03-01'),
      row('2020-04-01', { target: null }),
      row('2020-05-01'),
    ],
  });
  assert.equal(audit.longestFalseStreak.months, 2);
  assert.equal(audit.longestFalseStreak.end, '2020-03-01');
  assert.equal(audit.longestFalseStreak.rightBoundary, 'pending-outcome');
  assert.equal(audit.longestFalseStreak.rightCensored, true);
  assert.equal(audit.spells[0].classification, 'pending');
});

test('positive and false classifications require fully known outcomes; quiet pending months stay explicit', () => {
  const history = [
    row('2020-01-01', { target: 1 }),
    row('2020-02-01', { target: 1 }),
    row('2020-03-01', { probability: 0.1, target: null }),
    row('2020-04-01'),
  ];
  const audit = deriveAlarmSpells({ history });
  assert.deepEqual(
    audit.spells.map((s) => s.classification),
    ['positive', 'false'],
  );
  assert.equal(audit.monthlyRows[2].status, 'pending');
  assert.equal(audit.monthlyRows[2].alarm, false);
  assert.equal(audit.coverage.pendingOutcomeMonths, 1);
  assert.equal(audit.stats.pendingAlarmMonths, 0);
});

test('missing candidate scores do not become quiet months or mature observations', () => {
  const audit = deriveAlarmSpells(
    { history: [row('2020-01-01'), row('2020-02-01')] },
    { rule: 'challenger' },
  );
  assert.equal(audit.spells.length, 0);
  assert.equal(audit.coverage.missingSignalMonths, 2);
  assert.equal(audit.stats.matureScoredMonths, 0);
  assert.equal(audit.stats.alarmShare, null);
  assert.equal(audit.longestFalseStreak, null);
  assert.ok(audit.monthlyRows.every((r) => r.status === 'missing'));
});

test('gate reuses threshold and strict credit/inclusive labor rules without inventing probability', () => {
  const history = [
    row('2020-01-01', { credit: 0, labor: 0.499 }),
    row('2020-02-01', { credit: 0, labor: 0.5 }),
    row('2020-03-01', { credit: 0.01, curveProbability: 0.299 }),
  ];
  const audit = deriveAlarmSpells({ history }, { rule: 'gate', threshold: 0.3 });
  assert.deepEqual(
    audit.monthlyRows.map((r) => r.alarm),
    [false, true, false],
  );
  assert.ok(audit.monthlyRows.every((r) => r.probability === null));
  assert.equal(audit.monthlyRows[1].curveProbability, 0.8);
  assert.equal(audit.spells[0].start, '2020-02-01');
});

test('invalid settings fail; empty data has explicit empty coverage and unavailable shares', () => {
  for (const threshold of [-0.1, 1.1, NaN, Infinity, null])
    assert.throws(() => deriveAlarmSpells({}, { threshold }), RangeError);
  assert.throws(() => deriveAlarmSpells({}, { rule: 'unknown' }), RangeError);
  const empty = deriveAlarmSpells({});
  assert.equal(empty.coverage.start, null);
  assert.equal(empty.coverage.calendarMonths, 0);
  assert.equal(empty.stats.alarmShare, null);
  assert.equal(empty.stats.longestFalseStreakMonths, 0);
});

test('CSV selected evidence is deterministic and preserves pending, numeric scores and censor metadata', () => {
  const audit = deriveAlarmSpells({
    history: [
      row('2020-01-01'),
      row('2020-02-01', { target: null }),
      row('2020-03-01', { probability: 0.1 }),
    ],
  });
  const csv = alarmSpellsCsv(audit, audit.spells[0].id);
  assert.equal(csv, alarmSpellsCsv(audit, audit.spells[0].id));
  assert.equal(csv.trim().split('\n').length, 3);
  assert.match(csv, /left_censored,right_censored,left_boundary,right_boundary/);
  assert.ok(csv.includes('Latest-vintage retrospective labels'));
  assert.ok(csv.includes('"pending"'));
  assert.ok(csv.includes('"0.8"'));
  assert.throws(() => alarmSpellsCsv(audit, 'unknown'), RangeError);
});

test('real annual replay flags and mature shares equal warning audit, with known false streak censored at pending horizons', async () => {
  const snapshot = JSON.parse(await readFile(new URL('../data/snapshot.json', import.meta.url), 'utf8'));
  const before = JSON.stringify(snapshot),
    warning = deriveWarningAudit(snapshot, 0.3);
  for (const rule of ['original', 'curve', 'challenger', 'gate']) {
    const audit = deriveAlarmSpells(snapshot, { rule, threshold: 0.3 }),
      metrics = warning.cohorts.all.rules[rule];
    assert.equal(audit.stats.matureScoredMonths, metrics.n);
    assert.equal(audit.stats.alarmMonths, metrics.alertMonths);
    assert.equal(audit.stats.falseAlarmMonths, metrics.fp);
    assert.equal(audit.stats.positiveAlarmMonths, metrics.tp);
    assert.equal(
      audit.spells.reduce((n, s) => n + s.months, 0),
      audit.stats.allAlarmMonths,
    );
    for (const s of audit.spells) assert.equal(s.months, s.falseMonths + s.positiveMonths + s.pendingMonths);
  }
  assert.equal(JSON.stringify(snapshot), before, 'derive must not mutate snapshots');
  const original = deriveAlarmSpells(snapshot);
  const monthly = snapshot.innovation.history
    .filter((r) => r.target === 0 && r.originalProbability >= 0.3)
    .sort((a, b) => (a.date < b.date ? -1 : 1));
  const monthId = (value) => Number(value.slice(0, 4)) * 12 + Number(value.slice(5, 7)) - 1;
  const runs = [];
  for (const r of monthly) {
    const previous = runs.at(-1);
    if (previous && monthId(r.date) === monthId(previous.end) + 1) {
      previous.end = r.date;
      previous.months++;
    } else runs.push({ start: r.date, end: r.date, months: 1 });
  }
  const expected = runs.reduce((best, run) => (!best || run.months > best.months ? run : best), null);
  assert.equal(original.longestFalseStreak?.start ?? null, expected?.start ?? null);
  assert.equal(original.longestFalseStreak?.end ?? null, expected?.end ?? null);
  assert.equal(original.longestFalseStreak?.months ?? 0, expected?.months ?? 0);
  if (expected) {
    const next = original.monthlyRows.find((r) => monthId(r.date) === monthId(expected.end) + 1);
    if (next?.alarm && next.target === null) {
      assert.equal(original.longestFalseStreak.rightBoundary, 'pending-outcome');
      assert.equal(original.longestFalseStreak.rightCensored, true);
    }
  }
});
