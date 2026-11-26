'use client';

import { useMemo } from 'react';
import { ArrowDownToLine, ChevronDown, CircleHelp } from 'lucide-react';
import type { Snapshot } from '../lib/types';
import { deriveProbabilityAudit, probabilityAuditCsv } from '../lib/probability-audit';
import { useProbabilitySelection } from './use-probability-selection';
import './probability-audit.css';

type Method = 'original' | 'prequential' | 'base' | 'fixedBlend';
const methods: { id: Method; label: string; description: string }[] = [
  { id: 'original', label: 'Original model', description: 'Three-signal logistic forecast' },
  {
    id: 'prequential',
    label: 'Past-fitted blend',
    description: 'Weight fitted to earlier eligible forecasts',
  },
  { id: 'base', label: 'Historical base rate', description: 'Expanding training-sample prevalence' },
  { id: 'fixedBlend', label: 'Fixed 50/50 blend', description: 'Equal original-model and base-rate weights' },
];
const probabilityKeys = {
  original: 'originalProbability',
  prequential: 'prequentialProbability',
  base: 'baselineProbability',
  fixedBlend: 'fixedBlendProbability',
} as const;

function percent(value: number | null | undefined, digits = 1) {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(digits)}%` : '—';
}

function decimal(value: number | null | undefined, digits = 4) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
}

function month(value: string | null | undefined) {
  return value
    ? new Date(value.slice(0, 7) + '-15T12:00:00Z').toLocaleDateString('en-US', {
        month: 'short',
        year: 'numeric',
        timeZone: 'UTC',
      })
    : '—';
}

export default function ProbabilityAudit({ data }: { data: Snapshot }) {
  const audit = useMemo(() => deriveProbabilityAudit(data), [data]);
  const { method, selectedBand, setMethod, setSelectedBand } = useProbabilitySelection(audit);
  const bands = audit.bins[method];
  const band = bands[selectedBand] ?? bands[0];
  const activeMethod = methods.find((item) => item.id === method)!;
  const learnedBrier = audit.metrics.prequential.brier;
  const baseBrier = audit.metrics.base.brier;
  const high = audit.bins.original[4];
  const trailsBase = learnedBrier !== null && baseBrier !== null && learnedBrier > baseBrier;
  const selectedRows = band
    ? audit.rows.filter((row) => {
        const probability = row[probabilityKeys[method]];
        return (
          row.target !== null &&
          probability !== null &&
          probability >= band.lower &&
          (probability < band.upper || (band.upperInclusive && probability === band.upper))
        );
      })
    : [];

  function download(selectedOnly = false) {
    const csv = probabilityAuditCsv(audit, { method, ...(selectedOnly ? { bin: band.id } : {}) });
    const url = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `horizon-probability-${method}${selectedOnly ? `-band-${band.id}` : ''}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <div className="probability-audit">
      <header className="pa-heading">
        <div>
          <div className="pa-eyebrow">PROBABILITY AUDIT</div>
          <h1>What followed a high recession forecast?</h1>
          <p>
            {high.n ? (
              <>
                When the original model put the risk at 80% or higher, its average forecast was{' '}
                <strong>{percent(high.meanPredicted)}</strong>. A recession appeared in the next twelve months
                for{' '}
                <strong>
                  {high.positiveWindows} of {high.n} issues
                </strong>{' '}
                ({percent(high.observedRate)}).
              </>
            ) : (
              'Compare forecasts with the share of subsequent twelve-month windows that contained a U.S. recession.'
            )}
          </p>
        </div>
        <button className="pa-download" onClick={() => download()}>
          <ArrowDownToLine size={16} />
          Download issue-level CSV
        </button>
      </header>

      <section className="pa-current" aria-label="Current illustrative probabilities">
        <div className="pa-current-label">
          <span className="pa-eyebrow">CURRENT ILLUSTRATION</span>
          <p>
            {month(data.meta.forecastStart as string)} – {month(data.meta.forecastEnd as string)}
          </p>
          <small>Unobserved forward outcome</small>
        </div>
        {methods.map((item) => (
          <div className={item.id === 'prequential' ? 'pa-current-learned' : ''} key={item.id}>
            <span>{item.label}</span>
            <strong>{percent(audit.current[probabilityKeys[item.id]], 2)}</strong>
          </div>
        ))}
      </section>
      <p className="pa-current-note">
        {audit.current.status === 'available' &&
        audit.current.weight !== null &&
        audit.current.foldYear !== null ? (
          <>
            Inputs are from {month(audit.current.featureDate)}. The past-fitted blend assigns the original
            model a weight of <strong>{percent(audit.current.weight)}</strong> from the{' '}
            {audit.current.foldYear} January fit. The forecast window is still open.
          </>
        ) : (
          <>The current blend illustration is unavailable. {audit.current.note}</>
        )}
      </p>

      <section className="pa-band-section">
        <div className="pa-section-heading">
          <div>
            <h2>Forecasts and outcomes by probability band</h2>
            <p>Choose a method and inspect a probability band. Each issue counts once within that method.</p>
          </div>
        </div>
        <div className="pa-methods" role="group" aria-label="Probability method">
          {methods.map((item) => (
            <button
              key={item.id}
              aria-pressed={method === item.id}
              className={method === item.id ? 'selected' : ''}
              onClick={() => setMethod(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="pa-band-layout">
          <div className="pa-chart-column">
            <div className="pa-chart-legend">
              <span>
                <i /> Mean forecast
              </span>
              <span>
                <i /> Observed frequency
              </span>
              <small>{activeMethod.label}</small>
            </div>
            <div className="pa-band-chart">
              <div className="pa-y-axis" aria-hidden="true">
                {[100, 75, 50, 25, 0].map((value, index) => (
                  <span key={value} style={{ top: `${index * 25}%` }}>
                    {value}%
                  </span>
                ))}
              </div>
              <div className="pa-bin-grid" role="group" aria-label="Select a forecast probability band">
                {bands.map((item) => (
                  <button
                    key={item.id}
                    className={`pa-bin ${item.id === band.id ? 'selected' : ''} ${item.n === 0 ? 'pa-empty-bin' : ''}`}
                    aria-pressed={item.id === band.id}
                    onClick={() => setSelectedBand(item.id)}
                    aria-label={`${Math.round(item.lower * 100)} to ${Math.round(item.upper * 100)} percent band: ${item.n} issues; mean forecast ${percent(item.meanPredicted)}; observed frequency ${percent(item.observedRate)}`}
                  >
                    <span className="pa-bin-count">
                      {item.n} <small>issues</small>
                    </span>
                    <span className="pa-bars" aria-hidden="true">
                      {item.n > 0 ? (
                        <>
                          <i
                            className="pa-predicted-bar"
                            style={{ height: `${(item.meanPredicted ?? 0) * 100}%` }}
                          />
                          <i
                            className="pa-observed-bar"
                            style={{ height: `${(item.observedRate ?? 0) * 100}%` }}
                          />
                        </>
                      ) : (
                        <span className="pa-no-data">Empty</span>
                      )}
                    </span>
                    <span className="pa-bin-label">
                      {Math.round(item.lower * 100)}–<wbr />{Math.round(item.upper * 100)}%
                    </span>
                    <small className="pa-bin-status">{item.n > 0 && item.n < 20 ? 'Few issues' : ''}</small>
                  </button>
                ))}
              </div>
            </div>
            <p className="pa-note">
              Bars summarize scored forecasts, not future confidence limits. Bands are 20 percentage points
              wide; exactly 100% belongs to the final band. “Few issues” means fewer than 20 rows, not a
              statistical significance test.
            </p>
          </div>

          <aside className="pa-band-inspector" aria-live="polite">
            <div className="pa-eyebrow">SELECTED BAND</div>
            <h3>
              {Math.round(band.lower * 100)}–{Math.round(band.upper * 100)}%
            </h3>
            <span className="pa-inspector-method">{activeMethod.label}</span>
            <strong className="pa-band-n">
              {band.n}
              <small>scored issues</small>
            </strong>
            <dl>
              <div>
                <dt>Mean forecast</dt>
                <dd>{percent(band.meanPredicted)}</dd>
              </div>
              <div>
                <dt>Observed frequency</dt>
                <dd>{percent(band.observedRate)}</dd>
              </div>
              <div>
                <dt>Positive windows</dt>
                <dd>{band.positiveWindows}</dd>
              </div>
              <div>
                <dt>Brier within band</dt>
                <dd>{decimal(band.brier)}</dd>
              </div>
            </dl>
            <p>
              {band.n === 0
                ? 'No scored issues fall in this band. Missing estimates remain blank; they are not zero-frequency observations.'
                : band.n < 20
                  ? 'This band has few issues. Overlapping horizons further reduce the independent evidence.'
                  : 'Several monthly issues can share one eventual downturn. A larger row count does not create that many independent events.'}
            </p>
            <button disabled={!band.n} className="pa-band-download" onClick={() => download(true)}>
              <ArrowDownToLine size={14} /> Download this band
            </button>
          </aside>
        </div>
      </section>

      <section className="pa-score-section">
        <div className="pa-section-heading">
          <div>
            <h2>Did learning the weight improve the forecast?</h2>
          </div>
          <span>
            {month(audit.metrics.start)} – {month(audit.metrics.end)}
          </span>
        </div>
        <div className="pa-score-layout">
          <div className="pa-table-wrap">
            <table className="pa-score-table">
              <thead>
                <tr>
                  <th>Method</th>
                  <th>Brier score</th>
                  <th>Skill vs. base</th>
                </tr>
              </thead>
              <tbody>
                {methods.map((item) => (
                  <tr key={item.id} className={item.id === 'prequential' ? 'pa-emphasis' : ''}>
                    <td>{item.label}</td>
                    <td>{decimal(audit.metrics[item.id].brier)}</td>
                    <td>
                      {baseBrier && audit.metrics[item.id].brier !== null
                        ? percent(1 - audit.metrics[item.id].brier! / baseBrier)
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <aside className="pa-score-readout">
            <strong>
              {trailsBase ? 'The base rate beat the fitted blend.' : 'Performance against the base rate'}
            </strong>
            <p>
              Brier score measures mean squared probability error. Skill gives the percentage reduction in
              that error relative to the expanding base rate. Negative skill means larger errors.
            </p>
            <p>
              The fixed 50/50 strategy was proposed after the historical errors were visible. Its score
              describes this replay.
            </p>
          </aside>
        </div>
        <div className="pa-coverage">
          <span>
            <strong>{audit.metrics.n}</strong> common scored issues
          </span>
          <span>
            <strong>{audit.metrics.positiveWindows}</strong> recession-positive windows
          </span>
          <span>
            <strong>{audit.coverage.excludedWarmupMatureRows}</strong> mature issues excluded for warm-up
          </span>
          <span>
            <strong>{audit.coverage.unknownTargetRows}</strong> unknown forward outcomes
          </span>
        </div>
      </section>

      <section className="pa-issue-section">
        <div className="pa-section-heading">
          <div>
            <h2>Forecast months in the selected band</h2>
            <p>
              {activeMethod.description} · {selectedRows.length} scored issues in the selected band.
            </p>
          </div>
        </div>
        <div className="pa-issue-scroll">
          <table className="pa-issue-table">
            <thead>
              <tr>
                <th>Issue month</th>
                <th>Forecast</th>
                <th>Forward target</th>
                <th>Applied original-model weight</th>
                <th>Learned-weight training ended</th>
              </tr>
            </thead>
            <tbody>
              {selectedRows.map((row) => (
                <tr key={row.date}>
                  <td>{month(row.date)}</td>
                  <td>{percent(row[probabilityKeys[method]])}</td>
                  <td>{row.target === 1 ? 'Recession present' : 'No recession'}</td>
                  <td>
                    {percent(
                      method === 'original'
                        ? 1
                        : method === 'base'
                          ? 0
                          : method === 'fixedBlend'
                            ? 0.5
                            : row.weight,
                    )}
                  </td>
                  <td>{method === 'prequential' ? month(row.trainEnd) : 'Not applicable'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!selectedRows.length && <p className="pa-empty-message">No scored issues in this band.</p>}
        </div>
      </section>

      <div className="pa-caveat">
        <CircleHelp size={17} />
        <p>
          <strong>A past-only fit within a post-hoc experiment.</strong> This adjustment rule was proposed
          after viewing historical failures. Annual sequencing protects each weight fit from later targets; it
          does not turn the overall research idea into untouched evidence. Revised source history,
          retrospective NBER dates, and overlapping twelve-month targets remain limitations.
        </p>
      </div>

      <details className="pa-protocol">
        <summary>
          How the weight is fitted, and what was excluded <ChevronDown size={17} />
        </summary>
        <div className="pa-protocol-copy">
          <p>
            <strong>One fixed adjustment rule.</strong> Each January, fit q = b + w(p − b), where p is the
            original forecast and b is its historical base rate. Choose w between 0 and 1 to minimize squared
            error on earlier eligible forecast/target pairs. The minimum training history is{' '}
            {audit.minimumTrainingMonths} issues. A weight of zero uses the base rate; one uses the original
            model.
          </p>
          <p>
            <strong>Respect the forward clock.</strong> Only earlier annual forecasts with a fully known
            twelve-month target ending strictly before the January refit are eligible. The selected weight is
            held fixed during that calendar year. Insufficient-history folds do not produce an evaluated
            adjustment; if the two inputs are identical, the documented fallback is the base rate.
          </p>
          <p>
            <strong>Compare the same later issues.</strong> All score rows and probability bands use the
            common post-warm-up mature sample. Unknown future outcomes remain unknown. The source audit masks{' '}
            {audit.coverage.maskedFutureTargetRows} targets beyond the published label cutoff and reports{' '}
            {audit.coverage.nonAnnualRows} non-annual rows, {audit.coverage.missingProbabilityRows} incomplete
            probability rows, {audit.coverage.invalidDateRows} invalid dates, {audit.coverage.futureDateRows}{' '}
            future issue dates, and {audit.coverage.duplicateDateRows} duplicate dates separately.
          </p>
          <p>
            <strong>Current values are an illustration.</strong> The current display applies the applicable
            January weight to the current original-model/base-rate inputs. Its outcome is unobserved and it
            does not rewrite a frozen forecast receipt. Inspect the fold dates below and download individual
            issues to audit the historical scores.
          </p>
        </div>
        <div className="pa-table-wrap pa-fold-table-wrap">
          <table className="pa-fold-table">
            <thead>
              <tr>
                <th>January refit</th>
                <th>Eligible N</th>
                <th>Training issue end</th>
                <th>Last training target month</th>
                <th>Original weight</th>
                <th>Fit state</th>
              </tr>
            </thead>
            <tbody>
              {audit.folds.map((fold) => (
                <tr key={fold.year}>
                  <td>{month(fold.refitDate)}</td>
                  <td>{fold.trainingN}</td>
                  <td>{month(fold.trainEnd)}</td>
                  <td>{month(fold.lastTargetMonth)}</td>
                  <td>{percent(fold.weight)}</td>
                  <td>
                    {fold.status === 'fit'
                      ? 'Fitted'
                      : fold.status === 'degenerate-base'
                        ? 'Base-rate fallback'
                        : 'History too short'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
