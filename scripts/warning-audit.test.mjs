import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import { deriveWarningAudit, WARNING_RULES } from '../lib/warning-audit.ts';
const month = value => `${Math.floor(value / 12)}-${String(value % 12 + 1).padStart(2, '0')}-01`;
const row = (date, options = {}) => ({ date, probability: .1, curveProbability: .1, baseline: .2,
  target: 1, recession: 0, credit: -.1, labor: 0, ...options });
const onset = 2020 * 12 + 2; // March 2020, first USREC=1.
const fullPre = () => Array.from({ length: 12 }, (_, index) => row(month(onset - 12 + index)));
const period = { start: month(onset), end: month(onset + 2) };

test('strictly prior twelve expansion issues give UTC lead times twelve through one', () => {
  const history = fullPre(); history[0].probability = .8; history[11].curveProbability = .8;
  const audit = deriveWarningAudit({ history, recessions: [period] });
  assert.equal(audit.episodes.length, 1);
  const episode = audit.episodes[0];
  assert.equal(episode.availableMonths, 12); assert.equal(episode.coverage, 'complete');
  assert.equal(episode.rules.original.firstAlertDate, '2019-03-01');
  assert.equal(episode.rules.original.leadMonths, 12);
  assert.equal(episode.rules.curve.firstAlertDate, '2020-02-01');
  assert.equal(episode.rules.curve.leadMonths, 1);
  assert.equal(audit.episodeAggregate.original.completeEpisodes, 1);
  assert.equal(audit.episodeAggregate.original.hitEpisodes, 1);
});

test('thirteenth-month, onset-month and later alarms receive no pre-onset credit', () => {
  const history = [row(month(onset - 13), { probability: .99 }), ...fullPre(),
    row(month(onset), { probability: .99, curveProbability: .99, recession: 1, credit: 3 }),
    row(month(onset + 1), { probability: .99, curveProbability: .99, recession: 1, credit: 3 })];
  const audit = deriveWarningAudit({ history, recessions: [period] });
  assert.equal(audit.episodes[0].rules.original.alertMonths, 0);
  assert.equal(audit.episodes[0].rules.gate.alertMonths, 0);
  assert.equal(audit.episodes[0].rules.original.leadMonths, null);
  assert.equal(audit.cohorts.all.recessionIssueCount, 2);
  assert.equal(audit.cohorts.expansion.recessionIssueCount, 0);
  assert.equal(audit.cohorts.all.n - audit.cohorts.expansion.n, 2);
});

test('seven-month partial coverage is visible and excluded from complete-episode denominator', () => {
  const history = fullPre().slice(5).map(value => ({ ...value, probability: .8 }));
  const audit = deriveWarningAudit({ history, recessions: [period] });
  const episode = audit.episodes[0];
  assert.equal(episode.availableMonths, 7); assert.equal(episode.expectedMonths, 12);
  assert.equal(episode.coverage, 'partial'); assert.equal(episode.rules.original.hit, true);
  assert.equal(episode.rules.original.leadMonths, 7);
  assert.equal(audit.episodeAggregate.original.completeEpisodes, 0);
  assert.equal(audit.episodeAggregate.original.hitEpisodes, 0);
  assert.equal(audit.episodeAggregate.original.partialEpisodes, 1);
  assert.equal(audit.episodeAggregate.original.hitRate, null);
});

test('unknown targets and unknown issue regimes are not filled from candidate or recession bands', () => {
  const history = fullPre(); history[2].target = null; history[3].recession = null;
  const innovation = { history: history.map(value => ({ ...value, target: 1, recession: 0, challengerProbability: .8 })) };
  const audit = deriveWarningAudit({ history, innovation, recessions: [period] });
  assert.equal(audit.cohorts.all.n, 11);
  assert.equal(audit.cohorts.all.unknownRegimeCount, 1);
  assert.equal(audit.cohorts.expansion.n, 10);
  assert.equal(audit.episodes[0].availableMonths, 10);
  assert.equal(audit.episodes[0].rules.challenger.coverage, 'partial');
});

test('tied probabilities have AUC one-half and one-class cohorts have undefined AUC', () => {
  const history = [row('2020-01-01', { probability: .5, target: 0 }), row('2020-02-01', { probability: .5, target: 1 })];
  const metrics = deriveWarningAudit({ history }).cohorts.all.rules.original;
  assert.equal(metrics.auc, .5); assert.equal(metrics.brier, .25);
  assert.ok(Math.abs(metrics.logLoss - Math.log(2)) < 1e-12);
  assert.equal(deriveWarningAudit({ history: history.slice(1) }).cohorts.all.rules.original.auc, null);
  assert.equal(deriveWarningAudit({ history: [] }).cohorts.all.rules.original.auc, null);
  assert.equal(deriveWarningAudit({ history: [] }).cohorts.all.rules.original.brier, null);
});

test('missing experimental scores remain missing and gate remains a nonprobability policy', () => {
  const history = [row('2020-01-01', { curveProbability: .5, credit: 0, labor: .5 }),
    row('2020-02-01', { curveProbability: .5, credit: 0, labor: .499, target: 0 })];
  const rules = deriveWarningAudit({ history }).cohorts.all.rules;
  assert.equal(rules.challenger.n, 0); assert.equal(rules.challenger.missingScoreCount, 2);
  assert.equal(rules.challenger.brier, null); assert.equal(rules.challenger.auc, null);
  assert.equal(rules.gate.tp, 1); assert.equal(rules.gate.tn, 1);
  assert.equal(rules.gate.auc, null); assert.equal(rules.gate.brier, null); assert.equal(rules.gate.logLoss, null);
});

test('invalid thresholds throw and valid endpoint thresholds are deterministic', () => {
  for (const threshold of [-.01, 1.01, NaN, Infinity, '0.3', null]) assert.throws(() => deriveWarningAudit({}, threshold), RangeError);
  assert.equal(deriveWarningAudit({ history: [row('2020-01-01', { probability: 0 })] }, 0).cohorts.all.rules.original.alertMonths, 1);
  assert.equal(deriveWarningAudit({ history: [row('2020-01-01', { probability: 1 })] }, 1).cohorts.all.rules.original.alertMonths, 1);
});

test('real research output retains all matured rows, exposes expansion conditioning and partial 1990 coverage', async () => {
  const snapshot = JSON.parse(await readFile(new URL('../data/snapshot.json', import.meta.url), 'utf8'));
  const before = JSON.stringify(snapshot); const audit = deriveWarningAudit(snapshot);
  assert.equal(JSON.stringify(snapshot), before, 'pure audit must not mutate input');
  assert.equal(audit.cohorts.all.n, snapshot.metrics.n);
  assert.equal(audit.cohorts.all.positiveWindows, snapshot.metrics.positiveHorizons);
  assert.ok(audit.cohorts.expansion.n < audit.cohorts.all.n);
  assert.ok(Math.abs(audit.cohorts.all.rules.original.brier - snapshot.metrics.model.brier) < 1e-9);
  assert.ok(Math.abs(audit.cohorts.all.rules.original.auc - snapshot.metrics.model.auc) < 1e-9);
  assert.ok(Math.abs(audit.cohorts.all.rules.challenger.brier - snapshot.innovation.metrics.challenger.brier) < 1e-9);
  assert.equal(audit.episodes.length, 4);
  assert.equal(audit.episodes[0].availableMonths, 7); assert.equal(audit.episodes[0].coverage, 'partial');
  for (const rule of WARNING_RULES) assert.equal(audit.episodeAggregate[rule].completeEpisodes, 3);
  assert.match(audit.disclosure, /not onset-trained/);
});
