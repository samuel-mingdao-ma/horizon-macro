"""A fixed, chronological trial of building permits and initial unemployment claims."""

from __future__ import annotations

import numpy as np
import pandas as pd

BASE = ['slope', 'credit', 'labor']
FEATURES = [*BASE, 'permitGrowth6', 'claimsGrowth12']
MODELS = {
    'matchedThree': BASE,
    'permits': [*BASE, 'permitGrowth6'],
    'claims': [*BASE, 'claimsGrowth12'],
    'joint': FEATURES,
}
PREDICTIONS = {
    'existingBlend': 'existingBlendProbability',
    'matchedThreeBlend': 'matchedThreeBlendProbability',
    'permitsBlend': 'permitsBlendProbability',
    'claimsBlend': 'claimsBlendProbability',
    'rawFive': 'rawProbability',
    'candidate': 'probability',
}
MIN_TRAINING = 100
DESIGN_ID = 'permits-claims-five-same-base-v1'


def iso(value):
    return pd.Timestamp(value).strftime('%Y-%m-%d') if pd.notna(value) else None


def month_frame(frame, name):
    result = frame.copy()
    result.index = pd.DatetimeIndex(pd.to_datetime(result.index))
    if (
        result.index.hasnans
        or result.index.has_duplicates
        or not result.index.is_monotonic_increasing
        or not result.index.is_month_start.all()
    ):
        raise ValueError(f'{name} requires sorted, unique calendar-month start dates')
    return result


def add_leading_features(panel, source):
    """Source contains levels by observation month. Shift the dates, never the retained rows."""
    panel = month_frame(panel, 'Issue panel')
    source = month_frame(source, 'Monthly observations').asfreq('MS')
    for series, key, lag in [('PERMIT', 'permitGrowth6', 6), ('ICSA', 'claimsGrowth12', 12)]:
        level = pd.to_numeric(source.reindex(columns=[series])[series], errors='coerce')
        level = level.where(np.isfinite(level) & (level > 0))
        average = level.rolling(3, min_periods=3).mean()
        change = 100 * (average / average.shift(lag) - 1)
        change.index = change.index + pd.DateOffset(months=2)
        panel[key] = change.reindex(panel.index)
    panel[FEATURES] = panel[FEATURES].replace([np.inf, -np.inf], np.nan)
    panel['target'] = panel.target.where(panel.target.isin([0, 1]))
    if 'USREC' in source:
        # Gaps in the dated recession indicator leave the entire affected outcome pending.
        labels = source.USREC.where(source.USREC.isin([0, 1]))
        future = pd.concat([labels.shift(-i) for i in range(1, 13)], axis=1)
        verified = future.max(axis=1).where(future.notna().all(axis=1)).reindex(panel.index)
        both = verified.notna() & panel.target.notna()
        if (verified.loc[both] != panel.target.loc[both]).any():
            raise ValueError('Leading trial and source recession outcomes disagree')
        panel['target'] = panel.target.where(verified.notna())
    return panel


def number(value):
    return float(value) if pd.notna(value) and np.isfinite(value) else None


def probability(value):
    value = number(value)
    return value if value is not None and 0 <= value <= 1 else None


def fit_models(complete, refit, fit_logit, *, models=MODELS):
    cutoff = refit - pd.DateOffset(months=13)
    train = complete.loc[complete.index <= cutoff].dropna(subset=['target'])
    fold = dict(
        refitDate=iso(refit),
        trainingCutoff=iso(cutoff),
        trainingN=len(train),
        trainStart=iso(train.index.min()),
        trainEnd=iso(train.index.max()),
        lastTargetMonth=iso(train.index.max() + pd.DateOffset(months=12)),
        available=False,
        reason=None,
    )
    if len(train) < MIN_TRAINING or train.target.nunique() < 2:
        fold['reason'] = 'Fewer than 100 complete training issues or only one outcome class.'
        return {}, fold
    assert train.index[-1] + pd.DateOffset(months=12) < refit
    fitted = {name: fit_logit(train[columns], train.target, penalty=1.0) for name, columns in models.items()}
    # Keep original-scale and standardized coefficients so the fold's scores can be reproduced.
    for name, params in fitted.items():
        params.update(
            featureOrder=models[name],
            refitDate=iso(refit),
            trainingN=len(train),
            trainedFrom=fold['trainStart'],
            trainedThrough=fold['trainEnd'],
            trainingCutoff=fold['trainingCutoff'],
            lastTargetMonth=fold['lastTargetMonth'],
        )
    fold.update(available=True, models=fitted, trainingPrevalence=float(train.target.mean()))
    return fitted, fold


def forecasts(raw, base):
    """Apply the identical official base to the fitted models, including the two ablations."""

    def blend(name):
        return (raw[name] + base) / 2 if name in raw and base is not None else None

    return dict(
        matchedThreeBlendProbability=blend('matchedThree'),
        permitsBlendProbability=blend('permits'),
        claimsBlendProbability=blend('claims'),
        rawProbability=raw.get('joint'),
        probability=blend('joint'),
    )


def evaluation(history, start, end, metric_fn, *, predictions=PREDICTIONS, benchmark='existingBlendProbability'):
    window = [] if start is None or end is None else [r for r in history if start <= r['date'] <= end]
    incumbent = [r for r in window if r['target'] is not None and r[benchmark] is not None]
    common = [r for r in incumbent if r['commonMature']]
    y = [r['target'] for r in common]
    models = {
        key: metric_fn(y, [r[column] for r in common]) if common else dict(brier=None, logLoss=None, auc=None)
        for key, column in predictions.items()
    }
    months = 0 if start is None or end is None else len(pd.date_range(start, end, freq='MS'))
    return dict(
        windowStart=start,
        windowEnd=end,
        start=common[0]['date'] if common else None,
        end=common[-1]['date'] if common else None,
        n=len(common),
        positiveWindows=int(sum(y)),
        expectedCalendarMonths=months,
        incumbentN=len(incumbent),
        missingCandidateMonths=len(incumbent) - len(common),
        missingIncumbentMonths=months - len(incumbent),
        models=models,
    )


def build_leading_trial(panel, source, history_frame, latest, fit_logit, score, metrics):
    issue = pd.Timestamp(latest['issueDate'])
    official = history_frame.copy()
    if 'date' in official:
        official = official.set_index('date')
    official = month_frame(official, 'Official forecast history')
    if 'forecastType' in official:
        official = official.loc[official.forecastType == 'annual-walk-forward']
    official = official.loc[official.index <= issue]
    panel = month_frame(panel, 'Issue panel')
    # An absent candidate row must not move the incumbent's evaluation endpoint.
    absent = official.index.difference(panel.index)
    if len(absent):
        panel = panel.reindex(panel.index.union(absent))
        for key in ['target', 'recession']:
            if key in official:
                panel.loc[absent, key] = official.loc[absent, key]
    expanded = add_leading_features(panel, source)
    expanded = expanded.loc[expanded.index <= issue].copy()
    # The current issue month is still incomplete. No target ending this month is scored.
    expanded.loc[expanded.index + pd.DateOffset(months=12) >= issue, 'target'] = np.nan
    complete = expanded.dropna(subset=FEATURES)
    history, folds = [], []
    for year, old in official.groupby(official.index.year):
        refit = pd.Timestamp(year, 1, 1)
        fitted, fold = fit_models(complete, refit, fit_logit)
        folds.append(fold)
        issues = expanded.reindex(old.index)
        test = issues.dropna(subset=FEATURES)
        raw = (
            {
                name: pd.Series(score(model, test[MODELS[name]]), index=test.index)
                for name, model in fitted.items()
            }
            if not test.empty
            else {}
        )
        for date, original in old.iterrows():
            data = issues.loc[date]
            p, base = probability(original.probability), probability(original.baseline)
            target = number(data.target) if original.target in (0, 1) else None
            if target is not None and target != original.target:
                raise ValueError('Incumbent and leading trial have different outcome labels')
            old_blend = (p + base) / 2 if p is not None and base is not None else None
            if pd.notna(original.get('blendProbability')) and old_blend is not None:
                if abs(original.blendProbability - old_blend) > 1e-7:
                    raise ValueError(
                        'Existing 50/50 probability is inconsistent with its published components'
                    )
            predicted = {key: float(series.loc[date]) for key, series in raw.items() if date in series.index}
            row = dict(
                date=iso(date),
                featureDate=iso(date - pd.DateOffset(months=2)),
                target=target,
                recession=number(data.get('recession')),
                **{key: number(data.get(key)) for key in FEATURES},
                originalProbability=p,
                baselineProbability=base,
                existingBlendProbability=old_blend,
                **forecasts(predicted, base),
                refitDate=iso(refit),
                trainingCutoff=fold['trainingCutoff'],
                trainingN=fold['trainingN'],
                trainEnd=fold['trainEnd'],
                lastTargetMonth=fold['lastTargetMonth'],
            )
            row['commonMature'] = target is not None and all(
                row[col] is not None for col in PREDICTIONS.values()
            )
            history.append(row)

    eligible_dates = [
        r['date'] for r in history if r['target'] is not None and r['existingBlendProbability'] is not None
    ]
    first, last = (eligible_dates[0], eligible_dates[-1]) if eligible_dates else (None, None)
    recent_start = iso(pd.Timestamp(last) - pd.DateOffset(months=119)) if last else None
    periods = dict(
        all=evaluation(history, first, last, metrics),
        rolling120=evaluation(history, recent_start, last, metrics),
    )

    def beats(window):
        result = periods[window]
        return bool(
            result['n']
            and result['models']['candidate']['brier'] < result['models']['existingBlend']['brier']
        )

    all_passed, recent_passed = beats('all'), beats('rolling120')

    current_models, current_fit = fit_models(complete, issue, fit_logit)
    current = expanded.reindex([issue]).iloc[0]
    values = {key: number(current[key]) for key in FEATURES}
    missing = [key for key, val in values.items() if val is None]
    base = probability(latest.get('baselineProbability'))
    original_p = probability(latest.get('probability'))
    reason = current_fit['reason']
    if missing:
        reason = 'Unavailable at the required observation date: ' + ', '.join(missing)
    elif base is None or original_p is None:
        reason = 'The official forecast or expanding base is unavailable at this issue date.'
    current_raw = (
        {
            key: float(score(model, [[values[k] for k in MODELS[key]]])[0])
            for key, model in current_models.items()
        }
        if reason is None
        else {}
    )
    latest_result = dict(
        available=reason is None,
        reason=reason,
        issueDate=iso(issue),
        featureDate=iso(issue - pd.DateOffset(months=2)),
        forecastStart=iso(issue + pd.DateOffset(months=1)),
        forecastEnd=iso(issue + pd.DateOffset(months=12)),
        features=values,
        originalProbability=original_p,
        baselineProbability=base,
        existingBlendProbability=(
            (original_p + base) / 2 if original_p is not None and base is not None else None
        ),
        **forecasts(current_raw, base),
        trainingN=current_fit['trainingN'],
        trainingCutoff=current_fit['trainingCutoff'],
        trainStart=current_fit['trainStart'],
        trainEnd=current_fit['trainEnd'],
        lastTargetMonth=current_fit['lastTargetMonth'],
    )
    return dict(
        version='1.0',
        status='exploratory latest-vintage annual walk-forward replay',
        spec=dict(
            id=DESIGN_ID,
            featureOrder=FEATURES,
            modelWeight=0.5,
            priorWeight=0.5,
            penalty=1.0,
            minimumTrainingIssues=MIN_TRAINING,
            featureLagMonths=2,
            horizonMonths=12,
            excludedRecentIssues=12,
            featureFormulas={
                'permitGrowth6': 'Percent change over six calendar months in the trailing three-month mean of PERMIT.',
                'claimsGrowth12': 'Percent change over twelve calendar months in the trailing three-month mean of calendar-month weekly ICSA averages.',
            },
            baseline='The official expanding base from the original forecast on the identical issue date.',
            decision='Select the joint specification before scoring. Both paired Brier comparisons must improve. The single-signal fits are attribution controls.',
            validation='Later-revised data and retrospectively dated outcomes. Overlapping twelve-month windows share information.',
        ),
        latest=latest_result,
        model=current_models.get('joint'),
        currentModels=current_models,
        history=history,
        folds=folds,
        metrics=periods,
        gate=dict(allPassed=all_passed, rolling120Passed=recent_passed, passed=all_passed and recent_passed),
        coverage=dict(
            annualIssueMonths=len(history),
            incumbentMatureN=len(eligible_dates),
            commonMatureN=periods['all']['n'],
            latestMatureIncumbentIssue=last,
            missingCandidateMonths=periods['all']['missingCandidateMonths'],
        ),
    )
