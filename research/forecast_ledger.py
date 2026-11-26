#!/usr/bin/env python3
"""Append-only monthly prospective forecasts; outcomes are evaluated separately.

The SHA-256 chain detects inconsistent edits, not complete history replacement.
Public Git history is an audit trail, not an independently trusted timestamp.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'horizon-prospective-v1'
PREDICTIONS = ['baseline', 'challenger', 'historicalBase', 'blend']
MODEL_FIELDS = ['featureOrder', 'means', 'scales', 'coefficients', 'intercept', 'rawCoefficients', 'rawIntercept',
                'penalty', 'trainedFrom', 'trainedThrough', 'lastTargetMonth', 'trainingN', 'refitDate']


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def object_hash(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def receipt_hash(receipt):
    return object_hash({k: v for k, v in receipt.items() if k != 'hash'})


def current_recipe(snapshot):
    spec = snapshot['innovation']['spec']
    fitted_penalty = snapshot['innovation']['model'].get('penalty')
    declared_penalty = spec.get('penalty')
    if not isinstance(fitted_penalty, (int, float)) or not isinstance(declared_penalty, (int, float)) \
        or not math.isfinite(fitted_penalty) or not math.isfinite(declared_penalty) \
        or fitted_penalty != declared_penalty:
        raise ValueError('Challenger fitted penalty disagrees with its declared prospective specification')
    return dict(baselineFeatures=snapshot['model']['featureOrder'], challengerFeatures=snapshot['innovation']['model']['featureOrder'],
        interactionFormula=spec['featureFormula'], baselinePenalty=snapshot['model']['penalty'], challengerPenalty=fitted_penalty,
        featureLagMonths=spec['featureLagMonths'], horizonMonths=spec['horizonMonths'], eligibilityMonths=spec['eligibilityMonths'],
        refitFrequency=spec['refitFrequency'], confirmationRule=spec['confirmationRule'], defaultThreshold=spec['defaultThreshold'],
        blendWeights={'baseline':0.5,'historicalBase':0.5},
        laborMissingPolicy='Three-calendar-month mean requires at least two observations; twelve consecutive smoothed values for minimum; no interpolation')


def code_evidence(root):
    files = ['research/build_model.py', 'research/innovation.py', 'research/forecast_ledger.py']
    hashes = {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files}
    sha = os.environ.get('GITHUB_SHA', '') if os.environ.get('GITHUB_ACTIONS') == 'true' else ''
    return dict(codeCommit=sha if re.fullmatch(r'[0-9a-f]{40}',sha) else None, codeSha256=hashes)


def month_offset(date, months):
    return (pd.Timestamp(date) + pd.DateOffset(months=months)).strftime('%Y-%m-%d')


def model_probability(model, features):
    order = model.get('featureOrder')
    if not isinstance(order, list) or not order or not all(isinstance(key, str) for key in order) or len(set(order)) != len(order):
        raise ValueError('Frozen model feature dimensions are invalid')
    for name in ['means', 'scales', 'coefficients']:
        values = model.get(name)
        if not isinstance(values, list) or len(values) != len(order):
            raise ValueError('Frozen model parameter dimensions do not match its feature order')
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
            raise ValueError('Frozen model parameters must be finite numbers')
    if any(scale <= 0 for scale in model['scales']):
        raise ValueError('Frozen model scales must be positive')
    if not isinstance(model.get('intercept'), (int, float)) or not math.isfinite(model['intercept']):
        raise ValueError('Frozen model intercept must be a finite number')
    if not all(key in features and isinstance(features[key], (int, float)) and math.isfinite(features[key]) for key in order):
        raise ValueError('Frozen model features must be complete finite numbers')
    values = [float(features[key]) for key in order]
    z = float(model['intercept']) + sum((value - float(mean)) / float(scale) * float(coef)
        for value, mean, scale, coef in zip(values, model['means'], model['scales'], model['coefficients']))
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def verify_chain(receipts):
    previous = None
    last_issue = None
    for receipt in receipts:
        if receipt.get('protocolVersion') != VERSION:
            raise ValueError('Unrecognized prospective receipt protocol')
        if receipt.get('previousHash') != previous or receipt.get('hash') != receipt_hash(receipt):
            raise ValueError('Forecast receipt hash-chain verification failed')
        issue = receipt['issueDate']
        if last_issue is not None and issue <= last_issue:
            raise ValueError('Forecast issues must be unique and strictly increasing')
        if receipt['forecastStart'] != month_offset(issue, 1) or receipt['forecastEnd'] != month_offset(issue, 12):
            raise ValueError('Forecast receipt horizon inconsistent with issue month')
        recorded = pd.Timestamp(receipt['recordedAt'])
        if recorded.tzinfo is None or recorded >= pd.Timestamp(receipt['forecastStart'], tz='UTC'):
            raise ValueError('A prospective forecast must be captured before its outcome horizon starts')
        for name in PREDICTIONS:
            value = receipt['predictions'][name]
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('Invalid receipt probability')
        for name in ['baseline', 'challenger']:
            if abs(model_probability(receipt['models'][name], receipt['features'][name]) - receipt['predictions'][name]) > 1e-8:
                raise ValueError('Receipt probability does not reproduce from its frozen model')
        if abs(receipt['predictions']['blend'] - .5*(receipt['predictions']['baseline']+receipt['predictions']['historicalBase'])) > 1e-12:
            raise ValueError('Predeclared blend differs from its fixed equal-weight rule')
        if receipt.get('recipeHash') != object_hash(receipt['recipe']):
            raise ValueError('Forecast recipe fingerprint inconsistent')
        for name in ['baseline', 'challenger']:
            if receipt.get('modelHashes', {}).get(name) != object_hash(receipt['models'][name]):
                raise ValueError('Frozen model fingerprint inconsistent')
        previous, last_issue = receipt['hash'], issue
    return True


def read_ledger(path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if not line:
            raise ValueError('Blank line in canonical forecast ledger')
        receipt = json.loads(line)
        if line != canonical_json(receipt):
            raise ValueError('Forecast ledger line is not canonical JSON')
        rows.append(receipt)
    verify_chain(rows)
    return rows


def ensure_protocol(path, now, recipe):
    if path.exists():
        protocol = json.loads(path.read_text())
        if protocol.get('protocolVersion') != VERSION:
            raise ValueError('Prospective protocol version mismatch')
        if protocol.get('recipe') != recipe:
            raise ValueError('Prospective model recipe changed: register a new protocol version before continuing')
        return protocol
    protocol = dict(protocolVersion=VERSION, registeredAt=now.isoformat(), recipe=recipe,
        target='At least one NBER recession month in the next 12 calendar months after issue month; requires all 12 published USREC observations to score.',
        capture='Freeze the first successful research refresh in each issue month. Capture time is actual UTC time, never the nominal first of the issue month. No missed month is backfilled.',
        models=dict(baseline='Prespecified three-input L2 logistic recession model.',
                    challenger='Exploratory credit-confirmed curve challenger: same three inputs plus max(-slope,0)*credit; fixed L2 penalty 1.',
                    historicalBase='Recession-horizon prevalence in the baseline training sample.',
                    blend='Exploratory comparator: fixed equal weight of baseline model and historical training prevalence; chosen after historical inspection.'),
        disclosure='The challenger was proposed after examining historical results. Prospective receipts begin now; historical replay is not a real-time or untouched test.',
        revisions='Never rewrite a monthly receipt when data or models are revised. Evaluate outcomes separately against the latest actually published USREC values, which may themselves be revised.',
        integrity='SHA-256 over canonical JSON (sorted keys, compact UTF-8, no NaN), including the previous receipt hash. Hash-linked public Git receipts are not tamper-proof, blockchain-backed, or independently timestamped.',
        metrics=['Brier score', 'log loss'], probabilityUnits='fraction from 0 to 1')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(protocol, indent=2) + '\n')
    return protocol


def create_receipt(snapshot, previous_hash, now, protocol, evidence):
    latest = snapshot['latest']
    innovation = snapshot['innovation']
    issue = latest['issueDate']
    if pd.Timestamp(issue).day != 1 or issue > now.strftime('%Y-%m-01'):
        raise ValueError('Cannot capture a future or malformed issue month')
    if pd.Timestamp(latest['forecastStart'], tz='UTC') <= pd.Timestamp(now):
        raise ValueError('Current forecast horizon has already started; do not backfill a prospective receipt')
    frozen_models = {name: {field: copy.deepcopy(model[field]) for field in MODEL_FIELDS if field in model}
        for name, model in [('baseline', snapshot['model']), ('challenger', innovation['model'])]}
    receipt = dict(protocolVersion=VERSION, recordedAt=now.isoformat(),
        protocolHash=object_hash(protocol), recipe=copy.deepcopy(protocol['recipe']), recipeHash=object_hash(protocol['recipe']),
        modelHashes={name:object_hash(model) for name,model in frozen_models.items()}, **evidence,
        issueDate=issue, forecastStart=latest['forecastStart'], forecastEnd=latest['forecastEnd'], featureDate=latest['featureDate'],
        sourceBuildGeneratedAt=snapshot['meta']['generatedAt'],
        features=dict(baseline=copy.deepcopy(latest['features']), challenger=copy.deepcopy(innovation['latest']['features'])),
        models=frozen_models,
        predictions=dict(baseline=latest['probability'], challenger=innovation['latest']['probability'], historicalBase=latest['baselineProbability'], blend=.5*(latest['probability']+latest['baselineProbability'])),
        sources=[{field: copy.deepcopy(source.get(field)) for field in ['id', 'lastDate', 'retrievedAt', 'transportStatus', 'providerRetrievedAt', 'verifiedProviderLastDate']}
                 for source in snapshot['sources']], previousHash=previous_hash)
    receipt['hash'] = receipt_hash(receipt)
    return receipt


def append_receipt(path, snapshot, now, protocol, evidence):
    receipts = read_ledger(path)
    for row in receipts:
        if row.get('protocolHash') != object_hash(protocol) or row.get('recipeHash') != object_hash(protocol['recipe']):
            raise ValueError('Registered prospective protocol differs from a published receipt')
    issue = snapshot['latest']['issueDate']
    if any(row['issueDate'] == issue for row in receipts):
        return receipts, False
    if receipts and issue < receipts[-1]['issueDate']:
        raise ValueError('Cannot append an earlier issue to the prospective ledger')
    if pd.Timestamp(snapshot['latest']['forecastStart'], tz='UTC') <= pd.Timestamp(now):
        return receipts, False  # Stale inputs cannot create a retrospectively captured forecast.
    receipt = create_receipt(snapshot, receipts[-1]['hash'] if receipts else None, now, protocol, evidence)
    verify_chain(receipts + [receipt])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as output:
        output.write(canonical_json(receipt) + '\n')
    return receipts + [receipt], True


def evaluate_outcomes(receipts, recession, now, source_retrieved_at=None):
    if recession.index.has_duplicates:
        raise ValueError('Duplicate monthly recession labels')
    # Published monthly labels cannot come from the current incomplete month or the future.
    current_month = pd.Timestamp(now).tz_convert('UTC').tz_localize(None).to_period('M').to_timestamp()
    recession = recession.loc[recession.index < current_month]
    valid = recession.dropna()
    if not valid.isin([0, 1]).all():
        raise ValueError('USREC outcomes must contain only observed zero/one labels')
    source_last = valid.index[-1].strftime('%Y-%m-%d') if len(valid) else None
    outcomes = []
    for receipt in receipts:
        months = pd.date_range(receipt['forecastStart'], receipt['forecastEnd'], freq='MS')
        observations = recession.reindex(months)
        known = int(observations.notna().sum())
        matured = len(months) == 12 and known == 12
        outcomes.append(dict(receiptHash=receipt['hash'], issueDate=receipt['issueDate'],
            status='matured' if matured else 'pending', knownMonths=known, requiredMonths=12,
            target=int(observations.max()) if matured else None,
            sourceLastDate=source_last, sourceRetrievedAt=source_retrieved_at, evaluatedAt=now.isoformat()))
    return outcomes


def prospective_summary(receipts, outcomes, protocol, now, appended):
    matured = [(receipt, outcome) for receipt, outcome in zip(receipts, outcomes) if outcome['status'] == 'matured']
    metrics = {}
    for name in PREDICTIONS:
        if not matured:
            metrics[name] = None
            continue
        brier, log_loss = [], []
        for receipt, outcome in matured:
            p, y = receipt['predictions'][name], outcome['target']
            clipped = min(max(p, 1e-12), 1 - 1e-12)
            brier.append((p-y)**2)
            log_loss.append(-(y*math.log(clipped)+(1-y)*math.log(1-clipped)))
        metrics[name] = dict(n=len(matured), brier=sum(brier)/len(brier), logLoss=sum(log_loss)/len(log_loss))
    return dict(protocolVersion=VERSION, protocolRegisteredAt=protocol['registeredAt'],
        receiptCount=len(receipts), maturedCount=len(matured), chainValid=verify_chain(receipts),
        lastHash=receipts[-1]['hash'] if receipts else None,
        latestReceipt=receipts[-1] if receipts else None, receipts=receipts, outcomes=outcomes, metrics=metrics,
        appendedThisRun=appended, evaluatedAt=now.isoformat(), downloadUrl='/api/download?file=ledger',
        note='First captures are frozen at their actual UTC capture time. Outcomes stay pending until all 12 future USREC months are published. Hash-linked public Git receipts provide an inspectable audit trail, not tamper-proof storage or an independent timestamp.')


def update_ledger(root=ROOT, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Ledger capture time requires a timezone')
    now = now.astimezone(timezone.utc)
    snapshot_path = root / 'data' / 'snapshot.json'
    public_snapshot = root / 'public' / 'data' / 'snapshot.json'
    snapshot = json.loads(snapshot_path.read_text())
    if 'innovation' not in snapshot:
        raise ValueError('Build the challenger innovation model before recording forecasts')
    path, mirror = root / 'data' / 'forecast-ledger.jsonl', root / 'public' / 'data' / 'forecast-ledger.jsonl'
    if path.exists() and mirror.exists() and path.read_bytes() != mirror.read_bytes():
        raise ValueError('Canonical and public forecast ledgers disagree; audit before proceeding')
    if mirror.exists() and not path.exists():
        raise ValueError('Public ledger exists without the canonical ledger; audit before proceeding')
    protocol = ensure_protocol(root / 'research' / 'prospective-protocol.json', now, current_recipe(snapshot))
    receipts, appended = append_receipt(path, snapshot, now, protocol, code_evidence(root))
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_bytes(path.read_bytes())
    rec_frame = pd.read_csv(root / 'research' / 'raw' / 'USREC.csv', index_col=0, parse_dates=True)
    recession = pd.to_numeric(rec_frame.USREC, errors='coerce')
    rec_source = next((row for row in snapshot['sources'] if row['id']=='USREC'), {})
    outcomes = evaluate_outcomes(receipts, recession, now, rec_source.get('retrievedAt'))
    snapshot['prospective'] = prospective_summary(receipts, outcomes, protocol, now, appended)
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    snapshot_path.write_text(payload)
    public_snapshot.write_text(payload)
    return snapshot['prospective']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    summary = update_ledger()
    print(json.dumps({key:summary[key] for key in ['protocolVersion','receiptCount','maturedCount','chainValid','appendedThisRun','lastHash']}))


if __name__ == '__main__':
    main()
