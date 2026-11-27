"""Walk-forward decomposition of credit conditions in the existing 50/50 permits forecast."""

import numpy as np
import pandas as pd

from leading_trial import (
    FEATURES as LEADING_FEATURES, MIN_TRAINING, add_leading_features, evaluation, fit_models,
    iso, month_frame, number, probability,
)

MODELS = {
    'matchedLevel': ['slope', 'credit', 'labor', 'permitGrowth6'],
    'slowOnly': ['slope', 'creditSlow', 'labor', 'permitGrowth6'],
    'shockOnly': ['slope', 'creditShock', 'labor', 'permitGrowth6'],
    'candidate': ['slope', 'creditSlow', 'creditShock', 'labor', 'permitGrowth6'],
}
PREDICTIONS = {
    'benchmark': 'benchmarkProbability',
    'matchedLevel': 'matchedLevelProbability',
    'slowOnly': 'slowOnlyProbability',
    'shockOnly': 'shockOnlyProbability',
    'candidate': 'probability',
}
# Retain the original permits trial's complete-case policy, including the claims availability check.
REQUIRED = [*LEADING_FEATURES, 'creditSlow', 'creditShock']
FLAGS = ['persistent', 'sudden']
SPEC = dict(
    id='permits-fixed-half-credit-decomposition-v1',
    benchmark='Published fixed 50/50 permits signal and expanding base from the same issue.',
    featureLagMonths=2, horizonMonths=12, penalty=1.0, modelWeight=0.5,
    minimumTrainingIssues=MIN_TRAINING, priorMeanMonths=3, shockHistoryMonths=60,
    shockQuantile=0.9, flagPrecisionDecimals=12, warningThreshold=0.30,
    models=MODELS,
    design='Primary model replaces the credit level with the previous three months’ mean and the latest level minus that mean. The two single-component models and the matched level fit are controls.',
    flags='Persistent when each previous monthly level was positive. Sudden when the current shock is positive and exceeds the 90th percentile of the previous 60 monthly shocks. The two flags can overlap. They describe issues and do not enter the model.',
    fitClock='All four fits use identical complete training rows. Each January refit uses outcomes ending strictly before January. The current issue uses a separate monthly refit.',
)


def credit_signals(monthly_credit):
    """Return observation-month indexed components. Missing calendar months stay in the rolling windows."""
    levels = month_frame(monthly_credit.to_frame('level'), 'Monthly NFCICREDIT').asfreq('MS')['level']
    levels = pd.to_numeric(levels, errors='coerce').replace([np.inf, -np.inf], np.nan)
    prior = levels.shift(1).rolling(SPEC['priorMeanMonths'], min_periods=SPEC['priorMeanMonths'])
    slow = prior.mean()
    shock = levels - slow
    threshold = shock.shift(1).rolling(SPEC['shockHistoryMonths']).quantile(SPEC['shockQuantile'], interpolation='linear')
    digits = SPEC['flagPrecisionDecimals']
    persistent = (prior.min().round(digits) > 0).astype('boolean').where(slow.notna())
    sudden = ((shock.round(digits) > 0) & (shock.round(digits) > threshold.round(digits))).astype('boolean')
    return pd.DataFrame(dict(creditSlow=slow, creditShock=shock, shockThreshold=threshold,
                             persistent=persistent, sudden=sudden.where(shock.notna() & threshold.notna())))


def issue_features(panel, source):
    expanded = add_leading_features(panel, source)
    credit = source.reindex(columns=['NFCICREDIT'])['NFCICREDIT']
    derived = credit_signals(credit)
    derived.index = derived.index + pd.DateOffset(months=SPEC['featureLagMonths'])
    expanded = expanded.join(derived)
    valid = expanded[['credit', 'creditSlow', 'creditShock']].dropna()
    if not np.allclose(valid.credit, valid.creditSlow + valid.creditShock, rtol=0, atol=1e-10):
        raise ValueError('Decomposed credit level disagrees with the contemporaneous benchmark input')
    return expanded


def forecast_rows(rows, fitted, score):
    """All arms operate on the same input months, regardless of descriptive flag coverage."""
    eligible = rows.dropna(subset=REQUIRED)
    raw = pd.DataFrame(index=rows.index, columns=list(MODELS), dtype=float)
    if not eligible.empty:
        for arm, model in fitted.items():
            raw.loc[eligible.index, arm] = score(model, eligible[MODELS[arm]])
    return raw


def make_row(date, data, old, raw, fold):
    base = probability(old.get('baselineProbability'))
    result = dict(
        featureDate=iso(date - pd.DateOffset(months=2)),
        **{key: number(data[key]) for key in [*REQUIRED, 'shockThreshold']},
        **{key: bool(data[key]) if pd.notna(data[key]) else None for key in FLAGS},
        baselineProbability=base, benchmarkProbability=probability(old.get('permitsBlendProbability')),
        **{key: fold[key] for key in ['refitDate', 'trainingN', 'trainingCutoff', 'trainEnd', 'lastTargetMonth']},
    )
    if old['featureDate'] != result['featureDate']:
        raise ValueError('Different observation months for the benchmark and the credit decomposition')
    for arm in MODELS:
        p = probability(raw[arm])
        result[PREDICTIONS[arm]] = (p + base) / 2 if p is not None and base is not None else None
    return result


def build_credit_trial(panel, source, leading, fit_logit, score, metrics):
    old_latest = leading['latest']
    issue = pd.Timestamp(old_latest['issueDate'])
    published = pd.DataFrame(leading['history'])
    if published.empty:
        published = pd.DataFrame(index=pd.DatetimeIndex([], name='date'))
    else:
        published = month_frame(published.set_index('date'), 'Published permits issues')
    if not published.empty and published.index[-1] > issue:
        raise ValueError('A replay issue is later than the current issue')
    features = issue_features(panel.loc[:issue], source)
    features.loc[features.index + pd.DateOffset(months=12) >= issue, 'target'] = np.nan
    complete = features.dropna(subset=REQUIRED)

    history, folds = [], []
    for year, group in published.groupby(published.index.year):
        refit = pd.Timestamp(year, 1, 1)
        fitted, fold = fit_models(complete, refit, fit_logit, models=MODELS)
        folds.append(fold)
        rows = features.reindex(group.index)
        raw = forecast_rows(rows, fitted, score)
        for date, old in group.iterrows():
            target = number(old['target'])
            if target is not None and (target not in (0, 1) or date + pd.DateOffset(months=12) >= issue):
                raise ValueError('Invalid or incomplete benchmark outcome')
            if target is not None and pd.notna(rows.at[date, 'target']) and rows.at[date, 'target'] != target:
                raise ValueError('Different outcomes for the benchmark and the credit decomposition')
            row = dict(date=iso(date), target=target, recession=number(old['recession']),
                       **make_row(date, rows.loc[date], old, raw.loc[date], fold))
            row['issuePhase'] = old.get('issuePhase') if pd.notna(old.get('issuePhase')) else None
            row['onsetDate'] = old.get('onsetDate') if pd.notna(old.get('onsetDate')) else None
            row['monthsToOnset'] = number(old.get('monthsToOnset'))
            row['commonMature'] = target is not None and all(row[field] is not None for field in PREDICTIONS.values())
            history.append(row)

    dates = [r['date'] for r in history if r['target'] is not None and r['benchmarkProbability'] is not None]
    first, last = (dates[0], dates[-1]) if dates else (None, None)
    recent = iso(pd.Timestamp(last) - pd.DateOffset(months=119)) if last else None
    windows = {
        key: evaluation(history, start, last, metrics, predictions=PREDICTIONS, benchmark='benchmarkProbability')
        for key, start in [('all', first), ('rolling120', recent)]
    }
    passed = {
        key + 'Passed': bool(w['n'] and w['models']['candidate']['brier'] < w['models']['benchmark']['brier'])
        for key, w in windows.items()
    }

    fitted, current_fold = fit_models(complete, issue, fit_logit, models=MODELS)
    current = features.reindex([issue])
    raw = forecast_rows(current, fitted, score)
    latest = make_row(issue, current.iloc[0], old_latest, raw.iloc[0], current_fold)
    reason = current_fold['reason']
    missing = [field for field in REQUIRED if latest[field] is None]
    if missing:
        reason = 'Missing inputs for this issue: ' + ', '.join(missing)
    elif latest['benchmarkProbability'] is None or latest['baselineProbability'] is None:
        reason = 'The published permits forecast or its expanding base is unavailable.'
    if reason is not None:
        for arm in MODELS:
            latest[PREDICTIONS[arm]] = None
    start, end = iso(issue + pd.DateOffset(months=1)), iso(issue + pd.DateOffset(months=12))
    if start != old_latest['forecastStart'] or end != old_latest['forecastEnd']:
        raise ValueError('Different horizons for the benchmark and the credit decomposition')
    latest.update(available=reason is None, reason=reason, issueDate=iso(issue), forecastStart=start, forecastEnd=end)
    return dict(spec=SPEC, history=history, folds=folds, currentModels=fitted, latest=latest,
                metrics=windows, gate={**passed, 'passed': all(passed.values())})
