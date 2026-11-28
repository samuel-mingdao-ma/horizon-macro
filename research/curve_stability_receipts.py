"""Freeze observed band-and-ratio decisions and clearly labeled sensitivity bounds at issue."""

import hashlib
import json
import math
from pathlib import Path
import re

import curve_legs_receipts as legs
from curve_stability import GRID, SPEC, grid_results
from expansion_receipts import CLOCK_FIELDS, evaluate_onsets
from forecast_ledger import object_hash, receipt_hash
from leading_receipts import report, same, update_trial_archive


ROOT = Path(__file__).resolve().parents[1]
VERSION = 'conditional-onset-curve-stability-prospective-v1'
PREDICTIONS = legs.PREDICTIONS
NEW_CODE = ('research/curve_stability.py', 'research/curve_stability_receipts.py')
CODE = (*legs.CODE, *NEW_CODE)
PARENT_FIELDS = ('recordedAt', 'sourceBuildGeneratedAt', *CLOCK_FIELDS, 'lagFeatureDate', 'predictions', 'codeCommit')
CONTROL_FIELDS = ('levelAlert', 'quarterAlert', 'mixedTwoToOneAlert')
FLAG_FIELDS = ('actual', 'guaranteed', 'possible', 'minus3', 'plus3')
BOUND_FIELDS = ('lowerBp', 'upperBp')


def frozen_results(curve):
    evidence, controls = curve['evidence'], curve['decisions']
    results = grid_results(evidence['shortChange'], evidence['longChange'],
                           controls['levelAlert'], controls['quarterAlert'])
    if results[SPEC['originalId']]['actual'] is not controls['mixedTwoToOneAlert']:
        raise ValueError('The zero-band 2:1 decision must reproduce the original issued rule')
    return results


def same_grid(actual, expected):
    """JSON releases round real-valued margins to 12 decimal places. Flags must match exactly."""
    if not isinstance(actual, dict) or set(actual) != set(expected):
        return False
    for key, cell in expected.items():
        found = actual[key]
        if not isinstance(found, dict) or set(found) != set(cell):
            return False
        if any(found[field] is not cell[field] for field in (*FLAG_FIELDS, 'upperInclusive')):
            return False
        for field in BOUND_FIELDS:
            a, b = found[field], cell[field]
            if b is None:
                if a is not None:
                    return False
            elif type(a) not in (int, float) or not math.isclose(a, b, rel_tol=0, abs_tol=1e-10):
                return False
    return True


def create_receipt(snapshot, root, now, previous_hash):
    # Build a standalone same-vintage control. The older ledger's first capture could
    # have preceded revisions to this issue and need not agree with today's inputs.
    curve = legs.create_receipt(snapshot, root, now, None)
    trial = snapshot['curveStabilityTrial']
    latest = trial['latest']
    controls = curve['decisions']
    changes = curve['evidence']
    results = frozen_results(curve)
    if (trial['spec'] != SPEC or latest['available'] is not True
            or any(latest[k] != curve[k] for k in (*CLOCK_FIELDS, 'lagFeatureDate'))
            or latest['refitDate'] != curve['model']['refitDate']
            or not same(latest['probability'], curve['predictions']['conditionalRisk'])
            or any(latest[k] != changes[k] for k in ('shortChange', 'longChange'))
            or any(latest[k] is not controls[k] for k in CONTROL_FIELDS)
            or not same_grid(latest['results'], results)):
        raise ValueError('Stability issue disagrees with same-vintage Treasury rates, controls or results')
    hashes = dict(curve['codeSha256'])
    hashes.update({k: hashlib.sha256((root / k).read_bytes()).hexdigest() for k in NEW_CODE})
    record = {k: curve[k] for k in PARENT_FIELDS}
    record.update(protocolVersion=VERSION, previousHash=previous_hash, recipe=SPEC, recipeHash=object_hash(SPEC),
                  codeSha256=hashes, curveRecord=curve, results=results)
    record['hash'] = receipt_hash(record)
    return record


def verify_receipts(rows, now):
    previous_issue = previous_hash = None
    for record in rows:
        if (record['previousHash'] != previous_hash or record['hash'] != receipt_hash(record)
                or record['protocolVersion'] != VERSION or record['recipe'] != SPEC
                or record['recipeHash'] != object_hash(SPEC)
                or (previous_issue and record['issueDate'] <= previous_issue)):
            raise ValueError('Invalid stability record chain, issue order or grid specification')
        curve = record['curveRecord']
        legs.verify_receipts([curve], now)
        if any(record[k] != curve[k] for k in PARENT_FIELDS):
            raise ValueError('Stability probability, timestamps or provenance differ from the frozen controls')
        expected = frozen_results(curve)
        if object_hash(record['results']) != object_hash(expected):
            raise ValueError('Stability decisions or sensitivity bounds disagree with the frozen Treasury path')
        hashes = record['codeSha256']
        if (any(hashes.get(k) != v for k,v in curve['codeSha256'].items())
                or any(not re.fullmatch(r'[0-9a-f]{64}', hashes.get(k, '')) for k in NEW_CODE)):
            raise ValueError('Missing stability research code provenance')
        previous_issue, previous_hash = record['issueDate'], record['hash']
    return True


def summarize(rows, outcomes, now, status, available):
    summary = report(rows, outcomes, now, status, available, version=VERSION, predictions=PREDICTIONS,
                     download_url='/api/download?file=stabilityreceipts')
    matured = [(r, o['target']) for r,o in zip(rows,outcomes) if o['status']=='matured']
    positives = sum(y for _,y in matured)
    metrics = {}
    for cell, _, _ in GRID:
        alerts = [(r,y) for r,y in matured if r['results'][cell]['actual']]
        extra = [y for r,y in alerts if not r['curveRecord']['decisions']['levelAlert']]
        hits = sum(y for _,y in alerts)
        metrics[cell] = dict(n=len(matured), quietMonths=len(matured)-positives, preOnsetMonths=positives,
                             quietAlerts=len(alerts)-hits, preOnsetAlerts=hits,
                             newQuietAlerts=extra.count(0), newPreOnsetAlerts=extra.count(1))
    summary.update(
        decisionMetrics=metrics,
        excludedCount=sum(o['status']=='excluded' for o in outcomes),
        pendingCount=sum(o['status']=='pending' for o in outcomes),
        note='Each monthly record freezes its co-issued probability, Treasury evidence and 20 decision rules. Only actual alerts enter outcome scores. Guaranteed, possible and endpoint decisions are hypothetical sensitivities to a long-rate perturbation with the probability and pace held fixed.',
    )
    return summary


def update_receipts(root=ROOT, now=None):
    return update_trial_archive(root, now, trial_key='curveStabilityTrial', name='curve-stability',
                                fields=PREDICTIONS, available=lambda t: bool(t.get('spec')),
                                create=create_receipt, verify=verify_receipts, summarize=summarize,
                                evaluate=evaluate_onsets)


if __name__ == '__main__':
    result = update_receipts()
    print(json.dumps({k: result[k] for k in ('receiptCount','maturedCount','excludedCount','pendingCount','status','chainValid')}))
