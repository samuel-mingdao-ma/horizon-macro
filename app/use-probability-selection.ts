'use client';

import { useEffect, useState } from 'react';
import { PROBABILITY_METHODS, type ProbabilityAudit, type ProbabilityMethod } from '../lib/probability-audit';

type Selection = { method: ProbabilityMethod; band?: number };
const initial: Selection = { method: 'original' };

function fromHash(): Selection {
  const [view, query] = window.location.hash.slice(1).split('?');
  if (view !== 'calibration') return initial;
  const params = new URLSearchParams(query);
  const method = PROBABILITY_METHODS.find((id) => id === params.get('method')) ?? initial.method;
  const band = params.get('band') ?? '';
  return /^[0-4]$/.test(band) ? { method, band: Number(band) } : { method };
}

function currentBand(audit: ProbabilityAudit, method: ProbabilityMethod) {
  const probabilities = {
    original: audit.current.originalProbability,
    prequential: audit.current.prequentialProbability,
    fixedBlend: audit.current.fixedBlendProbability,
    base: audit.current.baselineProbability,
  };
  const value = probabilities[method];
  if (value !== null) return Math.min(4, Math.floor(5 * value));
  return audit.bins[method].reduce((most, band) => (band.n > most.n ? band : most)).id;
}

export function useProbabilitySelection(audit: ProbabilityAudit) {
  const [selection, setSelection] = useState<Selection>(initial);
  useEffect(() => {
    const sync = () => setSelection(fromHash());
    sync();
    window.addEventListener('hashchange', sync);
    window.addEventListener('popstate', sync);
    return () => {
      window.removeEventListener('hashchange', sync);
      window.removeEventListener('popstate', sync);
    };
  }, []);

  function select(method: ProbabilityMethod, band: number) {
    setSelection({ method, band });
    window.history.replaceState(window.history.state, '', `#calibration?method=${method}&band=${band}`);
  }

  return {
    method: selection.method,
    selectedBand: selection.band ?? currentBand(audit, selection.method),
    setMethod: (method: ProbabilityMethod) => select(method, currentBand(audit, method)),
    setSelectedBand: (band: number) => select(selection.method, band),
  };
}
