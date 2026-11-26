import assert from 'node:assert/strict';
import test from 'node:test';
import { annualOriginScores } from '../lib/regime-annual-check.ts';

test('annual horizons are grouped by the actual calendar month on paired, dated outcomes', () => {
  const issue = (date, target) => ({
    date,
    target,
    originalProbability: 0.5,
    baselineProbability: 0.5,
    recentPriorProbability: 0.5,
    recentBlendProbability: 0.5,
    expandingBlendProbability: 0.5,
    dynamicPriorProbability: 0.5,
    fixedBlendProbability: 0.5,
    probability: 0.25,
    adaptiveProbability: 0.5,
  });
  const rows = annualOriginScores(
    [
      issue('1999-01-01', 1),
      issue('2000-01-01', 0),
      issue('2000-02-01', 1),
      issue('2001-01-01', 0),
      issue('2001-01-01', 0),
      issue('2001-02-01', null),
      { ...issue('2001-03-01', 1), probability: null },
      issue('2001-04-01', 0),
    ],
    '2000-01-01',
    '2001-03-01',
  );
  assert.deepEqual(rows[0], {
    month: 1,
    n: 2,
    positives: 0,
    fixed: 0.25,
    regimeDelta: -0.1875,
    adaptiveDelta: 0,
  });
  assert.deepEqual(rows[1], {
    month: 2,
    n: 1,
    positives: 1,
    fixed: 0.25,
    regimeDelta: 0.3125,
    adaptiveDelta: 0,
  });
  assert.equal(rows[2].fixed, null);
  assert.equal(rows[3].n, 0);
});
