#!/usr/bin/env python3
"""Independent monthly receipts for the fixed regime prior and secondary adaptive experiment.

Only this trial's files and its snapshot summary are written. Existing ledgers and
protocols remain untouched. Public hashes are an audit, not trusted timestamps.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import pandas as pd
from forecast_ledger import (
    canonical_json,
    object_hash,
    model_probability,
    evaluate_outcomes,
    month_offset,
    MODEL_FIELDS,
)

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'regime-prior-prospective-v1'
PREDICTIONS = [
    'original',
    'fixedBlend',
    'recentPrior',
    'recentBlend',
    'dynamicPrior',
    'candidate',
    'adaptivePrior',
    'adaptive',
]
PAIRS = {
    'candidateVsFixedBlend': ('candidate', 'fixedBlend'),
    'candidateVsOriginal': ('candidate', 'original'),
    'dynamicPriorVsRecentPrior': ('dynamicPrior', 'recentPrior'),
    'adaptiveVsFixedBlend': ('adaptive', 'fixedBlend'),
    'adaptiveVsCandidate': ('adaptive', 'candidate'),
    'adaptiveVsRecentBlend': ('adaptive', 'recentBlend'),
}
STATES = {
    'loose-low': (False, False),
    'loose-elevated': (False, True),
    'tight-low': (True, False),
    'tight-elevated': (True, True),
}


def _now(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError('Regime receipt capture requires an aware UTC clock')
    return value.astimezone(timezone.utc)


def _p(value):
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Regime receipt probabilities must be finite and lie in [0,1]')
    return value


def _close(a, b, tolerance=1e-8):
    return (
        isinstance(a, (int, float))
        and isinstance(b, (int, float))
        and math.isfinite(a)
        and math.isfinite(b)
        and abs(a - b) <= tolerance
    )


def current_recipe(snapshot):
    spec = snapshot['regimePrior']['spec']
    expected = {
        'pseudoMonths': 24,
        'windowMonths': 180,
        'minimumObserved': 120,
        'creditThreshold': 0,
        'laborThreshold': 0.5,
        'statePrecisionDecimals': 10,
        'rawWeight': 0.5,
        'priorWeight': 0.5,
        'adaptiveMinimumTrainingN': 60,
    }
    if any(spec.get(key) != value for key, value in expected.items()):
        raise ValueError('Regime prior differs from the fixed declared receipt specification')
    return dict(
        protocolVersion=VERSION,
        designId=spec['id'],
        **expected,
        originalFeatures=snapshot['model']['featureOrder'],
        originalPenalty=snapshot['model']['penalty'],
        featureLagMonths=2,
        horizonMonths=12,
        trainingEligibilityMonths=13,
        priorFormula='(state positives + 24 * pooled 180-month rate) / (state N + 24)',
        stateFormula='round(credit,10)>0 crossed with round(labor,10)>=0.5',
        primaryFormula='0.5 * original three-input probability + 0.5 * fixed shrunk state prior',
        incumbent='Existing fixed 50/50 original-three-input and original expanding training prevalence, on the same issue/input dates',
        adaptiveDesignId=spec['adaptiveDesignId'],
        adaptiveFormula='recentBlend + alpha * (fixedRegimeBlend - recentBlend); original retains 50 percent',
        adaptiveFit='clip(sum((fixedRegimeBlend-recentBlend)*(target-recentBlend))/sum((fixedRegimeBlend-recentBlend)^2),0,1); only earlier prequential rows with target end before refit; alpha=0 if N<60 or denominator=0',
        primaryStatus='Fixed four-state experiment; adaptive variant is a separately labelled secondary experiment. Historical design is post-hoc; prospective capture begins now.',
    )


def _evidence(root):
    names = [
        'research/build_model.py',
        'research/regime_prior.py',
        'research/regime_receipts.py',
        'research/forecast_ledger.py',
    ]
    sha = os.environ.get('GITHUB_SHA', '') if os.environ.get('GITHUB_ACTIONS') == 'true' else ''
    return dict(
        codeCommit=sha if re.fullmatch(r'[0-9a-f]{40}', sha) else None,
        codeSha256={name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names},
    )


def digest(row):
    return object_hash({key: value for key, value in row.items() if key != 'hash'})


def _validate_prior(row):
    prior = row['prior']
    features = row['features']
    if (
        prior['cutoff'] != month_offset(row['issueDate'], -13)
        or prior['end'] != prior['cutoff']
        or prior['start'] != month_offset(prior['end'], -179)
    ):
        raise ValueError('Regime prior must use its fixed 180-month eligible calendar window')
    if not isinstance(prior['n'], int) or not 120 <= prior['n'] <= 180:
        raise ValueError('Regime prior requires at least 120 observed rows in the 180-month window')
    canonical = {'credit': round(features['credit'], 10), 'labor': round(features['labor'], 10)}
    if canonical != row['stateInputs']:
        raise ValueError('Regime state inputs are not canonicalized to the declared precision')
    selected = ('tight' if canonical['credit'] > 0 else 'loose') + (
        '-elevated' if canonical['labor'] >= 0.5 else '-low'
    )
    if (
        selected != row['state']
        or len(prior['stateMap']) != 4
        or {cell['id'] for cell in prior['stateMap']} != set(STATES)
    ):
        raise ValueError('Regime states or current selection do not match declared boundaries')
    n = positives = 0
    selected_prior = None
    for cell in prior['stateMap']:
        if (cell['creditTight'], cell['laborElevated']) != STATES[cell['id']]:
            raise ValueError('Regime state flags are inconsistent')
        count, k = cell['n'], cell['positiveWindows']
        if not isinstance(count, int) or not isinstance(k, int) or not 0 <= k <= count:
            raise ValueError('Invalid observed state counts')
        expected = (k + 24 * prior['pooledProbability']) / (count + 24)
        if not _close(cell['pooledRate'], prior['pooledProbability']) or not _close(
            cell['priorProbability'], expected
        ):
            raise ValueError('Regime prior does not reproduce its fixed 24-month shrinkage')
        if cell['selected'] != (cell['id'] == selected):
            raise ValueError('Regime selected-cell flag is inconsistent')
        if count == 0 and cell['rawRate'] is not None:
            raise ValueError('Empty state must not invent an observed frequency')
        if count and not _close(cell['rawRate'], k / count):
            raise ValueError('Raw state frequency is inconsistent')
        if cell['id'] == selected:
            selected_prior = expected
        n += count
        positives += k
    if n != prior['n'] or not _close(prior['pooledProbability'], positives / n):
        raise ValueError('State counts do not partition the observed training sample')
    p = row['predictions']
    if not _close(p['recentPrior'], prior['pooledProbability']) or not _close(
        p['dynamicPrior'], selected_prior
    ):
        raise ValueError('Regime receipt priors disagree with their frozen counts')
    for key, value in [
        ('fixedBlend', 0.5 * (p['original'] + row['comparison']['baselineProbability'])),
        ('recentBlend', 0.5 * (p['original'] + p['recentPrior'])),
        ('candidate', 0.5 * (p['original'] + p['dynamicPrior'])),
    ]:
        if not _close(p[key], value):
            raise ValueError('Regime fixed forecast mixture is inconsistent')


def _validate_weight(row):
    fit = row['weightFit']
    p = row['predictions']
    alpha = fit['weight']
    n = fit['trainingN']
    if (
        not isinstance(n, int)
        or n < 0
        or not isinstance(alpha, (int, float))
        or not math.isfinite(alpha)
        or not 0 <= alpha <= 1
    ):
        raise ValueError('Invalid adaptive regime weight or observed count')
    if (
        fit['refitDate'] != row['issueDate']
        or fit['trainingCutoff'] != month_offset(row['issueDate'], -13)
        or fit['minimumTrainingN'] != 60
    ):
        raise ValueError('Adaptive regime fit uses an invalid refit or outcome cutoff')
    denominator = fit['denominator']
    numerator = fit['numerator']
    if (
        not isinstance(denominator, (int, float))
        or not math.isfinite(denominator)
        or denominator < 0
        or not isinstance(numerator, (int, float))
        or not math.isfinite(numerator)
    ):
        raise ValueError('Adaptive regime fit statistics must be finite')
    expected = 0 if n < 60 or denominator == 0 else min(1, max(0, numerator / denominator))
    if not _close(alpha, expected):
        raise ValueError('Adaptive regime weight does not reproduce its declared earlier-data fit')
    if n:
        if (
            not fit['trainStart'] <= fit['trainEnd'] <= fit['trainingCutoff']
            or fit['lastTargetMonth'] != month_offset(fit['trainEnd'], 12)
            or fit['lastTargetMonth'] >= row['issueDate']
        ):
            raise ValueError('Adaptive regime training outcomes overlap the current forecast')
    elif any(fit.get(key) is not None for key in ['trainStart', 'trainEnd', 'lastTargetMonth']):
        raise ValueError('Empty adaptive fit must not invent training dates')
    adaptive_prior = (1 - alpha) * p['recentPrior'] + alpha * p['dynamicPrior']
    if not _close(p['adaptivePrior'], adaptive_prior) or not _close(
        p['adaptive'], 0.5 * (p['original'] + adaptive_prior)
    ):
        raise ValueError('Adaptive regime forecasts disagree with the frozen weight')


def verify_receipts(receipts, now=None):
    previous = last_issue = fingerprint = None
    clock = pd.Timestamp(_now(now))
    for row in receipts:
        if (
            row.get('protocolVersion') != VERSION
            or row.get('previousHash') != previous
            or row.get('hash') != digest(row)
        ):
            raise ValueError('Regime receipt hash chain is inconsistent')
        issue = row['issueDate']
        if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])-01', issue) or (
            last_issue is not None and issue <= last_issue
        ):
            raise ValueError('Regime issue dates must be unique increasing calendar months')
        if (
            row['featureDate'] != month_offset(issue, -2)
            or row['forecastStart'] != month_offset(issue, 1)
            or row['forecastEnd'] != month_offset(issue, 12)
        ):
            raise ValueError('Regime forecast or input dates are inconsistent')
        captured = pd.Timestamp(row['recordedAt'])
        if (
            captured.tzinfo is None
            or captured > clock
            or captured >= pd.Timestamp(row['forecastStart'], tz='UTC')
        ):
            raise ValueError('Regime capture must be real-time and precede its future outcome horizon')
        if row.get('recipeHash') != object_hash(row['recipe']) or (
            fingerprint is not None and row['recipeHash'] != fingerprint
        ):
            raise ValueError('Regime recipe changed within the same prospective trial')
        for name in PREDICTIONS:
            _p(row['predictions'][name])
        if row['modelHash'] != object_hash(row['model']) or not _close(
            model_probability(row['model'], row['features']), row['predictions']['original']
        ):
            raise ValueError('Frozen original model does not reproduce its comparator')
        comparison = row['comparison']
        if (
            comparison['issueDate'] != issue
            or comparison['featureDate'] != row['featureDate']
            or comparison['id'] != 'original-three-signal-fixed-50-50'
        ):
            raise ValueError('Regime incumbent comparison provenance is inconsistent')
        if row['model']['lastTargetMonth'] >= issue:
            raise ValueError('Original comparator uses future training outcomes')
        _p(comparison['baselineProbability'])
        _validate_prior(row)
        _validate_weight(row)
        previous, last_issue, fingerprint = row['hash'], issue, row['recipeHash']
    return True


def read_receipts(path, now=None):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        row = json.loads(line)
        if line != canonical_json(row):
            raise ValueError('Regime receipt is not canonical JSON')
        rows.append(row)
    verify_receipts(rows, now)
    return rows


def create_receipt(snapshot, now, previous_hash, evidence):
    latest = snapshot['regimePrior']['latest']
    original = snapshot['latest']
    if latest['issueDate'] != original['issueDate'] or latest['featureDate'] != original['featureDate']:
        raise ValueError('Incumbent and regime candidate must use the same issue and inputs')
    if any(
        not _close(latest['features'][key], original['features'][key]) for key in ['slope', 'credit', 'labor']
    ):
        raise ValueError('Incumbent and candidate feature vintages differ')
    if not _close(latest['originalProbability'], original['probability']) or not _close(
        latest['baselineProbability'], original['baselineProbability']
    ):
        raise ValueError('Regime incumbent probabilities do not match the current original forecast')
    fit = latest['weightFit']
    if (
        not _close(latest['regimeWeight'], fit.get('weight'))
        or latest['weightTrainingN'] != fit.get('trainingN')
        or latest['weightTrainingCutoff'] != fit.get('trainingCutoff')
    ):
        raise ValueError('Adaptive regime comparison provenance fields disagree with the frozen weight fit')
    frozen = {key: copy.deepcopy(snapshot['model'][key]) for key in MODEL_FIELDS if key in snapshot['model']}
    values = {
        name: latest[field]
        for name, field in [
            ('original', 'originalProbability'),
            ('fixedBlend', 'fixedBlendProbability'),
            ('recentPrior', 'recentPriorProbability'),
            ('recentBlend', 'recentBlendProbability'),
            ('dynamicPrior', 'dynamicPriorProbability'),
            ('candidate', 'probability'),
            ('adaptivePrior', 'adaptivePriorProbability'),
            ('adaptive', 'adaptiveProbability'),
        ]
    }
    recipe = current_recipe(snapshot)
    row = dict(
        protocolVersion=VERSION,
        recordedAt=now.isoformat(),
        issueDate=latest['issueDate'],
        featureDate=latest['featureDate'],
        forecastStart=latest['forecastStart'],
        forecastEnd=latest['forecastEnd'],
        sourceBuildGeneratedAt=snapshot['meta']['generatedAt'],
        recipe=recipe,
        recipeHash=object_hash(recipe),
        model=frozen,
        modelHash=object_hash(frozen),
        features=copy.deepcopy(latest['features']),
        predictions=values,
        state=latest['state'],
        stateInputs=copy.deepcopy(latest['stateInputs']),
        comparison=dict(
            id='original-three-signal-fixed-50-50',
            issueDate=original['issueDate'],
            featureDate=original['featureDate'],
            baselineProbability=original['baselineProbability'],
            modelRefitDate=frozen.get('refitDate'),
            trainedThrough=frozen.get('trainedThrough'),
        ),
        prior=dict(
            start=latest['windowStart'],
            end=latest['windowEnd'],
            cutoff=latest['trainingCutoff'],
            n=latest['trainingN'],
            pooledProbability=latest['recentPriorProbability'],
            stateMap=copy.deepcopy(latest['stateMap']),
        ),
        weightFit=copy.deepcopy(latest['weightFit']),
        sources=[
            {
                key: copy.deepcopy(source.get(key))
                for key in [
                    'id',
                    'lastDate',
                    'retrievedAt',
                    'transportStatus',
                    'providerRetrievedAt',
                    'verifiedProviderLastDate',
                ]
            }
            for source in snapshot['sources']
        ],
        previousHash=previous_hash,
        **evidence,
    )
    row['hash'] = digest(row)
    return row


def _score(p, y):
    p = min(max(p, 1e-12), 1 - 1e-12)
    return (p - y) ** 2, -(y * math.log(p) + (1 - y) * math.log(1 - p))


def summarize(rows, outcomes, now, appended, status):
    mature = [(row, outcome) for row, outcome in zip(rows, outcomes) if outcome['status'] == 'matured']
    metrics = {key: None for key in PREDICTIONS}
    paired = {key: None for key in PAIRS}
    for name in PREDICTIONS:
        values = [_score(row['predictions'][name], outcome['target']) for row, outcome in mature]
        if values:
            metrics[name] = dict(
                n=len(values),
                brier=sum(v[0] for v in values) / len(values),
                logLoss=sum(v[1] for v in values) / len(values),
            )
    for name, (candidate, comparator) in PAIRS.items():
        if mature:
            paired[name] = dict(
                n=len(mature),
                brierDifference=metrics[candidate]['brier'] - metrics[comparator]['brier'],
                logLossDifference=metrics[candidate]['logLoss'] - metrics[comparator]['logLoss'],
            )
    return dict(
        protocolVersion=VERSION,
        receiptCount=len(rows),
        maturedCount=len(mature),
        chainValid=verify_receipts(rows, now),
        registeredAt=rows[0]['recordedAt'] if rows else None,
        latestReceipt=rows[-1] if rows else None,
        receipts=rows,
        outcomes=outcomes,
        metrics=metrics,
        pairedComparisons=paired,
        lastHash=rows[-1]['hash'] if rows else None,
        appendedThisRun=appended,
        status=status,
        evaluatedAt=now.isoformat(),
        downloadUrl='/api/download?file=regimereceipts',
        note='Independent prospective record. The fixed four-state prior remains the primary experiment; adaptive weighting is secondary. All forecasts use the same known future outcome. Monthly horizons overlap. Later data revisions update outcomes, never frozen forecasts. Public hash-linked Git records are not tamper-proof or independently timestamped.',
    )


def stage_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.regime.tmp')
    temporary.write_text(text)
    temporary.replace(path)


def _mirror_ok(canonical, mirror):
    if mirror.exists():
        value = mirror.read_bytes()
        if not canonical.startswith(value) or (value and not value.endswith(b'\n')):
            raise ValueError('Regime public mirror diverges from verified canonical receipts')


def _complete(snapshot):
    experiment = snapshot.get('regimePrior')
    if not isinstance(experiment, dict) or not isinstance(experiment.get('latest'), dict):
        return False
    latest = experiment['latest']
    needed = [
        'originalProbability',
        'fixedBlendProbability',
        'baselineProbability',
        'recentPriorProbability',
        'recentBlendProbability',
        'dynamicPriorProbability',
        'probability',
        'adaptivePriorProbability',
        'adaptiveProbability',
        'regimeWeight',
        'weightTrainingN',
        'weightTrainingCutoff',
        'weightFit',
        'issueDate',
        'featureDate',
        'forecastStart',
        'forecastEnd',
        'trainingCutoff',
        'windowStart',
        'windowEnd',
        'trainingN',
        'state',
        'stateInputs',
        'features',
        'stateMap',
    ]
    return all(latest.get(key) is not None for key in needed)


def update_receipts(root=ROOT, now=None):
    root = Path(root)
    actual_clock = now is None
    now = _now(now)
    source = root / 'data/snapshot.json'
    public_source = root / 'public/data/snapshot.json'
    snapshot = json.loads(source.read_text())
    path = root / 'data/regime-receipts.jsonl'
    mirror = root / 'public/data/regime-receipts.jsonl'
    if mirror.exists() and not path.exists():
        raise ValueError('Regime mirror exists without canonical receipts')
    complete = _complete(snapshot)
    prior = path.exists() and path.stat().st_size > 0
    if not complete and not prior:
        return dict(
            receiptCount=0,
            maturedCount=0,
            chainValid=True,
            appendedThisRun=False,
            status='model-unavailable-no-capture',
        )
    issue = snapshot['regimePrior']['latest']['issueDate'] if complete else None
    if issue and issue > now.strftime('%Y-%m-01'):
        raise ValueError('Cannot capture a future regime issue')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as locked:
        fcntl.flock(locked.fileno(), fcntl.LOCK_EX)
        if actual_clock:
            now = _now()
        rows = read_receipts(path, now)
        _mirror_ok(path.read_bytes(), mirror)
        appended = False
        if not complete:
            status = 'incomplete-current-forecast-no-capture'
        else:
            recipe = current_recipe(snapshot)
            if rows and rows[0]['recipeHash'] != object_hash(recipe):
                raise ValueError('Regime recipe changed; register a separate prospective trial')
            if any(row['issueDate'] == issue for row in rows):
                status = 'already-captured'
            elif (rows and issue < rows[-1]['issueDate']) or pd.Timestamp(
                month_offset(issue, 1), tz='UTC'
            ) <= pd.Timestamp(now):
                status = 'stale-issue-no-capture'
            else:
                row = create_receipt(snapshot, now, rows[-1]['hash'] if rows else None, _evidence(root))
                verify_receipts(rows + [row], now)
                locked.write(canonical_json(row) + '\n')
                locked.flush()
                os.fsync(locked.fileno())
                rows.append(row)
                appended = True
                status = 'captured'
        stage_write(mirror, path.read_text())
        rec = pd.read_csv(root / 'research/raw/USREC.csv', index_col=0, parse_dates=True).USREC
        source_meta = next((item for item in snapshot['sources'] if item['id'] == 'USREC'), {})
        outcomes = evaluate_outcomes(
            rows, pd.to_numeric(rec, errors='coerce'), now, source_meta.get('retrievedAt')
        )
        summary = summarize(rows, outcomes, now, appended, status)
        summary['modelAvailable'] = complete
        if isinstance(snapshot.get('regimePrior'), dict):
            snapshot['regimePrior']['prospective'] = summary
            snapshot.pop('regimePriorProspective', None)
        else:
            snapshot['regimePriorProspective'] = summary
        payload = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        stage_write(source, payload)
        stage_write(public_source, payload)
        fcntl.flock(locked.fileno(), fcntl.LOCK_UN)
    return summary


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    result = update_receipts()
    print(
        json.dumps(
            {
                key: result[key]
                for key in ['receiptCount', 'maturedCount', 'chainValid', 'appendedThisRun', 'status']
            }
        )
    )


if __name__ == '__main__':
    main()
