import Dashboard from './dashboard';
import snapshot from '../data/snapshot.json';
import type { Snapshot } from '../lib/types';
export default function Home(){return <Dashboard initial={snapshot as unknown as Snapshot}/>;}
