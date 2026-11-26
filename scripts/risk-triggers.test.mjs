import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';
import { probabilityAtFeatures, solveCreditTrigger } from '../lib/risk-triggers.ts';
const snapshot = JSON.parse(await readFile(new URL('../data/snapshot.json', import.meta.url), 'utf8'));
const base = { slope: 0, credit: 0, labor: 0 };
const rawModel = coefficients => ({ featureOrder: ['slope','credit','labor','interaction'], rawCoefficients: coefficients, rawIntercept: 0 });

test('original model inverse round-trips at positive and inverted held slopes', () => {
  for (const slope of [1.05, -1.1]) for (const targetProbability of [.3, .5]) {
    const result = solveCreditTrigger({ model: snapshot.model, features: snapshot.latest.features, slope, targetProbability });
    const coefficient=result.effectiveCreditCoefficient;
    assert.equal(result.relation,coefficient>0?'at-least':coefficient<0?'at-most':'insensitive');
    if(coefficient===0){
      assert.equal(result.requiredCredit,null);
      assert.equal(result.triggerFeatures,null);
      assert.ok(['constant-at-target','unreachable'].includes(result.status));
    }else{
      assert.equal(result.status,'solved');
      assert.ok(Math.abs(probabilityAtFeatures(snapshot.model,result.triggerFeatures)-targetProbability)<1e-10);
    }
    assert.equal(result.features.slope, slope);
    assert.equal(result.features.labor, snapshot.latest.features.labor);
    assert.equal(result.modelDate, snapshot.model.refitDate);
  }
});

test('challenger inverse includes the interaction at each held slope', () => {
  for (const slope of [1.05, -1.1]) for (const targetProbability of [.3, .5]) {
    const model = snapshot.innovation.model;
    const result = solveCreditTrigger({ model, features: snapshot.innovation.latest.features, slope, targetProbability });
    if(result.effectiveCreditCoefficient===0){
      assert.equal(result.relation,'insensitive');
      assert.equal(result.triggerFeatures,null);
    }else{
      assert.ok(Math.abs(probabilityAtFeatures(model,result.triggerFeatures)-targetProbability)<1e-10);
      assert.equal(result.triggerFeatures.interaction,Math.max(-slope,0)*result.requiredCredit);
    }
  }
  assert.ok(Math.abs(probabilityAtFeatures(snapshot.innovation.model, snapshot.innovation.latest.features) - snapshot.innovation.latest.probability) < 1e-8);
});

test('a negative effective credit coefficient reverses the threshold inequality', () => {
  const model = rawModel([0,1,0,-2]);
  const result = solveCreditTrigger({ model, features: { ...base, slope: -1 }, targetProbability: .3 });
  assert.equal(result.effectiveCreditCoefficient, -1);
  assert.equal(result.relation, 'at-most');
  assert.ok(Math.abs(probabilityAtFeatures(model, result.triggerFeatures) - .3) < 1e-12);
  assert.ok(probabilityAtFeatures(model, { ...result.triggerFeatures, credit: result.requiredCredit - .1 }) > .3);
  assert.ok(probabilityAtFeatures(model, { ...result.triggerFeatures, credit: result.requiredCredit + .1 }) < .3);
});

test('zero effective credit sensitivity distinguishes constant equality from unreachable targets', () => {
  const model = rawModel([0,1,0,-1]);
  const atTarget = solveCreditTrigger({ model, features: { ...base, slope: -1 }, targetProbability: .5 });
  assert.equal(atTarget.relation, 'insensitive');
  assert.equal(atTarget.status, 'constant-at-target');
  assert.equal(atTarget.reachable, true);
  assert.equal(atTarget.requiredCredit, null);
  for (const targetProbability of [.3,.8]) {
    const result = solveCreditTrigger({ model, features: { ...base, slope: -1 }, targetProbability });
    assert.equal(result.status, 'unreachable');
    assert.equal(result.reachable, false);
    assert.equal(result.thresholdSatisfied, targetProbability < .5);
  }
});

test('support counts use training standardization, include the radius boundary, and flag extrapolation', () => {
  const model = { featureOrder: ['slope','credit','labor'], means: [0,0,0], scales: [2,4,1], coefficients: [0,4,0], intercept: 0 };
  const trainingPoints = [{ slope: .6, credit: 0 },{ slope: 0, credit: 1.2 },{ slope: .6, credit: 1.2 },{ slope: .7, credit: 0 }];
  const result = solveCreditTrigger({ model, features: base, targetProbability: .5, trainingPoints });
  assert.equal(result.support.available, true);
  assert.equal(result.support.currentN, 3);
  assert.equal(result.support.targetN, 3);
  assert.equal(result.support.observedCreditMin, 0);
  assert.equal(result.support.observedCreditMax, 1.2);
  assert.equal(result.support.outsideObservedCreditRange, false);
  const far = solveCreditTrigger({ model, features: base, targetProbability: .95, trainingPoints });
  assert.equal(far.support.outsideObservedCreditRange, true);
  assert.equal(far.support.targetN, 0);
});

test('missing support metadata stays unavailable rather than claiming zero neighbors', () => {
  const result = solveCreditTrigger({ model: rawModel([0,1,0,0]), features: base });
  assert.equal(result.support.available, false);
  assert.equal(result.support.currentN, null);
  assert.equal(result.support.targetN, null);
});

test('invalid probabilities, features, dimensions, support, and inconsistent parameterizations are rejected', () => {
  for (const targetProbability of [0,1,-.1,NaN,Infinity]) assert.throws(() => solveCreditTrigger({ model: snapshot.model, features: base, targetProbability }), RangeError);
  assert.throws(() => probabilityAtFeatures(snapshot.model, { ...base, credit: Infinity }), RangeError);
  assert.throws(() => probabilityAtFeatures(snapshot.model, { ...base, labor: -1 }), RangeError);
  assert.throws(() => solveCreditTrigger({ model: snapshot.model, features: base, supportRadiusStd: 0 }), RangeError);
  assert.throws(() => solveCreditTrigger({ model: snapshot.model, features: base, trainingPoints: [{ slope: NaN, credit: 0 }] }), RangeError);
  const short = { ...snapshot.model, coefficients: [1] };
  assert.throws(() => probabilityAtFeatures(short, base), /dimensions/);
  const inconsistent = { ...snapshot.model, rawIntercept: snapshot.model.rawIntercept + 1 };
  assert.throws(() => probabilityAtFeatures(inconsistent, base), /disagree/);
  const unknown = { ...snapshot.model, featureOrder: ['slope','credit','unknown'] };
  assert.throws(() => probabilityAtFeatures(unknown, base), /feature order/);
});
