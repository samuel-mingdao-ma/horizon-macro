"""Conditional onset forecasts trained on mature, expansion-origin permits issues."""

import pandas as pd

from leading_trial import (
    FEATURES as COMPLETE_CASE,
    MIN_TRAINING,
    MODELS as LEADING_MODELS,
    add_leading_features,
    fit_models,
    iso,
    month_frame,
    number,
    probability,
)

FEATURES = LEADING_MODELS['permits']
PREDICTIONS = {
    'benchmark': 'benchmarkProbability',
    'candidate': 'probability',
    'signalOnlyChange': 'signalOnlyChangeProbability',
    'baseOnlyChange': 'baseOnlyChangeProbability',
    'expansionPrior': 'expansionPriorProbability',
}
FIT_FIELDS = (
    'refitDate',
    'trainingCutoff',
    'trainingN',
    'trainingPositives',
    'trainingOnsets',
    'trainStart',
    'trainEnd',
    'lastTargetMonth',
)
SPEC = dict(
    id='expansion-onset-permits-fixed-half-v1',
    featureOrder=FEATURES,
    modelWeight=0.5,
    penalty=1.0,
    warningThreshold=0.30,
    featureLagMonths=2,
    horizonMonths=12,
    minimumTrainingIssues=MIN_TRAINING,
    target='First USREC transition from zero to one in the next twelve months, conditional on expansion in the issue month.',
    benchmark='Published same-issue fixed 50/50 permits forecast and original historical base.',
    prior='Fraction of the expansion-only estimation sample followed by an onset within twelve months.',
    fitClock='January replay and separate monthly live refit. All thirteen training labels must be observed and the horizon must end before the refit month.',
    scoring='Produce conditional probabilities every issue. Select mature expansion-origin months for retrospective scoring only. Current business-cycle status is not an input.',
)


def onset_labels(source, as_of):
    """Keep the last month incomplete. A positive target needs thirteen consecutive binary labels."""
    flags = month_frame(source[['USREC']], 'Recession labels').asfreq('MS')['USREC']
    flags = flags.loc[flags.index < as_of]
    if not flags.dropna().isin([0, 1]).all():
        raise ValueError('USREC labels must be zero, one, or missing')
    future = pd.concat([flags.shift(-i) for i in range(1, 13)], axis=1)
    transitions = flags.eq(1) & flags.shift(1).eq(0)
    future_entries = pd.DataFrame({i: transitions.shift(-i) for i in range(1, 13)})
    eligible = flags.eq(0) & future.notna().all(axis=1)
    positive = eligible & future_entries.eq(True).any(axis=1)
    target = positive.astype(float).where(eligible)
    lead = future_entries.eq(True).idxmax(axis=1).where(positive)
    dates = pd.Series(pd.NaT, index=flags.index, dtype='datetime64[ns]')
    for distance in range(1, 13):
        subset = lead.index[lead.eq(distance)]
        dates.loc[subset] = subset + pd.DateOffset(months=distance)
    return pd.DataFrame(dict(issueRecession=flags, target=target, onsetDate=dates, monthsToOnset=lead))


def fit_expansion(eligible, refit, fit_logit):
    models, fold = fit_models(eligible, refit, fit_logit, models={'candidate': FEATURES})
    train = eligible.loc[: fold['trainingCutoff']]
    counts = dict(trainingPositives=int(train.target.sum()), trainingOnsets=int(train.onsetDate.nunique()))
    fold.update(counts)
    prior = float(train.target.mean()) if len(train) else None
    fold['trainingPrevalence'] = prior
    model = models.get('candidate')
    if model is not None:
        model.update(**counts, trainingPrevalence=prior)
    return model, fold


def issue_forecasts(rows, published, model, fold, score):
    eligible = rows.dropna(subset=COMPLETE_CASE)
    fitted = pd.Series(dtype=float)
    if model is not None and not eligible.empty:
        fitted = pd.Series(score(model, eligible[FEATURES]), index=eligible.index)
    expected = (rows.index - pd.DateOffset(months=2)).strftime('%Y-%m-%d')
    if not (published['featureDate'].to_numpy() == expected).all():
        raise ValueError('Permits benchmark and expansion forecast have different feature dates')
    results = []
    for date, data in rows.iterrows():
        old = published.loc[date]
        base = probability(old.get('baselineProbability'))
        benchmark = probability(old.get('permitsBlendProbability'))
        permits = 2 * benchmark - base if benchmark is not None and base is not None else None
        if permits is not None:
            if permits < -1e-8 or permits > 1 + 1e-8:
                raise ValueError('Published permits forecast cannot be reconstructed as a 50/50 blend')
            permits = min(1.0, max(0.0, permits))
        p = probability(fitted.get(date))
        prior = fold['trainingPrevalence']
        results.append(
            dict(
                date=iso(date),
                featureDate=old['featureDate'],
                **{key: number(data[key]) for key in COMPLETE_CASE},
                **{key: fold[key] for key in FIT_FIELDS},
                baselineProbability=base,
                expansionPriorProbability=prior,
                rawExpansionProbability=p,
                rawPermitsProbability=permits,
                benchmarkProbability=benchmark,
                probability=(p + prior) / 2 if p is not None and prior is not None else None,
                signalOnlyChangeProbability=(p + base) / 2 if p is not None and base is not None else None,
                baseOnlyChangeProbability=(
                    (permits + prior) / 2 if permits is not None and prior is not None else None
                ),
            )
        )
    return results


def evaluate(history, start, end, metrics):
    rows = [r for r in history if start and end and start <= r['date'] <= end and r['matureBenchmark']]
    paired = [r for r in rows if r['commonMature']]
    y = [r['target'] for r in paired]
    scores = {
        k: metrics(y, [r[field] for r in paired]) if paired else dict(brier=None, logLoss=None, auc=None)
        for k, field in PREDICTIONS.items()
    }
    months = len(pd.date_range(start, end, freq='MS')) if end and start else 0
    known = sum(r['issueRecession'] == 0 and r['target'] is not None for r in rows)
    return dict(
        windowStart=start,
        windowEnd=end,
        expectedCalendarMonths=months,
        matureBenchmarkN=len(rows),
        recessionN=sum(r['issueRecession'] == 1 for r in rows),
        unknownPhaseN=sum(r['issueRecession'] is None for r in rows),
        incompleteHorizonN=sum(r['issueRecession'] == 0 and r['target'] is None for r in rows),
        missingBenchmarkMonths=months - len(rows),
        expansionN=known,
        missingCandidateMonths=known - len(paired),
        n=len(paired),
        positiveWindows=int(sum(y)),
        distinctOnsets=len({r['onsetDate'] for r in paired if r['target'] == 1}),
        models=scores,
    )


def build_expansion_trial(panel, source, leading, fit_logit, score, metrics):
    current = leading['latest']
    issue = pd.Timestamp(current['issueDate'])
    # This transformation uses observed permits and claims only. USREC is handled
    # separately on the strictly completed-month clock, including when a source
    # happens to contain a preliminary issue-month label.
    signals = add_leading_features(panel.loc[:issue], source.reindex(columns=['PERMIT', 'ICSA']))
    labels = onset_labels(source, issue)
    data = signals.drop(columns='target').join(labels)
    train_pool = data.dropna(subset=[*COMPLETE_CASE, 'target'])
    published = pd.DataFrame(leading['history'])
    if not published.empty:
        published = month_frame(published.set_index('date'), 'Published permits issues')
        if published.index[-1] > issue:
            raise ValueError('A replay issue is later than the current issue')

    history, folds = [], []
    groups = published.groupby(published.index.year) if not published.empty else ()
    for year, group in groups:
        model, fold = fit_expansion(train_pool, pd.Timestamp(year, 1, 1), fit_logit)
        folds.append(fold)
        forecasts = issue_forecasts(data.reindex(group.index), group, model, fold, score)
        evaluation_labels = labels.reindex(group.index)
        for row in forecasts:
            date = pd.Timestamp(row['date'])
            verified = evaluation_labels.loc[date]
            origin, target = number(verified.issueRecession), number(verified.target)
            old_target = number(group.loc[date, 'target'])
            if old_target is not None:
                if old_target not in (0, 1) or date + pd.DateOffset(months=12) >= issue:
                    raise ValueError('Invalid or incomplete benchmark outcome')
                if target is not None and target != old_target:
                    raise ValueError('Benchmark and onset target differ on a mature expansion month')
            phase = (
                'recession-issued'
                if origin == 1
                else 'pre-onset' if target == 1 else 'expansion-no-recession' if target == 0 else None
            )
            mature = old_target is not None and row['benchmarkProbability'] is not None
            row.update(
                issueRecession=origin,
                issuePhase=phase,
                target=target,
                onsetDate=iso(verified.onsetDate),
                monthsToOnset=number(verified.monthsToOnset),
                matureBenchmark=mature,
                commonMature=mature
                and target is not None
                and all(row[f] is not None for f in PREDICTIONS.values()),
            )
        history.extend(forecasts)
    dates = [r['date'] for r in history if r['matureBenchmark']]
    start, end = (dates[0], dates[-1]) if dates else (None, None)
    recent = iso(pd.Timestamp(end) - pd.DateOffset(months=119)) if end else None
    windows = {k: evaluate(history, lo, end, metrics) for k, lo in [('all', start), ('rolling120', recent)]}
    wins = {
        k + 'Passed': bool(w['n'] and w['models']['candidate']['brier'] < w['models']['benchmark']['brier'])
        for k, w in windows.items()
    }

    model, fold = fit_expansion(train_pool, issue, fit_logit)
    (latest,) = issue_forecasts(
        data.reindex([issue]), pd.DataFrame([current], index=[issue]), model, fold, score
    )
    start, end = iso(issue + pd.DateOffset(months=1)), iso(issue + pd.DateOffset(months=12))
    if (start, end) != (current['forecastStart'], current['forecastEnd']):
        raise ValueError('Benchmark and expansion onset forecast have different horizons')
    reason = fold['reason']
    if any(latest[f] is None for f in COMPLETE_CASE):
        reason = 'The required two-month-lagged permits model inputs are incomplete.'
    elif latest['rawPermitsProbability'] is None:
        reason = 'The published permits 50/50 comparison is unavailable.'
    if reason is not None:
        for field in ('probability', 'signalOnlyChangeProbability', 'baseOnlyChangeProbability'):
            latest[field] = None
    latest.update(
        issueDate=latest.pop('date'),
        forecastStart=start,
        forecastEnd=end,
        available=reason is None,
        reason=reason,
        conditionalOnExpansion=True,
    )
    return dict(
        spec=SPEC,
        latest=latest,
        currentModel=model,
        history=history,
        folds=folds,
        metrics=windows,
        gate={**wins, 'passed': all(wins.values())},
    )
