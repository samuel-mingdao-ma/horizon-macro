'use client';

import { useState } from 'react';
import { ArrowDownToLine, ChevronDown, CircleHelp, ShieldCheck } from 'lucide-react';
import type { Snapshot } from '../lib/types';
import type { RegimePriorMethod, RegimePriorSlice, RegimeStateId } from '../lib/regime-prior-types';
import { regimeErrorBreakdown } from '../lib/regime-annual-check';
import { RegimeAnnualCheck } from './regime-annual-check';
import './regime-prior.css';

const stateOrder: RegimeStateId[] = ['loose-low', 'loose-elevated', 'tight-low', 'tight-elevated'];
const stateLabel = (tight: boolean, labor: boolean) =>
  `${tight ? 'Tighter' : 'Looser'} credit · ${labor ? 'elevated' : 'low'} labor gap`;
const methodLabels: { key: RegimePriorMethod | 'adaptive'; label: string }[] = [
  { key: 'candidate', label: 'Fixed regime blend' },
  { key: 'adaptive', label: 'Past-fitted regime influence' },
  { key: 'fixedBlend', label: 'Existing fixed 50/50' },
  { key: 'original', label: 'Original model, unchanged' },
  { key: 'dynamicPrior', label: 'Shrunken state prior alone' },
  { key: 'recentBlend', label: 'Pooled recent-prior blend' },
  { key: 'expandingBlend', label: 'Expanding-prior blend' },
];

function percent(value: number | null | undefined, digits = 1) {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(digits)}%` : '—';
}
function number(value: number | null | undefined, digits = 4) {
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
function reduction(cohort: RegimePriorSlice, adaptive = false) {
  const incumbent = cohort.models.fixedBlend.brier;
  const candidate = (adaptive ? cohort.models.adaptive : cohort.models.candidate)?.brier;
  return typeof incumbent === 'number' && incumbent > 0 && typeof candidate === 'number'
    ? (incumbent - candidate) / incumbent
    : null;
}
function signedPercent(value: number | null) {
  return value === null ? '—' : `${value > 0 ? '+' : ''}${(value * 100).toFixed(2)}%`;
}

export default function RegimePrior({ data }: { data: Snapshot }) {
  const [inspectedId, setInspectedId] = useState<RegimeStateId | null>(null);
  const [cohortId, setCohortId] = useState<'all' | 'rolling120'>('rolling120');
  const trial = data.regimePrior;
  if (!trial)
    return (
      <section className="regime-prior">
        <header className="rg-heading">
          <div className="rg-eyebrow">ECONOMIC REGIMES</div>
          <h1>The regime-prior trial has not loaded.</h1>
          <p>
            The supplied snapshot does not contain this experiment. No result is inferred from missing data.
          </p>
        </header>
      </section>
    );

  const latest = trial.latest;
  const inspected =
    latest.stateMap.find((cell) => cell.id === (inspectedId ?? latest.state)) ?? latest.stateMap[0];
  const selectedCohort = trial.metrics[cohortId];
  const { outcomes } = regimeErrorBreakdown(trial.history, selectedCohort.start, selectedCohort.end);
  const prospective = trial.prospective;
  const receipt = prospective?.latestReceipt;
  const hasAdaptive = typeof latest.adaptiveProbability === 'number';
  const shrinkWeight = inspected ? inspected.n / (inspected.n + trial.spec.pseudoMonths) : null;
  const stateInputs = latest.stateInputs ?? latest.features ?? { credit: null, labor: null, slope: null };
  const currentAvailable = latest.available !== false && typeof latest.probability === 'number';
  const recentScores = trial.metrics.rolling120.models;
  const fullScores = trial.metrics.all.models;
  function scoreOrder(a: number | null | undefined, b: number | null | undefined) {
    return typeof a !== 'number' || typeof b !== 'number'
      ? 'comparison unavailable'
      : Math.abs(a - b) < 1e-12
        ? 'equal error'
        : a < b
          ? 'lower error'
          : 'higher error';
  }

  return (
    <div className="regime-prior">
      <header className="rg-heading">
        <div>
          <div className="rg-eyebrow">ECONOMIC REGIMES · FORECAST TRIAL</div>
          <h1>Does a changing base rate beat 50/50?</h1>
          <p>
            What is the chance of at least one U.S. recession month in the next year? Half of each estimate
            comes from the same market and labor model. The other half uses a historical recession frequency
            that can vary with credit and employment.
          </p>
        </div>
        <a className="rg-download" href="/api/download?file=regimes">
          <ArrowDownToLine size={16} /> Download issue-level CSV
        </a>
      </header>

      <section className="rg-screen" aria-labelledby="rg-screen-title">
        <div className="rg-section-heading">
          <h2 id="rg-screen-title">Both windows must pass.</h2>
          <span>Brier error · lower is better</span>
        </div>
        <div className="rg-table-wrap">
          <table className="rg-primary-table">
            <thead>
              <tr>
                <th>Fixed evaluation window</th>
                <th>Scored N</th>
                <th>Existing 50/50</th>
                <th>Fixed regime blend</th>
                <th>Past-fitted influence</th>
              </tr>
            </thead>
            <tbody>
              {(['all', 'rolling120'] as const).map((key) => {
                const slice = trial.metrics[key];
                const fixedAvailable =
                  slice.n > 0 &&
                  typeof slice.models.candidate.brier === 'number' &&
                  typeof slice.models.fixedBlend.brier === 'number';
                const learnedAvailable =
                  slice.n > 0 &&
                  typeof slice.models.adaptive?.brier === 'number' &&
                  typeof slice.models.fixedBlend.brier === 'number';
                const fixedPass = fixedAvailable
                  ? key === 'all'
                    ? trial.publicationGate.allPassed
                    : trial.publicationGate.rolling120Passed
                  : null;
                const learnedPass =
                  trial.adaptiveGate && learnedAvailable
                    ? key === 'all'
                      ? trial.adaptiveGate.allPassed
                      : trial.adaptiveGate.rolling120Passed
                    : null;
                return (
                  <tr key={key}>
                    <td>
                      <strong>{key === 'all' ? 'Full common history' : 'Trailing 120 issue months'}</strong>
                      <small>
                        {month(slice.windowStart ?? slice.start)} – {month(slice.windowEnd ?? slice.end)}
                      </small>
                    </td>
                    <td data-label="Scored N">
                      {slice.n}
                      <small>{slice.positiveWindows} positive windows</small>
                    </td>
                    <td data-label="Existing 50/50">
                      <strong>{number(slice.models.fixedBlend.brier, 5)}</strong>
                      <small>Incumbent</small>
                    </td>
                    <td data-label="Fixed regime">
                      <strong>{number(slice.models.candidate.brier, 5)}</strong>
                      <small>{signedPercent(reduction(slice))} error reduction</small>
                      <span className={fixedPass ? 'rg-pass' : 'rg-fail'}>
                        {fixedPass === null ? 'Not available' : fixedPass ? 'Pass' : 'Fail'}
                      </span>
                    </td>
                    <td data-label="Past-fitted influence">
                      <strong>{number(slice.models.adaptive?.brier, 5)}</strong>
                      <small>{signedPercent(reduction(slice, true))} error reduction</small>
                      <span className={learnedPass ? 'rg-pass' : 'rg-fail'}>
                        {learnedPass === null ? 'Not available' : learnedPass ? 'Pass' : 'Fail'}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="rg-note">
          Positive reductions mean less squared probability error than the incumbent. Each rule must be
          strictly better in both windows. The trailing window ends at the latest mature incumbent issue and
          spans exactly 120 calendar months, including any gaps.
        </p>
        <div className="rg-screen-verdict">
          <span>
            The fixed rule{' '}
            <strong>
              {trial.publicationGate.passed ? 'passes this historical screen' : 'does not clear both windows'}
            </strong>
            .
          </span>
          <span>
            The adaptive rule{' '}
            <strong>
              {trial.adaptiveGate
                ? trial.adaptiveGate.passed
                  ? 'passes this historical screen'
                  : 'does not clear both windows'
                : 'not yet available'}
            </strong>
            .
          </span>
        </div>
        <p className="rg-note">
          We specified the adaptive rule after seeing the fixed rule’s result. We track both forecasts against
          future outcomes below.
        </p>
      </section>

      <section className="rg-current">
        <div className="rg-section-heading">
          <div>
            <div className="rg-eyebrow">CURRENT CALCULATION · OUTCOME UNOBSERVED</div>
            <h2>
              {month(latest.forecastStart)} – {month(latest.forecastEnd)}
            </h2>
          </div>
          <span>
            Issue {month(latest.issueDate)} · inputs {month(latest.featureDate)}
          </span>
        </div>
        <div className="rg-current-values">
          <div>
            <span>Fixed regime blend</span>
            <strong>{percent(latest.probability)}</strong>
          </div>
          <div>
            <span>Past-fitted regime influence</span>
            <strong>{percent(latest.adaptiveProbability)}</strong>
          </div>
          <div>
            <span>Existing fixed 50/50</span>
            <strong>{percent(latest.fixedBlendProbability)}</strong>
          </div>
        </div>
        {!currentAvailable && (
          <p className="rg-unavailable">
            Current regime forecasts are unavailable: required inputs or eligible prior evidence are missing.
            Unavailable values remain blank; they are not zero probabilities.
          </p>
        )}
        <div className="rg-decomposition">
          <p>
            The original forecast stays at <strong>{percent(latest.originalProbability)}</strong>. Every
            candidate keeps <strong>50% original + 50% prior</strong>.
          </p>
          <p>
            Fixed state prior <strong>{percent(latest.dynamicPriorProbability)}</strong>, past-fitted prior{' '}
            <strong>{percent(latest.adaptivePriorProbability)}</strong>, pooled recent prior{' '}
            <strong>{percent(latest.recentPriorProbability)}</strong>.
          </p>
        </div>
        <p className="rg-note">
          The prior uses {latest.trainingN} eligible issues from {month(latest.windowStart)} to
          {month(latest.windowEnd)}. Each positive issue was followed by at least one recession month in its
          twelve-month forecast window.
        </p>
        {hasAdaptive && (
          <p className="rg-note">
            Past-fitted regime influence α = {percent(latest.regimeWeight)} from {latest.weightTrainingN ?? 0}{' '}
            earlier eligible annual predictions. Last training issue {month(latest.weightTrainEnd)}; last
            training target month {month(latest.weightLastTargetMonth)}.
          </p>
        )}
      </section>

      <section className="rg-state-section">
        <div className="rg-section-heading">
          <div>
            <div className="rg-eyebrow">FOUR STATES · ONE RECENT TRAINING WINDOW</div>
            <h2>Inspect the evidence behind the prior.</h2>
          </div>
        </div>
        {inspected ? (
          <div className="rg-state-layout">
            <div>
              <div className="rg-matrix">
                <div className="rg-corner">Credit / labor gap</div>
                <div className="rg-matrix-axis">Below 0.50 pp</div>
                <div className="rg-matrix-axis">At least 0.50 pp</div>
                {[false, true].map((tight) => (
                  <div className="rg-matrix-row" key={String(tight)}>
                    <div className="rg-credit-axis">
                      {tight ? 'Tighter credit' : 'Looser credit'}
                      <small>{tight ? '> 0 index' : '≤ 0 index'}</small>
                    </div>
                    {stateOrder
                      .filter((id) => id.startsWith(tight ? 'tight-' : 'loose-'))
                      .map((id) => {
                        const cell = latest.stateMap.find((item) => item.id === id);
                        if (!cell)
                          return (
                            <button key={id} disabled className="rg-state-cell">
                              State evidence unavailable
                            </button>
                          );
                        const current = cell.id === latest.state;
                        return (
                          <button
                            key={id}
                            className={`rg-state-cell ${cell.id === inspected.id ? 'selected' : ''} ${current ? 'rg-current-cell' : ''}`}
                            onClick={() => setInspectedId(cell.id)}
                            aria-pressed={cell.id === inspected.id}
                            aria-label={`${stateLabel(cell.creditTight, cell.laborElevated)}: ${cell.n} issues, ${cell.positiveWindows} positive windows, shrunken prior ${percent(cell.priorProbability)}${current ? ', current state' : ''}`}
                          >
                            <span>
                              {current
                                ? 'Current state'
                                : cell.n < trial.spec.pseudoMonths
                                  ? 'Sparse state'
                                  : 'Training state'}
                            </span>
                            <strong>{percent(cell.priorProbability)}</strong>
                            <small>
                              {cell.positiveWindows} positive / {cell.n} issues
                            </small>
                          </button>
                        );
                      })}
                  </div>
                ))}
              </div>
              <p className="rg-note">
                {latest.state ? (
                  <>
                    Current credit {number(stateInputs.credit, 4)}; labor gap {number(stateInputs.labor, 4)}{' '}
                    pp.
                  </>
                ) : (
                  <>Current state is unavailable because an assignment input is missing.</>
                )}{' '}
                Inputs are rounded to ten decimals for state assignment. Selecting a cell inspects its
                training evidence; it does not change the current forecast.
              </p>
            </div>
            <aside className="rg-state-inspector" aria-live="polite">
              <div className="rg-eyebrow">SELECTED STATE</div>
              <h3>{stateLabel(inspected.creditTight, inspected.laborElevated)}</h3>
              <strong className="rg-state-n">
                {inspected.n}
                <small>eligible issues</small>
              </strong>
              <dl>
                <div>
                  <dt>Positive forward windows</dt>
                  <dd>{inspected.positiveWindows}</dd>
                </div>
                <div>
                  <dt>Raw state frequency</dt>
                  <dd>{percent(inspected.rawRate)}</dd>
                </div>
                <div>
                  <dt>Pooled recent frequency</dt>
                  <dd>{percent(inspected.pooledRate)}</dd>
                </div>
                <div>
                  <dt>Shrunken state prior</dt>
                  <dd>{percent(inspected.priorProbability)}</dd>
                </div>
              </dl>
              <p>
                {inspected.n === 0 ? (
                  'This state has no observed issues. Its raw frequency is unavailable and its prior falls back to the pooled rate.'
                ) : (
                  <>
                    The state frequency receives {percent(shrinkWeight)} weight; the pooled rate receives{' '}
                    {percent(shrinkWeight === null ? null : 1 - shrinkWeight)}. Fewer observations mean more
                    pooling.
                  </>
                )}
              </p>
              <p className="rg-formula">
                ({inspected.positiveWindows} + {trial.spec.pseudoMonths} × {percent(inspected.pooledRate)}) /
                ({inspected.n} + {trial.spec.pseudoMonths})
              </p>
            </aside>
          </div>
        ) : (
          <p className="rg-unavailable">State-level training evidence is unavailable in this snapshot.</p>
        )}
      </section>

      <section className="rg-controls">
        <div className="rg-section-heading">
          <div>
            <div className="rg-eyebrow">CONTROLS AND ABLATIONS</div>
            <h2>Separate the model from its prior.</h2>
          </div>
          <div className="rg-cohorts" role="group" aria-label="Control comparison window">
            {(['all', 'rolling120'] as const).map((id) => (
              <button
                key={id}
                className={cohortId === id ? 'selected' : ''}
                aria-pressed={cohortId === id}
                onClick={() => setCohortId(id)}
              >
                {id === 'all' ? 'Full history' : 'Trailing 120'}
              </button>
            ))}
          </div>
        </div>
        <p className="rg-note">
          {selectedCohort.n} common mature issues · {selectedCohort.positiveWindows} positive windows ·{' '}
          {month(selectedCohort.start)}–{month(selectedCohort.end)}. Missing months in the calendar window:{' '}
          {selectedCohort.missingMonths ?? 0}.
        </p>
        <div className="rg-table-wrap">
          <table>
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
              {methodLabels.map((method) => (
                <tr
                  key={method.key}
                  className={method.key === 'candidate' || method.key === 'adaptive' ? 'rg-emphasis' : ''}
                >
                  <td>{method.label}</td>
                  <td>{number(selectedCohort.models[method.key]?.brier)}</td>
                  <td>{number(selectedCohort.models[method.key]?.logLoss)}</td>
                  <td>{number(selectedCohort.models[method.key]?.auc, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="rg-empirical-readout">
          <h3>Where did the forecast error change?</h3>
          <p aria-live="polite">
            In the {cohortId === 'all' ? 'full replay' : 'latest ten years'}, {outcomes[0].n} forecasts were
            followed by a year without a recession month. For those forecasts, average squared error went from{' '}
            <strong>{number(outcomes[0].fixed, 5)}</strong> with the existing 50/50 to{' '}
            <strong>{number(outcomes[0].regime, 5)}</strong> with the regime blend. In the {outcomes[1].n}{' '}
            windows containing a recession month, it went from <strong>{number(outcomes[1].fixed, 5)}</strong>{' '}
            to <strong>{number(outcomes[1].regime, 5)}</strong>.
          </p>
          <p>
            Over the exact trailing window, the pooled recent-prior blend has Brier{' '}
            {number(recentScores.recentBlend.brier)}, versus {number(recentScores.fixedBlend.brier)} for the
            incumbent ({scoreOrder(recentScores.recentBlend.brier, recentScores.fixedBlend.brier)}). Fixed
            credit/labor conditioning gives {number(recentScores.candidate.brier)} (
            {scoreOrder(recentScores.candidate.brier, recentScores.recentBlend.brier)} versus the pooled blend
            and {scoreOrder(recentScores.candidate.brier, recentScores.fixedBlend.brier)} versus the
            incumbent).
          </p>
          <p>
            Across the full history, fixed conditioning gives {number(fullScores.candidate.brier)}, versus{' '}
            {number(fullScores.recentBlend.brier)} for the pooled recent-prior blend (
            {scoreOrder(fullScores.candidate.brier, fullScores.recentBlend.brier)}). Both comparisons use the
            same model weight and the same issue dates.
          </p>
        </div>
      </section>

      <RegimeAnnualCheck trial={trial} />

      <section className="rg-prospective">
        <div className="rg-section-heading">
          <div>
            <div className="rg-eyebrow">FROZEN PROSPECTIVE RECORD</div>
            <h2>Forecasts and realized outcomes</h2>
          </div>
          <a className="rg-text-link" href="/api/download?file=regimereceipts">
            <ArrowDownToLine size={15} /> Download receipts
          </a>
        </div>
        <div className="rg-receipt-status">
          <ShieldCheck size={21} />
          <div>
            <strong>
              {prospective?.receiptCount ?? 0} frozen receipts · {prospective?.maturedCount ?? 0} mature
              outcomes
            </strong>
            <p>
              {(prospective?.maturedCount ?? 0) === 0
                ? 'There is no prospective accuracy result. A complete, actually published forward window must mature first.'
                : 'Only complete source outcomes enter prospective scoring; historical results remain a separate experiment.'}
            </p>
          </div>
          <span>{prospective?.chainValid ? 'Hash chain consistent' : 'Chain not verified'}</span>
        </div>
        {receipt ? (
          <>
            <dl className="rg-receipt-dates">
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
                <dt>Frozen horizon / source month</dt>
                <dd>
                  {month(receipt.forecastStart)}–{month(receipt.forecastEnd)} / {month(receipt.featureDate)}
                </dd>
              </div>
            </dl>
            <div className="rg-table-wrap">
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
                    ['Existing fixed 50/50', receipt.predictions.fixedBlend],
                    ['Pooled recent prior', receipt.predictions.recentPrior],
                    ['Pooled recent-prior blend', receipt.predictions.recentBlend],
                    ['Shrunken state prior', receipt.predictions.dynamicPrior],
                    ['Fixed regime blend', receipt.predictions.candidate],
                    ['Past-fitted prior', receipt.predictions.adaptivePrior],
                    ['Past-fitted regime blend', receipt.predictions.adaptive],
                  ].map(([label, value]) => (
                    <tr key={String(label)}>
                      <td>{label}</td>
                      <td>{percent(typeof value === 'number' ? value : null)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="rg-hash">
              Receipt SHA-256{' '}
              <code title={receipt.hash}>
                {receipt.hash.slice(0, 18)}…{receipt.hash.slice(-12)}
              </code>
            </p>
          </>
        ) : (
          <p className="rg-empty">
            A published receipt has not loaded. Missing records are not reconstructed as earlier forecasts.
          </p>
        )}
        <p className="rg-note">
          Receipts retain actual capture dates, inputs, state counts, recipes, and fitted weights. Hash
          linking checks consistency of the supplied chain; it does not provide independent timestamping or
          tamper-proof certification.
        </p>
      </section>

      <div className="rg-caveat">
        <CircleHelp size={17} />
        <p>
          <strong>Two sequential exploratory hypotheses.</strong> The fixed state rule was specified before
          its scoring. The adaptive rule followed the fixed rule's result and uses only earlier eligible
          annual forecasts for each weight. This sequencing does not undo the research idea's hindsight.
          Source revisions, retrospective NBER dating, overlapping horizons, and few downturns limit the
          evidence.
        </p>
      </div>
      <details className="rg-method">
        <summary>
          Prior construction and past-fitted influence <ChevronDown size={17} />
        </summary>
        <div>
          <p>
            <strong>The recent sample.</strong> Use 180 fixed calendar issue months ending thirteen months
            before the formal forecast/refit, with a full fifteen-year span and at least 120 valid observed
            targets. The pooled rate is the fraction of positive twelve-month horizons. The window does not
            slide around missing labels.
          </p>
          <p>
            <strong>Four states, with pooling.</strong> Credit above zero and labor gap at least 0.50 pp
            define four cells. Round these inputs to ten decimals before assigning a cell. Its prior is
            (positive cell outcomes + 24 × pooled rate) / (cell N + 24). Empty cells use the pooled rate.
            These thresholds and 24 pseudo-months are fixed, not optimized on the displayed test.
          </p>
          <p>
            <strong>One adaptive influence.</strong> Let a be the 50/50 original-plus-pooled blend and c the
            fixed state blend. Fit α between zero and one by minimizing earlier squared forecast error for a +
            α(c − a). Historical fits update each January and only use prior annual issues whose full
            twelve-month targets end before that fit. Below 60 eligible issues or with no identifiable
            difference, α is zero. The original model remains 50% of the final forecast.
          </p>
          <p>
            <strong>Interpretation.</strong> This changes a statistical prior, not the causal effect of
            tighter credit or unemployment. All forecast targets still include any recession month in the
            following year, including continuations. AUC is ranking, not percent accuracy; a one-class slice
            has no AUC. No return, investment recommendation, or future accuracy guarantee follows.
          </p>
        </div>
      </details>
    </div>
  );
}
