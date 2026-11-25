import snapshot from '../../../data/snapshot.json';
import { getMacroSnapshot } from '../../../lib/live-data';

export async function GET(request: Request) {
  const file = new URL(request.url).searchParams.get('file') ?? 'snapshot';
  if (file === 'snapshot') {
    const data = await getMacroSnapshot(snapshot);
    return new Response(JSON.stringify(data, null, 2), { headers: { 'Content-Type': 'application/json; charset=utf-8', 'Content-Disposition': 'attachment; filename="horizon-snapshot.json"', 'Cache-Control': 'no-store' } });
  }
  if (file === 'panel' || file === 'predictions') {
    try {
      const url = `https://raw.githubusercontent.com/samuel-mingdao-ma/horizon-macro/main/public/data/${file}.csv`;
      const result = await fetch(url, {signal: AbortSignal.timeout(5000)});
      const csv = await result.text();
      if (result.ok && /^(date|issueDate|issue_date),/.test(csv) && csv.includes('\n')) {
        return new Response(csv, {headers: {'Content-Type':'text/csv; charset=utf-8','Content-Disposition':`attachment; filename="horizon-${file}.csv"`,'Cache-Control':'public, max-age=3600','X-Research-Source':'scheduled-github-research'}});
      }
    } catch { /* Retain the downloadable bundled research vintage if remote access fails. */ }
    return Response.redirect(new URL(`/data/${file}.csv`, request.url), 303);
  }
  return Response.json({ error: 'Choose snapshot, panel, or predictions.' }, { status: 400 });
}
