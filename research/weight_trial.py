"""Chronological test of state-dependent signal weights against the same expanding base."""

from __future__ import annotations

from math import fsum, isfinite

import pandas as pd

from leading_trial import iso

MIN_TRAINING = 60
PENALTY = 1.0
PRECISION = 10
PREDICTIONS = {
    'existingBlend': 'existingBlendProbability',
    'fixedPermits': 'fixedPermitsProbability',
    'pooledPermits': 'pooledPermitsProbability',
    'originalDynamic': 'originalDynamicProbability',
    'candidate': 'probability',
    'fixedRule': 'fixedRuleProbability',
}
SPEC = dict(
    id='state-dependent-permits-weight-v1',
    minimumTrainingIssues=MIN_TRAINING,
    penalty=PENALTY,
    warmupWeight=0.5,
    featureLagMonths=2,
    horizonMonths=12,
    statePrecisionDecimals=PRECISION,
    warningThreshold=0.30,
    stateRule='Stress when the issue-time 10Y minus 3M slope is negative or the credit subindex is positive. Otherwise normal.',
    blend='base + state weight * (raw permits model - base)',
    pooledFit='clip((sum(d*(y-base)) + 0.5) / (sum(d*d) + 1), 0, 1)',
    stateFit='clip((sum_state(d*(y-base)) + pooled weight) / (sum_state(d*d) + 1), 0, 1)',
    design='Primary uses the permits-augmented signal. The original signal with the same rule and the single pooled permits weight are comparison models.',
    ruleId='direct-state-permits-75-25-v1',
    ruleWeights={'stress': 0.75, 'normal': 0.25},
    ruleDesign='Secondary rule specified after the primary replay and before this control was scored. Its two weights are fixed, including during the primary warmup.',
    fitClock='Past annual out-of-fold predictions only. The full twelve-month outcome window ends strictly before each refit. Historical weights refit each January and live weights refit monthly.',
)


def finite(value):
    return float(value) if isinstance(value, (int, float)) and isfinite(value) else None


def prob(value):
    value = finite(value)
    return value if value is not None and 0 <= value <= 1 else None


def state_for(slope, credit):
    slope, credit = finite(slope), finite(credit)
    if slope is None or credit is None:
        return None
    return 'stress' if round(slope, PRECISION) < 0 or round(credit, PRECISION) > 0 else 'normal'


def components(row):
    """Recover a signal from a documented equal-weight blend with its own official base."""
    base = prob(row.get('baselineProbability'))
    original = prob(row.get('originalProbability'))
    existing = prob(row.get('existingBlendProbability'))
    fixed = prob(row.get('permitsBlendProbability'))
    raw = None
    if base is not None and original is not None and existing is not None:
        if abs(existing - (original + base) / 2) > 1e-8:
            raise ValueError('Incumbent does not reproduce from its original signal and base')
    if base is not None and fixed is not None:
        recovered = 2 * fixed - base
        if not -1e-10 <= recovered <= 1 + 1e-10:
            raise ValueError('Fixed permits blend implies an invalid raw probability')
        # The public snapshot rounds fields independently to twelve decimals.
        raw = min(1.0, max(0.0, recovered))
    features = row.get('features', row)
    slope, credit = finite(features.get('slope')), finite(features.get('credit'))
    return dict(
        slope=slope,
        credit=credit,
        state=state_for(slope, credit),
        originalProbability=original,
        baselineProbability=base,
        rawPermitsProbability=raw,
        existingBlendProbability=existing,
        fixedPermitsProbability=fixed,
    )


def fit_weights(history, refit):
    """Fit on the intersection of available issued signals, states and already-complete outcomes."""
    date = pd.Timestamp(refit)
    cutoff = iso(date - pd.DateOffset(months=13))
    eligible = [
        r
        for r in history
        if r['date'] <= cutoff
        and r['target'] is not None
        and r['state'] is not None
        and r['originalProbability'] is not None
        and r['rawPermitsProbability'] is not None
        and r['existingBlendProbability'] is not None
    ]
    warmup = len(eligible) < MIN_TRAINING

    def moment_fit(data, field, anchor):
        disagreements = [
            (r[field] - r['baselineProbability'], r['target'] - r['baselineProbability']) for r in data
        ]
        numerator = fsum(d * residual for d, residual in disagreements)
        denominator = fsum(d * d for d, _ in disagreements)
        weight = (
            0.5 if warmup else min(1.0, max(0.0, (numerator + PENALTY * anchor) / (denominator + PENALTY)))
        )
        return dict(n=len(data), numerator=numerator, denominator=denominator, weight=weight)

    fits = {}
    by_state = {s: [r for r in eligible if r['state'] == s] for s in ('normal', 'stress')}
    for name, field in [('permits', 'rawPermitsProbability'), ('original', 'originalProbability')]:
        pool = moment_fit(eligible, field, 0.5)
        fits[name] = {
            'pool': pool,
            **{s: moment_fit(group, field, pool['weight']) for s, group in by_state.items()},
        }
    end = eligible[-1]['date'] if eligible else None
    return dict(
        refitDate=iso(date),
        trainingCutoff=cutoff,
        trainStart=eligible[0]['date'] if eligible else None,
        trainEnd=end,
        lastTargetMonth=iso(pd.Timestamp(end) + pd.DateOffset(months=12)) if end else None,
        trainingN=len(eligible),
        warmup=warmup,
        **fits,
    )


def apply_weights(row, fit):
    state, base = row['state'], row['baselineProbability']
    permit_weight = fit['permits'][state]['weight'] if state else None
    original_weight = fit['original'][state]['weight'] if state else None
    pooled = fit['permits']['pool']['weight']
    rule_weight = SPEC['ruleWeights'].get(state)

    def blend(signal, weight):
        return base + weight * (signal - base) if None not in (base, signal, weight) else None

    return dict(
        fixedRuleWeight=rule_weight,
        fixedRuleProbability=blend(row['rawPermitsProbability'], rule_weight),
        permitsWeight=permit_weight,
        originalWeight=original_weight,
        pooledWeight=pooled,
        probability=blend(row['rawPermitsProbability'], permit_weight),
        pooledPermitsProbability=blend(row['rawPermitsProbability'], pooled),
        originalDynamicProbability=blend(row['originalProbability'], original_weight),
        refitDate=fit['refitDate'],
        trainingCutoff=fit['trainingCutoff'],
        trainingN=fit['trainingN'],
    )


def evaluate(rows, start, end, metrics):
    period = [r for r in rows if start and end and start <= r['date'] <= end]
    incumbent = [r for r in period if r['target'] is not None and r['existingBlendProbability'] is not None]
    paired = [r for r in incumbent if r['commonMature']]
    scores = {
        name: (
            metrics([r['target'] for r in paired], [r[field] for r in paired])
            if paired
            else dict(brier=None, logLoss=None, auc=None)
        )
        for name, field in PREDICTIONS.items()
    }
    expected = len(pd.date_range(start, end, freq='MS')) if start and end else 0
    return dict(
        windowStart=start,
        windowEnd=end,
        start=paired[0]['date'] if paired else None,
        end=paired[-1]['date'] if paired else None,
        n=len(paired),
        positiveWindows=sum(r['target'] for r in paired),
        expectedCalendarMonths=expected,
        incumbentN=len(incumbent),
        missingCandidateMonths=len(incumbent) - len(paired),
        missingIncumbentMonths=expected - len(incumbent),
        warmupMonths=sum(r['trainingN'] < MIN_TRAINING for r in paired),
        models=scores,
    )


def build_weight_trial(leading, metrics):
    current = leading['latest']
    issue = pd.Timestamp(current['issueDate'])
    if not issue.is_month_start:
        raise ValueError('Current issue must be a calendar-month start')
    history = []
    for source in leading['history']:
        if source.get('forecastType') not in (None, 'annual-walk-forward'):
            continue
        date = pd.Timestamp(source['date'])
        if date > issue:
            continue
        if not date.is_month_start or (history and source['date'] <= history[-1]['date']):
            raise ValueError('Annual forecasts must have unique increasing calendar months')
        if source.get('refitDate', iso(pd.Timestamp(date.year, 1, 1))) != iso(pd.Timestamp(date.year, 1, 1)):
            raise ValueError('Historical signals must come from an annual forecast refit')
        if source['featureDate'] != iso(date - pd.DateOffset(months=2)):
            raise ValueError('Historical signal date differs from its two-month lag')
        target = source.get('target')
        mature = target in (0, 1) and date + pd.DateOffset(months=12) < issue
        history.append(
            dict(
                date=iso(date),
                featureDate=source['featureDate'],
                target=int(target) if mature else None,
                recession=source.get('recession'),
                issuePhase=source.get('issuePhase') if mature else None,
                onsetDate=source.get('onsetDate') if mature else None,
                monthsToOnset=source.get('monthsToOnset') if mature else None,
                **components(source),
            )
        )

    folds = {}
    for row in history:
        january = row['date'][:4] + '-01-01'
        if january not in folds:
            folds[january] = fit_weights(history, january)
        row.update(apply_weights(row, folds[january]))
        row['commonMature'] = row['target'] is not None and all(
            row[key] is not None for key in PREDICTIONS.values()
        )

    eligible_dates = [
        r['date'] for r in history if r['target'] is not None and r['existingBlendProbability'] is not None
    ]
    start, end = (eligible_dates[0], eligible_dates[-1]) if eligible_dates else (None, None)
    recent_start = iso(pd.Timestamp(end) - pd.DateOffset(months=119)) if end else None
    periods = dict(
        all=evaluate(history, start, end, metrics), rolling120=evaluate(history, recent_start, end, metrics)
    )

    def gate(method, control):
        def beats(key):
            models = periods[key]['models']
            return bool(periods[key]['n'] and models[method]['brier'] < models[control]['brier'])

        full, recent = beats('all'), beats('rolling120')
        return dict(allPassed=full, rolling120Passed=recent, passed=full and recent)

    fit = fit_weights(history, issue)
    latest = components(current)
    if current['featureDate'] != iso(issue - pd.DateOffset(months=2)):
        raise ValueError('Current signal date differs from its two-month lag')
    if current['forecastStart'] != iso(issue + pd.DateOffset(months=1)) or current['forecastEnd'] != iso(
        issue + pd.DateOffset(months=12)
    ):
        raise ValueError('Current forecast horizon differs from its issue date')
    if not current.get('available', True):
        latest['rawPermitsProbability'] = latest['fixedPermitsProbability'] = None
    latest.update(apply_weights(latest, fit))
    available = all(latest[field] is not None for field in PREDICTIONS.values())
    reason = (
        None
        if available
        else current.get('reason')
        or 'A dated regime input, permits forecast or incumbent comparison is unavailable.'
    )
    latest.update(
        available=available,
        reason=reason,
        fit=fit,
        issueDate=iso(issue),
        featureDate=current['featureDate'],
        forecastStart=current['forecastStart'],
        forecastEnd=current['forecastEnd'],
    )
    return dict(
        version='1.0',
        spec=SPEC.copy(),
        latest=latest,
        history=history,
        folds=list(folds.values()),
        metrics=periods,
        gate={**gate('candidate', 'existingBlend'), 'versusFixedPermits': gate('candidate', 'fixedPermits')},
        ruleGate={
            **gate('fixedRule', 'existingBlend'),
            'versusFixedPermits': gate('fixedRule', 'fixedPermits'),
        },
        coverage=dict(
            annualIssueMonths=len(history),
            incumbentMatureN=len(eligible_dates),
            commonMatureN=periods['all']['n'],
            latestMatureIncumbentIssue=end,
            missingCandidateMonths=periods['all']['missingCandidateMonths'],
        ),
    )
