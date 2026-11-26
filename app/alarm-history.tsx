'use client';
import { useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { ArrowDownToLine, ChevronDown, CircleHelp, Link2 } from 'lucide-react';
import type { Snapshot } from '../lib/types';
import { deriveAlarmSpells, alarmSpellsCsv } from '../lib/alarm-spells';
import { useAlarmHistorySelection } from './use-alarm-history-selection';
import { AlarmRuleComparison } from './alarm-rule-comparison';
import './alarm-history.css';

const rules = [
  { id: 'original', name: 'Original model' },
  { id: 'curve', name: 'Curve only' },
  { id: 'challenger', name: 'Interaction candidate' },
  { id: 'gate', name: 'Curve + confirmation gate' },
] as const;
const classLabels = {
  positive: 'Recession-positive',
  false: 'False warning',
  mixed: 'Mixed outcomes',
  pending: 'Outcomes pending',
};
const month = (v: string | null | undefined) =>
  v
    ? new Date(v.slice(0, 7) + '-15T12:00:00Z').toLocaleDateString('en-US', {
        month: 'short',
        year: 'numeric',
        timeZone: 'UTC',
      })
    : '—';
const percent = (v: number | null | undefined) =>
  typeof v === 'number' && Number.isFinite(v) ? `${(v * 100).toFixed(1)}%` : '—';
const formatBoundary = (v: string) => v.replace(/[-_]/g, ' ');

export default function AlarmHistory({ data }: { data: Snapshot }) {
  const { rule, threshold, setRule, setThreshold, shareUrl } = useAlarmHistorySelection();
  const audit = useMemo(() => deriveAlarmSpells(data, { rule, threshold }), [data, rule, threshold]);
  const [range, setRange] = useState<'15Y' | 'ALL'>('15Y'),
    [filter, setFilter] = useState<'all' | 'positive' | 'false' | 'mixed' | 'pending'>('all'),
    [selection, setSelection] = useState<{
      signature: string;
      spellId: string | null;
      date: string | null;
    } | null>(null);
  const calendarRef = useRef<HTMLDivElement | null>(null),
    inspectorRef = useRef<HTMLElement | null>(null),
    [cursorDate, setCursorDate] = useState<string | null>(null);
  const signature = rule + '-' + threshold,
    lookup = useMemo(() => new Map(audit.monthlyRows.map((r) => [r.date, r])), [audit.monthlyRows]);
  const longest = audit.longestFalseStreak,
    defaultSpell = longest
      ? audit.spells.find((s) => s.start <= longest.start && s.end >= longest.end)
      : audit.spells.at(-1),
    activeSelection = selection?.signature === signature ? selection : null;
  const selectedSpell = activeSelection
      ? audit.spells.find((s) => s.id === activeSelection.spellId)
      : defaultSpell,
    selectedMonth = activeSelection?.date ? lookup.get(activeSelection.date) : null;
  const lastYear = Number(audit.coverage.end?.slice(0, 4)),
    firstYear = Number(audit.coverage.start?.slice(0, 4)),
    startYear = range === 'ALL' ? firstYear : Math.max(firstYear, lastYear - 14),
    years =
      Number.isFinite(lastYear) && Number.isFinite(startYear)
        ? Array.from({ length: Math.max(0, lastYear - startYear + 1) }, (_, i) => startYear + i)
        : [];
  const visibleMonths = audit.monthlyRows.filter(
    (r) => Number(r.date.slice(0, 4)) >= startYear && Number(r.date.slice(0, 4)) <= lastYear,
  );
  const activeDate =
    cursorDate && visibleMonths.some((r) => r.date === cursorDate)
      ? cursorDate
      : selectedMonth && visibleMonths.some((r) => r.date === selectedMonth.date)
        ? selectedMonth.date
        : (visibleMonths.find((r) => selectedSpell && r.spellId === selectedSpell.id)?.date ??
          visibleMonths.at(-1)?.date);
  const selectedContainsLongest = !!(
    longest &&
    selectedSpell &&
    selectedSpell.start <= longest.start &&
    selectedSpell.end >= longest.end
  );
  const filtered = audit.spells
      .filter((s) => filter === 'all' || s.classification === filter)
      .sort((a, b) => b.start.localeCompare(a.start)),
    ruleName = rules.find((r) => r.id === rule)?.name ?? rule;
  function selectSpell(id: string) {
    setSelection({ signature, spellId: id, date: null });
    requestAnimationFrame(() => {
      const panel = inspectorRef.current;
      if (!panel) return;
      const box = panel.getBoundingClientRect();
      if (box.top < 80 || box.top > window.innerHeight - 170)
        panel.scrollIntoView({
          block: 'start',
          behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
        });
    });
  }
  function inspectMonth(date: string) {
    const row = lookup.get(date);
    if (!row) return;
    setCursorDate(date);
    setSelection({ signature, spellId: row.spellId, date });
    calendarRef.current?.focus({ preventScroll: true });
  }
  function moveCalendar(event: KeyboardEvent<HTMLDivElement>) {
    const moves: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -12, ArrowDown: 12 };
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      if (activeDate) inspectMonth(activeDate);
      return;
    }
    if (!(event.key in moves) || !visibleMonths.length) return;
    event.preventDefault();
    const index = Math.max(
        0,
        visibleMonths.findIndex((r) => r.date === activeDate),
      ),
      next = visibleMonths[Math.max(0, Math.min(visibleMonths.length - 1, index + moves[event.key]))];
    setCursorDate(next.date);
    requestAnimationFrame(() =>
      document
        .getElementById('ah-cell-' + next.date)
        ?.scrollIntoView({ block: 'nearest', inline: 'nearest' }),
    );
  }
  function exportCsv(id?: string) {
    const blob = new Blob(['\ufeff' + alarmSpellsCsv(audit, id)], { type: 'text/csv;charset=utf-8' }),
      url = URL.createObjectURL(blob),
      a = document.createElement('a');
    a.href = url;
    a.download = `horizon-${rule}-${Math.round(threshold * 100)}-alarm-spells${id ? '-selected' : ''}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <div className="alarm-history">
      <header className="ah-heading">
        <div>
          <div className="ah-eyebrow">ALARM HISTORY</div>
          <h1>How long did the warning last?</h1>
          <p>
            Inspect consecutive alarms against their eventual twelve-month outcomes, including the
            false-warning stretches.
          </p>
        </div>
        <div className="ah-heading-actions">
          <a href={shareUrl}>
            <Link2 size={14} /> Permalink
          </a>
          <button onClick={() => exportCsv()}>
            <ArrowDownToLine size={15} /> Download CSV
          </button>
        </div>
      </header>
      <section className="ah-controls" aria-label="Alarm history settings">
        <label className="ah-rule">
          <span>Alarm rule</span>
          <div className="ah-select-wrap">
            <select
              value={rule}
              onChange={(e) => setRule(e.target.value as typeof rule)}
              aria-label="Alarm rule"
            >
              {rules.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
            <ChevronDown size={15} />
          </div>
        </label>
        <label className="ah-threshold" htmlFor="ah-threshold">
          <span>
            Alarm threshold <output htmlFor="ah-threshold">{Math.round(threshold * 100)}%</output>
          </span>
          <input
            id="ah-threshold"
            type="range"
            min="0.1"
            max="0.8"
            step="0.05"
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
          />
          <span className="ah-range">
            <small>10%</small>
            <small>80%</small>
          </span>
        </label>
        <div className="ah-setting-note">
          <span>
            {month(audit.coverage.start)} – {month(audit.coverage.end)}
          </span>
          <p>
            {rule === 'gate'
              ? 'The gate requires a curve alarm plus credit > 0 or labor gap ≥ 0.50 pp. It is a policy, not a probability model.'
              : 'An alarm means the fitted probability is at or above the selected threshold. Outcomes retain the original forward target.'}
          </p>
        </div>
      </section>
      <section className="ah-summary" aria-label="Alarm history summary">
        <div>
          <span>Consecutive alarm spells</span>
          <strong>{audit.stats.spellCount}</strong>
          <small>Missing signals break a run</small>
        </div>
        <div>
          <span>Mature false-warning months</span>
          <strong>{audit.stats.falseAlarmMonths}</strong>
          <small>Of {audit.stats.matureScoredMonths} mature scored issues</small>
        </div>
        <div>
          <span>Recession-positive alarm months</span>
          <strong>{audit.stats.positiveAlarmMonths}</strong>
          <small>Overlapping forward targets</small>
        </div>
        <div className="ah-false-summary">
          <span>Longest known-false stretch</span>
          <strong>
            {longest && (longest.leftCensored || longest.rightCensored) ? '≥' : ''}
            {longest?.months ?? 0}
            <em> months</em>
          </strong>
          <small>
            {longest ? `${month(longest.start)} – ${month(longest.end)}` : 'No observed false-warning run'}
          </small>
          {longest && (longest.leftCensored || longest.rightCensored) && (
            <small className="ah-censored-note">
              {longest.rightBoundary === 'pending-outcome'
                ? 'Next alarm outcomes are pending; duration is a lower bound.'
                : 'A censored boundary makes this a lower bound.'}
            </small>
          )}
        </div>
      </section>
      <div className="ah-workspace">
        <section className="ah-calendar-section">
          <div className="ah-section-heading">
            <div>
              <h2>Monthly alarm calendar</h2>
              <p>
                {ruleName} · selected threshold {Math.round(threshold * 100)}%
              </p>
            </div>
            <div className="ah-segmented" role="group" aria-label="Calendar range">
              <button
                aria-pressed={range === '15Y'}
                className={range === '15Y' ? 'selected' : ''}
                onClick={() => setRange('15Y')}
              >
                Recent 15Y
              </button>
              <button
                aria-pressed={range === 'ALL'}
                className={range === 'ALL' ? 'selected' : ''}
                onClick={() => setRange('ALL')}
              >
                Full history
              </button>
            </div>
          </div>
          <div
            className="ah-calendar"
            ref={calendarRef}
            role="grid"
            aria-multiselectable="true"
            tabIndex={0}
            aria-activedescendant={activeDate ? 'ah-cell-' + activeDate : undefined}
            aria-label="Monthly alarm calendar"
            aria-describedby="ah-calendar-help"
            onKeyDown={moveCalendar}
          >
            <div className="ah-calendar-head" role="row">
              <span role="columnheader">Issue</span>
              {['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D'].map((m, i) => (
                <span
                  key={i}
                  role="columnheader"
                  aria-label={new Date(2000, i, 15).toLocaleDateString('en-US', { month: 'long' })}
                >
                  {m}
                </span>
              ))}
            </div>
            {years.map((year) => (
              <div className="ah-calendar-year" key={year} role="row">
                <strong role="rowheader">{year}</strong>
                {Array.from({ length: 12 }, (_, i) => {
                  const date = `${year}-${String(i + 1).padStart(2, '0')}-01`,
                    row = lookup.get(date);
                  if (!row)
                    return (
                      <span
                        key={date}
                        role="gridcell"
                        aria-label="Outside supplied research history"
                        className="ah-outside"
                        title="Outside the supplied research history"
                      />
                    );
                  const status = row.alarm === true ? row.status : row.alarm === null ? 'missing' : 'quiet',
                    selected =
                      selectedMonth?.date === date || (selectedSpell && row.spellId === selectedSpell.id),
                    outcome =
                      row.target === null
                        ? 'outcome pending'
                        : row.target === 1
                          ? 'recession in next 12 months'
                          : 'no recession in next 12 months',
                    alarm = row.alarm === null ? 'signal unavailable' : row.alarm ? 'alarm' : 'no alarm';
                  return (
                    <button
                      key={date}
                      id={'ah-cell-' + date}
                      role="gridcell"
                      tabIndex={-1}
                      className={`ah-month ah-${status} ${activeDate === date ? 'ah-cursor' : ''} ${selected ? 'ah-selected' : ''} ${row.target === null && row.alarm === false ? 'ah-unscored-quiet' : ''}`}
                      aria-selected={!!selected}
                      aria-label={`${month(date)}: ${alarm}; ${outcome}${row.probability === null ? '' : `; ${percent(row.probability)} forecast`}`}
                      title={`${month(date)} · ${alarm} · ${outcome}`}
                      onClick={() => inspectMonth(date)}
                    >
                      <span className="ah-sr">{month(date)}</span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
          <div className="ah-calendar-legend">
            <span>
              <i className="ah-false" />
              False-warning month
            </span>
            <span>
              <i className="ah-positive" />
              Recession-positive alarm
            </span>
            <span>
              <i className="ah-pending" />
              Alarm · outcome pending
            </span>
            <span>
              <i className="ah-quiet" />
              No alarm
            </span>
            <span>
              <i className="ah-missing" />
              Signal missing
            </span>
          </div>
          <p className="ah-keyboard-help" id="ah-calendar-help">
            Tab enters the calendar once. Use left/right to move one month, up/down to move twelve months, and
            Enter to inspect. Click selects a month and keeps keyboard focus in the calendar.
          </p>
          <p className="ah-note">
            Colors describe the next twelve months after each issue, not the economy in that displayed month.
            Quiet months can also have unobserved future outcomes. Missing dates and unavailable alarm signals
            interrupt spells; missing outcomes do not become false alarms.
          </p>
        </section>
        <aside className="ah-inspector" ref={inspectorRef} aria-live="polite">
          {selectedMonth && (
            <div className="ah-month-inspection">
              <span className="ah-eyebrow">SELECTED ISSUE</span>
              <h3>{month(selectedMonth.date)}</h3>
              <dl>
                <div>
                  <dt>Alarm</dt>
                  <dd>{selectedMonth.alarm === null ? 'Unavailable' : selectedMonth.alarm ? 'Yes' : 'No'}</dd>
                </div>
                <div>
                  <dt>{rule === 'gate' ? 'Curve input probability' : 'Model probability'}</dt>
                  <dd>
                    {percent(rule === 'gate' ? selectedMonth.curveProbability : selectedMonth.probability)}
                  </dd>
                </div>
                <div>
                  <dt>Forward outcome</dt>
                  <dd>
                    {selectedMonth.target === null
                      ? 'Not yet observable'
                      : selectedMonth.target === 1
                        ? 'Recession present'
                        : 'No recession'}
                  </dd>
                </div>
              </dl>
            </div>
          )}
          {selectedSpell ? (
            <section className="ah-spell-details">
              <div className="ah-eyebrow">CONSECUTIVE ALARM SPELL</div>
              <span className={`ah-class-label ah-class-${selectedSpell.classification}`}>
                {classLabels[selectedSpell.classification]}
              </span>
              <h3>
                {month(selectedSpell.start)}
                <span>to {month(selectedSpell.end)}</span>
              </h3>
              <strong className="ah-spell-length">
                {selectedSpell.months}
                <small>consecutive months</small>
              </strong>
              <div className="ah-spell-distinction">
                <strong>Full alarm spell: {selectedSpell.months} months</strong>
                <p>
                  {selectedContainsLongest && longest ? (
                    <>
                      Known-false stretch:{' '}
                      <b>
                        {longest.leftCensored || longest.rightCensored ? 'at least ' : ''}
                        {longest.months} months
                      </b>
                      , {month(longest.start)}–{month(longest.end)}.{' '}
                      {longest.rightBoundary === 'pending-outcome'
                        ? 'The following alarm outcomes remain pending.'
                        : 'This is a subset of the full alarm spell.'}
                    </>
                  ) : (
                    <>
                      The spell duration includes all alarm months. Only mature months can be classified as
                      false or recession-positive.
                    </>
                  )}
                </p>
              </div>
              <dl className="ah-spell-counts">
                <div>
                  <dt>False-warning months</dt>
                  <dd>{selectedSpell.falseMonths}</dd>
                </div>
                <div>
                  <dt>Recession-positive months</dt>
                  <dd>{selectedSpell.positiveMonths}</dd>
                </div>
                <div>
                  <dt>Pending-outcome months</dt>
                  <dd>{selectedSpell.pendingMonths}</dd>
                </div>
              </dl>
              <div className="ah-boundaries">
                <strong>
                  {selectedSpell.leftCensored || selectedSpell.rightCensored
                    ? 'Boundary-limited duration'
                    : 'Observed spell boundaries'}
                </strong>
                <span>Start: {formatBoundary(selectedSpell.leftBoundary)}</span>
                <span>End: {formatBoundary(selectedSpell.rightBoundary)}</span>
                <p>
                  {selectedSpell.leftCensored || selectedSpell.rightCensored
                    ? 'The full warning run can extend beyond the observed signal boundary. The displayed duration is the observed segment.'
                    : 'Adjacent observed non-alarm months delimit this run.'}
                </p>
              </div>
              <button className="ah-export-selected" onClick={() => exportCsv(selectedSpell.id)}>
                <ArrowDownToLine size={14} /> Download this spell
              </button>
            </section>
          ) : (
            <div className="ah-no-spell">
              <h3>{selectedMonth ? 'No alarm spell here.' : 'No spell at this setting.'}</h3>
              <p>
                {selectedMonth?.alarm === null
                  ? 'The alarm signal is unavailable for this issue; this gap breaks continuity.'
                  : 'Select a colored alarm month or a row below to inspect consecutive warnings.'}
              </p>
            </div>
          )}
        </aside>
      </div>
      <AlarmRuleComparison data={data} threshold={threshold} rule={rule} setRule={setRule} />
      <section className="ah-spells-section">
        <div className="ah-section-heading">
          <div>
            <div className="ah-eyebrow">SPELL REGISTER</div>
            <h2>Alarm spells by date</h2>
            <p>Most recent spells first. Select a date range for details.</p>
          </div>
          <label className="ah-filter">
            <span className="ah-sr">Filter by spell outcome</span>
            <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
              <option value="all">All outcomes</option>
              <option value="false">False warnings only</option>
              <option value="mixed">Mixed outcomes</option>
              <option value="positive">Recession-positive</option>
              <option value="pending">Outcomes pending</option>
            </select>
            <ChevronDown size={14} />
          </label>
        </div>
        <div className="ah-spells-table-wrap">
          <table className="ah-spells-table">
            <thead>
              <tr>
                <th>Alarm spell</th>
                <th>Months</th>
                <th>Forward outcomes</th>
                <th>False</th>
                <th>Positive</th>
                <th>Pending</th>
                <th>Coverage</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((spell) => (
                <tr key={spell.id} className={selectedSpell?.id === spell.id ? 'ah-active-row' : ''}>
                  <td>
                    <button
                      onClick={() => selectSpell(spell.id)}
                      aria-pressed={selectedSpell?.id === spell.id}
                    >
                      {month(spell.start)} – {month(spell.end)}
                    </button>
                  </td>
                  <td>{spell.months}</td>
                  <td>
                    <span className={`ah-class-${spell.classification}`}>
                      {classLabels[spell.classification]}
                    </span>
                  </td>
                  <td>{spell.falseMonths}</td>
                  <td>{spell.positiveMonths}</td>
                  <td>{spell.pendingMonths}</td>
                  <td>
                    {spell.leftCensored || spell.rightCensored ? 'Boundary-limited' : 'Observed boundaries'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <p className="ah-empty">No spells match this outcome filter at the selected threshold.</p>
          )}
        </div>
      </section>
      <div className="ah-maturity">
        <CircleHelp size={17} />
        <p>
          <strong>{audit.stats.pendingAlarmMonths} alarm months have pending outcomes.</strong> Across the
          supplied calendar, {audit.coverage.pendingOutcomeMonths} issue outcomes are still unknown,{' '}
          {audit.coverage.missingCalendarMonths} calendar months are absent, and{' '}
          {audit.coverage.missingSignalMonths} issue signals are unavailable. Unknown outcomes are never
          filled with zero. A mixed spell contains both positive and false mature months; a spell with any
          pending months remains pending overall.
        </p>
      </div>
      <details className="ah-method">
        <summary>
          Spell definitions and interpretation <ChevronDown size={16} />
        </summary>
        <div>
          <p>
            <strong>Continuity comes from calendar months.</strong> A spell is a maximal run of consecutive
            available issues with an active alarm. A quiet issue or unavailable signal ends the observed run.
            Missing outcome labels do not prevent an alarm from being recorded, but prevent that month from
            being scored.
          </p>
          <p>
            <strong>“False” concerns a forward target.</strong> A false-warning month has an alarm and a fully
            observed target of zero. A positive-warning month has a target of one. These are not dates when a
            recession necessarily occurred. The longest false stretch can sit inside a longer mixed or pending
            spell.
          </p>
          <p>
            <strong>Boundaries matter.</strong> A run touching the dataset edge or a missing-signal gap is
            censored: its complete duration is not observed. Pending spells have incomplete outcome maturity
            even when their signal boundaries are known.
          </p>
          <p>
            <strong>Research limits remain.</strong> Data and recession dating are revised retrospectively.
            Overlapping twelve-month targets and repeated warnings are not independent predictions. The
            interaction and confirmation rules remain exploratory; a spell register is not a trading backtest,
            and no return is inferred.
          </p>
        </div>
      </details>
    </div>
  );
}
