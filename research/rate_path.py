"""Fixed-design five-input rate-path trial; annual latest-vintage replay only.

Design: original three signals plus six-month term-spread change and twelve-month
Fed funds change, each observed two months before issue. One raw L2 logistic and
its fixed 50/50 training-prevalence blend. No variant search or tuned blend weight.
The matched-three models are controlled ablations, not additional candidates.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
import numpy as np
import pandas as pd

FEATURES = ['slope', 'credit', 'labor', 'slopeChange6', 'fedFundsChange12']
BASE_FEATURES = FEATURES[:3]
RECIPE = '0.5 * raw five-input probability + 0.5 * expanding training prevalence'
DESIGN_ID = 'rate-path-5-fixed-50-v1'
PREDICTIONS = {
    'original': 'originalProbability',
    'existingBlend': 'existingBlendProbability',
    'base': 'baselineProbability',
    'rawFive': 'rawProbability',
    'candidate': 'probability',
    'candidateBase': 'candidateBaseProbability',
    'matchedThree': 'matchedThreeProbability',
    'matchedThreeBlend': 'matchedThreeBlendProbability',
    'recentPrior': 'recentPriorProbability',
    'recentBlend': 'recentBlendProbability',
}


def iso(value):
    return pd.Timestamp(value).strftime('%Y-%m-%d')


def _calendar(frame, name):
    result = frame.copy()
    result.index = pd.DatetimeIndex(pd.to_datetime(result.index))
    if result.index.has_duplicates or not result.index.is_monotonic_increasing:
        raise ValueError(f'{name}: duplicate or unsorted dates')
    if result.index.hasnans or any(result.index.day != 1):
        raise ValueError(f'{name}: dates must be calendar-month starts')
    return result


def add_rate_path_features(panel, source):
    """Calendar endpoint differences, then an explicit two-calendar-month lag."""
    panel = _calendar(panel, 'Issue panel')
    monthly = _calendar(source, 'Observation source').asfreq('MS')
    if 'FEDFUNDS' not in monthly:
        raise ValueError('FEDFUNDS observation levels are required')
    if {'GS10', 'TB3MS'}.issubset(monthly.columns):
        slope = monthly.GS10 - monthly.TB3MS
    elif 'slope' in monthly:
        slope = monthly.slope
    else:
        raise ValueError('Observed GS10/TB3MS or slope levels are required')
    additions = pd.DataFrame({
        'slopeChange6': slope - slope.shift(6),
        'fedFundsChange12': monthly.FEDFUNDS - monthly.FEDFUNDS.shift(12),
    })
    # Shift the DATE labels, never two rows of a potentially gapped issue panel.
    additions.index = additions.index + pd.DateOffset(months=2)
    for key in FEATURES[3:]:
        panel[key] = additions[key].reindex(panel.index)
    panel[FEATURES] = panel[FEATURES].replace([np.inf, -np.inf], np.nan)
    panel.loc[~panel.target.isin([0, 1]), 'target'] = np.nan
    if 'USREC' in monthly and not monthly.USREC.dropna().empty:
        label_cutoff = monthly.USREC.dropna().index[-1]
        panel.loc[panel.index + pd.DateOffset(months=12) > label_cutoff, 'target'] = np.nan
    return panel


def recent_training_prior(panel, cutoff):
    """Exactly 180 calendar issues ending at formal cutoff; no sliding window."""
    cutoff = pd.Timestamp(cutoff)
    start = cutoff - pd.DateOffset(months=179)
    original = _calendar(panel, 'Recent-prior issue panel')
    full_span = bool(len(original) and original.index[0] <= start and original.index[-1] >= cutoff)
    window = original.loc[(original.index >= start) & (original.index <= cutoff)].copy()
    window[BASE_FEATURES] = window[BASE_FEATURES].replace([np.inf, -np.inf], np.nan)
    eligible = window.dropna(subset=BASE_FEATURES + ['target'])
    eligible = eligible.loc[eligible.target.isin([0, 1])]
    valid = full_span and len(eligible) >= 120
    return dict(probability=float(eligible.target.mean()) if valid else None,
                n=len(eligible), start=iso(start), end=iso(cutoff), fullSpan=full_span,
                observedStart=iso(eligible.index[0]) if len(eligible) else None,
                observedEnd=iso(eligible.index[-1]) if len(eligible) else None)


def _original_frame(original_history):
    frame = pd.DataFrame(original_history).copy()
    if 'date' in frame.columns:
        frame = frame.set_index('date')
    frame = _calendar(frame, 'Official annual forecasts')
    aliases = {'originalProbability': 'probability', 'baselineProbability': 'baseline'}
    for old, new in aliases.items():
        if new not in frame and old in frame:
            frame[new] = frame[old]
    if not {'probability', 'baseline'}.issubset(frame.columns):
        raise ValueError('Official annual probabilities and training base rates are required')
    if 'forecastType' in frame:
        frame = frame.loc[frame.forecastType == 'annual-walk-forward']
    return frame


def _metric_slice(frame, metric_fn, key, label):
    mature = frame.dropna(subset=['target'] + list(PREDICTIONS.values()))
    model_metrics = {}
    for model, column in PREDICTIONS.items():
        model_metrics[model] = metric_fn(mature.target, mature[column]) if len(mature) else dict(auc=None, brier=None, logLoss=None)
    def improvement(first, comparator):
        return {metric: model_metrics[comparator][metric] - model_metrics[first][metric]
                if len(mature) else None for metric in ['brier', 'logLoss']}
    return dict(id=key, label=label, start=iso(mature.index[0]) if len(mature) else None,
                end=iso(mature.index[-1]) if len(mature) else None, n=len(mature),
                positiveWindows=int(mature.target.sum()),
                recessionIssueMonths=int((mature.recession == 1).sum()), models=model_metrics,
                improvement={
                    'candidateVsExistingBlend': improvement('candidate', 'existingBlend'),
                    'candidateVsBase': improvement('candidate', 'base'),
                    'rawFiveVsOriginal': improvement('rawFive', 'original'),
                    'rawFiveVsMatchedThree': improvement('rawFive', 'matchedThree'),
                    'candidateVsMatchedThreeBlend': improvement('candidate', 'matchedThreeBlend'),
                    'recentBlendVsExistingBlend': improvement('recentBlend', 'existingBlend'),
                    'recentBlendVsBase': improvement('recentBlend', 'base'),
                    'recentBlendVsRecentPrior': improvement('recentBlend', 'recentPrior'),
                })


def build_rate_path(panel, source, original_history, latest, fit_logit, score, metrics, generated_at=None):
    expanded = add_rate_path_features(panel, source)
    original = _original_frame(original_history)
    complete = expanded.loc[expanded[FEATURES].notna().all(axis=1)]
    if complete.empty:
        raise ValueError('No complete five-input rate-path issue month')
    history, folds, skipped = [], [], []
    unmatched, invalid_comparators = 0, 0
    for year in range(1990, expanded.index[-1].year + 1):
        refit = pd.Timestamp(year, 1, 1)
        training_cutoff = refit - pd.DateOffset(months=13)
        train = complete.loc[complete.index <= training_cutoff].dropna(subset=['target'])
        test = complete.loc[(complete.index >= refit) & (complete.index < pd.Timestamp(year + 1, 1, 1))]
        if test.empty:
            continue
        if len(train) < 100 or train.target.nunique() != 2:
            skipped.append(dict(refitDate=iso(refit), trainingN=len(train), reason='Insufficient eligible training history'))
            continue
        last_target = train.index[-1] + pd.DateOffset(months=12)
        assert last_target < refit
        raw_model = fit_logit(train[FEATURES], train.target, penalty=1.)
        matched_three = fit_logit(train[BASE_FEATURES], train.target, penalty=1.)
        raw_predictions = score(raw_model, test[FEATURES])
        matched_predictions = score(matched_three, test[BASE_FEATURES])
        prevalence = float(train.target.mean())
        recent_prior = recent_training_prior(expanded, training_cutoff)
        fold = dict(refitDate=iso(refit), trainingCutoff=iso(training_cutoff),
                    trainStart=iso(train.index[0]), trainEnd=iso(train.index[-1]),
                    lastTargetMonth=iso(last_target), trainingN=len(train),
                    trainingPrevalence=prevalence, means=raw_model['means'], scales=raw_model['scales'],
                    recentPrior=recent_prior)
        folds.append(fold)
        for (date, row), raw_probability, matched_probability in zip(test.iterrows(), raw_predictions, matched_predictions):
            if date not in original.index:
                unmatched += 1
                continue
            official = original.loc[date]
            p3, b3 = float(official.probability), float(official.baseline)
            if not all(np.isfinite(v) and 0 <= v <= 1 for v in [p3, b3]):
                invalid_comparators += 1
                continue
            fixed_three = .5 * p3 + .5 * b3
            if 'blendProbability' in official and pd.notna(official.blendProbability):
                if abs(float(official.blendProbability) - fixed_three) > 1e-7:
                    raise ValueError('Official fixed-three blend disagrees with its published recipe')
            if 'target' in official and pd.notna(official.target) and pd.notna(row.target) and official.target != row.target:
                raise ValueError('Candidate and original outcome clocks disagree')
            history.append(dict(
                date=iso(date), featureDate=iso(date - pd.DateOffset(months=2)),
                target=float(row.target) if pd.notna(row.target) else None,
                recession=float(row.recession) if pd.notna(row.recession) else None,
                **{key: float(row[key]) for key in FEATURES},
                originalProbability=p3, existingBlendProbability=fixed_three,
                baselineProbability=b3, candidateBaseProbability=prevalence,
                rawProbability=float(raw_probability), probability=.5 * float(raw_probability) + .5 * prevalence,
                fixed50Probability=.5 * float(raw_probability) + .5 * prevalence,
                matchedThreeProbability=float(matched_probability),
                matchedThreeBlendProbability=.5 * float(matched_probability) + .5 * prevalence,
                recentPriorProbability=recent_prior['probability'],
                recentBlendProbability=.5 * p3 + .5 * recent_prior['probability'] if recent_prior['probability'] is not None else None,
                recentPriorN=recent_prior['n'], recentPriorStart=recent_prior['start'], recentPriorEnd=recent_prior['end'],
                recentPriorObservedStart=recent_prior['observedStart'], recentPriorObservedEnd=recent_prior['observedEnd'],
                refitDate=iso(refit), trainingCutoff=iso(training_cutoff), trainEnd=iso(train.index[-1]),
                lastTargetMonth=iso(last_target), trainingN=len(train),
                forecastType='annual-walk-forward', candidateLabelType='fixed-five-input-50-50-base-blend',
            ))
    if not history:
        raise ValueError('No comparable annual rate-path forecasts')
    frame = pd.DataFrame(history).set_index('date')
    frame.index = pd.to_datetime(frame.index)
    all_metrics = _metric_slice(frame, metrics, 'all', 'All common mature issues')
    recent_metrics = _metric_slice(frame.loc[frame.index >= '2016-01-01'], metrics, 'recent', 'Precommitted recent window: 2016 onward')
    decades = []
    for decade in sorted(set((frame.index.year // 10) * 10)):
        group = frame.loc[(frame.index.year >= decade) & (frame.index.year < decade + 10)]
        decades.append(_metric_slice(group, metrics, str(decade), f'{decade}s'))
    issue = complete.index[-1]
    train = complete.loc[complete.index <= issue - pd.DateOffset(months=13)].dropna(subset=['target'])
    if len(train) < 100 or train.target.nunique() != 2:
        raise ValueError('Insufficient current monthly rate-path training history')
    final = fit_logit(train[FEATURES], train.target, penalty=1.)
    final.update(featureOrder=FEATURES, trainedFrom=iso(train.index[0]), trainedThrough=iso(train.index[-1]),
                 trainingN=len(train), lastTargetMonth=iso(train.index[-1] + pd.DateOffset(months=12)),
                 refitDate=iso(issue))
    current_features = {key: float(complete.loc[issue, key]) for key in FEATURES}
    raw_probability = float(score(final, [[current_features[key] for key in FEATURES]])[0])
    prevalence = float(train.target.mean())
    current_recent_prior = recent_training_prior(expanded, issue - pd.DateOffset(months=13))
    same_issue = iso(issue) == latest['issueDate']
    current_original = float(latest['probability']) if same_issue else float(original.loc[issue, 'probability']) if issue in original.index else None
    current_original_base = float(latest['baselineProbability']) if same_issue else float(original.loc[issue, 'baseline']) if issue in original.index else None
    def cleared(slice_metrics):
        models = slice_metrics['models']
        return bool(slice_metrics['n'] and models['candidate']['brier'] < models['existingBlend']['brier']
                    and models['candidate']['brier'] < models['base']['brier'])
    all_passed, recent_passed = cleared(all_metrics), cleared(recent_metrics)
    def recent_cleared(slice_metrics, comparator):
        models = slice_metrics['models']
        return bool(slice_metrics['n'] and models['recentBlend']['brier'] < models[comparator]['brier'])
    recent_all_passed = all(recent_cleared(all_metrics, key) for key in ['existingBlend', 'base'])
    recent_recent_passed = all(recent_cleared(recent_metrics, key) for key in ['existingBlend', 'base'])
    own_all_passed = recent_cleared(all_metrics, 'recentPrior')
    own_recent_passed = recent_cleared(recent_metrics, 'recentPrior')
    coverage = dict(inputIssueMonths=len(expanded), completeFiveIssueMonths=len(complete),
                    missingFiveIssueMonths=len(expanded) - len(complete),
                    missingByFeature={key: int(expanded[key].isna().sum()) for key in FEATURES},
                    unmatchedOfficialForecastMonths=unmatched, invalidComparatorMonths=invalid_comparators,
                    historyRows=len(history), matureN=all_metrics['n'],
                    matureTargetN=int(frame.target.notna().sum()), pendingN=int(frame.target.isna().sum()),
                    commonExcludedMatureN=int(frame.target.notna().sum()) - all_metrics['n'],
                    candidateBaseDiffersFromOfficialN=sum(abs(row['candidateBaseProbability'] - row['baselineProbability']) > 1e-7 for row in history),
                    latestOriginalIssueDate=latest['issueDate'], latestCandidateIssueDate=iso(issue),
                    staleIssueMonths=(pd.Timestamp(latest['issueDate']).year - issue.year) * 12 + pd.Timestamp(latest['issueDate']).month - issue.month,
                    skippedFolds=skipped,
                    missingRecentPriorMonths=sum(row['recentPriorProbability'] is None for row in history),
                    commonComparisonModels=list(PREDICTIONS),
                    rawMatureBeforeCommonFilter=int(frame.target.notna().sum()))
    return dict(
        version='1.0', status='experimental fixed-design chronological replay',
        generatedAt=generated_at or datetime.now(timezone.utc).isoformat(),
        issueDate=iso(issue), featureDate=iso(issue - pd.DateOffset(months=2)),
        spec=dict(id=DESIGN_ID, name='Rate-path five-input trial', featureOrder=FEATURES,
                  recipe=RECIPE,
                  recentPriorDesignId='recent-prior-180-fixed-50-v1',
                  recentPriorRecipe='0.5 * original three-input probability + 0.5 * recent 180-calendar-month training prevalence',
                  recentPriorCalendarMonths=180, recentPriorMinimumObserved=120,
                  recentPriorDefinition='Mean known binary targets on complete original-three-input issues in 180 consecutive calendar months ending at formal issue/refit minus 13 months; requires full 15-year calendar span and at least 120 observed eligible months. Window boundaries do not slide when recent labels are missing.',
                  recentPriorDesignStatus='Second distinct hypothesis specified before its scoring after the first rate-path candidate was evaluated; no tuning after seeing this second result. It remains exploratory, not untouched holdout evidence.',
                  rawWeight=.5, trainingBaseWeight=.5, penalty=1.,
                  featureLagMonths=2, horizonMonths=12, eligibilityMonths=13,
                  recentStart='2016-01-01', annualRefit='January; expanding window; target ends strictly before refit',
                  currentRefit='Monthly on eligible mature labels',
                  featureFormulas={
                      'slopeChange6': '(GS10_t - TB3MS_t) - (GS10_(t-6) - TB3MS_(t-6)); percentage points',
                      'fedFundsChange12': 'FEDFUNDS_t - FEDFUNDS_(t-12); percentage points',
                  },
                  designStatus='One specification, fixed weights and comparison windows set before calculating these trial results. The wider project was motivated by historical failures, so this remains exploratory latest-vintage replay, not untouched or real-time validation.',
                  comparatorPolicy='Official original annual forecasts, their expanding base and fixed 50/50 blend, on the exact common issue dates. Candidate uses its own complete-five training prevalence; matched-three ablations share that training sample and prevalence.',
                  improvementSign='Positive differences mean lower candidate/raw-five error than the named comparator.',
                  limitations=[
                      'The target includes continuation of an existing recession, not onset alone.',
                      'Revised observations and retrospectively dated NBER labels remain; target purging does not reconstruct historical vintages or announcement availability.',
                      'Monthly outcomes overlap and recent slices contain few independent downturns.',
                      'The fixed blend is an experimental probability recipe, not independently validated calibration.',
                      'No missing observations are interpolated; endpoint changes require the exact calendar-month endpoints.',
                  ]),
        model=final,
        latest=dict(probability=.5 * raw_probability + .5 * prevalence,
                    fixed50Probability=.5 * raw_probability + .5 * prevalence, rawProbability=raw_probability,
                    originalProbability=current_original, originalBaseProbability=current_original_base,
                    existingBlendProbability=.5 * (current_original + current_original_base) if current_original is not None and current_original_base is not None else None,
                    baselineProbability=prevalence, candidateBaseProbability=prevalence, features=current_features,
                    recentPriorProbability=current_recent_prior['probability'],
                    recentBlendProbability=.5 * current_original + .5 * current_recent_prior['probability'] if current_original is not None and current_recent_prior['probability'] is not None else None,
                    recentPriorN=current_recent_prior['n'], recentPriorStart=current_recent_prior['start'], recentPriorEnd=current_recent_prior['end'],
                    recentPriorObservedStart=current_recent_prior['observedStart'], recentPriorObservedEnd=current_recent_prior['observedEnd'],
                    recentPriorFullSpan=current_recent_prior['fullSpan'],
                    issueDate=iso(issue), featureDate=iso(issue - pd.DateOffset(months=2)),
                    forecastStart=iso(issue + pd.DateOffset(months=1)), forecastEnd=iso(issue + pd.DateOffset(months=12)),
                    trainingN=len(train), trainedThrough=iso(train.index[-1]),
                    originalComparisonFit='current-original-monthly-or-live' if same_issue else 'dated-original-annual-replay'),
        metrics=dict(all=all_metrics, recent=recent_metrics, decades=decades), history=history, folds=folds, coverage=coverage,
        recentPriorGate=dict(
            criterion='Recent blend must beat official fixed-three blend and expanding base in both all and 2016-onward windows; incremental model contribution additionally requires beating its own recent-prior-only control in both.',
            allPassed=recent_all_passed, recentPassed=recent_recent_passed,
            benchmarksPassed=recent_all_passed and recent_recent_passed,
            beatsOwnPriorAll=own_all_passed, beatsOwnPriorRecent=own_recent_passed,
            incrementalModelContributionSupported=own_all_passed and own_recent_passed,
            passed=recent_all_passed and recent_recent_passed and own_all_passed and own_recent_passed,
            decision='passes-retrospective-screen-still-experimental' if recent_all_passed and recent_recent_passed and own_all_passed and own_recent_passed else 'not-cleared-preserve-current-default',
            note='Changing the prior can help without incremental value from the raw model. Compare both controls; no main-model promotion or future-performance claim follows from this historical experiment.'),
        publicationGate=dict(criterion='Candidate Brier must beat both official fixed-three blend and official expanding base in BOTH all-history and precommitted 2016-onward windows.',
                             allPassed=all_passed, recentPassed=recent_passed, passed=all_passed and recent_passed,
                             decision='passes-retrospective-screen-still-experimental' if all_passed and recent_passed else 'not-cleared-preserve-current-default',
                             note='A passed retrospective screen is not prospective validation. No post-result feature, weight or window search is permitted.'),
    )


def rate_path_history_csv(result):
    """Deterministic complete annual evidence, including explicitly pending targets."""
    return pd.DataFrame(result['history']).to_csv(index=False, float_format='%.12f', na_rep='')


def from_raw(root, as_of):
    """Rebuild trial inputs from retained provider observations without network or writes."""
    from build_model import fit_logit, score, metrics
    root = Path(root)
    asof = pd.Timestamp(as_of).to_period('M').to_timestamp()
    observations = {}
    for series in ['GS10', 'TB3MS', 'FEDFUNDS', 'NFCICREDIT', 'UNRATE', 'USREC']:
        values = pd.read_csv(root / 'research' / 'raw' / f'{series}.csv', index_col=0, parse_dates=True, na_values=['.', ''])[series]
        values = pd.to_numeric(values, errors='coerce')
        if series == 'NFCICREDIT':
            values = values.groupby(values.index.to_period('M')).mean()
            values.index = values.index.to_timestamp()
        observations[series] = values.loc[values.index < asof]
    source = pd.DataFrame(observations).sort_index().asfreq('MS')
    source['slope'] = source.GS10 - source.TB3MS
    source['credit'] = source.NFCICREDIT
    smooth = source.UNRATE.rolling(3, min_periods=2).mean()
    source['labor'] = smooth - smooth.rolling(12, min_periods=12).min()
    index = pd.date_range('1971-01-01', asof, freq='MS')
    panel = pd.DataFrame(index=index)
    for key in BASE_FEATURES:
        panel[key] = source[key].reindex(index).shift(2)
    rec = observations['USREC'].reindex(pd.date_range(observations['USREC'].index.min(), asof, freq='MS'))
    forward = pd.concat([rec.shift(-i) for i in range(1, 13)], axis=1)
    panel['target'] = forward.max(axis=1).where(forward.notna().all(axis=1)).reindex(index)
    panel['recession'] = rec.reindex(index)
    panel = panel.loc[panel[BASE_FEATURES].notna().all(axis=1)]
    original = pd.read_csv(root / 'public' / 'data' / 'predictions.csv', index_col=0, parse_dates=True)
    latest = json.loads((root / 'data' / 'snapshot.json').read_text())['latest']
    return build_rate_path(panel, source, original, latest, fit_logit, score, metrics)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--as-of', default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument('--csv', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = from_raw(root, args.as_of)
    if args.csv:
        print(rate_path_history_csv(result), end='')
    else:
        from build_model import clean
        print(json.dumps(clean({key: result[key] for key in ['spec', 'latest', 'metrics', 'coverage', 'publicationGate', 'recentPriorGate']}), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
