import snapshot from '../../../data/snapshot.json';
import { getMacroSnapshot } from '../../../lib/live-data';

export async function GET() {
  const data = await getMacroSnapshot(snapshot);
  const maxAge = data.meta?.refresh?.status === 'fresh' ? 3600 : 60;
  return Response.json(data, { headers: { 'Cache-Control': `public, max-age=${maxAge}, s-maxage=${maxAge}`, 'X-Content-Type-Options': 'nosniff' } });
}
