import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFile} from 'node:fs/promises';
import {buildDecisionBrief,renderDecisionBrief} from '../lib/decision-brief.ts';
const snapshot=JSON.parse(await readFile(new URL('../data/snapshot.json',import.meta.url),'utf8'));

test('memo preserves forecast horizon, actual observation dates and the current prospective count',()=>{
 const b=buildDecisionBrief(snapshot),html=renderDecisionBrief(snapshot);
 assert.equal(b.probability,snapshot.latest.probability);
 assert.ok(html.includes(b.horizon));
 assert.ok(html.includes(b.inflationDate));
 assert.ok(html.includes(b.indicatorDate));
 assert.ok(html.includes(snapshot.meta.generatedAt));
 assert.ok(html.includes(`${snapshot.prospective?.maturedCount ?? 0} matured`));
 assert.ok(b.bondDown.priceChange>0);
 assert.ok(b.bondUp.priceChange<0);
 assert.equal(b.bondDown.couponPercent,b.bondUp.couponPercent);
});
test('economic confirmation rule changes only at its declared boundaries',()=>{
 const s=structuredClone(snapshot);
 s.latest.features.credit=0;s.latest.features.labor=.49;
 assert.equal(buildDecisionBrief(s).confirming,false);
 s.latest.features.labor=.5;
 assert.equal(buildDecisionBrief(s).confirming,true);
 s.latest.features.labor=0;s.latest.features.credit=.0001;
 assert.equal(buildDecisionBrief(s).confirming,true);
 assert.ok(buildDecisionBrief(s).thesis.includes('Credit at or below zero'));
});
test('standalone memo escapes upstream string fields and has no executable scripts',()=>{
 const s=structuredClone(snapshot);
 s.meta.generatedAt='<script>alert("injected")</script>';
 const html=renderDecisionBrief(s);
 assert.ok(html.includes('&lt;script&gt;'));
 assert.ok(!html.includes('<script>'));
 assert.ok(html.includes('not causal economic tipping points'));
});


test('memo updates when a controlled prospective fixture matures from zero to one',()=>{
 const pending=structuredClone(snapshot);
 pending.prospective={...pending.prospective,receiptCount:1,maturedCount:0};
 const first=renderDecisionBrief(pending);
 assert.ok(first.includes('1 frozen; 0 matured'));
 const matured=structuredClone(pending);
 matured.prospective.maturedCount=1;
 const second=renderDecisionBrief(matured);
 assert.ok(second.includes('1 frozen; 1 matured'));
 assert.ok(!second.includes('1 frozen; 0 matured'));
 assert.equal(pending.prospective.maturedCount,0,'rendering and fixture updates must not mutate the prior record');
});
