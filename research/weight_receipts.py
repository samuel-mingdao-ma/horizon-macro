"""Freeze the same-issue signals, historical base, fitted weights, and six comparator forecasts."""

import hashlib
import json
import math
import os
import re
from pathlib import Path

import pandas as pd

from forecast_ledger import model_probability, month_offset, object_hash, receipt_hash
from leading_receipts import is_month, report, same, update_trial_archive
from weight_trial import PREDICTIONS, SPEC, state_for

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'conditional-weight-prospective-v1'
CODE = (
    'research/build_model.py',
    'research/leading_trial.py',
    'research/weight_trial.py',
    'research/weight_warning.py',
    'research/weight_receipts.py',
    'research/leading_receipts.py',
    'research/forecast_ledger.py',
)
SOURCE_IDS = {'GS10', 'TB3MS', 'NFCICREDIT', 'UNRATE', 'PERMIT', 'ICSA', 'USREC'}


def validate_fit(fit, issue):
    n = fit['trainingN']
    if type(n) is not int or n < 0 or fit['warmup'] != (n < SPEC['minimumTrainingIssues']):
        raise ValueError('Invalid weight training count or warmup status')
    if fit['refitDate'] != issue or fit['trainingCutoff'] != month_offset(issue, -13):
        raise ValueError('Invalid weight training cutoff')
    if n:
        if not (
            is_month(fit['trainStart'])
            and is_month(fit['trainEnd'])
            and fit['trainStart'] <= fit['trainEnd'] <= fit['trainingCutoff']
            and fit['lastTargetMonth'] == month_offset(fit['trainEnd'], 12)
        ):
            raise ValueError('Weight training outcomes overlap the forecast refit')
    elif any(fit[key] is not None for key in ('trainStart', 'trainEnd', 'lastTargetMonth')):
        raise ValueError('Empty training history has dates')
    for arm in ('permits', 'original'):
        groups = fit[arm]
        if groups['pool']['n'] != n or groups['normal']['n'] + groups['stress']['n'] != n:
            raise ValueError('State counts do not match weight training count')
        for name in ('pool', 'normal', 'stress'):
            g = groups[name]
            if (
                type(g['n']) is not int
                or g['n'] < 0
                or not math.isfinite(g['numerator'])
                or not math.isfinite(g['denominator'])
                or g['denominator'] < 0
            ):
                raise ValueError('Invalid state fit statistics')
            anchor = 0.5 if name == 'pool' else groups['pool']['weight']
            implied = (
                0.5 if fit['warmup'] else min(1, max(0, (g['numerator'] + anchor) / (g['denominator'] + 1)))
            )
            if not same(g['weight'], implied):
                raise ValueError('Frozen weight disagrees with its historical fit')
        for field in ('numerator', 'denominator'):
            if not same(groups['pool'][field], groups['normal'][field] + groups['stress'][field]):
                raise ValueError('Pooled and conditional training moments disagree')


def verify_receipts(rows, now):
    prev = last_issue = None
    for row in rows:
        issue = row['issueDate']
        if (
            row.get('protocolVersion') != VERSION
            or row.get('hash') != receipt_hash(row)
            or row.get('previousHash') != prev
            or not is_month(issue)
            or (last_issue and issue <= last_issue)
        ):
            raise ValueError('Invalid adaptive forecast chain or issue')
        recorded, built = pd.Timestamp(row['recordedAt']), pd.Timestamp(row['sourceBuildGeneratedAt'])
        if (
            any(
                row[k] != month_offset(issue, i)
                for k, i in [('featureDate', -2), ('forecastStart', 1), ('forecastEnd', 12)]
            )
            or recorded.tzinfo is None
            or built.tzinfo is None
            or pd.isna(built)
            or built > recorded
            or recorded > pd.Timestamp(now)
            or recorded.strftime('%Y-%m-01') != issue
        ):
            raise ValueError('Invalid forecast horizon or capture time')
        if row['recipe'] != SPEC or row['recipeHash'] != object_hash(row['recipe']):
            raise ValueError('Adaptive-weight recipe mismatch')
        f, fit, base = row['features'], row['fit'], row['baseProbability']
        if not isinstance(base, (float, int)) or not 0 <= base <= 1:
            raise ValueError('Invalid historical base probability')
        state = state_for(f['slope'], f['credit'])
        if not state or row['state'] != state:
            raise ValueError('Frozen state disagrees with its issue-time inputs')
        validate_fit(fit, issue)
        signal = {}
        for arm, order in [
            ('original', ['slope', 'credit', 'labor']),
            ('permits', ['slope', 'credit', 'labor', 'permitGrowth6']),
        ]:
            model = row['models'][arm]
            if (
                model['featureOrder'] != order
                or model['refitDate'] != issue
                or model['penalty'] != 1
                or not is_month(model['trainedThrough'])
                or model['trainedThrough'] > month_offset(issue, -13)
                or model['lastTargetMonth'] != month_offset(model['trainedThrough'], 12)
                or row['modelHashes'][arm] != object_hash(model)
            ):
                raise ValueError('Invalid underlying model or training clock')
            signal[arm] = model_probability(model, f)
        a, p = signal['original'], signal['permits']
        expected = {
            'existingBlend': (a + base) / 2,
            'fixedPermits': (p + base) / 2,
            'pooledPermits': base + fit['permits']['pool']['weight'] * (p - base),
            'originalDynamic': base + fit['original'][state]['weight'] * (a - base),
            'candidate': base + fit['permits'][state]['weight'] * (p - base),
            'fixedRule': base + SPEC['ruleWeights'][state] * (p - base),
        }
        if set(row['predictions']) != set(expected) or any(
            not same(row['predictions'][k], v) for k, v in expected.items()
        ):
            raise ValueError('Frozen forecasts disagree with recorded weights and signals')
        if {s['id'] for s in row['sources']} != SOURCE_IDS or any(
            not re.fullmatch(r'[0-9a-f]{64}', row['codeSha256'].get(path, '')) for path in CODE
        ):
            raise ValueError('Missing source or code evidence')
        last_issue, prev = issue, row['hash']
    return True


def create_receipt(snapshot, root, now, previous_hash):
    t = snapshot['weightTrial']
    w, lead, original = t['latest'], snapshot['leadingTrial'], snapshot['latest']
    if (
        t['spec'] != SPEC
        or any(
            w[k] != lead['latest'][k] or w[k] != original[k]
            for k in ['issueDate', 'forecastStart', 'forecastEnd', 'featureDate']
        )
        or not same(w['baselineProbability'], original['baselineProbability'])
        or not same(w['fixedPermitsProbability'], lead['latest']['permitsBlendProbability'])
    ):
        raise ValueError('Weight forecast has a different source model, base, or issue date')
    models = {'original': snapshot['model'], 'permits': lead['currentModels']['permits']}
    features = {k: lead['latest']['features'][k] for k in models['permits']['featureOrder']}
    if any(not same(w[k], features[k]) for k in ('slope', 'credit')):
        raise ValueError('Adaptive state inputs differ from signal input vintage')
    sha = os.environ.get('GITHUB_SHA', '') if os.environ.get('GITHUB_ACTIONS') == 'true' else ''
    row = dict(
        protocolVersion=VERSION,
        recordedAt=now.isoformat(),
        sourceBuildGeneratedAt=snapshot['meta']['generatedAt'],
        **{k: w[k] for k in ['issueDate', 'featureDate', 'forecastStart', 'forecastEnd', 'state', 'fit']},
        models=models,
        modelHashes={k: object_hash(m) for k, m in models.items()},
        features=features,
        baseProbability=original['baselineProbability'],
        predictions={k: w[f] for k, f in PREDICTIONS.items()},
        recipe=SPEC,
        recipeHash=object_hash(SPEC),
        previousHash=previous_hash,
        sources=[s for s in snapshot['sources'] if s['id'] in SOURCE_IDS],
        codeCommit=sha if re.fullmatch(r'[0-9a-f]{40}', sha) else None,
        codeSha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in CODE}
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
        download_url='/api/download?file=weightreceipts',
    )


def update_receipts(root=ROOT, now=None):
    return update_trial_archive(
        root,
        now,
        trial_key='weightTrial',
        name='weight',
        fields=PREDICTIONS,
        available=lambda t: bool(t['latest'].get('fit')),
        create=create_receipt,
        verify=verify_receipts,
        summarize=summarize,
    )


if __name__ == '__main__':
    result = update_receipts()
    print(json.dumps({k: result[k] for k in ['receiptCount', 'maturedCount', 'status', 'chainValid']}))
