"""First-capture forecasts and reproducible credit-regime evidence for the permits benchmark trial."""

import hashlib
import json
import math
import os
import re
from pathlib import Path

import pandas as pd

from credit_trial import MODELS, PREDICTIONS, SPEC
from forecast_ledger import model_probability, month_offset, object_hash, receipt_hash
from leading_receipts import SOURCE_IDS, is_month, report, same, update_trial_archive
from leading_trial import MIN_TRAINING
from provider_fallback import parse_fred_csv

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'credit-dynamics-prospective-v1'
CODE = (
    'research/build_model.py',
    'research/provider_fallback.py',
    'research/leading_trial.py',
    'research/credit_trial.py',
    'research/credit_receipts.py',
    'research/leading_receipts.py',
    'research/forecast_ledger.py',
)
CLOCK_FIELDS = ('issueDate', 'featureDate', 'forecastStart', 'forecastEnd')
MODEL_ORDERS = {'benchmark': ['slope', 'credit', 'labor', 'permitGrowth6'], **MODELS}
FEATURES = ('slope', 'credit', 'labor', 'permitGrowth6', 'creditSlow', 'creditShock')


def credit_evidence(root, feature_date):
    """Freeze exactly the observation months needed to reconstruct today's 60-shock comparison."""
    raw = (root / 'research/raw/NFCICREDIT.csv').read_bytes()
    values = parse_fred_csv(raw.decode(), 'NFCICREDIT')
    months = pd.date_range(end=feature_date, periods=64, freq='MS')
    means = values.groupby(values.index.to_period('M')).mean().reindex(months.to_period('M'))
    return dict(
        series='NFCICREDIT',
        rawSha256=hashlib.sha256(raw).hexdigest(),
        monthlyLevels=[
            [month.strftime('%Y-%m-%d'), float(value) if pd.notna(value) else None]
            for month, value in zip(months, means)
        ],
    )


def check_credit(row):
    proof = row['creditEvidence']
    if proof['series'] != 'NFCICREDIT' or not re.fullmatch(r'[0-9a-f]{64}', proof['rawSha256']):
        raise ValueError('Missing credit source or raw-file fingerprint')
    months = pd.date_range(end=row['featureDate'], periods=64, freq='MS').strftime('%Y-%m-%d').tolist()
    readings = proof['monthlyLevels']
    if [date for date, _ in readings] != months:
        raise ValueError('Credit evidence calendar must end at the two-month-lagged observation month')
    levels = [level for _, level in readings]
    if any(v is not None and (type(v) not in (float, int) or not math.isfinite(v)) for v in levels):
        raise ValueError('Credit level must be finite or explicitly missing')
    if any(v is None for v in levels[-4:]):
        raise ValueError('The active credit signals require four consecutive observed months')

    slow = math.fsum(levels[-4:-1]) / 3
    shock = levels[-1] - slow
    signals = {'credit': levels[-1], 'creditSlow': slow, 'creditShock': shock}
    if any(not same(row['features'][key], val) for key, val in signals.items()):
        raise ValueError('Current credit inputs disagree with frozen monthly source levels')
    persist = all(round(v, 12) > 0 for v in levels[-4:-1])
    threshold = sudden = None
    if None not in levels:
        # 60 prior shocks. Their interpolated 90th percentile lies at zero-based index 53.1.
        shocks = sorted(levels[i] - math.fsum(levels[i - 3 : i]) / 3 for i in range(3, 63))
        threshold = shocks[53] + 0.1 * (shocks[54] - shocks[53])
        sudden = round(shock, 12) > max(0, round(threshold, 12))
    states = row['regime']
    threshold_ok = (
        states['shockThreshold'] is None if threshold is None else same(states['shockThreshold'], threshold)
    )
    if not threshold_ok or states['persistent'] is not persist or states['sudden'] is not sudden:
        raise ValueError('Frozen credit regime disagrees with its trailing observations')


def verify_receipts(rows, now):
    previous_issue = previous_hash = None
    for row in rows:
        issue = row['issueDate']
        if (
            row.get('protocolVersion') != VERSION
            or row.get('previousHash') != previous_hash
            or row.get('hash') != receipt_hash(row)
            or not is_month(issue)
            or (previous_issue and issue <= previous_issue)
        ):
            raise ValueError('Invalid credit forecast chain or issue order')
        if any(
            row[k] != month_offset(issue, i)
            for k, i in [('featureDate', -2), ('forecastStart', 1), ('forecastEnd', 12)]
        ):
            raise ValueError('Credit forecast horizon or observation lag is inconsistent')
        built, recorded = pd.Timestamp(row['sourceBuildGeneratedAt']), pd.Timestamp(row['recordedAt'])
        if (
            pd.isna(built)
            or pd.isna(recorded)
            or built.tzinfo is None
            or recorded.tzinfo is None
            or not pd.Timestamp(issue, tz='UTC') <= built <= recorded <= pd.Timestamp(now)
            or recorded >= pd.Timestamp(row['forecastStart'], tz='UTC')
        ):
            raise ValueError('Credit forecast must be generated and captured in its actual issue month')
        if row['recipe'] != SPEC or row['recipeHash'] != object_hash(row['recipe']):
            raise ValueError('Credit trial recipe mismatch')
        check_credit(row)
        base = row['baseProbability']
        if type(base) not in (int, float) or not 0 <= base <= 1:
            raise ValueError('Invalid frozen historical base')
        if any(set(row[k]) != set(MODEL_ORDERS) for k in ['models', 'modelHashes', 'predictions']):
            raise ValueError('The five model forecasts and their fingerprints must be complete')
        training = None
        cutoff = month_offset(issue, -13)
        for name, columns in MODEL_ORDERS.items():
            model = row['models'][name]
            if (
                model['featureOrder'] != columns
                or model['penalty'] != 1
                or row['modelHashes'][name] != object_hash(model)
                or model['refitDate'] != issue
                or model['trainingCutoff'] != cutoff
                or not is_month(model['trainedFrom'])
                or not is_month(model['trainedThrough'])
                or not model['trainedFrom'] <= model['trainedThrough'] <= cutoff
                or model['lastTargetMonth'] != month_offset(model['trainedThrough'], 12)
                or type(model['trainingN']) is not int
                or model['trainingN'] < MIN_TRAINING
            ):
                raise ValueError('A frozen credit model has invalid features, training clock or fingerprint')
            if name != 'benchmark':
                sample = (model['trainedFrom'], model['trainedThrough'], model['trainingN'])
                if training is not None and sample != training:
                    raise ValueError('Credit controls must share the candidate training sample')
                training = sample
            p = row['predictions'][name]
            if not same(p, (model_probability(model, row['features']) + base) / 2) or not 0 <= p <= 1:
                raise ValueError('Frozen 50/50 credit forecast disagrees with its model and base')
        sources = [s['id'] for s in row['sources']]
        if (
            set(sources) != SOURCE_IDS
            or len(sources) != len(SOURCE_IDS)
            or any(not re.fullmatch(r'[0-9a-f]{64}', row['codeSha256'].get(key, '')) for key in CODE)
        ):
            raise ValueError('Credit forecast source or code evidence missing')
        previous_issue, previous_hash = issue, row['hash']
    return True


def create_receipt(snapshot, root, now, previous_hash):
    trial, lead, official = snapshot['creditTrial'], snapshot['leadingTrial'], snapshot['latest']
    latest, benchmark = trial['latest'], lead['latest']
    if (
        trial['spec'] != SPEC
        or any(latest[k] != benchmark[k] or latest[k] != official[k] for k in CLOCK_FIELDS)
        or not same(latest['baselineProbability'], official['baselineProbability'])
        or not same(benchmark['baselineProbability'], latest['baselineProbability'])
        or not same(benchmark['permitsBlendProbability'], latest['benchmarkProbability'])
        or any(not same(latest[k], benchmark['features'][k]) for k in MODEL_ORDERS['benchmark'])
    ):
        raise ValueError('Credit trial does not match the published permits benchmark, base or issue inputs')
    models = {'benchmark': lead['currentModels']['permits'], **trial['currentModels']}
    commit = os.environ.get('GITHUB_SHA', '') if os.environ.get('GITHUB_ACTIONS') == 'true' else ''
    row = dict(
        protocolVersion=VERSION,
        previousHash=previous_hash,
        recordedAt=now.isoformat(),
        sourceBuildGeneratedAt=snapshot['meta']['generatedAt'],
        **{k: latest[k] for k in CLOCK_FIELDS},
        recipe=SPEC,
        recipeHash=object_hash(SPEC),
        baseProbability=latest['baselineProbability'],
        features={k: latest[k] for k in FEATURES},
        regime={k: latest[k] for k in ('persistent', 'sudden', 'shockThreshold')},
        creditEvidence=credit_evidence(root, latest['featureDate']),
        models=models,
        modelHashes={name: object_hash(model) for name, model in models.items()},
        predictions={key: latest[field] for key, field in PREDICTIONS.items()},
        sources=[s for s in snapshot['sources'] if s['id'] in SOURCE_IDS],
        codeCommit=commit if re.fullmatch(r'[0-9a-f]{40}', commit) else None,
        codeSha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in CODE},
    )
    row['hash'] = receipt_hash(row)
    return row


def summarize(rows, outcomes, now, status, available):
    return report(
        rows,
        outcomes,
        now,
        status,
        available,
        version=VERSION,
        predictions=PREDICTIONS,
        download_url='/api/download?file=creditreceipts',
    )


def update_receipts(root=ROOT, now=None):
    return update_trial_archive(
        root,
        now,
        trial_key='creditTrial',
        name='credit',
        fields=PREDICTIONS,
        available=lambda t: bool(t.get('currentModels')),
        create=create_receipt,
        verify=verify_receipts,
        summarize=summarize,
    )


if __name__ == '__main__':
    result = update_receipts()
    print(json.dumps({k: result[k] for k in ('receiptCount', 'maturedCount', 'status', 'chainValid')}))
