'use client';

import { useMemo } from 'react';
import { deriveAlarmSpells, type AlarmSpellRule } from '../lib/alarm-spells';
import type { Snapshot } from '../lib/types';
import './alarm-rule-comparison.css';

const rules = [
  ['original', 'Original model'],
  ['curve', 'Yield curve only'],
  ['challenger', 'Interaction candidate'],
  ['gate', 'Curve + confirmation'],
] as const;

function compareRules(data: Snapshot, threshold: number) {
  const audits = rules.map(([id, label]) => ({
    id,
    label,
    audit: deriveAlarmSpells(data, { rule: id, threshold }),
  }));
  const scored = audits.map(
    ({ audit }) =>
      new Map(
        audit.monthlyRows
          .filter((row) => row.alarm !== null && row.target !== null)
          .map((row) => [row.date, row]),
      ),
  );
  const common = [...scored[0].keys()].filter((date) => scored.every((model) => model.has(date)));
  const positive = common.filter((date) => scored[0].get(date)!.target === 1).length;
  const caseMonths = common.filter((date) => date.startsWith('2023-') && scored[0].get(date)!.target === 0);
  const allFourWarned = caseMonths.filter((date) => scored.every((model) => model.get(date)!.alarm)).length;
  const rows = audits.map(({ id, label, audit }, i) => {
    const months = common.map((date) => scored[i].get(date)!);
    return {
      id,
      label,
      streak: audit.longestFalseStreak,
      falseAlarms: months.filter((row) => row.alarm && row.target === 0).length,
      missed: months.filter((row) => !row.alarm && row.target === 1).length,
    };
  });
  return { months: common.length, positive, rows, caseMonths: caseMonths.length, allFourWarned };
}

export function AlarmRuleComparison({
  data,
  threshold,
  rule,
  setRule,
}: {
  data: Snapshot;
  threshold: number;
  rule: AlarmSpellRule;
  setRule: (next: AlarmSpellRule) => void;
}) {
  const comparison = useMemo(() => compareRules(data, threshold), [data, threshold]);
  return (
    <section className="alarm-rule-comparison" aria-labelledby="alarm-rule-comparison-heading">
      <h2 id="alarm-rule-comparison-heading">What does a shorter warning cost?</h2>
      <p>
        At a {Math.round(threshold * 100)}% threshold, compare false alarms with recession windows that each
        rule missed. Select a rule to inspect its calendar.
      </p>
      <div className="arc-scroll" tabIndex={0} role="region" aria-label="Alarm rule comparison">
        <table>
          <thead>
            <tr>
              <th scope="col">Rule</th>
              <th scope="col">Longest false streak</th>
              <th scope="col">False alarm months</th>
              <th scope="col">Missed positive windows</th>
            </tr>
          </thead>
          <tbody>
            {comparison.rows.map((row) => (
              <tr key={row.id} data-active={row.id === rule}>
                <th scope="row">
                  <button type="button" aria-pressed={row.id === rule} onClick={() => setRule(row.id)}>
                    {row.label}
                  </button>
                </th>
                <td>
                  {row.streak ? (
                    <>
                      {(row.streak.leftCensored || row.streak.rightCensored) && '≥'}
                      {row.streak.months} mo
                    </>
                  ) : (
                    '0 mo'
                  )}
                </td>
                <td>{comparison.months ? row.falseAlarms : '—'}</td>
                <td>{comparison.positive ? row.missed + ' / ' + comparison.positive : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {comparison.caseMonths > 0 && (
        <p className="arc-case">
          <strong>2023 replay.</strong> All four rules signaled together in {comparison.allFourWarned} of the{' '}
          {comparison.caseMonths} forecast months whose following year contained no recession.
        </p>
      )}
      <p className="arc-note">
        Error counts use the same {comparison.months} mature issue months for all four rules. Streaks use each
        rule’s available history. A ≥ marks a streak that could extend beyond its verified months.
      </p>
    </section>
  );
}
