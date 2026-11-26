#!/usr/bin/env python3
"""Separate, append-only prospective trial for the five-input rate-path model.

This module never writes the original forecast ledger or its protocol. It reuses
only pure canonicalization, model-scoring and delayed-outcome helpers.
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
from forecast_ledger import canonical_json, object_hash, model_probability, evaluate_outcomes, month_offset, MODEL_FIELDS

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'rate-path-prospective-v1'
PREDICTIONS = ['original', 'existingBlend', 'historicalBase', 'candidateRaw', 'candidateBlend', 'recentPrior', 'recentBlend']
FEATURES = ['slope', 'credit', 'labor', 'slopeChange6', 'fedFundsChange12']
PAIRINGS = {'candidateBlendVsOriginal': ('candidateBlend','original'),
            'candidateBlendVsExistingBlend': ('candidateBlend','existingBlend'),
            'candidateBlendVsHistoricalBase': ('candidateBlend','historicalBase'),
            'candidateRawVsOriginal': ('candidateRaw','original'),
            'recentBlendVsOriginal': ('recentBlend','original'),
            'recentBlendVsExistingBlend': ('recentBlend','existingBlend'),
            'recentPriorVsHistoricalBase': ('recentPrior','historicalBase'),
            'candidateBlendVsRecentBlend': ('candidateBlend','recentBlend')}


def utc_now(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError('Rate-path capture time must have a timezone')
    return value.astimezone(timezone.utc)


def probability(value):
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Rate-path forecasts must be finite probabilities')
    return value


def recipe(snapshot):
    experiment = snapshot['ratePath']
    model = experiment['model']
    if model.get('featureOrder') != FEATURES or model.get('penalty') != 1.0:
        raise ValueError('Rate-path fitted recipe differs from the declared five-input L2 specification')
    declared_penalty = experiment.get('spec', {}).get('penalty', model['penalty'])
    if declared_penalty != model['penalty']:
        raise ValueError('Rate-path fitted and declared penalties disagree')
    return dict(protocolVersion=VERSION, originalFeatures=snapshot['model']['featureOrder'], candidateFeatures=FEATURES,
        formulas=dict(slope='GS10 - TB3MS', credit='Calendar-month mean of weekly NFCICREDIT',
            labor='3-calendar-month UNRATE mean (at least 2 observed), minus 12-smoothed-month minimum',
            slopeChange6='slope_m - slope_(m-6)', fedFundsChange12='FEDFUNDS_m - FEDFUNDS_(m-12)'),
        featureLagMonths=2, horizonMonths=12, trainingEligibilityMonths=13,
        historicalRefit='Expanding January refit', currentRefit='Expanding monthly refit',
        originalPenalty=snapshot['model']['penalty'], candidatePenalty=model['penalty'],
        candidateWeights=dict(rawFiveInput=0.5, candidateTrainingPrevalence=0.5),
        existingBlendWeights=dict(original=0.5, originalTrainingPrevalence=0.5),
        recentPriorDesignId=experiment.get('spec',{}).get('recentPriorDesignId','recent-prior-180-fixed-50-v1'),
        recentPriorRecipe=experiment.get('spec',{}).get('recentPriorRecipe','0.5 * original three-input probability + 0.5 * recent 180-calendar-month training prevalence'),
        recentPriorWindowMonths=180,recentPriorMinimumCompleteRows=120,recentBlendWeights=dict(original=0.5,recentPrior=0.5),
        target='Any recession month in the next 12 calendar months after issue; score only after all 12 published USREC months are known.',
        status='Specification proposed after examining historical failures; future receipt performance is separate from retrospective replay.')


def code_evidence(root):
    names = ['research/build_model.py','research/rate_path.py','research/rate_path_ledger.py','research/forecast_ledger.py']
    hashes = {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names}
    sha = os.environ.get('GITHUB_SHA','') if os.environ.get('GITHUB_ACTIONS') == 'true' else ''
    return dict(codeCommit=sha if re.fullmatch(r'[0-9a-f]{40}',sha) else None, codeSha256=hashes)


def digest(receipt):
    return object_hash({key:value for key,value in receipt.items() if key != 'hash'})


def verify_receipts(receipts, now=None):
    previous, last_issue, fixed_recipe = None, None, None
    clock = pd.Timestamp(utc_now(now))
    for row in receipts:
        if row.get('protocolVersion') != VERSION or row.get('previousHash') != previous or row.get('hash') != digest(row):
            raise ValueError('Rate-path receipt hash chain is inconsistent')
        if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])-01',row['issueDate']):
            raise ValueError('Rate-path issue must be a calendar month start')
        if last_issue is not None and row['issueDate'] <= last_issue:
            raise ValueError('Rate-path issues must be unique and strictly increasing')
        if row['featureDate'] != month_offset(row['issueDate'],-2) or row['forecastStart'] != month_offset(row['issueDate'],1) or row['forecastEnd'] != month_offset(row['issueDate'],12):
            raise ValueError('Rate-path feature date or forecast horizon is inconsistent')
        recorded = pd.Timestamp(row['recordedAt'])
        if recorded.tzinfo is None or recorded >= pd.Timestamp(row['forecastStart'],tz='UTC') or recorded > clock:
            raise ValueError('Rate-path capture must occur before its future horizon and cannot be future-dated')
        if row.get('recipeHash') != object_hash(row['recipe']):
            raise ValueError('Rate-path recipe fingerprint is inconsistent')
        if fixed_recipe is not None and row['recipeHash'] != fixed_recipe:
            raise ValueError('Rate-path recipe changed inside the same prospective trial')
        for name in PREDICTIONS:
            probability(row['predictions'][name])
        for name,prediction in [('original','original'),('candidate','candidateRaw')]:
            if row['modelHashes'].get(name) != object_hash(row['models'][name]):
                raise ValueError('Rate-path frozen model fingerprint is inconsistent')
            if abs(model_probability(row['models'][name],row['features'][name])-row['predictions'][prediction]) > 1e-8:
                raise ValueError('Rate-path frozen model does not reproduce its forecast')
            if pd.Timestamp(row['models'][name]['lastTargetMonth']) >= pd.Timestamp(row['issueDate']):
                raise ValueError('Rate-path training outcome reaches into the forecast issue')
        if abs(row['predictions']['historicalBase']-row['baseRates']['original']) > 1e-12:
            raise ValueError('Rate-path original base-rate comparator changed')
        if abs(row['predictions']['existingBlend']-.5*(row['predictions']['original']+row['baseRates']['original'])) > 1e-12:
            raise ValueError('Rate-path existing 50/50 comparator is inconsistent')
        if abs(row['predictions']['candidateBlend']-.5*(row['predictions']['candidateRaw']+row['baseRates']['candidate'])) > 1e-12:
            raise ValueError('Rate-path candidate differs from its fixed 50/50 mixture')
        recent=row['recentPrior']
        if recent['end']!=month_offset(row['issueDate'],-13) or recent['start']!=month_offset(recent['end'],-179):
            raise ValueError('Recent-prior receipt does not retain its fixed 180-month eligible window')
        if not isinstance(recent['n'],int) or not 120<=recent['n']<=180:
            raise ValueError('Recent-prior receipt does not have sufficient known training outcomes')
        if not recent['start']<=recent['observedStart']<=recent['observedEnd']<=recent['end']:
            raise ValueError('Recent-prior observed dates fall outside the frozen eligible window')
        if abs(row['predictions']['recentPrior']-recent['probability'])>1e-12 or abs(row['predictions']['recentBlend']-.5*(row['predictions']['original']+recent['probability']))>1e-12:
            raise ValueError('Recent-prior mixture differs from its frozen rule')
        previous, last_issue, fixed_recipe = row['hash'], row['issueDate'], row['recipeHash']
    return True


def read_receipts(path, now=None):
    if not path.exists():
        return []
    receipts=[]
    for line in path.read_text().splitlines():
        row=json.loads(line)
        if line != canonical_json(row):
            raise ValueError('Rate-path receipt is not canonical JSON')
        receipts.append(row)
    verify_receipts(receipts,now)
    return receipts


def create_receipt(snapshot, now, previous_hash, evidence):
    experiment=snapshot['ratePath']; latest=experiment['latest']; original=snapshot['latest']
    issue=latest.get('issueDate',experiment.get('issueDate',original['issueDate']))
    feature=latest.get('featureDate',experiment.get('featureDate',original['featureDate']))
    if issue != original['issueDate'] or feature != original['featureDate']:
        raise ValueError('Original and rate-path forecasts must have the same issue and input dates')
    if issue > now.strftime('%Y-%m-01'):
        raise ValueError('Cannot capture a future rate-path issue')
    if pd.Timestamp(month_offset(issue,1),tz='UTC') <= pd.Timestamp(now):
        raise ValueError('Do not backfill a rate-path forecast after its horizon started')
    frozen={name:{field:copy.deepcopy(model[field]) for field in MODEL_FIELDS if field in model}
            for name,model in [('original',snapshot['model']),('candidate',experiment['model'])]}
    raw=probability(latest['rawProbability']); candidate_base=probability(latest['baselineProbability'])
    old_base=probability(original['baselineProbability']); original_p=probability(original['probability'])
    mixed=probability(latest['probability'])
    recent_p=probability(latest['recentPriorProbability'])
    if abs(probability(latest['recentBlendProbability'])-.5*(original_p+recent_p))>1e-8:
        raise ValueError('Published recent-prior candidate is not its declared 50/50 mixture')
    if abs(mixed-.5*(raw+candidate_base))>1e-8:
        raise ValueError('Published rate-path candidate is not the declared 50/50 mixture')
    specification=recipe(snapshot)
    row=dict(protocolVersion=VERSION,recordedAt=now.isoformat(),issueDate=issue,featureDate=feature,
        forecastStart=month_offset(issue,1),forecastEnd=month_offset(issue,12),
        sourceBuildGeneratedAt=snapshot['meta']['generatedAt'],recipe=specification,recipeHash=object_hash(specification),
        models=frozen,modelHashes={name:object_hash(model) for name,model in frozen.items()},
        features=dict(original=copy.deepcopy(original['features']),candidate=copy.deepcopy(latest['features'])),
        baseRates=dict(original=old_base,candidate=candidate_base),
        predictions=dict(original=original_p,existingBlend=.5*(original_p+old_base),historicalBase=old_base,
            candidateRaw=raw,candidateBlend=.5*(raw+candidate_base),recentPrior=recent_p,recentBlend=.5*(original_p+recent_p)),
        recentPrior=dict(probability=recent_p,n=latest['recentPriorN'],start=latest['recentPriorStart'],end=latest['recentPriorEnd'],
            observedStart=latest['recentPriorObservedStart'],observedEnd=latest['recentPriorObservedEnd']),
        sources=[{field:copy.deepcopy(source.get(field)) for field in ['id','lastDate','retrievedAt','transportStatus','providerRetrievedAt','verifiedProviderLastDate']}
            for source in snapshot['sources']],previousHash=previous_hash,**evidence)
    row['hash']=digest(row)
    return row


def scores(p,y):
    clipped=min(max(p,1e-12),1-1e-12)
    return (p-y)**2,-(y*math.log(clipped)+(1-y)*math.log(1-clipped))


def summarize(receipts,outcomes,now,appended,status):
    paired=[(row,outcome) for row,outcome in zip(receipts,outcomes) if outcome['status']=='matured']
    metrics={name:None for name in PREDICTIONS}
    comparisons={name:None for name in PAIRINGS}
    if paired:
        for name in PREDICTIONS:
            values=[scores(row['predictions'][name],outcome['target']) for row,outcome in paired]
            metrics[name]=dict(n=len(values),brier=sum(v[0] for v in values)/len(values),logLoss=sum(v[1] for v in values)/len(values))
        for name,(candidate,comparator) in PAIRINGS.items():
            changes=[tuple(a-b for a,b in zip(scores(row['predictions'][candidate],outcome['target']),scores(row['predictions'][comparator],outcome['target']))) for row,outcome in paired]
            comparisons[name]=dict(n=len(changes),brierDifference=sum(v[0] for v in changes)/len(changes),
                logLossDifference=sum(v[1] for v in changes)/len(changes),
                winsBrier=sum(v[0]<0 for v in changes),lossesBrier=sum(v[0]>0 for v in changes),tiesBrier=sum(v[0]==0 for v in changes))
    return dict(protocolVersion=VERSION,available=True,status=status,
        registeredAt=receipts[0]['recordedAt'] if receipts else None,receiptCount=len(receipts),maturedCount=len(paired),
        chainValid=verify_receipts(receipts,now),latestReceipt=receipts[-1] if receipts else None,
        receipts=receipts,outcomes=outcomes,metrics=metrics,pairedComparisons=comparisons,
        lastHash=receipts[-1]['hash'] if receipts else None,appendedThisRun=appended,evaluatedAt=now.isoformat(),
        downloadUrl='/api/download?file=ratepathreceipts',
        note='Separate prospective trial; first actual UTC capture per issue is immutable. All seven forecasts are scored on exactly the same matured receipts after all 12 USREC months are known. Paired differences are candidate minus comparator; negative is better. Monthly horizons overlap. A public hash-linked Git audit is not tamper-proof or independently timestamped.')


def _atomic_write(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.rate-path.tmp')
    temporary.write_text(payload)
    temporary.replace(path)


def _check_mirror(canonical,mirror):
    if mirror.exists():
        published=mirror.read_bytes()
        # An interrupted append can leave an older, complete public prefix.
        if not canonical.startswith(published) or (published and not published.endswith(b'\n')):
            raise ValueError('Canonical and public rate-path receipts disagree; audit before continuing')


def _complete_inputs(snapshot):
    experiment=snapshot.get('ratePath')
    if not isinstance(experiment,dict):
        return False
    latest=experiment.get('latest')
    if not isinstance(latest,dict):
        return False
    required=['probability','rawProbability','baselineProbability','features','recentPriorProbability','recentBlendProbability',
        'recentPriorN','recentPriorStart','recentPriorEnd','recentPriorObservedStart','recentPriorObservedEnd']
    if any(latest.get(key) is None for key in required):
        return False
    model=experiment.get('model')
    if not isinstance(model,dict):
        return False
    return all(model.get(key) is not None for key in ['featureOrder','means','scales','coefficients','intercept','penalty','lastTargetMonth'])


def update_ledger(root=ROOT,now=None):
    actual_clock=now is None
    root=Path(root);now=utc_now(now)
    snapshot_path=root/'data'/'snapshot.json';mirror_snapshot=root/'public'/'data'/'snapshot.json'
    snapshot=json.loads(snapshot_path.read_text())
    path=root/'data'/'rate-path-receipts.jsonl';mirror=root/'public'/'data'/'rate-path-receipts.jsonl'
    if mirror.exists() and not path.exists():
        raise ValueError('Public rate-path receipts have no canonical ledger')
    complete=_complete_inputs(snapshot)
    experiment=snapshot.get('ratePath')
    prior_exists=path.exists() and path.stat().st_size>0
    if not complete and not prior_exists:
        # Legacy snapshots or an unscorable new experiment do not invent a trial.
        return dict(available=False,status='model-unavailable' if not isinstance(experiment,dict) else 'incomplete-comparators-no-capture',
            receiptCount=0,appendedThisRun=False,chainValid=True)
    issue=None
    if complete:
        issue=experiment['latest'].get('issueDate',experiment.get('issueDate',snapshot['latest']['issueDate']))
        if issue>now.strftime('%Y-%m-01'):
            raise ValueError('Cannot capture a future rate-path issue')
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+') as locked:
        fcntl.flock(locked.fileno(),fcntl.LOCK_EX)
        if actual_clock:
            now=utc_now()  # A competing writer may have captured after our entry time.
        receipts=read_receipts(path,now)
        _check_mirror(path.read_bytes(),mirror)
        if not complete:
            appended=False
            status='model-unavailable-no-capture' if not isinstance(experiment,dict) else 'incomplete-comparators-no-capture'
        else:
            specification=recipe(snapshot)
            if receipts and receipts[0]['recipeHash']!=object_hash(specification):
                raise ValueError('Rate-path specification changed; register a new prospective trial')
            if any(row['issueDate']==issue for row in receipts):
                appended,status=False,'already-captured'
            elif (receipts and issue<receipts[-1]['issueDate']) or pd.Timestamp(month_offset(issue,1),tz='UTC')<=pd.Timestamp(now):
                appended,status=False,'stale-issue-no-capture'
            else:
                row=create_receipt(snapshot,now,receipts[-1]['hash'] if receipts else None,code_evidence(root))
                verify_receipts(receipts+[row],now)
                locked.write(canonical_json(row)+'\n');locked.flush();os.fsync(locked.fileno())
                receipts.append(row);appended,status=True,'captured'
        _atomic_write(mirror,path.read_text())
        frame=pd.read_csv(root/'research'/'raw'/'USREC.csv',index_col=0,parse_dates=True)
        rec=pd.to_numeric(frame.USREC,errors='coerce')
        source=next((row for row in snapshot['sources'] if row['id']=='USREC'),{})
        outcomes=evaluate_outcomes(receipts,rec,now,source.get('retrievedAt'))
        summary=summarize(receipts,outcomes,now,appended,status)
        summary['modelAvailable']=complete
        if isinstance(experiment,dict):
            snapshot['ratePath']['prospective']=summary
            snapshot.pop('ratePathProspective',None)
        else:
            # Preserve the separate audit even if an older producer omits the
            # model; do not fabricate a partial ratePath model for the UI.
            snapshot['ratePathProspective']=summary
        payload=json.dumps(snapshot,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        _atomic_write(snapshot_path,payload);_atomic_write(mirror_snapshot,payload)
        fcntl.flock(locked.fileno(),fcntl.LOCK_UN)
    return summary


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    result=update_ledger()
    print(json.dumps({key:result[key] for key in ['available','status','receiptCount','appendedThisRun','chainValid']}))


if __name__=='__main__':
    main()
