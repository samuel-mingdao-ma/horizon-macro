"""Freeze each month's conditional probability, same-fit risk path and three warning decisions."""

import hashlib
import json
import math
import os
from pathlib import Path
import re

import pandas as pd

from expansion_receipts import CLOCK_FIELDS, evaluate_onsets
from expansion_trial import FEATURES as MODEL_FEATURES
from forecast_ledger import model_probability, month_offset, object_hash, receipt_hash
from leading_receipts import SOURCE_IDS, is_month, report, same, update_trial_archive
from leading_trial import FEATURES as COMPLETE_CASE, MIN_TRAINING
from pace_trial import SPEC, decisions

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'conditional-onset-momentum-prospective-v1'
PREDICTIONS = {'conditionalRisk': 'probability'}
ALERT_FIELDS = ('levelAlert', 'quarterAlert', 'monthAlert')
PACE_FIELDS = ('change1m', 'change3m', 'paceAvailable')
CODE = (
    'research/build_model.py',
    'research/leading_trial.py',
    'research/expansion_trial.py',
    'research/pace_trial.py',
    'research/pace_receipts.py',
    'research/expansion_receipts.py',
    'research/leading_receipts.py',
    'research/forecast_ledger.py',
    'research/provider_fallback.py',
)


def verify_model(model, issue):
    n, positive, events = (model[k] for k in ('trainingN', 'trainingPositives', 'trainingOnsets'))
    if (
        model.get('featureOrder') != MODEL_FEATURES
        or model['penalty'] != 1
        or model['refitDate'] != issue
        or model['trainingCutoff'] != month_offset(issue, -13)
        or not is_month(model['trainedFrom'])
        or not is_month(model['trainedThrough'])
        or not model['trainedFrom'] <= model['trainedThrough'] <= model['trainingCutoff']
        or model['lastTargetMonth'] != month_offset(model['trainedThrough'], 12)
        or any(type(v) is not int for v in (n, positive, events))
        or n < MIN_TRAINING
        or not 0 < events <= positive < n
        or positive > 12 * events
        or not same(positive / n, model['trainingPrevalence'])
    ):
        raise ValueError('Invalid frozen expansion fit, training clock or onset prevalence')


def verify_path(path, model, issue):
    if len(path) != 4:
        raise ValueError('A warning needs exactly four consecutive dated risk-path entries')
    for lag, point in zip(range(-3, 1), path):
        date = month_offset(issue, lag)
        features, probability = point['features'], point['probability']
        if (
            point['date'] != date
            or point['featureDate'] != month_offset(date, -2)
            or set(features) != set(COMPLETE_CASE)
            or any(v is not None and (type(v) not in (float, int) or not math.isfinite(v)) for v in features.values())
        ):
            raise ValueError('Frozen path has misdated or invalid feature inputs')
        if None in features.values():
            if probability is not None:
                raise ValueError('An incomplete feature month cannot supply a pace probability')
        else:
            predicted = (model_probability(model, features) + model['trainingPrevalence']) / 2
            if not same(probability, predicted) or not 0 <= probability <= 1:
                raise ValueError('The frozen monthly fit must reproduce every path probability')
    return decisions([p['probability'] for p in path])


def verify_receipts(rows, now):
    previous_issue = previous_hash = None
    for row in rows:
        issue = row['issueDate']
        if (
            not is_month(issue)
            or row['previousHash'] != previous_hash
            or row['hash'] != receipt_hash(row)
            or (previous_issue and issue <= previous_issue)
            or row['protocolVersion'] != VERSION
            or row['recipe'] != SPEC
            or row['recipeHash'] != object_hash(SPEC)
        ):
            raise ValueError('Invalid momentum receipt chain, sequence or registered rule')
        if any(row[k] != month_offset(issue, off) for k, off in (
            ('featureDate', -2), ('forecastStart', 1), ('forecastEnd', 12)
        )):
            raise ValueError('Momentum issue and forecast dates disagree')
        built, recorded = pd.Timestamp(row['sourceBuildGeneratedAt']), pd.Timestamp(row['recordedAt'])
        if (
            pd.isna(built) or pd.isna(recorded) or built.tzinfo is None or recorded.tzinfo is None
            or not pd.Timestamp(issue, tz='UTC') <= built <= recorded <= pd.Timestamp(now)
            or recorded >= pd.Timestamp(row['forecastStart'], tz='UTC')
        ):
            raise ValueError('Risk warnings must be generated and captured in the actual issue month')
        model = row['model']
        if row['modelHash'] != object_hash(model):
            raise ValueError('Frozen model fingerprint mismatch')
        verify_model(model, issue)
        expected = verify_path(row['path'], model, issue)
        if set(row['predictions']) != set(PREDICTIONS) or not same(
            row['predictions']['conditionalRisk'], row['path'][-1]['probability']
        ):
            raise ValueError('Archive must retain the expansion model probability')
        if set(row['decisions']) != set(ALERT_FIELDS) or any(
            type(row['decisions'][k]) is not bool or row['decisions'][k] is not expected[k] for k in ALERT_FIELDS
        ):
            raise ValueError('Archived warning decisions must reproduce from the frozen path')
        changes = row['pace']
        if set(changes) != set(PACE_FIELDS) or changes['paceAvailable'] is not expected['paceAvailable']:
            raise ValueError('Frozen pace availability disagrees with path coverage')
        for k in ('change1m', 'change3m'):
            if not (changes[k] is None and expected[k] is None) and not same(changes[k], expected[k]):
                raise ValueError('Frozen risk change disagrees with its dated endpoints')
        if (
            {s['id'] for s in row['sources']} != SOURCE_IDS or len(row['sources']) != len(SOURCE_IDS)
            or any(not re.fullmatch(r'[0-9a-f]{64}', row['codeSha256'].get(path, '')) for path in CODE)
        ):
            raise ValueError('Missing source vintage or research code evidence')
        previous_issue, previous_hash = issue, row['hash']
    return True


def create_receipt(snapshot, root, now, previous_hash):
    trial = snapshot['momentumTrial']
    latest = trial['latest']
    expansion = snapshot['expansionTrial']
    source = expansion['latest']
    model = expansion['currentModel']
    if (
        trial['spec'] != SPEC
        or source.get('conditionalOnExpansion') is not True
        or source.get('available') is not True
        or any(latest[k] != source[k] or latest[k] != snapshot['latest'][k] for k in CLOCK_FIELDS)
        or latest['refitDate'] != model['refitDate']
        or not same(latest['probability'], source['probability'])
        or any(not same(latest['path'][-1]['features'][k], source[k]) for k in COMPLETE_CASE)
    ):
        raise ValueError('Momentum warning does not match the published conditional forecast')
    sha = os.environ.get('GITHUB_SHA', '') if os.environ.get('GITHUB_ACTIONS') == 'true' else ''
    row = dict(
        protocolVersion=VERSION,
        previousHash=previous_hash,
        recordedAt=now.isoformat(),
        sourceBuildGeneratedAt=snapshot['meta']['generatedAt'],
        **{k: latest[k] for k in CLOCK_FIELDS},
        recipe=SPEC,
        recipeHash=object_hash(SPEC),
        model=model,
        modelHash=object_hash(model),
        path=latest['path'],
        pace={k: latest[k] for k in PACE_FIELDS},
        predictions={'conditionalRisk': latest['probability']},
        decisions={k: latest[k] for k in ALERT_FIELDS},
        sources=[s for s in snapshot['sources'] if s['id'] in SOURCE_IDS],
        codeCommit=sha if re.fullmatch(r'[0-9a-f]{40}', sha) else None,
        codeSha256={k: hashlib.sha256((root / k).read_bytes()).hexdigest() for k in CODE},
    )
    row['hash'] = receipt_hash(row)
    return row


def summarize(rows, outcomes, now, status, available):
    result = report(rows, outcomes, now, status, available, version=VERSION, predictions=PREDICTIONS,
                    download_url='/api/download?file=momentumreceipts')
    pairs = [(r['decisions'], o['target']) for r, o in zip(rows, outcomes) if o['status'] == 'matured']
    positive = sum(y for _, y in pairs)
    decision_metrics = {}
    for key in ALERT_FIELDS:
        warnings = [y for flags, y in pairs if flags[key]]
        added = [y for flags, y in pairs if flags[key] and not flags['levelAlert']]
        decision_metrics[key] = dict(
            n=len(pairs), preOnsetMonths=positive, quietMonths=len(pairs) - positive,
            preOnsetAlerts=sum(warnings), quietAlerts=len(warnings) - sum(warnings),
            newPreOnsetAlerts=sum(added), newQuietAlerts=len(added) - sum(added),
        )
    result.update(
        pendingCount=sum(o['status'] == 'pending' for o in outcomes),
        excludedCount=sum(o['status'] == 'excluded' for o in outcomes),
        decisionMetrics=decision_metrics,
        note='Each receipt freezes the first available monthly fit, four dated input vectors, one conditional probability and three warning decisions. Only closed thirteen-month USREC windows with an expansion origin enter the scores. Revised dates can change outcomes.',
    )
    return result


def update_receipts(root=ROOT, now=None):
    return update_trial_archive(
        root, now, trial_key='momentumTrial', name='momentum', fields=PREDICTIONS,
        available=lambda trial: bool(trial.get('spec')), create=create_receipt, verify=verify_receipts,
        summarize=summarize, evaluate=evaluate_onsets,
    )


if __name__ == '__main__':
    result = update_receipts()
    print(json.dumps({k: result[k] for k in ('receiptCount', 'maturedCount', 'pendingCount', 'excludedCount', 'status', 'chainValid')}))
