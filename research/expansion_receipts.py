"""Issue every available conditional forecast, then identify eligible expansion origins at evaluation."""

from datetime import timezone
import hashlib
import json
import os
from pathlib import Path
import re

import pandas as pd

from expansion_trial import FEATURES, PREDICTIONS, SPEC
from forecast_ledger import model_probability, month_offset, object_hash, receipt_hash
from leading_receipts import SOURCE_IDS, is_month, report, same, update_trial_archive
from leading_trial import MIN_TRAINING

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'expansion-onset-prospective-v1'
CODE = (
    'research/build_model.py',
    'research/leading_trial.py',
    'research/expansion_trial.py',
    'research/expansion_receipts.py',
    'research/leading_receipts.py',
    'research/forecast_ledger.py',
    'research/provider_fallback.py',
)
CLOCK_FIELDS = ('issueDate', 'featureDate', 'forecastStart', 'forecastEnd')
TRAINING_FIELDS = ('trainingN', 'trainingPositives', 'trainingOnsets')


def forecasts(permits, expansion, benchmark_base, onset_base):
    return dict(
        benchmark=(permits + benchmark_base) / 2,
        candidate=(expansion + onset_base) / 2,
        signalOnlyChange=(expansion + benchmark_base) / 2,
        baseOnlyChange=(permits + onset_base) / 2,
        expansionPrior=onset_base,
    )


def verify_receipts(rows, now):
    previous_issue = previous_hash = None
    for row in rows:
        issue = row['issueDate']
        if (
            row.get('protocolVersion') != VERSION
            or not is_month(issue)
            or row.get('previousHash') != previous_hash
            or row.get('hash') != receipt_hash(row)
            or (previous_issue and previous_issue >= issue)
        ):
            raise ValueError('Invalid expansion forecast chain or issue order')
        if any(
            row[k] != month_offset(issue, offset)
            for k, offset in [('featureDate', -2), ('forecastStart', 1), ('forecastEnd', 12)]
        ):
            raise ValueError('Expansion receipt dates must match the registered forecast horizon')
        built, recorded = pd.Timestamp(row['sourceBuildGeneratedAt']), pd.Timestamp(row['recordedAt'])
        if (
            pd.isna(built)
            or pd.isna(recorded)
            or built.tzinfo is None
            or recorded.tzinfo is None
            or not pd.Timestamp(issue, tz='UTC') <= built <= recorded <= pd.Timestamp(now)
            or recorded >= pd.Timestamp(row['forecastStart'], tz='UTC')
        ):
            raise ValueError('Expansion forecasts must be generated and captured in the actual issue month')
        if row['recipe'] != SPEC or row['recipeHash'] != object_hash(row['recipe']):
            raise ValueError('Expansion forecast protocol mismatch')
        if (
            set(row['models']) != {'benchmark', 'candidate'}
            or set(row['modelHashes']) != set(row['models'])
            or set(row['features']) != set(FEATURES)
        ):
            raise ValueError('Expansion receipt requires all four inputs and both fitted models')
        raw = {}
        for arm, model in row['models'].items():
            if (
                model.get('featureOrder') != list(FEATURES)
                or model['penalty'] != 1
                or model['refitDate'] != issue
                or row['modelHashes'][arm] != object_hash(model)
                or model['trainingCutoff'] != month_offset(issue, -13)
                or not is_month(model['trainedFrom'])
                or not is_month(model['trainedThrough'])
                or not model['trainedFrom'] <= model['trainedThrough'] <= model['trainingCutoff']
                or model['lastTargetMonth'] != month_offset(model['trainedThrough'], 12)
                or type(model['trainingN']) is not int
                or model['trainingN'] < MIN_TRAINING
            ):
                raise ValueError('Invalid expansion model training clock, features or fingerprint')
            raw[arm] = model_probability(model, row['features'])
        train = row['expansionTraining']
        n, positive, onsets = (train[k] for k in TRAINING_FIELDS)
        if (
            any(type(v) is not int for v in (n, positive, onsets))
            or n > row['models']['benchmark']['trainingN']
            or not 0 < onsets <= positive < n
            or positive > 12 * onsets
        ):
            raise ValueError('Invalid expansion training prevalence or distinct onset count')
        for key in TRAINING_FIELDS:
            if train[key] != row['models']['candidate'].get(key):
                raise ValueError('Expansion cohort counts disagree with fitted model')
        if not same(positive / n, row['models']['candidate'].get('trainingPrevalence')):
            raise ValueError('Expansion prevalence disagrees with the eligible training counts')
        base = row['benchmarkBaseProbability']
        if type(base) not in (int, float) or not 0 <= base <= 1:
            raise ValueError('Invalid historical base probability')
        calculated = forecasts(raw['benchmark'], raw['candidate'], base, positive / n)
        if set(row['predictions']) != set(PREDICTIONS) or any(
            not same(row['predictions'][arm], value) or not 0 <= row['predictions'][arm] <= 1
            for arm, value in calculated.items()
        ):
            raise ValueError('Frozen expansion probabilities disagree with the models or training counts')
        ids = [s['id'] for s in row['sources']]
        if (
            set(ids) != SOURCE_IDS
            or len(ids) != len(SOURCE_IDS)
            or any(not re.fullmatch(r'[0-9a-f]{64}', row['codeSha256'].get(p, '')) for p in CODE)
        ):
            raise ValueError('Missing expansion forecast evidence')
        previous_issue, previous_hash = issue, row['hash']
    return True


def create_receipt(snapshot, root, now, previous_hash):
    trial, leading, official = snapshot['expansionTrial'], snapshot['leadingTrial'], snapshot['latest']
    latest, permits = trial['latest'], leading['latest']
    models = {'candidate': trial['currentModel'], 'benchmark': leading['currentModels']['permits']}
    if (
        trial['spec'] != SPEC
        or latest.get('conditionalOnExpansion') is not True
        or any(latest[k] != permits[k] or latest[k] != official[k] for k in CLOCK_FIELDS)
        or not same(latest['baselineProbability'], official['baselineProbability'])
        or not same(latest['baselineProbability'], permits['baselineProbability'])
        or not same(latest['benchmarkProbability'], permits['permitsBlendProbability'])
        or any(not same(latest[k], permits['features'][k]) for k in FEATURES)
        or not same(latest['rawPermitsProbability'], model_probability(models['benchmark'], latest))
        or not same(latest['rawExpansionProbability'], model_probability(models['candidate'], latest))
    ):
        raise ValueError('Expansion receipt disagrees with its dated inputs, published benchmark or fit')
    sha = os.environ.get('GITHUB_SHA', '') if os.environ.get('GITHUB_ACTIONS') == 'true' else ''
    row = dict(
        protocolVersion=VERSION,
        previousHash=previous_hash,
        recordedAt=now.isoformat(),
        sourceBuildGeneratedAt=snapshot['meta']['generatedAt'],
        **{k: latest[k] for k in CLOCK_FIELDS},
        recipe=SPEC,
        recipeHash=object_hash(SPEC),
        features={k: latest[k] for k in FEATURES},
        models=models,
        modelHashes={k: object_hash(m) for k, m in models.items()},
        benchmarkBaseProbability=latest['baselineProbability'],
        expansionTraining={k: latest[k] for k in TRAINING_FIELDS},
        predictions={k: latest[f] for k, f in PREDICTIONS.items()},
        sources=[s for s in snapshot['sources'] if s['id'] in SOURCE_IDS],
        codeCommit=sha if re.fullmatch(r'[0-9a-f]{40}', sha) else None,
        codeSha256={k: hashlib.sha256((root / k).read_bytes()).hexdigest() for k in CODE},
    )
    row['hash'] = receipt_hash(row)
    return row


def evaluate_onsets(rows, labels, now, source_retrieved_at=None):
    """Reevaluate 13 consecutive USREC months against the latest dated outcome vintage."""
    labels = labels.sort_index()
    if labels.index.has_duplicates or not labels.index.is_month_start.all():
        raise ValueError('USREC labels must have unique calendar-month dates')
    current = pd.Timestamp(now).tz_convert(timezone.utc).tz_localize(None).to_period('M').to_timestamp()
    elapsed = labels[labels.index < current].dropna()
    if not elapsed.isin([0, 1]).all():
        raise ValueError('USREC labels must be binary or missing')
    last = elapsed.index.max().date().isoformat() if len(elapsed) else None
    outcomes = []
    for row in rows:
        months = pd.date_range(row['issueDate'], periods=13, freq='MS')
        window = elapsed.reindex(months)
        known = int(window.notna().sum())
        origin = int(window.iloc[0]) if pd.notna(window.iloc[0]) else None
        status, target, onset_date = 'pending', None, None
        if known == 13:
            if origin == 1:
                status = 'excluded'
            else:
                starts = window[(window == 1) & (window.shift() == 0)]
                onset_date = starts.index[0].date().isoformat() if len(starts) else None
                status, target = 'matured', int(onset_date is not None)
        outcomes.append(
            dict(
                receiptHash=row['hash'],
                issueDate=row['issueDate'],
                status=status,
                issueRecession=origin,
                knownMonths=known,
                requiredMonths=13,
                target=target,
                onsetDate=onset_date,
                sourceLastDate=last,
                sourceRetrievedAt=source_retrieved_at,
                evaluatedAt=now.isoformat(),
            )
        )
    return outcomes


def summarize(rows, outcomes, now, status, available):
    summary = report(
        rows,
        outcomes,
        now,
        status,
        available,
        version=VERSION,
        predictions=PREDICTIONS,
        download_url='/api/download?file=expansionreceipts',
    )
    summary.update(
        excludedCount=sum(o['status'] == 'excluded' for o in outcomes),
        pendingCount=sum(o['status'] == 'pending' for o in outcomes),
        note='Each issue is frozen before its horizon opens. The outcome uses the issue-month label and all twelve subsequent labels after the months close. Forecasts issued in a retrospectively dated expansion enter the onset score. Recession-origin receipts are counted separately. Outcomes can change with revised dates.',
    )
    return summary


def update_receipts(root=ROOT, now=None):
    return update_trial_archive(
        root,
        now,
        trial_key='expansionTrial',
        name='expansion',
        fields=PREDICTIONS,
        available=lambda t: bool(t.get('currentModel')),
        create=create_receipt,
        verify=verify_receipts,
        summarize=summarize,
        evaluate=evaluate_onsets,
    )


if __name__ == '__main__':
    result = update_receipts()
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    'receiptCount',
                    'maturedCount',
                    'pendingCount',
                    'excludedCount',
                    'status',
                    'chainValid',
                )
            }
        )
    )
