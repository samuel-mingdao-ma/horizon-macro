"""Freeze observed monthly Treasury rates and the decisions made from a single risk vintage."""

import hashlib
import json
import math
from pathlib import Path
import re

import pandas as pd

from curve_legs import ALERTS, SPEC, leg_decisions, leg_evidence
from expansion_receipts import CLOCK_FIELDS, evaluate_onsets
from forecast_ledger import month_offset, object_hash, receipt_hash
from leading_receipts import SOURCE_IDS, is_month, report, same, update_trial_archive
import pace_receipts as pace
from provider_fallback import parse_fred_csv

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'conditional-onset-curve-legs-prospective-v1'
PREDICTIONS = pace.PREDICTIONS
POLICIES = tuple(ALERTS.values())
YIELDS = {'TB3MS': 'shortYield', 'GS10': 'longYield'}
CODE = (*pace.CODE, 'research/weight_warning.py', 'research/confirmation_trial.py',
        'research/curve_legs.py', 'research/curve_legs_receipts.py')


def check_yield_path(curve, risk):
    if len(curve) != 4:
        raise ValueError('Both Treasury rates require four dated observation slots')
    for point, parent in zip(curve, risk):
        if point['date'] != parent['featureDate'] or set(point) != {'date', *YIELDS.values()}:
            raise ValueError('Treasury observations must match the four lagged risk inputs')
        short, long = point['shortYield'], point['longYield']
        if any(v is not None and (type(v) not in (int, float) or not math.isfinite(v)) for v in (short,long)):
            raise ValueError('Treasury rates must be finite observed yields or null')
        slope = parent['features']['slope']
        if short is not None and long is not None and slope is not None and not same(long-short,slope):
            raise ValueError('Treasury rates disagree with the frozen model slope')


def raw_yield_evidence(root, path):
    # Read the bytes once so the recorded fingerprint identifies exactly the source verified.
    digests = {}
    for sid, field in YIELDS.items():
        data = (root / 'research/raw' / f'{sid}.csv').read_bytes()
        observations = parse_fred_csv(data.decode('utf-8'), sid)
        for slot in path:
            original = observations.get(pd.Timestamp(slot['date']))
            expected = round(float(original) * 10**12) / 10**12 if pd.notna(original) else None
            if slot[field] != expected:
                raise ValueError(f'{sid} observation disagrees with the dated research source')
        digests[sid] = hashlib.sha256(data).hexdigest()
    return digests


def evaluate_decisions(yields, flags):
    evidence = leg_evidence(yields)
    level, quarter = flags['levelAlert'], flags['quarterAlert']
    return evidence, dict(levelAlert=level, quarterAlert=quarter, **leg_decisions(level, quarter, evidence))


def verify_receipts(rows, now):
    previous_issue = previous_hash = None
    for row in rows:
        issue = row['issueDate']
        if (
            not is_month(issue) or (previous_issue and issue <= previous_issue)
            or row['previousHash'] != previous_hash or receipt_hash(row) != row['hash']
            or row['protocolVersion'] != VERSION or row['recipe'] != SPEC
            or row['recipeHash'] != object_hash(SPEC) or row['paceRecipe'] != pace.SPEC
        ):
            raise ValueError('Curve-leg record has an invalid protocol, issue order or hash chain')
        if any(row[k] != month_offset(issue, off) for k, off in (
            ('lagFeatureDate',-5), ('featureDate',-2), ('forecastStart',1), ('forecastEnd',12)
        )):
            raise ValueError('Curve-leg issue, observation and forecast dates disagree')
        built, captured = pd.Timestamp(row['sourceBuildGeneratedAt']), pd.Timestamp(row['recordedAt'])
        if (pd.isna(built) or pd.isna(captured) or built.tzinfo is None or captured.tzinfo is None
                or not pd.Timestamp(issue, tz='UTC') <= built <= captured <= pd.Timestamp(now)
                or captured >= pd.Timestamp(row['forecastStart'], tz='UTC')):
            raise ValueError('Curve-leg forecast must be captured before its horizon opens')
        model, path = row['model'], row['path']
        if row['modelHash'] != object_hash(model):
            raise ValueError('Curve-leg frozen model fingerprint changed')
        pace.verify_model(model, issue)
        flags = pace.verify_path(path, model, issue)
        if (set(row['predictions']) != set(PREDICTIONS) or not same(row['predictions']['conditionalRisk'], path[-1]['probability'])
                or object_hash(row['pace']) != object_hash({k:flags[k] for k in pace.PACE_FIELDS})):
            raise ValueError('Curve-leg record disagrees with its original probability or pace')
        check_yield_path(row['yieldPath'], path)
        evidence, decisions = evaluate_decisions(row['yieldPath'], flags)
        if object_hash(row['evidence']) != object_hash(evidence) or object_hash(row['decisions']) != object_hash(decisions):
            raise ValueError('Curve-leg decomposition or warning disagrees with frozen inputs')
        if ({s['id'] for s in row['sources']} != SOURCE_IDS or len(row['sources']) != len(SOURCE_IDS)
                or set(row['rawYieldSha256']) != set(YIELDS)
                or any(not re.fullmatch(r'[0-9a-f]{64}', v) for v in row['rawYieldSha256'].values())
                or any(not re.fullmatch(r'[0-9a-f]{64}', row['codeSha256'].get(p,'')) for p in CODE)):
            raise ValueError('Curve-leg record lacks source or research code provenance')
        previous_issue, previous_hash = issue, row['hash']
    return True


def create_receipt(snapshot, root, now, previous_hash):
    parent = pace.create_receipt(snapshot, root, now, previous_hash)
    trial = snapshot['curveLegsTrial']
    latest = trial['latest']
    curve = latest['yieldPath']
    check_yield_path(curve, parent['path'])
    raw_hashes = raw_yield_evidence(root, curve)
    evidence, decisions = evaluate_decisions(curve, parent['decisions'])
    if (trial['spec'] != SPEC or latest['available'] is not True
            or any(latest[k] != parent[k] for k in CLOCK_FIELDS)
            or latest['refitDate'] != parent['model']['refitDate'] or latest['lagFeatureDate'] != curve[0]['date']
            or not same(latest['probability'],parent['predictions']['conditionalRisk'])
            or any(latest[k] != parent['pace'][k] for k in ('change1m','change3m'))
            or object_hash({k:latest[k] for k in evidence}) != object_hash(evidence)
            or any(latest[k] is not v for k,v in decisions.items())):
        raise ValueError('Curve-leg record disagrees with the co-issued warning trial')
    row = {k:parent[k] for k in (
        'previousHash','recordedAt','sourceBuildGeneratedAt',*CLOCK_FIELDS,'model','modelHash','path','pace',
        'predictions','sources','codeCommit','codeSha256',
    )}
    row.update(protocolVersion=VERSION, recipe=SPEC, recipeHash=object_hash(SPEC), paceRecipe=parent['recipe'],
               yieldPath=curve, lagFeatureDate=curve[0]['date'], evidence=evidence, decisions=decisions,
               rawYieldSha256=raw_hashes)
    for file in CODE[len(pace.CODE):]:
        row['codeSha256'][file] = hashlib.sha256((root/file).read_bytes()).hexdigest()
    row['hash'] = receipt_hash(row)
    return row


def summarize(rows, outcomes, now, status, available):
    result = report(rows, outcomes, now, status, available, version=VERSION, predictions=PREDICTIONS,
                    download_url='/api/download?file=curvelegsreceipts')
    evaluated = [(r['decisions'], o['target']) for r,o in zip(rows,outcomes) if o['status'] == 'matured']
    n, positives = len(evaluated), sum(y for _,y in evaluated)
    metrics = {}
    for k in POLICIES:
        alerted = [y for flags,y in evaluated if flags[k]]
        added = [y for flags,y in evaluated if flags[k] and not flags['levelAlert']]
        metrics[k] = dict(n=n, preOnsetMonths=positives, quietMonths=n-positives, preOnsetAlerts=sum(alerted),
                          quietAlerts=alerted.count(0), newPreOnsetAlerts=sum(added), newQuietAlerts=added.count(0))
    result.update(decisionMetrics=metrics, excludedCount=sum(o['status']=='excluded' for o in outcomes),
                  pendingCount=sum(o['status']=='pending' for o in outcomes),
                  note='Each monthly record freezes the conditional risk, four monthly Treasury yield pairs, their source vintages and each warning, including the exploratory 2-to-1 rule. Only expansion-origin forecasts with all thirteen closed USREC months enter the scores.')
    return result


def update_receipts(root=ROOT, now=None):
    return update_trial_archive(root, now, trial_key='curveLegsTrial', name='curve-legs', fields=PREDICTIONS,
                                available=lambda t: bool(t.get('spec')), create=create_receipt,
                                verify=verify_receipts, summarize=summarize, evaluate=evaluate_onsets)


if __name__ == '__main__':
    result = update_receipts()
    print(json.dumps({k:result[k] for k in ('receiptCount','maturedCount','excludedCount','pendingCount','status','chainValid')}))
