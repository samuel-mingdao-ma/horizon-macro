"""Freeze comparable warning decisions, their signal evidence and their shared probability."""

import hashlib
import json
from pathlib import Path
import re

import pandas as pd

from confirmation_trial import SPEC, confirmation_decisions, signal_evidence
from expansion_receipts import CLOCK_FIELDS, evaluate_onsets
from forecast_ledger import month_offset, object_hash, receipt_hash
from leading_receipts import SOURCE_IDS, is_month, report, same, update_trial_archive
import pace_receipts as pace

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'conditional-onset-signal-confirmation-prospective-v1'
PREDICTIONS = pace.PREDICTIONS
POLICIES = ('levelAlert', 'quarterAlert', 'pressureAlert', 'directionAlert', 'breadthAlert')
CODE = (*pace.CODE, 'research/confirmation_trial.py', 'research/confirmation_receipts.py')


def decision_evidence(path, flags):
    evidence = signal_evidence(path[-1]['features'], path[0]['features'])
    decisions = {k: flags[k] for k in POLICIES[:2]}
    decisions.update(confirmation_decisions(flags['levelAlert'], flags['quarterAlert'],
                                            evidence['pressureVotes'], evidence['directionVotes']))
    return evidence, decisions


def verify_receipts(rows, now):
    previous_issue = previous_hash = None
    for row in rows:
        issue = row['issueDate']
        if (
            not is_month(issue) or (previous_issue and previous_issue >= issue)
            or row['previousHash'] != previous_hash or row['hash'] != receipt_hash(row)
            or row['protocolVersion'] != VERSION or row['recipe'] != SPEC
            or row['recipeHash'] != object_hash(SPEC) or row['paceRecipe'] != pace.SPEC
        ):
            raise ValueError('Signal confirmation receipt protocol, chain or issue order changed')
        if any(row[k] != month_offset(issue, off) for k, off in (
            ('featureDate', -2), ('lagFeatureDate', -5), ('forecastStart', 1), ('forecastEnd', 12)
        )):
            raise ValueError('Confirmation issue, lag or horizon dates disagree')
        built, recorded = pd.Timestamp(row['sourceBuildGeneratedAt']), pd.Timestamp(row['recordedAt'])
        if (
            pd.isna(built) or pd.isna(recorded) or built.tzinfo is None or recorded.tzinfo is None
            or not pd.Timestamp(issue, tz='UTC') <= built <= recorded <= pd.Timestamp(now)
            or recorded >= pd.Timestamp(row['forecastStart'], tz='UTC')
        ):
            raise ValueError('Capture must be made within the issue month before the horizon opens')
        model, path = row['model'], row['path']
        if row['modelHash'] != object_hash(model):
            raise ValueError('Signal confirmation model fingerprint mismatch')
        pace.verify_model(model, issue)
        flags = pace.verify_path(path, model, issue)
        if set(row['predictions']) != set(PREDICTIONS) or not same(row['predictions']['conditionalRisk'], path[-1]['probability']):
            raise ValueError('Confirmation did not preserve the frozen conditional probability')
        if object_hash(row['pace']) != object_hash({k: flags[k] for k in pace.PACE_FIELDS}):
            raise ValueError('Momentum evidence disagrees with the four dated observations')
        evidence, decisions = decision_evidence(path, flags)
        if object_hash(row['evidence']) != object_hash(evidence):
            raise ValueError('Confirmation readings or votes disagree with the dated input vectors')
        if object_hash(row['decisions']) != object_hash(decisions):
            raise ValueError('Confirmation decisions disagree with the votes or parent pace decision')
        if (
            {s['id'] for s in row['sources']} != SOURCE_IDS or len(row['sources']) != len(SOURCE_IDS)
            or any(not re.fullmatch(r'[0-9a-f]{64}', row['codeSha256'].get(p, '')) for p in CODE)
        ):
            raise ValueError('Signal confirmation is missing source or code provenance')
        previous_issue, previous_hash = issue, row['hash']
    return True


def create_receipt(snapshot, root, now, previous_hash):
    # Reuse the co-issued expansion fit and the original calculation's dated inputs.
    # Existing first-capture momentum records may come from an earlier vintage.
    parent = pace.create_receipt(snapshot, root, now, previous_hash)
    trial = snapshot['confirmationTrial']
    latest = trial['latest']
    evidence, decisions = decision_evidence(parent['path'], parent['decisions'])
    if (
        trial['spec'] != SPEC or latest['available'] is not True
        or any(latest[k] != parent[k] for k in CLOCK_FIELDS)
        or latest['lagFeatureDate'] != parent['path'][0]['featureDate']
        or latest['refitDate'] != parent['model']['refitDate']
        or not same(latest['probability'], parent['predictions']['conditionalRisk'])
        or any(latest[k] is not v for k, v in decisions.items())
        or object_hash({k: latest[k] for k in evidence}) != object_hash(evidence)
        or any(latest[k] != parent['pace'][k] for k in ('change1m', 'change3m'))
    ):
        raise ValueError('Confirmation forecast disagrees with its co-issued probability, inputs or decisions')
    row = {k: parent[k] for k in (
        'previousHash', 'recordedAt', 'sourceBuildGeneratedAt', *CLOCK_FIELDS, 'model', 'modelHash',
        'path', 'pace', 'predictions', 'sources', 'codeCommit', 'codeSha256',
    )}
    row.update(
        protocolVersion=VERSION, recipe=SPEC, recipeHash=object_hash(SPEC), paceRecipe=parent['recipe'],
        lagFeatureDate=latest['lagFeatureDate'], evidence=evidence, decisions=decisions,
    )
    for p in ('research/confirmation_trial.py', 'research/confirmation_receipts.py'):
        row['codeSha256'][p] = hashlib.sha256((root / p).read_bytes()).hexdigest()
    row['hash'] = receipt_hash(row)
    return row


def summarize(rows, outcomes, now, status, available):
    summary = report(rows, outcomes, now, status, available, version=VERSION, predictions=PREDICTIONS,
                     download_url='/api/download?file=confirmationreceipts')
    pairs = [(r['decisions'], o['target']) for r, o in zip(rows, outcomes) if o['status'] == 'matured']
    decision_metrics = {}
    for key in POLICIES:
        alerts = [y for flags, y in pairs if flags[key]]
        extra = [y for flags, y in pairs if flags[key] and not flags['levelAlert']]
        decision_metrics[key] = dict(
            n=len(pairs), preOnsetMonths=sum(y for _, y in pairs), quietMonths=sum(y == 0 for _, y in pairs),
            preOnsetAlerts=sum(alerts), quietAlerts=alerts.count(0),
            newPreOnsetAlerts=sum(extra), newQuietAlerts=extra.count(0),
        )
    summary.update(
        excludedCount=sum(o['status'] == 'excluded' for o in outcomes),
        pendingCount=sum(o['status'] == 'pending' for o in outcomes), decisionMetrics=decision_metrics,
        note='Each record freezes one conditional probability, the common four-month path, the permit, claims and credit votes and all five decisions. The level and pace controls use the same capture vintage as the confirmation rules. Scoring uses 13 closed USREC months and includes expansion origins. Revised labels can change scoring.',
    )
    return summary


def update_receipts(root=ROOT, now=None):
    return update_trial_archive(
        root, now, trial_key='confirmationTrial', name='confirmation', fields=PREDICTIONS,
        available=lambda t: bool(t.get('spec')), create=create_receipt, verify=verify_receipts,
        summarize=summarize, evaluate=evaluate_onsets,
    )


if __name__ == '__main__':
    result = update_receipts()
    print(json.dumps({k: result[k] for k in ('receiptCount', 'maturedCount', 'pendingCount', 'excludedCount', 'status', 'chainValid')}))
