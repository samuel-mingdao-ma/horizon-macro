import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import { bondRisk, repriceBond, modelScenario } from '../lib/bond-math.ts';
const snapshot = JSON.parse(await readFile(new URL('../data/snapshot.json', import.meta.url), 'utf8'));

test('a new par coupon bond prices at par across sensible yields', () => {
  for (const y of [0, 1, 3, 5.13, 12]) assert.ok(Math.abs(bondRisk(y).price - 100) < 1e-10);
});

test('zero-coupon durations and convexity equal their closed forms', () => {
  const y = 0.05, years = 10, m = 2;
  const r = bondRisk(y * 100, { years, couponPercent: 0 });
  assert.ok(Math.abs(r.price - 100 / (1 + y / m) ** (years * m)) < 1e-10);
  assert.ok(Math.abs(r.macaulayDuration - years) < 1e-10);
  assert.ok(Math.abs(r.modifiedDuration - years / (1 + y / m)) < 1e-10);
  assert.ok(Math.abs(r.convexity - years * (years + 1 / m) / (1 + y / m) ** 2) < 1e-10);
});

test('analytical duration, convexity and DV01 reproduce numerical derivatives', () => {
  const y = 5.13, h = 0.0001;
  const r = bondRisk(y), opts = { couponPercent: y };
  const up = bondRisk(y + h * 100, opts).price, down = bondRisk(y - h * 100, opts).price;
  const duration = (down - up) / (2 * h * r.price);
  const convexity = (up + down - 2 * r.price) / (h * h * r.price);
  assert.ok(Math.abs(duration - r.modifiedDuration) < 0.00001);
  assert.ok(Math.abs(convexity - r.convexity) < 0.0001);
  assert.ok(Math.abs((down - up) / 2 - r.dv01) < 0.000001);
});

test('repricing holds coupon fixed and produces expected bond-loss direction', () => {
  const up = repriceBond(5.13, 100), down = repriceBond(5.13, -100);
  assert.equal(up.couponPercent, 5.13);
  assert.ok(up.exactReturn < 0 && down.exactReturn > 0);
  assert.ok(down.exactReturn > -up.exactReturn, 'positive convexity');
  assert.ok(Math.abs(up.exactReturn - up.durationConvexityReturn) < 0.0002);
  assert.ok(Math.abs(repriceBond(5.13, 0).exactReturn) < 1e-12);
});

test('scenario base case reproduces model and labor gap is nonnegative', () => {
  assert.ok(Math.abs(modelScenario(snapshot.model, snapshot.latest.features).probability - snapshot.latest.probability) < 1e-8);
  const stressed = modelScenario(snapshot.model, snapshot.latest.features, { laborPp: -1 });
  assert.equal(stressed.features.labor, 0);
  assert.ok(stressed.probability >= 0 && stressed.probability <= 1);
});
