import assert from 'node:assert/strict';
import { test } from 'node:test';
import { forecastStability } from '../lib/forecast-stability.ts';

const sample = Array.from({ length: 25 }, (_, i) => ({
  date: new Date(Date.UTC(2020, i, 1)).toISOString().slice(0, 10),
  target: 0,
  existingBlendProbability: 0.5,
  probability: i === 0 ? 1 : 0,
  recentBlendProbability: 0.25,
}));

test('block endpoints leave the correct paired observations behind', () => {
  const result = forecastStability(sample, sample[0].date, sample.at(-1).date, 'probability');
  assert.deepEqual(result, { lowest: -0.75, highest: 0.25, n: 2, full: 5.25 / 25 });
});

test('calendar gaps, pending outcomes, and empty remaining samples never bridge blocks', () => {
  const from = sample[0].date,
    to = sample.at(-1).date;
  for (const input of [
    sample.slice(1),
    sample.filter((_, i) => i !== 13),
    [...sample, sample[0]],
    sample.map((r, i) => (i === 8 ? { ...r, target: null } : r)),
  ]) {
    assert.equal(forecastStability(input, from, to, 'probability'), null);
  }
  const missingComparator = sample.map((row, i) =>
    i === 8 ? { ...row, recentBlendProbability: null } : row,
  );
  assert.equal(forecastStability(missingComparator, from, to, 'probability'), null);
});
