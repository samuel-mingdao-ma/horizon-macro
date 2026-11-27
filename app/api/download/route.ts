import snapshot from '../../../data/snapshot.json';
import { getMacroSnapshot, uncachedResearchUrl } from '../../../lib/live-data';
import { deriveProbabilityAudit, probabilityAuditCsv } from '../../../lib/probability-audit';

const files = {
  panel: {path:'panel.csv',type:'text/csv; charset=utf-8'},
  predictions: {path:'predictions.csv',type:'text/csv; charset=utf-8'},
  audit: {path:'alarm-audit.csv',type:'text/csv; charset=utf-8'},
  expansion: {path:'expansion-onset.csv',type:'text/csv; charset=utf-8'},
  expansionreceipts: {path:'expansion-receipts.jsonl',type:'application/x-ndjson; charset=utf-8'},
  creditdynamics: {path:'credit-dynamics.csv',type:'text/csv; charset=utf-8'},
  creditreceipts: {path:'credit-receipts.jsonl',type:'application/x-ndjson; charset=utf-8'},
  weights: {path:'adaptive-weights.csv',type:'text/csv; charset=utf-8'},
  weightreceipts: {path:'weight-receipts.jsonl',type:'application/x-ndjson; charset=utf-8'},
  leading: {path:'leading-indicators.csv',type:'text/csv; charset=utf-8'},
  leadingreceipts: {path:'leading-receipts.jsonl',type:'application/x-ndjson; charset=utf-8'},
  regimes: {path:'regime-prior.csv',type:'text/csv; charset=utf-8'},
  regimereceipts: {path:'regime-receipts.jsonl',type:'application/x-ndjson; charset=utf-8'},
  ratepath: {path:'rate-path.csv',type:'text/csv; charset=utf-8'},
  ratepathreceipts: {path:'rate-path-receipts.jsonl',type:'application/x-ndjson; charset=utf-8'},
  ledger: {path:'forecast-ledger.jsonl',type:'application/x-ndjson; charset=utf-8'},
} as const;

export async function GET(request: Request) {
  const file = new URL(request.url).searchParams.get('file') ?? 'snapshot';
  if (file === 'probability') {
    const data = await getMacroSnapshot(snapshot);
    const audit = deriveProbabilityAudit(data);
    return new Response(probabilityAuditCsv(audit), {headers: {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': 'attachment; filename="horizon-probability-audit.csv"',
      'Cache-Control': 'no-store',
    }});
  }
  if (file === 'snapshot') {
    const data = await getMacroSnapshot(snapshot);
    return new Response(JSON.stringify(data, null, 2), {headers:{'Content-Type':'application/json; charset=utf-8','Content-Disposition':'attachment; filename="horizon-snapshot.json"','Cache-Control':'no-store'}});
  }
  if (Object.prototype.hasOwnProperty.call(files,file)) {
    const entry=files[file as keyof typeof files];
    try {
      const url=`https://raw.githubusercontent.com/samuel-mingdao-ma/horizon-macro/main/public/data/${entry.path}`;
      const response=await fetch(uncachedResearchUrl(url),{signal:AbortSignal.timeout(5000),cache:'no-store'});
      const body=await response.text();
      const valid=entry.path.endsWith('.jsonl') ? body.trim().split('\n').every(line=>{try{return typeof JSON.parse(line).hash==='string';}catch{return false;}}) : /^(date|issueDate|issue_date),/.test(body)&&body.includes('\n');
      if(response.ok&&body.trim()&&valid) return new Response(body,{headers:{'Content-Type':entry.type,'Content-Disposition':`attachment; filename="horizon-${entry.path}"`,'Cache-Control':'public, max-age=3600','X-Research-Source':'scheduled-github-research'}});
    }catch{/* Bundled, dated downloads remain available if the remote source fails. */}
    return Response.redirect(new URL(`/data/${entry.path}`,request.url),303);
  }
  return Response.json({error:'Choose snapshot, panel, predictions, audit, probability, ledger, ratepath, ratepathreceipts, regimes, regimereceipts, leading, leadingreceipts, weights, weightreceipts, creditdynamics, creditreceipts, expansion, or expansionreceipts.'},{status:400});
}
