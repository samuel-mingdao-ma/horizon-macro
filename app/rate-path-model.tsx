'use client';

import { useEffect, useState } from 'react';
import { ArrowDownToLine, ChevronDown, CircleHelp, ShieldCheck } from 'lucide-react';
import type { Snapshot } from '../lib/types';
import type { RatePathCohort, RatePathMethod } from '../lib/rate-path-types';
import { ForecastStability } from './forecast-stability';
import './rate-path-model.css';

const methods: { id: RatePathMethod; label: string; detail: string }[] = [
  {
    id: 'recentBlend',
    label: 'Recent-prior 50/50',
    detail: 'Original model + recent 15-year forward-target prevalence',
  },
  { id: 'candidate', label: 'Fixed rate-path trial', detail: '50% five-input model + 50% its training base' },
  { id: 'rawFive', label: 'Raw five-input model', detail: 'Original signals plus two changes in rates' },
  { id: 'original', label: 'Original model', detail: 'Curve, credit, and labor' },
  { id: 'existingBlend', label: 'Existing fixed 50/50', detail: 'Original model + its historical base rate' },
  { id: 'base', label: 'Historical base rate', detail: 'Established original-model training prevalence' },
  {
    id: 'recentPrior',
    label: 'Recent prior alone',
    detail: 'Positive forward horizons among eligible 15-year training issues',
  },
];

function number(value: number | null | undefined, digits = 4) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
}

function percent(value: number | null | undefined, digits = 1) {
  return typeof value === 'number' && Number.isFinite(value) ? `${(100 * value).toFixed(digits)}%` : '—';
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

function previousMonth(value: string, offset: number) {
  const [year, dateMonth] = value.slice(0, 7).split('-').map(Number);
  return new Date(Date.UTC(year, dateMonth - 1 + offset, 1)).toISOString().slice(0, 10);
}

function delta(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${value > 0 ? '+' : ''}${value.toFixed(4)}`
    : '—';
}

function comparison(
  cohort: RatePathCohort,
  benchmark: 'base' | 'existingBlend' | 'recentPrior',
  method: 'candidate' | 'recentBlend' = 'candidate',
) {
  const candidate = cohort.models[method].brier;
  const reference = cohort.models[benchmark].brier;
  return candidate !== null && reference !== null ? candidate - reference : null;
}

export default function RatePathModel({ data }: { data: Snapshot }) {
  const [selectedId, setSelectedId] = useState('all');
  useEffect(() => {
    const sync = () => {
      const [route, query] = window.location.hash.slice(1).split('?');
      if (route === 'forecast') setSelectedId(new URLSearchParams(query).get('period') || 'all');
    };
    sync();
    window.addEventListener('hashchange', sync);
    window.addEventListener('popstate', sync);
    return () => {
      window.removeEventListener('hashchange', sync);
      window.removeEventListener('popstate', sync);
    };
  }, []);
  function selectPeriod(id: string) {
    setSelectedId(id);
    window.history.replaceState(window.history.state, '', '#forecast?period=' + encodeURIComponent(id));
  }
  const ratePath = data.ratePath;
  if (!ratePath) {
    return (
      <section className="rate-path-model">
        <header className="rt-heading">
          <div>
            <div className="rt-eyebrow">FORECAST TRIAL</div>
            <h1>The rate-path trial is not available.</h1>
            <p>
              The current snapshot does not contain this experiment. Existing model evidence remains available
              in the research desk.
            </p>
          </div>
        </header>
      </section>
    );
  }

  const cohorts = [ratePath.metrics.all, ratePath.metrics.recent, ...ratePath.metrics.decades];
  const selectedCohort = cohorts.find((cohort) => cohort.id === selectedId) ?? ratePath.metrics.all;
  const current = ratePath.latest;
  const prospective = ratePath.prospective;
  const receipt = prospective?.latestReceipt;
  const candidateBrier = selectedCohort.models.candidate.brier;
  const baseDifference = comparison(selectedCohort, 'base');
  const blendDifference = comparison(selectedCohort, 'existingBlend');
  const recentBaseDifference = comparison(selectedCohort, 'base', 'recentBlend');
  const recentBlendDifference = comparison(selectedCohort, 'existingBlend', 'recentBlend');
  const recentOwnDifference = comparison(selectedCohort, 'recentPrior', 'recentBlend');
  const recentClears =
    recentBaseDifference !== null &&
    recentBlendDifference !== null &&
    recentOwnDifference !== null &&
    recentBaseDifference < 0 &&
    recentBlendDifference < 0 &&
    recentOwnDifference < 0;
  const beatsBoth =
    baseDifference !== null && blendDifference !== null && baseDifference < 0 && blendDifference < 0;
  const chartMaximum =
    Math.max(0.2, ...methods.map((method) => selectedCohort.models[method.id].brier ?? 0)) * 1.12;
  const currentValues: Record<RatePathMethod, number | null> = {
    recentBlend: current.recentBlendProbability,
    recentPrior: current.recentPriorProbability,
    candidate: current.probability,
    rawFive: current.rawProbability,
    original: current.originalProbability,
    existingBlend: current.existingBlendProbability,
    base:
      current.originalBaseProbability === undefined
        ? current.baselineProbability
        : current.originalBaseProbability,
  };

  return (
    <div className="rate-path-model">
      <header className="rt-heading">
        <div>
          <div className="rt-eyebrow">FORECAST TRIAL · FIXED RECIPE</div>
          <h1>Can we improve the one-year recession forecast?</h1>
          <p>
            Compare two changes to the existing 50/50 forecast. One adds movements in interest rates. The
            other gives more weight to the frequency of recession exposure over the past 15 years.
          </p>
        </div>
        <a className="rt-download" href="/api/download?file=ratepath">
          <ArrowDownToLine size={16} /> Download issue-level CSV
        </a>
      </header>

      <section className="rt-current" aria-label="Comparable current-month estimates">
        <div className="rt-current-header">
          <div>
            <span className="rt-eyebrow">CURRENT MONTH · OUTCOME UNOBSERVED</span>
            <h2>
              {month(current.forecastStart)} – {month(current.forecastEnd)}
            </h2>
          </div>
          <span>
            Issue {month(current.issueDate)} · signals {month(current.featureDate)}
          </span>
        </div>
        <div className="rt-current-values">
          {methods
            .filter((method) => ['candidate', 'recentBlend', 'existingBlend'].includes(method.id))
            .map((method) => (
              <div
                key={method.id}
                className={method.id === 'candidate' || method.id === 'recentBlend' ? 'rt-trial-value' : ''}
              >
                <span>{method.label}</span>
                <strong>{percent(currentValues[method.id], 2)}</strong>
              </div>
            ))}
        </div>
        <details className="rt-current-detail">
          <summary>
            Other current estimates and prior inputs <ChevronDown size={15} />
          </summary>
          <div className="rt-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Current comparator</th>
                  <th>Probability</th>
                </tr>
              </thead>
              <tbody>
                {methods
                  .filter((method) => !['candidate', 'recentBlend', 'existingBlend'].includes(method.id))
                  .map((method) => (
                    <tr key={method.id}>
                      <td>{method.label}</td>
                      <td>{percent(currentValues[method.id])}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <p className="rt-note">
            The recent prior uses {current.recentPriorN} eligible forecast issues in the fixed calendar window{' '}
            {month(current.recentPriorStart)}–{month(current.recentPriorEnd)}. It measures positive
            next-twelve-month horizons, not the percentage of months actually spent in recession.
          </p>
        </details>
        <p className="rt-meta">
          The five-input model used {current.trainingN} training issues through{' '}
          {month(current.trainedThrough)}. Current estimates are refitted monthly. Historical estimates below
          are refitted each January.
        </p>
      </section>

      <section className="rt-evidence" aria-labelledby="rt-evidence-title">
        <div className="rt-section-heading">
          <div>
            <div className="rt-eyebrow">SAME DATES · SAME FORWARD TARGET</div>
            <h2 id="rt-evidence-title">Which forecast had smaller errors?</h2>
          </div>
        </div>
        <div className="rt-cohorts" role="group" aria-label="Evaluation period">
          {[ratePath.metrics.all, ratePath.metrics.recent].map((cohort) => (
            <button
              key={cohort.id}
              className={selectedCohort.id === cohort.id ? 'selected' : ''}
              aria-pressed={selectedCohort.id === cohort.id}
              onClick={() => selectPeriod(cohort.id)}
            >
              {cohort === ratePath.metrics.all ? 'Full common history' : 'Since 2016'}
            </button>
          ))}
          {ratePath.metrics.decades.length > 0 && (
            <label className="rt-decade-select">
              <span className="rt-sr">Fixed decade slice</span>
              <select
                value={
                  ratePath.metrics.decades.some((cohort) => cohort.id === selectedCohort.id)
                    ? selectedCohort.id
                    : ''
                }
                onChange={(event) => {
                  if (event.target.value) selectPeriod(event.target.value);
                }}
              >
                <option value="">Fixed decade slices</option>
                {ratePath.metrics.decades.map((cohort) => (
                  <option key={cohort.id} value={cohort.id}>
                    {cohort.label}
                  </option>
                ))}
              </select>
              <ChevronDown size={14} />
            </label>
          )}
        </div>
        <div className="rt-cohort-meta">
          <span>
            {month(selectedCohort.start)} – {month(selectedCohort.end)}
          </span>
          <span>
            {selectedCohort.n} mature common issues · {selectedCohort.positiveWindows} recession-positive
            windows
          </span>
        </div>
        <div className="rt-score-workspace">
          <div
            className="rt-brier-chart"
            role="group"
            aria-label="Brier probability error comparison. Lower values are better."
          >
            <div className="rt-chart-heading">
              <span>Brier probability error</span>
              <small>Lower is better</small>
            </div>
            {methods.map((method) => {
              const score = selectedCohort.models[method.id].brier;
              return (
                <div
                  className={`rt-brier-row ${method.id === 'candidate' ? 'rt-brier-trial' : method.id === 'recentBlend' ? 'rt-brier-recent' : ''}`}
                  key={method.id}
                >
                  <div>
                    <span>{method.label}</span>
                    <strong>{number(score)}</strong>
                  </div>
                  <div className="rt-brier-track" aria-hidden="true">
                    <i style={{ width: score === null ? '0%' : `${(score / chartMaximum) * 100}%` }} />
                  </div>
                </div>
              );
            })}
            <p className="rt-note">
              All bars start at zero. A smaller bar means lower average squared probability error.
            </p>
          </div>
          <aside className="rt-verdict" aria-live="polite">
            <span className="rt-eyebrow">VERDICT FOR THIS SLICE</span>
            <h3>
              {selectedCohort.n === 0
                ? 'No mature comparison.'
                : beatsBoth && recentClears
                  ? 'Both trials beat their benchmarks in this period.'
                  : beatsBoth
                    ? 'The rate-path blend beat both benchmarks in this period.'
                    : recentClears
                      ? 'The recent-base blend beat its benchmarks in this period.'
                      : 'Neither trial beat all its benchmarks.'}
            </h3>
            <p>
              The rate-path blend scores {number(candidateBrier)}: <strong>{delta(baseDifference)}</strong>{' '}
              versus the established base and <strong>{delta(blendDifference)}</strong> versus the existing
              50/50.
            </p>
            <p>
              The recent-prior blend scores {number(selectedCohort.models.recentBlend.brier)}:{' '}
              <strong>{delta(recentBlendDifference)}</strong> versus the existing blend and{' '}
              <strong>{delta(recentOwnDifference)}</strong> versus its recent prior alone.
            </p>
            <p>
              Negative differences favor the trial. A historical win alone does not justify a prospective
              accuracy claim.
            </p>
          </aside>
        </div>
        <div className="rt-table-wrap">
          <table className="rt-score-table">
            <thead>
              <tr>
                <th>Method</th>
                <th>
                  Brier <small>primary · lower</small>
                </th>
                <th>
                  Log loss <small>lower</small>
                </th>
                <th>
                  AUC <small>higher</small>
                </th>
              </tr>
            </thead>
            <tbody>
              {methods.map((method) => (
                <tr
                  key={method.id}
                  className={method.id === 'candidate' || method.id === 'recentBlend' ? 'rt-emphasis' : ''}
                >
                  <td>
                    <strong>{method.label}</strong>
                    <small>{method.detail}</small>
                  </td>
                  <td>{number(selectedCohort.models[method.id].brier)}</td>
                  <td>{number(selectedCohort.models[method.id].logLoss)}</td>
                  <td>{number(selectedCohort.models[method.id].auc, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="rt-gates">
          <h3>Results across the two evaluation periods</h3>
          <div className="rt-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Hypothesis / period</th>
                  <th>Blend Brier</th>
                  <th>Existing 50/50</th>
                  <th>Established base</th>
                  <th>Own prior</th>
                  <th>Clears checks?</th>
                </tr>
              </thead>
              <tbody>
                {[ratePath.metrics.all, ratePath.metrics.recent].flatMap((cohort) =>
                  (['candidate', 'recentBlend'] as const).map((method) => {
                    const versusBase = comparison(cohort, 'base', method),
                      versusBlend = comparison(cohort, 'existingBlend', method);
                    const versusOwn =
                      method === 'recentBlend' ? comparison(cohort, 'recentPrior', method) : null;
                    const available = cohort.n > 0 && versusBase !== null && versusBlend !== null;
                    const clears =
                      available &&
                      versusBase! < 0 &&
                      versusBlend! < 0 &&
                      (method === 'candidate' || (versusOwn !== null && versusOwn < 0));
                    return (
                      <tr key={cohort.id + method}>
                        <td>
                          {method === 'candidate' ? 'Rate-path' : 'Recent-prior'} ·{' '}
                          {cohort === ratePath.metrics.all ? 'all history' : 'since 2016'}
                        </td>
                        <td>{number(cohort.models[method].brier)}</td>
                        <td>{number(cohort.models.existingBlend.brier)}</td>
                        <td>{number(cohort.models.base.brier)}</td>
                        <td>
                          {number(
                            method === 'recentBlend'
                              ? cohort.models.recentPrior.brier
                              : cohort.models.candidateBase?.brier,
                          )}
                        </td>
                        <td>{available ? (clears ? 'Yes, historically' : 'No') : 'Not available'}</td>
                      </tr>
                    );
                  }),
                )}
              </tbody>
            </table>
          </div>
          <p className="rt-note">
            Rate-path screening requires lower Brier than the established base and incumbent blend in both
            fixed periods. The recent-prior blend must also beat its recent prior alone to demonstrate
            incremental model contribution. Decades remain diagnostics, not a search for a favorable period.
          </p>
        </div>
      </section>

      <ForecastStability rows={ratePath.history} start={selectedCohort.start} end={selectedCohort.end} />

      <section className="rt-signals">
        <div className="rt-section-heading">
          <div>
            <div className="rt-eyebrow">THE TWO ADDITIONAL INPUTS</div>
            <h2>Changes in interest rates at issuance</h2>
          </div>
        </div>
        <div className="rt-signal-grid">
          <article>
            <span>Six-month change in the term spread</span>
            <strong>
              {current.features.slopeChange6 > 0 ? '+' : ''}
              {number(current.features.slopeChange6, 2)}
              <small> pp</small>
            </strong>
            <p>
              10Y minus 3M slope in {month(current.featureDate)}, less its value in{' '}
              {month(previousMonth(current.featureDate, -6))}.
            </p>
          </article>
          <article>
            <span>Twelve-month change in the policy rate</span>
            <strong>
              {current.features.fedFundsChange12 > 0 ? '+' : ''}
              {number(current.features.fedFundsChange12, 2)}
              <small> pp</small>
            </strong>
            <p>
              Monthly effective federal funds rate in {month(current.featureDate)}, less its value in{' '}
              {month(previousMonth(current.featureDate, -12))}.
            </p>
          </article>
        </div>
        <p className="rt-note">
          All five inputs use the common signal month, two months before forecast issuance. A change in the
          spread can reflect movements at either end of the curve. These fitted associations are not estimates
          of what a policy move causes.
        </p>
      </section>

      <section className="rt-prospective">
        <div className="rt-section-heading">
          <div>
            <div className="rt-eyebrow">SEPARATE PROSPECTIVE TRIAL</div>
            <h2>Frozen forecasts and realized outcomes</h2>
          </div>
          <a href="/api/download?file=ratepathreceipts" className="rt-text-link">
            <ArrowDownToLine size={15} /> Download trial receipts
          </a>
        </div>
        <div className="rt-receipt-status">
          <ShieldCheck size={21} />
          <div>
            <strong>
              {prospective?.receiptCount ?? 0} frozen{' '}
              {prospective?.receiptCount === 1 ? 'receipt' : 'receipts'} · {prospective?.maturedCount ?? 0}{' '}
              mature {prospective?.maturedCount === 1 ? 'outcome' : 'outcomes'}
            </strong>
            <p>
              {(prospective?.maturedCount ?? 0) === 0
                ? 'No prospective performance result is available. A complete twelve-month outcome is required before scoring.'
                : 'Only complete, actually published forward outcomes enter the prospective scores.'}
            </p>
          </div>
          <span>{prospective?.chainValid ? 'Hash chain consistent' : 'Chain not verified'}</span>
        </div>
        {prospective && prospective.maturedCount > 0 && (
          <div className="rt-table-wrap">
            <table>
              <caption>Scores on the same mature frozen forecasts</caption>
              <thead>
                <tr>
                  <th>Recorded forecast</th>
                  <th>Count</th>
                  <th>Brier</th>
                  <th>Log loss</th>
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    ['Original model', 'original'],
                    ['Existing fixed 50/50', 'existingBlend'],
                    ['Historical base rate', 'historicalBase'],
                    ['Raw five-input model', 'candidateRaw'],
                    ['Rate-path blend', 'candidateBlend'],
                    ['15-year base rate', 'recentPrior'],
                    ['Recent-base blend', 'recentBlend'],
                  ] as const
                ).map(([label, key]) => {
                  const score = prospective.metrics[key];
                  return (
                    <tr key={key}>
                      <td>{label}</td>
                      <td>{score?.n ?? 0}</td>
                      <td>{number(score?.brier)}</td>
                      <td>{number(score?.logLoss)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {receipt ? (
          <>
            <dl className="rt-receipt-dates">
              <div>
                <dt>Actual capture</dt>
                <dd>
                  {new Date(receipt.recordedAt).toLocaleString('en-US', {
                    timeZone: 'America/New_York',
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric',
                    hour: 'numeric',
                    minute: '2-digit',
                  })}{' '}
                  ET
                </dd>
              </div>
              <div>
                <dt>Frozen window / source month</dt>
                <dd>
                  {month(receipt.forecastStart)} – {month(receipt.forecastEnd)} / {month(receipt.featureDate)}
                </dd>
              </div>
            </dl>
            <div className="rt-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Frozen comparator</th>
                    <th>Probability</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ['Original model', receipt.predictions.original],
                    ['Existing fixed 50/50', receipt.predictions.existingBlend],
                    ['Historical base rate', receipt.predictions.historicalBase],
                    ['Raw five-input model', receipt.predictions.candidateRaw],
                    ['Fixed rate-path trial', receipt.predictions.candidateBlend],
                    ['Recent prior alone', receipt.predictions.recentPrior],
                    ['Recent-prior 50/50', receipt.predictions.recentBlend],
                  ].map(([label, value]) => (
                    <tr key={String(label)}>
                      <td>{label}</td>
                      <td>{percent(Number(value))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="rt-hash">
              Receipt SHA-256{' '}
              <code title={receipt.hash}>
                {receipt.hash.slice(0, 18)}…{receipt.hash.slice(-12)}
              </code>
            </p>
          </>
        ) : (
          <p className="rt-empty">
            A frozen trial receipt has not loaded. Missing records are not reconstructed as if they were
            issued earlier.
          </p>
        )}
        <p className="rt-note">
          Current estimates above can change after data or model updates; a receipt preserves its actual
          captured values. Hash linking checks the supplied chain, not an independently trusted timestamp or
          tamper-proof history. Outcomes may be revised by the source.
        </p>
      </section>

      <div className="rt-caveat">
        <CircleHelp size={17} />
        <p>
          <strong>Experimental evidence, not model promotion.</strong> The rate-path recipe was fixed before
          its score comparison. The recent-prior hypothesis was then specified after the rate-path result,
          before scoring that second hypothesis. Neither fixed recipe removes the wider post-hoc,
          latest-vintage limitation. Annual target-window separation does not reconstruct historical data
          vintages or NBER announcement times. Twelve-month labels overlap.
        </p>
      </div>
      <details className="rt-method">
        <summary>
          Recipe, fair comparisons, and limits <ChevronDown size={17} />
        </summary>
        <div>
          <p>
            <strong>Fixed design.</strong> Add the six-month spread change and twelve-month policy-rate change
            to curve, credit, and labor. Use the same lagged twelve-month recession target and fixed-penalty
            logistic estimation. Blend the raw five-input probability equally with its own eligible training
            prevalence. No weight search is used for this trial.
          </p>
          <p>
            <strong>Second fixed hypothesis.</strong> Average the original three-input probability with the
            positive-forward-target fraction from 180 consecutive eligible calendar issues ending thirteen
            months before the formal fit. Require the full fifteen-year span and at least 120 valid observed
            issues. The window does not slide around missing labels. Compare the blend with that recent prior
            alone; a stronger prior is not proof of incremental model value.
          </p>
          <p>
            <strong>Same evaluation issues.</strong> The original model, existing fixed blend, established
            base rate, raw five-input model, and trial are compared on common mature dates. The established
            baseline can differ from the five-input model's own training prevalence because eligible training
            samples differ.
          </p>
          <p>
            <strong>Read the scoring hierarchy.</strong> Brier error is the primary comparison; log loss and
            AUC are secondary diagnostics. AUC is risk ranking, not percent accuracy. A null AUC in a
            one-class slice is unavailable, not zero. Selecting a successful decade after looking at the
            results would add selection bias.
          </p>
          <p>
            <strong>Future evidence is separate.</strong> Prospective receipts retain actual capture times and
            fixed inputs/models. Historical replay scores do not become prospective results. This site does
            not infer asset returns, profitable trading, or a causal policy effect from the trial.
          </p>
        </div>
        {(selectedCohort.models.matchedThree || selectedCohort.models.matchedThreeBlend) && (
          <div className="rt-training-controls">
            <p>
              Additional controls refit the three-input model on the five-input model's complete training
              sample. They help separate added-feature effects from changing training coverage.
            </p>
            <div className="rt-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Matched-training control</th>
                    <th>Brier</th>
                    <th>Log loss</th>
                    <th>AUC</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedCohort.models.matchedThree && (
                    <tr>
                      <td>Three-input refit</td>
                      <td>{number(selectedCohort.models.matchedThree.brier)}</td>
                      <td>{number(selectedCohort.models.matchedThree.logLoss)}</td>
                      <td>{number(selectedCohort.models.matchedThree.auc, 3)}</td>
                    </tr>
                  )}
                  {selectedCohort.models.matchedThreeBlend && (
                    <tr>
                      <td>Matched three-input 50/50</td>
                      <td>{number(selectedCohort.models.matchedThreeBlend.brier)}</td>
                      <td>{number(selectedCohort.models.matchedThreeBlend.logLoss)}</td>
                      <td>{number(selectedCohort.models.matchedThreeBlend.auc, 3)}</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </details>
    </div>
  );
}
