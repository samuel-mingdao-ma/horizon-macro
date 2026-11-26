import type {Snapshot} from './types';
import {repriceBond} from './bond-math.ts';
import {deriveWarningAudit} from './warning-audit.ts';
import {deriveProbabilityAudit} from './probability-audit.ts';

export const briefMonth=(value:string)=>new Date(value.slice(0,7)+'-15T12:00:00Z').toLocaleDateString('en-US',{month:'short',year:'numeric',timeZone:'UTC'});
export const briefPct=(value:number)=>Number.isFinite(value)?(100*value).toFixed(1)+'%':'unavailable';
export function buildDecisionBrief(data:Snapshot){
 const f=data.latest.features;
 const confirming=f.credit>0||f.labor>=.5;
 const headline=confirming?'Credit or labor warrants closer attention.':'Credit and labor do not confirm a downturn.';
 const curve=f.slope<0?'inverted':'upward sloping';
 const credit=f.credit>0?'tighter':'looser';
 const probability=data.latest.probability;
 const signal='The original model assigns '+briefPct(probability)+' to at least one recession month during '+briefMonth(String(data.meta.forecastStart))+'–'+briefMonth(String(data.meta.forecastEnd))+'. This is '+(probability>=.3?'above':'below')+' the illustrative 30% research alarm level; it is not a calibrated guarantee.';
 const interpretation='The curve is '+curve+' at '+f.slope.toFixed(2)+' percentage points. Credit is '+credit+' than its historical average ('+f.credit.toFixed(2)+' index), and the unemployment momentum gap is '+f.labor.toFixed(2)+' pp. The stated credit/labor confirmation rule '+(confirming?'is satisfied.':'is not satisfied.');
 const thesis='Conditional outlook for the coming year: monitor whether financing conditions tighten and labor momentum deteriorates together. Credit at or below zero together with a labor gap below 0.50 pp keeps the confirmation rule inactive; credit above zero or a labor gap of at least 0.50 pp activates it. That rule is an exploratory monitoring policy, not a demonstrated recession predictor.';
 const caveat='The original historical Brier score is '+data.metrics.model.brier.toFixed(3)+', versus '+data.metrics.baseRate.brier.toFixed(3)+' for the expanding base rate. Lower is better. Historical inputs are revised, outcomes overlap, and only '+data.metrics.events+' independent downturns are observed. The model should not determine a trade by itself.';
 const warning=deriveWarningAudit(data),expansion=warning.cohorts.expansion;
 const metric=(n:number|null)=>n===null?'unavailable':n.toFixed(3);
 const earlyWarningSummary='On '+expansion.n+' expansion-issued forecasts, curve-only AUC is '+metric(expansion.rules.curve.auc)+' and original-model AUC is '+metric(expansion.rules.original.auc)+'. This retrospective cohort excludes recession-issued months; it does not retrain an onset model or recover real-time regime information.';
 const audit = deriveProbabilityAudit(data);
 const originalBand = audit.bins.original.find(bin => probability >= bin.lower && (probability < bin.upper || bin.upperInclusive && probability === 1));
 const probabilityEvidence = originalBand?.n && originalBand.meanPredicted !== null
   ? `In the historical ${Math.round(originalBand.lower * 100)}–${Math.round(originalBand.upper * 100)}% band containing this issue’s original estimate, ${originalBand.positiveWindows} of ${originalBand.n} forecast windows contained a recession. The mean forecast in the band was ${briefPct(originalBand.meanPredicted)}. The comparison uses mature, overlapping windows from ${briefMonth(audit.metrics.start!)} through ${briefMonth(audit.metrics.end!)}.`
   : 'The comparable historical replay has no mature forecasts in the probability band containing this estimate.';
 const bondDown=repriceBond(data.latest.indicators.gs10,-100,{face:1_000_000});
 const bondUp=repriceBond(data.latest.indicators.gs10,100,{face:1_000_000});
 return {headline,signal,probabilityEvidence,interpretation,thesis,caveat,earlyWarningSummary,confirming,probability,bondDown,bondUp,
  issue:briefMonth(data.latest.issueDate),features:briefMonth(data.latest.featureDate),
  horizon:briefMonth(String(data.meta.forecastStart))+'–'+briefMonth(String(data.meta.forecastEnd)),
  build:data.meta.generatedAt,indicatorDate:briefMonth(data.latest.indicatorDate),inflationDate:briefMonth(data.latest.indicators.inflationDate)};
}

function escapeHtml(value:unknown){return String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]!));}
export function renderDecisionBrief(data:Snapshot){
 const b=buildDecisionBrief(data),q=data.latest.indicators;
 const paragraph=(value:string)=>'<p>'+escapeHtml(value)+'</p>';
 const money=(value:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(value);
 return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>HORIZON decision brief · '+escapeHtml(b.issue)+'</title><style>body{font:16px/1.65 system-ui,sans-serif;color:#172018;max-width:860px;margin:40px auto;padding:0 24px}h1{font-size:36px;line-height:1.15;letter-spacing:-.04em}h2{font-size:22px;margin-top:30px}small{font-size:13px;color:#48574a}.meta{border-block:1px solid #b8c4b7;padding:14px 0}table{border-collapse:collapse;width:100%}th,td{text-align:left;border-bottom:1px solid #b8c4b7;padding:10px 8px}a{color:#2e572b}.note{background:#eff3ed;padding:16px}@media print{body{margin:0;max-width:none}a{color:inherit}}</style><header><small>HORIZON / DECISION BRIEF / INDEPENDENT ACADEMIC RESEARCH</small><h1>'+escapeHtml(b.headline)+'</h1><p class="meta">Issue '+escapeHtml(b.issue)+' · Model inputs '+escapeHtml(b.features)+'<br>Forecast horizon '+escapeHtml(b.horizon)+'<br>Research build '+escapeHtml(b.build)+' · Data state '+escapeHtml(data.meta.refresh?.status??'bundled research vintage')+'</p></header><h2>Current evidence</h2>'+paragraph(b.signal)+paragraph(b.interpretation)+'<h2>How did similar probabilities perform?</h2>'+paragraph(b.probabilityEvidence)+'<p><a href="https://horizon-macro-observatory.samel23.chatgpt.site/#calibration">Inspect the probability audit</a></p><h2>A view with conditions</h2>'+paragraph(b.thesis)+paragraph('Inflation: '+q.inflation.toFixed(1)+'% year over year ('+b.inflationDate+'). Unemployment: '+q.unemployment.toFixed(1)+'%; effective federal funds rate: '+q.fedFunds.toFixed(2)+'% ('+b.indicatorDate+'). These releases have different observation dates.')+'<h2>Rates exposure is a separate risk</h2>'+paragraph('Illustrative $1m ten-year semiannual par-coupon bond at the '+q.gs10.toFixed(2)+'% Treasury-yield input. Hold its coupon fixed and reprice immediately; no elapsed time, carry, funding cost or default risk.')+'<table><tr><th>Parallel yield shock</th><th>Exact price change</th></tr><tr><td>−100 bp</td><td>'+escapeHtml(money(b.bondDown.priceChange))+'</td></tr><tr><td>+100 bp</td><td>'+escapeHtml(money(b.bondUp.priceChange))+'</td></tr></table><h2>What could overturn the view?</h2>'+paragraph('Reassess the rule when credit rises above zero or labor momentum reaches 0.50 pp. Use the website’s reverse trigger tool to quantify what credit level makes the fitted probability cross a chosen alarm threshold. These model thresholds are not causal economic tipping points.')+'<h2>Limits and accountability</h2>'+paragraph(b.caveat)+paragraph(b.earlyWarningSummary)+paragraph('Prospective receipts: '+(data.prospective?.receiptCount??0)+' frozen; '+(data.prospective?.maturedCount??0)+' matured. No future-performance claim is supported by an unscored receipt.')+'<p class="note">This memo uses the dated snapshot retrieved for this download. It describes conditional research, not a joint macro scenario or investment recommendation.</p><p><a href="https://horizon-macro-observatory.samel23.chatgpt.site/#brief">Interactive research</a> · <a href="https://github.com/samuel-mingdao-ma/horizon-macro">Source and refresh history</a> · <a href="https://github.com/samuel-mingdao-ma/horizon-macro/blob/main/research/INNOVATION.md">Research protocol</a></p></html>';
}
