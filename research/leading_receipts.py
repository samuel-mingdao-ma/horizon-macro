"""First-capture monthly forecasts for the housing-permits and initial-claims experiment."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
import re

import pandas as pd

from forecast_ledger import (
    canonical_json,
    evaluate_outcomes,
    model_probability,
    month_offset,
    object_hash,
    receipt_hash,
)
from leading_trial import BASE, DESIGN_ID, FEATURES, MIN_TRAINING, MODELS


ROOT = Path(__file__).resolve().parents[1]
VERSION = 'leading-indicators-prospective-v1'
PREDICTIONS = {
    'candidate': 'probability',
    'permitsBlend': 'permitsBlendProbability',
    'claimsBlend': 'claimsBlendProbability',
    'matchedThreeBlend': 'matchedThreeBlendProbability',
    'existingBlend': 'existingBlendProbability',
    'original': 'originalProbability',
    'base': 'baselineProbability',
    'rawFive': 'rawProbability',
}
BLENDS = {
    'joint': 'candidate',
    'permits': 'permitsBlend',
    'claims': 'claimsBlend',
    'matchedThree': 'matchedThreeBlend',
    'original': 'existingBlend',
}
MODEL_ORDERS = {'original': BASE, **MODELS}
SOURCE_IDS = {'PERMIT', 'ICSA', 'USREC', 'NFCICREDIT', 'GS10', 'TB3MS', 'UNRATE'}
CODE_PATHS = [
    'research/build_model.py',
    'research/provider_fallback.py',
    'research/leading_trial.py',
    'research/leading_receipts.py',
    'research/forecast_ledger.py',
]
RECIPE = {
    'id': DESIGN_ID,
    'featureOrder': FEATURES,
    'penalty': 1.0,
    'modelWeight': 0.5,
    'priorWeight': 0.5,
    'featureLagMonths': 2,
    'horizonMonths': 12,
    'minimumTrainingIssues': MIN_TRAINING,
    'target': 'At least one USREC=1 in the 12 calendar months following the issue month, including continuation.',
    'baseline': 'Official three-input expanding training prevalence at the same issue date for every blend.',
    'permits': '100 * (trailing 3-month mean of PERMIT / the same mean 6 calendar months earlier - 1).',
    'claims': '100 * (trailing 3-month mean of monthly ICSA / the same mean 12 calendar months earlier - 1). Monthly means require every scheduled Saturday.',
    'training': 'Monthly current refit on expanding samples. Last training outcome must end strictly before issue. All four experiment refits use identical, complete training issues.',
}


def clock(value=None):
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        raise ValueError('Capture time must have a time zone')
    return result.astimezone(timezone.utc)


def is_month(value):
    return isinstance(value, str) and re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])-01', value) is not None


def same(value, reference):
    return (
        all(type(v) in (int, float) and math.isfinite(v) for v in [value, reference])
        and abs(value - reference) <= 1e-8
    )


def verify_receipts(rows, now):
    previous_hash, previous_issue = None, None
    for row in rows:
        if (
            row.get('protocolVersion') != VERSION
            or row.get('previousHash') != previous_hash
            or row.get('hash') != receipt_hash(row)
        ):
            raise ValueError('Leading-indicator receipt hash chain is inconsistent')
        issue = row['issueDate']
        if not is_month(issue) or (previous_issue and issue <= previous_issue):
            raise ValueError('Forecast issue months must be unique and increasing')
        if any(
            row[key] != month_offset(issue, offset)
            for key, offset in [('featureDate', -2), ('forecastStart', 1), ('forecastEnd', 12)]
        ):
            raise ValueError('Feature date or forecast horizon does not follow the registered clock')
        recorded = pd.Timestamp(row['recordedAt'])
        if (
            recorded.tzinfo is None
            or recorded > pd.Timestamp(now)
            or recorded < pd.Timestamp(issue, tz='UTC')
            or recorded >= pd.Timestamp(row['forecastStart'], tz='UTC')
        ):
            raise ValueError('Capture must occur during the actual issue month')
        source_build = pd.Timestamp(row['sourceBuildGeneratedAt'])
        if pd.isna(source_build) or source_build.tzinfo is None or source_build > recorded:
            raise ValueError('The source build must exist before the forecast is captured')
        if row['recipeHash'] != object_hash(RECIPE) or row['recipeHash'] != object_hash(row['recipe']):
            raise ValueError('Leading-indicator receipt recipe fingerprint mismatch')
        forecasts = row['predictions']
        if set(forecasts) != set(PREDICTIONS) or any(
            type(value) not in (int, float) or not 0 <= value <= 1 for value in forecasts.values()
        ):
            raise ValueError('Incomplete or invalid prospective forecast probabilities')
        if set(row['features']) != set(FEATURES) or set(row['models']) != set(MODEL_ORDERS):
            raise ValueError(
                'The frozen joint model and its controls require all registered signals and models'
            )
        training = None
        for name, features in MODEL_ORDERS.items():
            model = row['models'][name]
            if (
                row['modelHashes'].get(name) != object_hash(model)
                or model['featureOrder'] != features
                or model['penalty'] != 1.0
            ):
                raise ValueError('Frozen model fingerprint or specification mismatch')
            cutoff = month_offset(issue, -13)
            if (
                model['refitDate'] != issue
                or model.get('trainingCutoff', cutoff) != cutoff
                or not is_month(model['trainedFrom'])
                or not is_month(model['trainedThrough'])
                or not model['trainedFrom'] <= model['trainedThrough'] <= cutoff
                or model['lastTargetMonth'] != month_offset(model['trainedThrough'], 12)
                or type(model['trainingN']) is not int
                or model['trainingN'] < MIN_TRAINING
            ):
                raise ValueError('Training sample or endpoint inconsistent with the forecast date')
            if name != 'original':
                dates = (model['trainedFrom'], model['trainedThrough'], model['trainingN'])
                if training is not None and training != dates:
                    raise ValueError(
                        'Single-signal controls and joint fit need the same training range and count'
                    )
                training = dates
            raw = model_probability(model, row['features'])
            if not same(forecasts[BLENDS[name]], (raw + forecasts['base']) / 2):
                raise ValueError('Frozen model does not reproduce its same-base 50/50 forecast')
            if (
                name == 'original'
                and not same(forecasts['original'], raw)
                or name == 'joint'
                and not same(forecasts['rawFive'], raw)
            ):
                raise ValueError('Frozen logistic probability is inconsistent')
        if {source['id'] for source in row['sources']} != SOURCE_IDS or len(row['sources']) != len(
            SOURCE_IDS
        ):
            raise ValueError('Source provenance is incomplete')
        if any(not re.fullmatch(r'[0-9a-f]{64}', row['codeSha256'].get(name, '')) for name in CODE_PATHS):
            raise ValueError('Research code fingerprint missing')
        previous_hash, previous_issue = row['hash'], issue
    return True


def create_receipt(snapshot, root, now, previous_hash):
    trial = snapshot['leadingTrial']
    latest, original = trial['latest'], snapshot['latest']
    spec = trial['spec']
    if any(
        spec.get(key) != RECIPE[key]
        for key in [
            'id',
            'featureOrder',
            'penalty',
            'modelWeight',
            'priorWeight',
            'featureLagMonths',
            'horizonMonths',
            'minimumTrainingIssues',
        ]
    ):
        raise ValueError('Leading trial changed its registered model design')
    if (
        any(
            latest.get(key) != original.get(key)
            for key in ['issueDate', 'featureDate', 'forecastStart', 'forecastEnd']
        )
        or not same(latest['originalProbability'], original['probability'])
        or not same(latest['baselineProbability'], original['baselineProbability'])
        or any(not same(latest['features'][k], original['features'][k]) for k in BASE)
    ):
        raise ValueError(
            'Mismatch with the official forecast, official expanding base, inputs or issue clock'
        )
    current_models = trial['currentModels']
    if object_hash(current_models['joint']) != object_hash(trial['model']):
        raise ValueError('Published joint model differs from its frozen comparator')
    source_fields = [
        'id',
        'lastDate',
        'lastValue',
        'retrievedAt',
        'transportStatus',
        'verifiedProviderLastDate',
        'providerRetrievedAt',
        'latestObservationFromCache',
        'url',
    ]
    sources = [
        {k: source.get(k) for k in source_fields}
        for source in snapshot['sources']
        if source['id'] in SOURCE_IDS
    ]
    models = {'original': snapshot['model'], **current_models}
    sha = os.environ.get('GITHUB_SHA', '') if os.environ.get('GITHUB_ACTIONS') == 'true' else ''
    row = dict(
        protocolVersion=VERSION,
        recordedAt=now.isoformat(),
        sourceBuildGeneratedAt=snapshot['meta']['generatedAt'],
        **{
            key: latest[key]
            for key in ['issueDate', 'featureDate', 'forecastStart', 'forecastEnd', 'features']
        },
        recipe=RECIPE,
        recipeHash=object_hash(RECIPE),
        models=models,
        modelHashes={key: object_hash(model) for key, model in models.items()},
        predictions={key: latest[field] for key, field in PREDICTIONS.items()},
        codeCommit=sha if re.fullmatch(r'[0-9a-f]{40}', sha) else None,
        codeSha256={name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in CODE_PATHS},
        sources=sources,
        previousHash=previous_hash,
    )
    row['hash'] = receipt_hash(row)
    return row


def report(rows, outcomes, now, status, available, *, version=VERSION, predictions=PREDICTIONS,
           download_url='/api/download?file=leadingreceipts'):
    matured = [(r['predictions'], o['target']) for r, o in zip(rows, outcomes) if o['status'] == 'matured']
    scores = {key: None for key in predictions}
    for key in predictions:
        if not matured:
            continue
        brier = loss = 0.0
        for issued, target in matured:
            p = issued[key]
            brier += (p - target) ** 2
            clipped = min(max(p, 1e-12), 1 - 1e-12)
            loss -= math.log(clipped if target else 1 - clipped)
        scores[key] = dict(n=len(matured), brier=brier / len(matured), logLoss=loss / len(matured))
    return dict(
        protocolVersion=version,
        receiptCount=len(rows),
        maturedCount=len(matured),
        chainValid=True,
        modelAvailable=available,
        status=status,
        appendedThisRun=status == 'captured',
        receipts=rows,
        outcomes=outcomes,
        metrics=scores,
        latestReceipt=rows[-1] if rows else None,
        lastHash=rows[-1]['hash'] if rows else None,
        evaluatedAt=now.isoformat(),
        downloadUrl=download_url,
        note='The first actual forecast for each issue is frozen before its window opens. Scores use all twelve published recession labels. Overlapping forecasts can share the same downturn.',
    )


def replace_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name('.' + path.name + '.leading.tmp')
    staged.write_text(content)
    staged.replace(path)


def update_receipts(root=ROOT, now=None):
    return update_trial_archive(root, now, trial_key='leadingTrial', name='leading', fields=PREDICTIONS,
        available=lambda trial: bool(trial.get('currentModels')), create=create_receipt,
        verify=verify_receipts, summarize=report)


def update_trial_archive(root, now, *, trial_key, name, fields, available, create, verify, summarize,
                         evaluate=evaluate_outcomes):
    root = Path(root)
    real_clock = now is None
    now = clock(now)
    canonical = root / 'data' / f'{name}-receipts.jsonl'
    mirror = root / 'public/data' / f'{name}-receipts.jsonl'
    snapshot_file = root / 'data/snapshot.json'
    if mirror.exists() and not canonical.exists():
        raise ValueError(f'Public {name} receipts exist without a canonical log')
    canonical.parent.mkdir(parents=True, exist_ok=True)
    with canonical.open('a+') as file:
        fcntl.flock(file.fileno(), fcntl.LOCK_EX)
        if real_clock:
            now = clock()
        snapshot = json.loads(snapshot_file.read_text())
        trial = snapshot.get(trial_key) or {}
        latest = trial.get('latest') or {}
        complete = (latest.get('available') is True and available(trial)
                    and all(latest.get(k) is not None for k in fields.values()))
        file.seek(0)
        saved = file.read()
        rows = [json.loads(line) for line in saved.splitlines()]
        if saved and not saved.endswith('\n'):
            raise ValueError('Incomplete leading receipt line')
        verify(rows, now)
        if mirror.exists():
            public = mirror.read_text()
            if not saved.startswith(public) or public and not public.endswith('\n'):
                raise ValueError(f'Public {name} receipts disagree with the canonical log')
        status = 'model-unavailable'
        if complete:
            issue = latest['issueDate']
            if not is_month(issue) or issue > now.strftime('%Y-%m-01'):
                raise ValueError('Cannot capture a future or invalid issue')
            if any(r['issueDate'] == issue for r in rows):
                status = 'already-captured'
            elif issue < now.strftime('%Y-%m-01'):
                status = 'stale-issue-no-capture'
            else:
                new = create(snapshot, root, now, rows[-1]['hash'] if rows else None)
                verify([*rows, new], now)
                addition = canonical_json(new) + '\n'
                file.write(addition)
                file.flush()
                os.fsync(file.fileno())
                saved += addition
                rows.append(new)
                status = 'captured'
        replace_text(mirror, saved)
        outcomes = []
        if rows:
            rec = pd.read_csv(root / 'research/raw/USREC.csv', index_col=0, parse_dates=True).USREC
            source = next((s for s in snapshot['sources'] if s['id'] == 'USREC'), {})
            outcomes = evaluate(
                rows, pd.to_numeric(rec, errors='raise'), now, source.get('retrievedAt')
            )
        result = summarize(rows, outcomes, now, status, complete)
        if isinstance(snapshot.get(trial_key), dict):
            snapshot[trial_key]['prospective'] = result
            data = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            replace_text(snapshot_file, data)
            replace_text(root / 'public/data/snapshot.json', data)
    return result


if __name__ == '__main__':
    result = update_receipts()
    print(json.dumps({key: result[key] for key in ['receiptCount', 'maturedCount', 'status', 'chainValid']}))
