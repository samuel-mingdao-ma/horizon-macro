import snapshot from '../../../data/snapshot.json';
import type {Snapshot} from '../../../lib/types';
import {getMacroSnapshot} from '../../../lib/live-data';
import {renderDecisionBrief} from '../../../lib/decision-brief';

export async function GET(){
 const data=await getMacroSnapshot(snapshot) as Snapshot;
 return new Response(renderDecisionBrief(data),{headers:{
  'Content-Type':'text/html; charset=utf-8',
  'Content-Disposition':'attachment; filename="horizon-decision-brief-'+data.latest.issueDate.slice(0,7)+'.html"',
  'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
  'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
 }});
}
