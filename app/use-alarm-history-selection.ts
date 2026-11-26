'use client';

import { useEffect, useState } from 'react';

export type HistoryRule = 'original' | 'curve' | 'challenger' | 'gate';
type Selection = { rule: HistoryRule; threshold: number };
const defaults: Selection = { rule: 'original', threshold: 0.3 };
const rules = new Set<HistoryRule>(['original', 'curve', 'challenger', 'gate']);

function readSelection(): Selection {
  const params = new URLSearchParams(window.location.hash.split('?')[1]);
  const rule = params.get('rule') as HistoryRule;
  const percent = Number(params.get('threshold'));
  return {
    rule: rules.has(rule) ? rule : defaults.rule,
    threshold: percent >= 10 && percent <= 80 && percent % 5 === 0 ? percent / 100 : defaults.threshold,
  };
}

function selectionUrl({ rule, threshold }: Selection) {
  return '#history?rule=' + rule + '&threshold=' + Math.round(100 * threshold);
}

export function useAlarmHistorySelection() {
  const [selection, setSelection] = useState(defaults);
  useEffect(() => {
    const sync = () => setSelection(readSelection());
    sync();
    window.addEventListener('hashchange', sync);
    window.addEventListener('popstate', sync);
    return () => {
      window.removeEventListener('hashchange', sync);
      window.removeEventListener('popstate', sync);
    };
  }, []);

  function change(next: Selection) {
    setSelection(next);
    window.history.replaceState(window.history.state, '', selectionUrl(next));
  }

  return {
    ...selection,
    setRule: (rule: HistoryRule) => change({ ...selection, rule }),
    setThreshold: (threshold: number) => change({ ...selection, threshold }),
    shareUrl: selectionUrl(selection),
  };
}
