"""Two explicitly specified, exploratory regime-prior experiments.

The first fixed rule conditions a recent base rate on credit/labor states.
The second, specified after the first result, learns reliability from previously
issued annual forecasts only. Neither changes the original model's 50% weight.
"""

from __future__ import annotations
from datetime import datetime, timezone
from io import StringIO
import numpy as np
import pandas as pd

BASE_FEATURES = ['slope', 'credit', 'labor']
WINDOW_MONTHS = 180
MINIMUM_OBSERVED = 120
PSEUDO_MONTHS = 24
STATE_PRECISION = 10
ADAPTIVE_MINIMUM = 60
STATES = [
    ('loose-low', False, False),
    ('loose-elevated', False, True),
    ('tight-low', True, False),
    ('tight-elevated', True, True),
]
PREDICTIONS = {
    'original': 'originalProbability',
    'fixedBlend': 'fixedBlendProbability',
    'recentBlend': 'recentBlendProbability',
    'expandingBlend': 'expandingBlendProbability',
    'dynamicPrior': 'dynamicPriorProbability',
    'candidate': 'probability',
    'adaptive': 'adaptiveProbability',
    'recentPrior': 'recentPriorProbability',
    'base': 'baselineProbability',
}


def iso(value):
    return pd.Timestamp(value).strftime('%Y-%m-%d')


def _finite(value):
    try:
        return bool(np.isfinite(value))
    except TypeError:
        return False


def _probability(value):
    return float(value) if _finite(value) and 0 <= value <= 1 else None


def _binary(value):
    return int(value) if _finite(value) and value in [0, 1] else None


def _calendar(frame, name):
    result = frame.copy()
    result.index = pd.DatetimeIndex(pd.to_datetime(result.index))
    if result.index.hasnans or result.index.has_duplicates or not result.index.is_monotonic_increasing:
        raise ValueError(f'{name}: invalid, duplicate or unsorted issue dates')
    if any(result.index.day != 1):
        raise ValueError(f'{name}: issues must be calendar-month starts')
    return result


def state_for_inputs(credit, labor):
    """Canonicalize classification inputs only; original probabilities stay intact."""
    if not _finite(credit) or not _finite(labor):
        return None
    credit = round(float(credit), STATE_PRECISION)
    labor = round(float(labor), STATE_PRECISION)
    return ('tight' if credit > 0 else 'loose') + ('-elevated' if labor >= 0.50 else '-low')


def fit_state_prior(panel, cutoff, expanding=False, selected_state=None):
    cutoff = pd.Timestamp(cutoff)
    frame = _calendar(panel, 'Prior training panel')
    start = frame.index[0] if expanding and len(frame) else cutoff - pd.DateOffset(months=WINDOW_MONTHS - 1)
    full_span = bool(len(frame) and frame.index[0] <= start and frame.index[-1] >= cutoff)
    window = frame.loc[(frame.index >= start) & (frame.index <= cutoff)].copy()
    window[BASE_FEATURES] = window[BASE_FEATURES].replace([np.inf, -np.inf], np.nan)
    eligible = window.dropna(subset=BASE_FEATURES + ['target'])
    eligible = eligible.loc[eligible.target.isin([0, 1])]
    count = len(eligible)
    pool = float(eligible.target.mean()) if count else None
    available = full_span and count >= MINIMUM_OBSERVED
    state_values = [state_for_inputs(row.credit, row.labor) for _, row in eligible.iterrows()]
    eligible = eligible.assign(_state=state_values)
    state_map = []
    for state, credit_tight, labor_elevated in STATES:
        group = eligible.loc[eligible._state == state]
        n, positives = len(group), int(group.target.sum())
        prior = (
            (pool if n == 0 else (positives + PSEUDO_MONTHS * pool) / (n + PSEUDO_MONTHS))
            if available
            else None
        )
        state_map.append(
            dict(
                id=state,
                creditTight=credit_tight,
                laborElevated=labor_elevated,
                n=n,
                positiveWindows=positives,
                rawRate=positives / n if n else None,
                pooledRate=pool,
                priorProbability=prior,
                selected=state == selected_state,
            )
        )
    return dict(
        available=available,
        fullSpan=full_span,
        windowStart=iso(start),
        windowEnd=iso(cutoff),
        trainingCutoff=iso(cutoff),
        trainingN=count,
        recentPriorProbability=pool if available else None,
        observedStart=iso(eligible.index[0]) if count else None,
        observedEnd=iso(eligible.index[-1]) if count else None,
        stateMap=state_map,
    )


def fit_reliability(history, refit):
    """Nested OLS reliability: only earlier issued a/c forecasts with mature targets."""
    refit = pd.Timestamp(refit)
    training = []
    for row in history:
        date = pd.Timestamp(row['date'])
        if date + pd.DateOffset(months=12) >= refit:
            continue
        if _binary(row.get('target')) is None:
            continue
        if (
            _probability(row.get('recentBlendProbability')) is None
            or _probability(row.get('probability')) is None
        ):
            continue
        training.append(row)
    training.sort(key=lambda row: row['date'])
    numerator = sum(
        (row['probability'] - row['recentBlendProbability']) * (row['target'] - row['recentBlendProbability'])
        for row in training
    )
    denominator = sum((row['probability'] - row['recentBlendProbability']) ** 2 for row in training)
    if len(training) < ADAPTIVE_MINIMUM:
        weight, unconstrained, status = 0.0, None, 'insufficient-history'
    elif denominator == 0:
        weight, unconstrained, status = 0.0, None, 'degenerate-recent-fallback'
    else:
        unconstrained = numerator / denominator
        weight, status = max(0.0, min(1.0, unconstrained)), 'fit'
    return dict(
        refitDate=iso(refit),
        trainingCutoff=iso(refit - pd.DateOffset(months=13)),
        trainingN=len(training),
        trainStart=training[0]['date'] if training else None,
        trainEnd=training[-1]['date'] if training else None,
        lastTargetMonth=(
            iso(pd.Timestamp(training[-1]['date']) + pd.DateOffset(months=12)) if training else None
        ),
        weight=weight,
        unconstrainedWeight=unconstrained,
        numerator=numerator,
        denominator=denominator,
        status=status,
        minimumTrainingN=ADAPTIVE_MINIMUM,
    )


def _state_probability(fit, state):
    match = next((cell for cell in fit['stateMap'] if cell['id'] == state), None)
    return match['priorProbability'] if match else None


def _metric_slice(frame, incumbent, metric_fn, key, label, start, end):
    if start is None or end is None:
        selected = frame.iloc[:0]
        incumbent_rows = incumbent.iloc[:0]
        expected = 0
    else:
        selected = frame.loc[(frame.index >= start) & (frame.index <= end)]
        incumbent_rows = incumbent.loc[(incumbent.index >= start) & (incumbent.index <= end)]
        expected = (end.year - start.year) * 12 + end.month - start.month + 1
    common = selected.dropna(subset=['target'] + list(PREDICTIONS.values()))
    scores = {
        name: (
            metric_fn(common.target, common[column])
            if len(common)
            else dict(auc=None, brier=None, logLoss=None)
        )
        for name, column in PREDICTIONS.items()
    }
    base_brier = scores['fixedBlend']['brier']

    def changes(name):
        error = scores[name]['brier']
        improvement = base_brier - error if error is not None and base_brier is not None else None
        return dict(
            brierDeltaVsIncumbent=-improvement if improvement is not None else None,
            brierImprovement=improvement,
            relativeBrierImprovement=(
                improvement / base_brier if improvement is not None and base_brier else None
            ),
        )

    return dict(
        id=key,
        label=label,
        windowStart=iso(start) if start is not None else None,
        windowEnd=iso(end) if end is not None else None,
        expectedCalendarMonths=expected,
        observedMonths=len(incumbent_rows),
        missingMonths=expected - len(common),
        missingIncumbentMonths=expected - len(incumbent_rows),
        missingCandidateMonths=len(incumbent_rows) - len(common),
        start=iso(common.index[0]) if len(common) else None,
        end=iso(common.index[-1]) if len(common) else None,
        n=len(common),
        positiveWindows=int(common.target.sum()),
        models=scores,
        **changes('candidate'),
        adaptiveComparison=changes('adaptive'),
    )


def build_regime_prior(panel, history_frame, latest, metrics):
    panel = _calendar(panel, 'Original issue panel')
    panel[BASE_FEATURES] = (
        panel[BASE_FEATURES].apply(pd.to_numeric, errors='coerce').replace([np.inf, -np.inf], np.nan)
    )
    panel.loc[~panel.target.isin([0, 1]), 'target'] = np.nan
    official = pd.DataFrame(history_frame).copy()
    if 'date' in official:
        official = official.set_index('date')
    official = _calendar(official, 'Official annual replay')
    if 'forecastType' in official:
        official = official.loc[official.forecastType == 'annual-walk-forward']
    if not {'probability', 'baseline', 'target'}.issubset(official.columns):
        raise ValueError('Annual original probabilities, base rates and outcomes are required')
    issue = pd.Timestamp(latest['issueDate'])
    source_end = min(issue, panel.index[-1]) if len(panel) else issue
    official = official.loc[official.index <= source_end]
    valid_probability = official.probability.apply(
        lambda value: _probability(value) is not None
    ) & official.baseline.apply(lambda value: _probability(value) is not None)
    official = official.loc[valid_probability].copy()
    official.loc[official.index + pd.DateOffset(months=12) >= issue, 'target'] = np.nan
    official.loc[~official.target.isin([0, 1]), 'target'] = np.nan
    incumbent = official.dropna(subset=['target'])
    label_cutoff = incumbent.index[-1] + pd.DateOffset(months=12) if len(incumbent) else None
    if label_cutoff is None:
        panel['target'] = np.nan
    else:
        panel.loc[panel.index + pd.DateOffset(months=12) > label_cutoff, 'target'] = np.nan
    # No yearly fit is manufactured beyond the annual replay's own dated issues.
    years = sorted(set(official.index.year))
    folds, fits = [], {}
    for year in years:
        refit = pd.Timestamp(year, 1, 1)
        recent = fit_state_prior(panel, refit - pd.DateOffset(months=13))
        expanding = fit_state_prior(panel, refit - pd.DateOffset(months=13), expanding=True)
        fits[year] = (recent, expanding)
        folds.append(dict(refitDate=iso(refit), **recent, expanding=expanding))
    history, missing_states, missing_features = [], 0, 0
    for date, reference in official.iterrows():
        recent, expanding = fits[date.year]
        row = panel.loc[date] if date in panel.index else None
        features = {
            key: float(row[key]) if row is not None and _finite(row[key]) else None for key in BASE_FEATURES
        }
        state = state_for_inputs(features['credit'], features['labor'])
        if any(value is None for value in features.values()):
            missing_features += 1
            state = None
        if state is None:
            missing_states += 1
        p, b = float(reference.probability), float(reference.baseline)
        pool = recent['recentPriorProbability']
        prior, expanding_prior = _state_probability(recent, state), _state_probability(expanding, state)
        target = _binary(reference.target)
        if (
            row is not None
            and target is not None
            and _binary(row.target) is not None
            and row.target != target
        ):
            raise ValueError('Original replay and issue panel target clocks disagree')
        selected = next((cell for cell in recent['stateMap'] if cell['id'] == state), None)
        history.append(
            dict(
                date=iso(date),
                featureDate=iso(date - pd.DateOffset(months=2)),
                target=target,
                **features,
                state=state,
                creditStateInput=(
                    round(features['credit'], STATE_PRECISION) if features['credit'] is not None else None
                ),
                laborStateInput=(
                    round(features['labor'], STATE_PRECISION) if features['labor'] is not None else None
                ),
                originalProbability=p,
                baselineProbability=b,
                fixedBlendProbability=0.5 * p + 0.5 * b,
                recentPriorProbability=pool,
                recentBlendProbability=0.5 * p + 0.5 * pool if pool is not None else None,
                dynamicPriorProbability=prior,
                probability=0.5 * p + 0.5 * prior if prior is not None else None,
                expandingPriorProbability=expanding_prior,
                expandingBlendProbability=(
                    0.5 * p + 0.5 * expanding_prior if expanding_prior is not None else None
                ),
                refitDate=iso(pd.Timestamp(date.year, 1, 1)),
                trainingCutoff=recent['trainingCutoff'],
                windowStart=recent['windowStart'],
                windowEnd=recent['windowEnd'],
                trainingN=recent['trainingN'],
                stateTrainingN=selected['n'] if selected else None,
                statePositiveWindows=selected['positiveWindows'] if selected else None,
                forecastType='annual-walk-forward',
                candidateLabelType='fixed-regime-prior-50-50-blend',
            )
        )
    weights = {year: fit_reliability(history, pd.Timestamp(year, 1, 1)) for year in years}
    for row in history:
        weight_fit = weights[pd.Timestamp(row['date']).year]
        alpha = weight_fit['weight']
        pool, prior = row['recentPriorProbability'], row['dynamicPriorProbability']
        adaptive_prior = pool + alpha * (prior - pool) if pool is not None and prior is not None else None
        row.update(
            adaptiveProbability=(
                0.5 * row['originalProbability'] + 0.5 * adaptive_prior
                if adaptive_prior is not None
                else None
            ),
            adaptivePriorProbability=adaptive_prior,
            regimeWeight=alpha,
            weightTrainingN=weight_fit['trainingN'],
            weightTrainStart=weight_fit['trainStart'],
            weightTrainEnd=weight_fit['trainEnd'],
            weightLastTargetMonth=weight_fit['lastTargetMonth'],
            weightTrainingCutoff=weight_fit['trainingCutoff'],
            weightStatus=weight_fit['status'],
        )
    for fold in folds:
        fold['weightFit'] = weights[pd.Timestamp(fold['refitDate']).year]
    frame = pd.DataFrame(history)
    if frame.empty:
        frame = pd.DataFrame(columns=['date', 'target'] + list(PREDICTIONS.values()))
    frame = frame.set_index('date')
    frame.index = pd.to_datetime(frame.index)
    first_mature, last_mature = (incumbent.index[0], incumbent.index[-1]) if len(incumbent) else (None, None)
    rolling_start = last_mature - pd.DateOffset(months=119) if last_mature is not None else None
    all_metrics = _metric_slice(
        frame, incumbent, metrics, 'all', 'All common mature annual issues', first_mature, last_mature
    )
    rolling_metrics = _metric_slice(
        frame,
        incumbent,
        metrics,
        'rolling120',
        'Trailing 120 calendar issue months ending latest mature incumbent issue',
        rolling_start,
        last_mature,
    )
    current_available = issue in panel.index and all(
        _finite(latest['features'].get(key)) for key in BASE_FEATURES
    )
    current_state = (
        state_for_inputs(latest['features'].get('credit'), latest['features'].get('labor'))
        if current_available
        else None
    )
    current_recent = fit_state_prior(panel, issue - pd.DateOffset(months=13), selected_state=current_state)
    current_expanding = fit_state_prior(
        panel, issue - pd.DateOffset(months=13), expanding=True, selected_state=current_state
    )
    current_pool = current_recent['recentPriorProbability']
    current_prior = _state_probability(current_recent, current_state) if current_available else None
    current_expanding_prior = (
        _state_probability(current_expanding, current_state) if current_available else None
    )
    current_weight = fit_reliability(history, issue) if current_available and issue.year in years else None
    alpha = current_weight['weight'] if current_weight else None
    adaptive_prior = (
        current_pool + alpha * (current_prior - current_pool)
        if alpha is not None and current_pool is not None and current_prior is not None
        else None
    )
    p, b = _probability(latest.get('probability')), _probability(latest.get('baselineProbability'))

    def mix(prior):
        return 0.5 * p + 0.5 * prior if p is not None and prior is not None else None

    def gate(model):
        def better(slice_):
            return bool(
                slice_['n'] and slice_['models'][model]['brier'] < slice_['models']['fixedBlend']['brier']
            )

        all_passed, rolling_passed = better(all_metrics), better(rolling_metrics)
        return dict(
            criterion='Brier must be strictly lower than the same official fixed 50/50 incumbent on BOTH all common mature dates and the trailing 120-calendar-month window; no relative-improvement margin is imposed.',
            allPassed=all_passed,
            rolling120Passed=rolling_passed,
            passed=all_passed and rolling_passed,
            decision=(
                'beats-retrospective-incumbent-screen-still-experimental'
                if all_passed and rolling_passed
                else 'not-cleared-preserve-current-default'
            ),
            note='A retrospective screen is not untouched or prospective validation. Revised outcomes overlap and NBER announcement availability is not reconstructed.',
        )

    return dict(
        version='1.0',
        status='experimental fixed-design chronological replay',
        generatedAt=datetime.now(timezone.utc).isoformat(),
        issueDate=iso(issue),
        featureDate=latest['featureDate'],
        spec=dict(
            id='regime-prior-180-24-fixed50-v1',
            windowMonths=180,
            minimumObserved=120,
            pseudoMonths=24,
            creditThreshold=0,
            laborThreshold=0.50,
            statePrecisionDecimals=10,
            rawWeight=0.5,
            priorWeight=0.5,
            featureLagMonths=2,
            horizonMonths=12,
            eligibilityMonths=13,
            recipe='0.5 * official original probability + 0.5 * smoothed recent credit-labor regime prior',
            priorFormula='(state positives + 24 * pooled 180-month rate) / (state count + 24)',
            canonicalization='Round credit and labor inputs to 10 decimal places before credit>0 and labor>=0.50 classification; original model probabilities are unchanged.',
            controls='Same-date official fixed blend; recent unconditioned blend; expanding four-state prior/blend with 24 pseudo issue-months; dynamic prior alone.',
            designStatus='Fixed state thresholds, window, strength and mixture specified before this experiment was scored. It remains exploratory latest-vintage chronological replay.',
            adaptiveDesignId='regime-reliability-prequential-v1',
            adaptiveMinimumTrainingN=60,
            adaptiveRecipe='recentBlend + alpha * (fixedRegimeBlend - recentBlend); original probability retains 50% weight',
            adaptiveFit='alpha=clip(sum((c-a)*(y-a))/sum((c-a)^2),0,1), from previously issued annual forecasts whose full 12-month targets end strictly before refit; minimum 60, otherwise zero; zero denominator also zero.',
            adaptiveDesignStatus='This second approach was specified before its scoring, after observing the first fixed-rule result. No further variants or threshold search are permitted; it is not untouched holdout evidence.',
            target='At least one recession month in the following 12 months, including continuation; not onset-only.',
            improvementSign='brierDeltaVsIncumbent=candidate minus incumbent (negative better); brierImprovement=incumbent minus candidate (positive better); relative is that improvement divided by incumbent Brier.',
            limitations=[
                'Original inputs are already lagged two months at issue; no additional lag or contemporaneous new data is used.',
                'Current and historical priors use retrospective revised labels; calendar purging does not reconstruct announcement delays.',
                'Four-state counts and pseudo issue-months are overlapping observations, not independent business cycles.',
                'Sparse/empty states shrink toward the same-window pool; an empty cell equals the pool exactly.',
            ],
        ),
        latest=dict(
            available=bool(
                current_available and current_prior is not None and p is not None and b is not None
            ),
            probability=mix(current_prior),
            originalProbability=p,
            baselineProbability=b,
            fixedBlendProbability=0.5 * p + 0.5 * b if p is not None and b is not None else None,
            dynamicPriorProbability=current_prior,
            recentPriorProbability=current_pool,
            recentBlendProbability=mix(current_pool),
            expandingPriorProbability=current_expanding_prior,
            expandingBlendProbability=mix(current_expanding_prior),
            adaptiveProbability=mix(adaptive_prior),
            adaptivePriorProbability=adaptive_prior,
            regimeWeight=alpha,
            weightTrainingN=current_weight['trainingN'] if current_weight else 0,
            weightTrainStart=current_weight['trainStart'] if current_weight else None,
            weightTrainEnd=current_weight['trainEnd'] if current_weight else None,
            weightLastTargetMonth=current_weight['lastTargetMonth'] if current_weight else None,
            weightTrainingCutoff=current_weight['trainingCutoff'] if current_weight else None,
            weightFit=current_weight,
            state=current_state,
            features=latest['features'].copy(),
            stateInputs=(
                dict(
                    credit=round(float(latest['features']['credit']), 10),
                    labor=round(float(latest['features']['labor']), 10),
                )
                if current_state
                else None
            ),
            issueDate=iso(issue),
            featureDate=latest['featureDate'],
            forecastStart=iso(issue + pd.DateOffset(months=1)),
            forecastEnd=iso(issue + pd.DateOffset(months=12)),
            trainingCutoff=current_recent['trainingCutoff'],
            windowStart=current_recent['windowStart'],
            windowEnd=current_recent['windowEnd'],
            trainingN=current_recent['trainingN'],
            observedStart=current_recent['observedStart'],
            observedEnd=current_recent['observedEnd'],
            stateMap=current_recent['stateMap'],
            expandingStateMap=current_expanding['stateMap'],
        ),
        metrics=dict(all=all_metrics, rolling120=rolling_metrics),
        history=history,
        folds=folds,
        coverage=dict(
            sourceIssueMonths=len(panel),
            annualReplayMonths=len(official),
            commonMatureN=all_metrics['n'],
            missingFeatureMonths=missing_features,
            missingStateMonths=missing_states,
            missingRecentPriorMonths=sum(row['recentPriorProbability'] is None for row in history),
            latestMatureIncumbentIssue=iso(last_mature) if last_mature is not None else None,
            labelCutoff=iso(label_cutoff) if label_cutoff is not None else None,
            rollingWindowStart=iso(rolling_start) if rolling_start is not None else None,
            rollingWindowEnd=iso(last_mature) if last_mature is not None else None,
        ),
        publicationGate=gate('candidate'),
        adaptiveGate=gate('adaptive'),
    )


def regime_history_csv(result):
    return pd.DataFrame(result['history']).to_csv(index=False, float_format='%.12f', na_rep='')
