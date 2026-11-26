"""One fixed, post-hoc research challenger and reproducible alarm diagnostics.

This is an exploratory replay designed after seeing historical false alarms.
It is not an untouched holdout, a causal model, or a new scientific method.
"""
from __future__ import annotations
from datetime import datetime, timezone
import numpy as np
import pandas as pd

BASE_FEATURES = ['slope', 'credit', 'labor']
CHALLENGER_FEATURES = BASE_FEATURES + ['interaction']
DEFAULT_THRESHOLD = .30
CASE_WINDOWS = [
    ('2007', 'Global financial crisis', '2006-01-01', '2009-12-01'),
    ('2020', 'Pandemic shock', '2019-01-01', '2021-12-01'),
    ('2023', 'Inversion without recession', '2022-01-01', '2024-12-01'),
]


def iso(value):
    return pd.Timestamp(value).strftime('%Y-%m-%d')


def add_interaction(panel):
    """Fixed formula; loose (negative) credit values retain their sign."""
    result = panel.copy()
    result['interaction'] = np.maximum(-result.slope, 0) * result.credit
    return result


def confirmation(features):
    """Supplementary alarm condition, never a probability transformation."""
    return bool(features['credit'] > 0 or features['labor'] >= .5)


def challenger_walk_forward(panel, fit_logit, score):
    rows, folds = [], []
    for year in range(1990, panel.index[-1].year + 1):
        refit = pd.Timestamp(year, 1, 1)
        train = panel.loc[panel.index <= refit-pd.DateOffset(months=13)].dropna(subset=CHALLENGER_FEATURES+['target'])
        test = panel.loc[(panel.index >= refit) & (panel.index < pd.Timestamp(year+1, 1, 1))].dropna(subset=CHALLENGER_FEATURES)
        if test.empty:
            continue
        if len(train) < 100 or train.target.nunique() != 2:
            raise ValueError(f'Insufficient challenger training data at {iso(refit)}')
        last_target = train.index[-1]+pd.DateOffset(months=12)
        assert last_target < refit, 'Challenger training target overlaps refit'
        model = fit_logit(train[CHALLENGER_FEATURES], train.target, penalty=1.0)
        probabilities = score(model, test[CHALLENGER_FEATURES])
        folds.append(dict(refit=iso(refit), trainStart=iso(train.index[0]), trainEnd=iso(train.index[-1]),
                          lastTargetMonth=iso(last_target), n=len(train), means=model['means'], scales=model['scales']))
        for (date, row), probability in zip(test.iterrows(), probabilities):
            rows.append(dict(date=iso(date), challengerProbability=float(probability), interaction=float(row.interaction)))
    return rows, folds


def _peak(rows, key):
    row = max(rows, key=lambda item: item[key])
    return dict(date=row['date'], probability=row[key], target=row['target'])


def case_summaries(history):
    result=[]
    for key, title, start, end in CASE_WINDOWS:
        rows=[row for row in history if start <= row['date'] <= end]
        mature=[row for row in rows if pd.notna(row['target'])]
        curve_alerts=[row for row in mature if row['curveProbability'] >= DEFAULT_THRESHOLD]
        confirmed=[row for row in curve_alerts if row['confirmation']]
        if not rows:
            raise ValueError(f'No observations in fixed case window {key}')
        positives=sum(int(row['target']) for row in mature)
        summary=dict(n=len(rows), evaluatedN=len(mature), positiveWindows=positives,
                     observedRate=positives/len(mature) if mature else None,
                     meanOriginal=float(np.mean([row['originalProbability'] for row in rows])),
                     meanCurve=float(np.mean([row['curveProbability'] for row in rows])),
                     meanChallenger=float(np.mean([row['challengerProbability'] for row in rows])),
                     peakOriginal=_peak(rows,'originalProbability'), peakCurve=_peak(rows,'curveProbability'),
                     peakChallenger=_peak(rows,'challengerProbability'), curveAlerts=len(curve_alerts),
                     confirmedAlerts=len(confirmed),unconfirmedAlerts=len(curve_alerts)-len(confirmed))
        result.append(dict(id=key,title=title,start=start,end=end,history=rows,summary=summary))
    return result


def build_surface(train, model, latest_labor, score):
    # A fixed grid over training 2.5th–97.5th percentiles. It is a conditional
    # sensitivity surface, not a distribution over economic scenarios.
    slope_axis=np.linspace(train.slope.quantile(.025),train.slope.quantile(.975),25)
    credit_axis=np.linspace(train.credit.quantile(.025),train.credit.quantile(.975),25)
    slope_scale=float(train.slope.std(ddof=0)) or 1.
    credit_scale=float(train.credit.std(ddof=0)) or 1.
    points=[]
    for credit in credit_axis:
        for slope in slope_axis:
            values=np.array([[slope,credit,latest_labor,max(-slope,0)*credit]])
            distance2=((train.slope.to_numpy()-slope)/slope_scale)**2+((train.credit.to_numpy()-credit)/credit_scale)**2
            points.append(dict(slope=float(slope),credit=float(credit),probability=float(score(model,values)[0]),
                               supportN=int(np.sum(distance2 <= .35**2))))
    training_points=[dict(date=iso(date),slope=float(row.slope),credit=float(row.credit),labor=float(row.labor),target=int(row.target))
                     for date,row in train.iterrows()]
    return dict(xFeature='slope',yFeature='credit',fixedLabor=float(latest_labor),gridSize=25,supportRadiusStd=.35,
                supportDefinition='Count of training months within radius 0.35 in training-standardized slope/credit space; labor proximity is not required. Counts are overlapping months, not independent episodes.',
                slopeValues=slope_axis,creditValues=credit_axis,points=points,trainingPoints=training_points)


def build_innovation(panel, original_history, latest, fit_logit, score, metrics, generated_at=None):
    expanded=add_interaction(panel)
    challenger_rows, folds=challenger_walk_forward(expanded,fit_logit,score)
    original=original_history.copy()
    original.index=pd.to_datetime(original.index)
    records=[]
    for row in challenger_rows:
        date=pd.Timestamp(row['date'])
        if date not in original.index:
            raise ValueError('Challenger/comparator evaluation clocks differ')
        previous=original.loc[date]
        features={key:float(expanded.loc[date,key]) for key in CHALLENGER_FEATURES}
        records.append(dict(date=iso(date),featureDate=iso(date-pd.DateOffset(months=2)),
                            target=float(previous.target) if pd.notna(previous.target) else None,
                            recession=float(previous.recession) if pd.notna(previous.recession) else None,
                            **features,originalProbability=float(previous.probability),curveProbability=float(previous.curveProbability),
                            challengerProbability=row['challengerProbability'],baseline=float(previous.baseline),
                            blendProbability=.5*float(previous.probability)+.5*float(previous.baseline),
                            confirmation=confirmation(features),forecastType='annual-walk-forward'))
    mature=pd.DataFrame(records).dropna(subset=['target'])
    if len(mature) != int(original.target.notna().sum()):
        raise ValueError('Challenger/comparator mature samples differ')
    issue=expanded.index[-1]
    train=expanded.loc[expanded.index <= issue-pd.DateOffset(months=13)].dropna(subset=CHALLENGER_FEATURES+['target'])
    final=fit_logit(train[CHALLENGER_FEATURES],train.target,penalty=1.)
    final.update(featureOrder=CHALLENGER_FEATURES,trainedFrom=iso(train.index[0]),trainedThrough=iso(train.index[-1]),
                 lastTargetMonth=iso(train.index[-1]+pd.DateOffset(months=12)),trainingN=len(train),refitDate=iso(issue))
    current_features={key:float(expanded.loc[issue,key]) for key in CHALLENGER_FEATURES}
    probability=float(score(final,np.array([[current_features[key] for key in CHALLENGER_FEATURES]]))[0])
    curve_model=fit_logit(train[['slope']],train.target,penalty=1.)
    curve_probability=float(score(curve_model,[[current_features['slope']]])[0])
    qualifies=confirmation(current_features)
    curve_alarm=curve_probability>=DEFAULT_THRESHOLD
    state='confirmed' if curve_alarm and qualifies else 'unconfirmed' if curve_alarm else 'below-threshold'
    regimes=[]
    for inverted in [False,True]:
        for tight in [False,True]:
            group=mature.loc[((mature.slope<0)==inverted)&((mature.credit>0)==tight)]
            positives=int(group.target.sum())
            regimes.append(dict(id=('inverted' if inverted else 'noninverted')+'-'+('tight' if tight else 'loose'),
                                inverted=inverted,creditTight=tight,n=len(group),positiveWindows=positives,
                                observedRate=positives/len(group) if len(group) else None,
                                meanOriginal=float(group.originalProbability.mean()) if len(group) else None,
                                meanChallenger=float(group.challengerProbability.mean()) if len(group) else None))
    rec=pd.Series([row['recession'] for row in records],index=pd.to_datetime([row['date'] for row in records]))
    independent=int(((rec==1)&(rec.shift(1)!=1)).sum())
    evaluation=dict(n=len(mature),start=mature.iloc[0].date,end=mature.iloc[-1].date,
                    positiveWindows=int(mature.target.sum()),independentRecessions=independent,
                    challenger=metrics(mature.target,mature.challengerProbability),
                    original=metrics(mature.target,mature.originalProbability),
                    curveOnly=metrics(mature.target,mature.curveProbability),baseRate=metrics(mature.target,mature.baseline),
                    blend=metrics(mature.target,mature.blendProbability))
    return dict(version='1.0',status='post-hoc exploratory research replay',
                generatedAt=generated_at or datetime.now(timezone.utc).isoformat(),issueDate=iso(issue),featureDate=latest['featureDate'],
                spec=dict(name='Credit-conditioned yield curve',
                    hypothesis='Does the relation between curve inversion and future recession risk depend on contemporaneous credit conditions?',
                    featureFormula='interaction = max(-slope, 0) * credit',penalty=1.,featureLagMonths=2,horizonMonths=12,
                    eligibilityMonths=13,refitFrequency='Annual expanding January refits; current estimate monthly refit',
                    designStatus='One fixed interaction specification proposed after viewing 2023 false alarms. No variant search. Chronological replay is not untouched holdout validation.',
                    confirmationRule='curveProbability >= threshold AND (credit > 0 OR labor >= 0.5)',defaultThreshold=DEFAULT_THRESHOLD,
                    caveats=['Post-hoc hypothesis: comparisons reuse the sample that motivated the design; prospective evaluation is needed.',
                             'Same revised-history and NBER announcement-lag limitations as the original model.',
                             'Confirmation is a supplementary decision policy, not a probability model or causal claim.',
                             'Cases and regime frequencies are descriptive, not independent validation sets.',
                             'The 50/50 original-model/base-rate blend is also post-hoc exploration motivated by historical calibration failure, not independently validated.',
                             'Surface support counts overlapping training months and ignores proximity in labor.']),
                model=final,latest=dict(probability=probability,originalProbability=latest['probability'],curveProbability=curve_probability,
                    baselineProbability=float(train.target.mean()),blendProbability=.5*latest['probability']+.5*float(train.target.mean()),features=current_features,
                    confirmation=dict(state=state,creditTight=current_features['credit']>0,laborDeteriorating=current_features['labor']>=.5,
                                      curveAlarm=curve_alarm,ruleSatisfied=qualifies,threshold=DEFAULT_THRESHOLD)),
                metrics=evaluation,history=records,cases=case_summaries(records),regimes=regimes,
                surface=build_surface(train,final,current_features['labor'],score),folds=folds)
