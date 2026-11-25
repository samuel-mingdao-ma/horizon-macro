#!/usr/bin/env python3
"""HORIZON: a reproducible latest-vintage recession-risk research pipeline.

Requires numpy, pandas, requests. No API key and no proprietary series.
Run `python3 research/build_model.py --refresh` from the project directory.
"""
from __future__ import annotations
import argparse
import concurrent.futures
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'research' / 'raw'
FEATURES = ['slope', 'credit', 'labor']
SERIES = {
 'GS10': ('10-year Treasury yield', 'Monthly', 'percent', 'Board of Governors of the Federal Reserve System'),
 'TB3MS': ('3-month Treasury bill rate', 'Monthly', 'percent, discount basis', 'Board of Governors of the Federal Reserve System'),
 'NFCICREDIT': ('Chicago Fed NFCI credit subindex', 'Weekly', 'index, standard deviations', 'Federal Reserve Bank of Chicago'),
 'UNRATE': ('Unemployment rate', 'Monthly', 'percent, seasonally adjusted', 'U.S. Bureau of Labor Statistics'),
 'USREC': ('NBER recession indicator', 'Monthly', '0 or 1', 'Federal Reserve Bank of St. Louis; NBER'),
 'CPIAUCSL': ('Consumer price index', 'Monthly', 'index, seasonally adjusted', 'U.S. Bureau of Labor Statistics'),
 'FEDFUNDS': ('Effective federal funds rate', 'Monthly', 'percent', 'Board of Governors of the Federal Reserve System'),
 'GS1': ('1-year Treasury yield', 'Monthly', 'percent', 'Board of Governors of the Federal Reserve System'),
 'GS2': ('2-year Treasury yield', 'Monthly', 'percent', 'Board of Governors of the Federal Reserve System'),
 'GS5': ('5-year Treasury yield', 'Monthly', 'percent', 'Board of Governors of the Federal Reserve System'),
 'GS30': ('30-year Treasury yield', 'Monthly', 'percent', 'Board of Governors of the Federal Reserve System'),
}


def iso(d):
    return pd.Timestamp(d).strftime('%Y-%m-%d')


def clean(x):
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(x) else round(float(x), 12)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (pd.Timestamp, datetime)):
        return iso(x)
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, np.ndarray)):
        return [clean(v) for v in x]
    return x


def load_series(series_id, refresh):
    path = RAW / f'{series_id}.csv'
    if refresh or not path.exists():
        url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'
        response = requests.get(url, timeout=(10, 20), headers={'User-Agent': 'Horizon-Macro-Research/1.0'})
        response.raise_for_status()
        if not response.text.splitlines()[0].endswith(',' + series_id):
            raise ValueError(f'{series_id}: unexpected FRED CSV format')
        path.write_text(response.text)
    frame = pd.read_csv(path, na_values=['.', ''], index_col=0, parse_dates=True)
    out = pd.to_numeric(frame[series_id], errors='coerce').dropna()
    if out.index.has_duplicates or not out.index.is_monotonic_increasing:
        raise ValueError(f'{series_id}: invalid index')
    return series_id, out


def sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -35, 35)))


def fit_logit(x, y, penalty=1.0):
    """Newton logistic: summed Bernoulli loss + .5*penalty*||beta||^2.

    Intercept unpenalized; standardization fitted solely on training features.
    Numerical line search, no class reweighting or data-dependent tuning.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mu, scale = x.mean(axis=0), x.std(axis=0, ddof=0)
    scale[scale < 1e-8] = 1.0
    design = np.column_stack([np.ones(len(x)), (x - mu) / scale])
    b = np.zeros(design.shape[1])
    b[0] = np.log(y.mean() / (1 - y.mean()))
    regularizer = np.diag([0] + [penalty] * x.shape[1])
    def objective(v):
        z = design @ v
        return np.sum(np.logaddexp(0, z) - y * z) + .5 * (v @ regularizer @ v)
    for _ in range(100):
        p = sigmoid(design @ b)
        grad = design.T @ (p-y) + regularizer @ b
        hess = design.T @ ((p * (1-p))[:, None] * design) + regularizer
        step = np.linalg.solve(hess + np.eye(len(b))*1e-10, grad)
        factor = 1.0
        old_loss = objective(b)
        while objective(b-factor*step) > old_loss and factor > 1e-8:
            factor *= .5
        b -= factor*step
        if np.max(np.abs(factor*step)) < 1e-9:
            break
    raw = b[1:] / scale
    return dict(means=mu, scales=scale, coefficients=b[1:], intercept=b[0],
                rawCoefficients=raw, rawIntercept=b[0] - np.dot(raw, mu), penalty=penalty)


def score(model, x):
    return sigmoid(np.asarray(x) @ model['rawCoefficients'] + model['rawIntercept'])


def auc(y, p):
    y, p = np.asarray(y), np.asarray(p)
    positive, negative = y.sum(), len(y)-y.sum()
    if not positive or not negative:
        return None
    ranks = pd.Series(p).rank(method='average').to_numpy()
    return float((ranks[y == 1].sum() - positive*(positive+1)/2) / (positive*negative))


def metrics(y, p):
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    clipped = np.clip(p, 1e-12, 1-1e-12)
    return dict(auc=auc(y, p), brier=np.mean((y-p)**2),
                logLoss=-np.mean(y*np.log(clipped)+(1-y)*np.log(1-clipped)))


def run_walk_forward(panel, embargo_months=13):
    records, fits = [], []
    for year in range(1990, panel.index[-1].year+1):
        refit = pd.Timestamp(year=year, month=1, day=1)
        train_max = refit - pd.DateOffset(months=embargo_months)
        train = panel.loc[panel.index <= train_max].dropna(subset=FEATURES+['target'])
        test = panel.loc[(panel.index >= refit) & (panel.index < pd.Timestamp(year+1, 1, 1))].dropna(subset=FEATURES)
        if len(test) == 0:
            continue
        if len(train) < 100 or train.target.nunique() < 2:
            raise ValueError(f'Insufficient training data at {refit}')
        model = fit_logit(train[FEATURES], train.target)
        curve = fit_logit(train[['slope']], train.target)
        p, pc = score(model, test[FEATURES]), score(curve, test[['slope']])
        fits.append({'refit': iso(refit), 'trainStart': iso(train.index[0]), 'trainEnd': iso(train.index[-1]),
                     'lastTargetMonth': iso(train.index[-1]+pd.DateOffset(months=12)), 'n':len(train)})
        assert train.index[-1] + pd.DateOffset(months=12) < refit
        for (date, row), probability, cp in zip(test.iterrows(), p, pc):
            records.append(dict(date=iso(date), featureDate=iso(date-pd.DateOffset(months=2)),
                                probability=float(probability), curveProbability=float(cp),
                                baseline=float(train.target.mean()), target=row.target,
                                recession=row.recession, slope=row.slope, credit=row.credit, labor=row.labor))
    return records, fits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh', action='store_true', help='Download all current FRED observations')
    parser.add_argument('--offline', action='store_true', help='Use existing cached raw CSV files')
    parser.add_argument('--as-of', default=datetime.now(timezone.utc).date().isoformat())
    args = parser.parse_args()
    asof = pd.Timestamp(args.as_of)
    asof_month = asof.to_period('M').to_timestamp()
    refresh = args.refresh and not args.offline
    RAW.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        raw = dict(pool.map(lambda s: load_series(s, refresh), SERIES))
    # Include only observations at or before the requested date. NFCI's partial
    # current month is never used as a monthly model feature or comparison point.
    raw = {s: v.loc[v.index <= asof] for s, v in raw.items()}
    monthly = {}
    for s, v in raw.items():
        if s == 'NFCICREDIT':
            agg = v.groupby(v.index.to_period('M')).mean()
            agg.index = agg.index.to_timestamp()
            monthly[s] = agg.loc[agg.index < asof_month]
        else:
            monthly[s] = v.loc[v.index < asof_month]
    source = pd.DataFrame(monthly).sort_index().asfreq('MS')
    # Calendar-month frequency is explicit: a missing month is not skipped.
    source['slope'] = source.GS10 - source.TB3MS
    source['credit'] = source.NFCICREDIT
    unemployment3 = source.UNRATE.rolling(3, min_periods=2).mean()
    source['labor'] = unemployment3 - unemployment3.rolling(12, min_periods=12).min()
    source['inflation'] = 100*(source.CPIAUCSL/source.CPIAUCSL.shift(12)-1)
    index = pd.date_range('1971-01-01', asof_month, freq='MS')
    panel = pd.DataFrame(index=index)
    for f in FEATURES:
        panel[f] = source[f].reindex(index).shift(2)
    # source extends to last complete month, but feature issue month may be now.
    rec = raw['USREC'].reindex(pd.date_range(raw['USREC'].index.min(), asof_month, freq='MS'))
    panel['recession'] = rec.reindex(index)
    future = pd.concat([rec.shift(-i) for i in range(1, 13)], axis=1)
    target = future.max(axis=1).where(future.notna().all(axis=1))
    panel['target'] = target.reindex(index)
    panel = panel.loc[panel[FEATURES].notna().all(axis=1)]
    history, folds = run_walk_forward(panel)
    # Exploratory post-hoc shrinkage diagnostic, never a replacement for the
    # prespecified production model or evidence of held-out calibration.
    for row in history:
        row['blendProbability'] = .5*row['probability'] + .5*row['baseline']
    history_frame = pd.DataFrame(history).set_index('date')
    mature = history_frame.dropna(subset=['target'])
    evaluation = dict(start=mature.index[0], end=mature.index[-1], n=len(mature),
                      events=None, positiveHorizons=int(mature.target.sum()), recessionMonths=int(mature.recession.sum()),
                      model=metrics(mature.target, mature.probability),
                      baseRate=metrics(mature.target, mature.baseline),
                      curveOnly=metrics(mature.target, mature.curveProbability))
    evaluation['exploratoryBlend'] = {**metrics(mature.target, mature.blendProbability),
        'modelWeight':.5, 'baseRateWeight':.5, 'n':len(mature),
        'status':'post-hoc exploratory',
        'note':'Equal-weight blend proposed after examining test-set calibration failures. Same historical rows, not an independently validated selected model. Requires future-vintage or untouched-period evaluation.'}
    issue = panel.index[-1]
    final_train = panel.loc[panel.index <= issue-pd.DateOffset(months=13)].dropna(subset=FEATURES+['target'])
    final_model = fit_logit(final_train[FEATURES], final_train.target)
    final_model.update(featureOrder=FEATURES, trainedFrom=iso(final_train.index[0]),
                       trainedThrough=iso(final_train.index[-1]), trainingN=len(final_train),
                       lastTargetMonth=iso(final_train.index[-1]+pd.DateOffset(months=12)), refitDate=iso(issue))
    feature_date = issue-pd.DateOffset(months=2)
    features = panel.loc[issue, FEATURES].to_numpy(dtype=float)
    probability = float(score(final_model, features))
    previous = float(score(final_model, panel.loc[panel.index[-2], FEATURES]))
    contributions=[]
    labels = {'slope':'Treasury curve', 'credit':'Credit conditions', 'labor':'Labor momentum'}
    for j, f in enumerate(FEATURES):
        z=(features[j]-final_model['means'][j])/final_model['scales'][j]
        contributions.append(dict(key=f,label=labels[f],value=features[j],standardized=z,
                                  coefficient=final_model['coefficients'][j],logOdds=z*final_model['coefficients'][j]))
    indicator_date = source.loc[source[['GS10','TB3MS','UNRATE','CPIAUCSL','FEDFUNDS']].notna().all(axis=1)].index[-1]
    obs = source.loc[indicator_date]
    latest = dict(probability=probability, previousProbability=previous, change=probability-previous,
                  regime='Elevated' if probability >= .30 else ('Watchful' if probability >= .15 else 'Contained'),
                  issueDate=iso(issue), featureDate=iso(feature_date),
                  features=dict(zip(FEATURES, features)),
                  forecastStart=iso(issue+pd.DateOffset(months=1)),forecastEnd=iso(issue+pd.DateOffset(months=12)),
                  indicatorDate=iso(indicator_date), indicators=dict(gs10=obs.GS10,tb3ms=obs.TB3MS,
                  unemployment=obs.UNRATE,inflation=source.inflation.dropna().iloc[-1],inflationDate=iso(source.inflation.dropna().index[-1]),fedFunds=obs.FEDFUNDS),
                  contributions=contributions,baselineProbability=float(final_train.target.mean()),
                  modelIntercept=final_model['intercept'])
    # Keep the live forecast separate from the annual walk-forward research model.
    # Last chart point is updated to the current production refit, explicitly tagged.
    for row in history:
        row['forecastType'] = 'annual-walk-forward'
    current_history = dict(date=iso(issue), featureDate=iso(feature_date), probability=probability,
                           baseline=float(final_train.target.mean()), curveProbability=float(score(fit_logit(final_train[['slope']],final_train.target),[[features[0]]])[0]),
                           blendProbability=.5*probability+.5*float(final_train.target.mean()),target=None,recession=None,slope=features[0],credit=features[1],labor=features[2],forecastType='current-month-refit')
    if history and history[-1]['date'] == iso(issue):
        history[-1] = current_history
    # recession shading, inclusive start and exclusive end.
    recession_periods=[]
    active=None
    for date, flag in rec.dropna().items():
        if flag == 1 and active is None:active=date
        if flag == 0 and active is not None:
            recession_periods.append(dict(start=iso(active),end=iso(date)))
            active=None
    if active is not None:recession_periods.append(dict(start=iso(active),end=iso(rec.dropna().index[-1]+pd.DateOffset(months=1))))
    evaluation['events'] = sum(1 for p in recession_periods if p['start'][:4] >= '1990' and p['start']<=evaluation['end'])
    calibration=[]
    for lo, hi in zip([0,.1,.2,.3,.4,.5,.6,.7,.8,.9],[.1,.2,.3,.4,.5,.6,.7,.8,.9,1.000001]):
        group=mature.loc[(mature.probability>=lo)&(mature.probability<hi)]
        if len(group):calibration.append(dict(lo=lo,hi=min(hi,1),n=len(group),predicted=group.probability.mean(),observed=group.target.mean()))
    # Label-delay sensitivity: eligibility target end is at least 12 months old.
    sensitivity_history, sensitivity_folds=run_walk_forward(panel, embargo_months=25)
    sensitivity_frame=pd.DataFrame(sensitivity_history).dropna(subset=['target'])
    sensitivity=dict(labelEmbargoMonths=25,n=len(sensitivity_frame),
                     model=metrics(sensitivity_frame.target,sensitivity_frame.probability),
                     note='Train issue <= refit minus 25 months; target end at least 12 months before refit. Latest-vintage inputs still revised.')
    yield_curve=[]
    for tenor, years, s in [('3M',.25,'TB3MS'),('1Y',1,'GS1'),('2Y',2,'GS2'),('5Y',5,'GS5'),('10Y',10,'GS10'),('30Y',30,'GS30')]:
        values=source[s].dropna()
        yield_curve.append(dict(tenor=tenor,years=years,value=values.iloc[-1],previousValue=values.iloc[-2],date=iso(values.index[-1]),series=s,
                                quoteBasis='discount' if s=='TB3MS' else 'investment'))
    sources=[]
    for s,(label,freq,unit,provider) in SERIES.items():
        v=raw[s]
        sources.append(dict(id=s,label=label,url=f'https://fred.stlouisfed.org/series/{s}',downloadUrl=f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={s}',
                            frequency=freq,unit=unit,provider=provider,lastDate=iso(v.index[-1]),lastValue=v.iloc[-1],
                            retrievedAt=datetime.now(timezone.utc).isoformat()))
    snapshot=dict(meta=dict(name='HORIZON',version='1.0',generatedAt=datetime.now(timezone.utc).isoformat(),asOf=args.as_of,
                            issueDate=iso(issue),featureDate=iso(feature_date), forecastStart=latest['forecastStart'],forecastEnd=latest['forecastEnd'],
                            methodology='L2 logistic; 2-month feature lag; future 12-month any-recession target; annual expanding walk-forward with 12-month target purge; latest-vintage historical simulation.'),
                  latest=latest,model=final_model,history=history,metrics=evaluation,calibration=calibration,
                  recessions=recession_periods,sources=sources,yieldCurve=yield_curve,sensitivity=sensitivity,
                  folds=folds,featureDefinitions={
                    'slope': {'formula':'GS10 - TB3MS', 'unit':'percentage points', 'caveat':'Investment-basis Treasury yield minus discount-basis bill rate; own proxy, not NY Fed replication.'},
                    'credit': {'formula':'Mean of all weekly NFCICREDIT observations whose observation dates fall in the complete calendar month', 'unit':'index, standard deviations', 'caveat':'Public Chicago Fed conditions index; not a traded credit spread; history revised.'},
                    'labor': {'formula':'Three-calendar-month UNRATE mean (at least 2observations) minus minimum of 12consecutive such smoothed values, including current', 'unit':'percentage points', 'caveat':'No interpolation. Explicit available-observation policy handles the missing October 2025 release.'},
                    'lagMonths':2,'horizonMonths':12,'trainingEligibilityMonths':13,'sensitivityEligibilityMonths':25
                  },limitations=[
                   'Latest-vintage historical simulation, not a real-time vintage backtest. UNRATE and NFCI history can be revised.',
                   'NBER dates are announced after the fact; recent zero labels can later change. The 25-month eligibility sensitivity delays labels but does not reconstruct historical vintages.',
                   'Monthly targets overlap for 12 months; monthly tests are not independent trials. Only four recession episodes occur in the evaluation period.',
                   'GS10 minus TB3MS is an investment-basis/discount-basis proxy, not a bond-equivalent or New York Fed replication.',
                   'Credit subindex is not a traded credit spread; positive means tighter than average. Its full-history normalization is revised.',
                   'Three-calendar-month unemployment averages require at least 2available observations. October 2025 is missing in official data; no value is interpolated. Twelve consecutive smoothed values are required for the labor-gap minimum.',
                   'The target includes both new recessions and continuation of an existing recession, not recession onset alone.',
                   'Probabilities are model estimates, not certainty or investment advice; stress scenarios are conditional sensitivities, not causal forecasts.'
                  ])
    # A compact panel with observation-month sources and issue-month lagged inputs.
    download=panel.copy()
    download.index.name='issue_date'
    download['feature_date']=[iso(d-pd.DateOffset(months=2)) for d in download.index]
    (ROOT/'data').mkdir(exist_ok=True)
    (ROOT/'public'/'data').mkdir(parents=True,exist_ok=True)
    payload=json.dumps(clean(snapshot),ensure_ascii=False,separators=(',',':'),allow_nan=False)
    (ROOT/'data'/'snapshot.json').write_text(payload)
    (ROOT/'public'/'data'/'snapshot.json').write_text(payload)
    download.to_csv(ROOT/'public'/'data'/'panel.csv',float_format='%.8f')
    history_frame.to_csv(ROOT/'public'/'data'/'predictions.csv',float_format='%.8f')
    # Audit trail records the full fold boundary data separately for review.
    (ROOT/'research'/'folds.json').write_text(json.dumps(clean(folds),indent=2))
    print(json.dumps(clean(dict(latest=latest,metrics=evaluation,sensitivity=sensitivity,model=final_model,historyN=len(history))),indent=2))


if __name__=='__main__':
    main()
