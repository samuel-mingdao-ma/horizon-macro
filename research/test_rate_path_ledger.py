"""Offline, temporary-fixture tests for the independent rate-path prospective trial."""
import concurrent.futures
import copy
from datetime import datetime,timezone
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'research'))
import rate_path_ledger as ledger


def fitted(order,coefs):
    return dict(featureOrder=order,means=[0.]*len(order),scales=[1.]*len(order),coefficients=coefs,intercept=-1.,
        rawCoefficients=coefs,rawIntercept=-1.,penalty=1.,trainingN=200,trainedFrom='2000-01-01',
        trainedThrough='2025-10-01',lastTargetMonth='2026-10-01',refitDate='2026-11-01')


def fixture():
    original=fitted(['slope','credit','labor'],[-.3,.4,.1])
    candidate=fitted(ledger.FEATURES,[-.3,.4,.1,.2,-.2])
    a=dict(slope=1.,credit=-.1,labor=.2)
    b=dict(**a,slopeChange6=.1,fedFundsChange12=-.5)
    p=ledger.model_probability(original,a);q=ledger.model_probability(candidate,b)
    return dict(meta=dict(generatedAt='2026-11-25T10:00:00+00:00'),model=original,
        latest=dict(issueDate='2026-11-01',featureDate='2026-09-01',probability=p,baselineProbability=.2,features=a),
        sources=[dict(id='USREC',lastDate='2026-10-01',retrievedAt='2026-11-25T10:00:00Z')],
        ratePath=dict(spec=dict(penalty=1.),model=candidate,
            latest=dict(issueDate='2026-11-01',featureDate='2026-09-01',features=b,rawProbability=q,
                baselineProbability=.3,probability=.5*(q+.3),recentPriorProbability=.1,recentBlendProbability=.5*(p+.1),
                recentPriorN=180,recentPriorStart='2010-11-01',recentPriorEnd='2025-10-01',
                recentPriorObservedStart='2010-11-01',recentPriorObservedEnd='2025-10-01')))


class RatePathLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='horizon-rate-path-ledger-')
        self.root=Path(self.temp.name)
        for folder in ['data','public/data','research/raw']:(self.root/folder).mkdir(parents=True,exist_ok=True)
        for name in ['build_model.py','rate_path.py','rate_path_ledger.py','forecast_ledger.py']:
            source=ROOT/'research'/name
            if source.exists():shutil.copy2(source,self.root/'research'/name)
            else:(self.root/'research'/name).write_text('# synthetic source fingerprint fixture\n')
        pd.DataFrame({'USREC':[0]*10},index=pd.date_range('2026-01-01',periods=10,freq='MS')).to_csv(self.root/'research/raw/USREC.csv',index_label='observation_date')
        self.data=fixture();self.now=datetime(2026,11,25,12,tzinfo=timezone.utc)
        self.save(self.data)
        self.original=b'original prospective ledger remains unchanged\n'
        for name in ['data/forecast-ledger.jsonl','public/data/forecast-ledger.jsonl','research/prospective-protocol.json']:
            (self.root/name).write_bytes(self.original)
    def tearDown(self):self.temp.cleanup()
    def save(self,value):(self.root/'data/snapshot.json').write_text(json.dumps(value))
    def receipt_bytes(self):return (self.root/'data/rate-path-receipts.jsonl').read_bytes()
    def test_first_capture_freezes_all_seven_forecasts_and_preserves_legacy_trial(self):
        result=ledger.update_ledger(self.root,self.now)
        self.assertEqual(result['receiptCount'],1);self.assertEqual(result['maturedCount'],0)
        self.assertTrue(result['chainValid']);self.assertTrue(result['appendedThisRun'])
        row=result['latestReceipt'];self.assertEqual(row['recordedAt'],self.now.isoformat())
        self.assertEqual(set(row['predictions']),set(ledger.PREDICTIONS))
        self.assertEqual(row['baseRates'],{'original':.2,'candidate':.3})
        self.assertAlmostEqual(row['predictions']['candidateBlend'],.5*(row['predictions']['candidateRaw']+.3))
        self.assertEqual(row['predictions']['historicalBase'],.2)
        self.assertTrue(all(value is None for value in result['metrics'].values()))
        self.assertTrue(all(value is None for value in result['pairedComparisons'].values()))
        self.assertEqual(self.receipt_bytes(),(self.root/'public/data/rate-path-receipts.jsonl').read_bytes())
        for name in ['data/forecast-ledger.jsonl','public/data/forecast-ledger.jsonl','research/prospective-protocol.json']:
            self.assertEqual((self.root/name).read_bytes(),self.original)
    def test_same_issue_revisions_leave_receipt_bytes_unchanged(self):
        first=ledger.update_ledger(self.root,self.now);before=self.receipt_bytes()
        revised=copy.deepcopy(self.data);revised['ratePath']['latest']['probability']=.99
        self.save(revised);second=ledger.update_ledger(self.root,self.now.replace(day=26))
        self.assertEqual(before,self.receipt_bytes());self.assertFalse(second['appendedThisRun'])
        self.assertEqual(first['latestReceipt'],second['latestReceipt'])
    def test_next_month_appends_hash_link_and_never_backfills_missing_months(self):
        first=ledger.update_ledger(self.root,self.now);before=self.receipt_bytes()
        updated=copy.deepcopy(self.data)
        for latest in [updated['latest'],updated['ratePath']['latest']]:
            latest['issueDate']='2027-01-01';latest['featureDate']='2026-11-01'
        updated['ratePath']['latest'].update(recentPriorStart='2011-01-01',recentPriorEnd='2025-12-01',recentPriorObservedStart='2011-01-01',recentPriorObservedEnd='2025-12-01')
        self.save(updated);result=ledger.update_ledger(self.root,datetime(2027,1,20,tzinfo=timezone.utc))
        self.assertEqual(result['receiptCount'],2);self.assertTrue(self.receipt_bytes().startswith(before))
        self.assertEqual(result['latestReceipt']['previousHash'],first['latestReceipt']['hash'])
        self.assertEqual([row['issueDate'] for row in result['receipts']],['2026-11-01','2027-01-01'])
    def test_future_issue_rejected_and_stale_issue_not_captured(self):
        future=copy.deepcopy(self.data);future['ratePath']['latest']['issueDate']='2026-12-01'
        self.save(future)
        with self.assertRaisesRegex(ValueError,'future'):ledger.update_ledger(self.root,self.now)
        self.assertFalse((self.root/'data/rate-path-receipts.jsonl').exists())
        self.save(self.data);result=ledger.update_ledger(self.root,datetime(2026,12,5,tzinfo=timezone.utc))
        self.assertEqual(result['receiptCount'],0);self.assertEqual(result['status'],'stale-issue-no-capture')
    def test_missing_legacy_model_is_noop(self):
        legacy=copy.deepcopy(self.data);del legacy['ratePath'];self.save(legacy)
        before=(self.root/'data/snapshot.json').read_bytes()
        result=ledger.update_ledger(self.root,self.now)
        self.assertFalse(result['available']);self.assertEqual(result['receiptCount'],0)
        self.assertEqual((self.root/'data/snapshot.json').read_bytes(),before)
        self.assertFalse((self.root/'data/rate-path-receipts.jsonl').exists())
    def test_missing_recent_comparators_defer_capture_instead_of_inventing_values(self):
        incomplete=copy.deepcopy(self.data);incomplete['ratePath']['latest']['recentPriorProbability']=None
        self.save(incomplete);before=(self.root/'data/snapshot.json').read_bytes()
        result=ledger.update_ledger(self.root,self.now)
        self.assertEqual(result['status'],'incomplete-comparators-no-capture')
        self.assertFalse((self.root/'data/rate-path-receipts.jsonl').exists())
        self.assertEqual((self.root/'data/snapshot.json').read_bytes(),before)
    def test_recent_prior_cannot_use_an_ineligible_or_shorter_window(self):
        invalid=copy.deepcopy(self.data);invalid['ratePath']['latest']['recentPriorEnd']='2026-01-01'
        self.save(invalid)
        with self.assertRaisesRegex(ValueError,'180-month'):ledger.update_ledger(self.root,self.now)
        self.assertEqual(self.receipt_bytes(),b'')
    def test_tamper_mirror_disagreement_and_recipe_changes_fail_closed(self):
        result=ledger.update_ledger(self.root,self.now)
        changed=copy.deepcopy(result['receipts']);changed[0]['predictions']['candidateRaw']+=.01
        with self.assertRaisesRegex(ValueError,'hash chain'):ledger.verify_receipts(changed,self.now)
        (self.root/'public/data/rate-path-receipts.jsonl').write_text('changed\n')
        with self.assertRaisesRegex(ValueError,'disagree'):ledger.update_ledger(self.root,self.now)
        (self.root/'public/data/rate-path-receipts.jsonl').write_bytes(self.receipt_bytes())
        changed=copy.deepcopy(self.data);changed['ratePath']['model']['penalty']=2.;self.save(changed)
        with self.assertRaisesRegex(ValueError,'recipe'):ledger.update_ledger(self.root,self.now)
    def test_twelve_actual_outcomes_required_and_paired_scores_use_identical_rows(self):
        initial=ledger.update_ledger(self.root,self.now);before=self.receipt_bytes();row=initial['latestReceipt']
        months=pd.date_range(row['forecastStart'],row['forecastEnd'],freq='MS')
        eleven=pd.Series([0]*11,index=months[:11])
        later=datetime(2028,1,15,tzinfo=timezone.utc)
        pending=ledger.evaluate_outcomes(initial['receipts'],eleven,later)
        self.assertIsNone(pending[0]['target']);self.assertEqual(pending[0]['knownMonths'],11)
        actual=pd.Series([0]*12,index=months)
        early=ledger.evaluate_outcomes(initial['receipts'],actual,self.now)
        self.assertEqual(early[0]['knownMonths'],0)
        outcomes=ledger.evaluate_outcomes(initial['receipts'],actual,later)
        summary=ledger.summarize(initial['receipts'],outcomes,later,False,'already-captured')
        self.assertEqual(summary['maturedCount'],1)
        for name in ledger.PREDICTIONS:
            self.assertEqual(summary['metrics'][name]['n'],1)
            self.assertAlmostEqual(summary['metrics'][name]['brier'],row['predictions'][name]**2)
        diff=summary['pairedComparisons']['candidateBlendVsExistingBlend']
        self.assertEqual(diff['n'],1)
        self.assertAlmostEqual(diff['brierDifference'],row['predictions']['candidateBlend']**2-row['predictions']['existingBlend']**2)
        actual.iloc[2]=1
        revised=ledger.evaluate_outcomes(initial['receipts'],actual,later)
        self.assertEqual(revised[0]['target'],1);self.assertEqual(before,self.receipt_bytes())
    def test_interrupted_public_mirror_is_repaired_only_when_it_is_a_complete_prefix(self):
        first=ledger.update_ledger(self.root,self.now);prefix=self.receipt_bytes()
        updated=copy.deepcopy(self.data)
        for latest in [updated['latest'],updated['ratePath']['latest']]:
            latest['issueDate']='2026-12-01';latest['featureDate']='2026-10-01'
        updated['ratePath']['latest'].update(recentPriorStart='2010-12-01',recentPriorEnd='2025-11-01',recentPriorObservedStart='2010-12-01',recentPriorObservedEnd='2025-11-01')
        self.save(updated);later=datetime(2026,12,20,tzinfo=timezone.utc)
        ledger.update_ledger(self.root,later);canonical=self.receipt_bytes()
        (self.root/'public/data/rate-path-receipts.jsonl').write_bytes(prefix)
        repaired=ledger.update_ledger(self.root,later)
        self.assertEqual(repaired['receiptCount'],2);self.assertFalse(repaired['appendedThisRun'])
        self.assertEqual((self.root/'public/data/rate-path-receipts.jsonl').read_bytes(),canonical)
        (self.root/'public/data/rate-path-receipts.jsonl').write_bytes(canonical[:-3])
        with self.assertRaisesRegex(ValueError,'disagree'):ledger.update_ledger(self.root,later)
    def test_existing_trial_outcomes_refresh_when_a_new_month_has_incomplete_inputs(self):
        first=ledger.update_ledger(self.root,self.now);before=self.receipt_bytes();receipt=first['latestReceipt']
        incomplete=copy.deepcopy(self.data)
        incomplete['ratePath']['latest'].update(issueDate='2027-12-01',featureDate='2027-10-01',recentPriorProbability=None)
        self.save(incomplete)
        months=pd.date_range(receipt['forecastStart'],receipt['forecastEnd'],freq='MS')
        pd.DataFrame({'USREC':[0]*12},index=months).to_csv(self.root/'research/raw/USREC.csv',index_label='observation_date')
        result=ledger.update_ledger(self.root,datetime(2028,1,15,tzinfo=timezone.utc))
        self.assertEqual(result['receiptCount'],1);self.assertEqual(result['maturedCount'],1)
        self.assertEqual(result['status'],'incomplete-comparators-no-capture');self.assertFalse(result['modelAvailable'])
        self.assertEqual(before,self.receipt_bytes())
        written=json.loads((self.root/'data/snapshot.json').read_text())
        self.assertEqual(written['ratePath']['prospective']['maturedCount'],1)
        missing_model=copy.deepcopy(self.data);missing_model['ratePath']['model']=None
        self.save(missing_model)
        again=ledger.update_ledger(self.root,datetime(2028,1,15,tzinfo=timezone.utc))
        self.assertEqual(again['maturedCount'],1);self.assertFalse(again['modelAvailable'])
        self.assertEqual(before,self.receipt_bytes())
    def test_prior_trial_survives_a_legacy_producer_without_fabricating_a_model(self):
        ledger.update_ledger(self.root,self.now);before=self.receipt_bytes()
        legacy=copy.deepcopy(self.data);del legacy['ratePath'];self.save(legacy)
        result=ledger.update_ledger(self.root,self.now.replace(day=26))
        self.assertEqual(result['receiptCount'],1);self.assertEqual(result['status'],'model-unavailable-no-capture')
        written=json.loads((self.root/'data/snapshot.json').read_text())
        self.assertNotIn('ratePath',written);self.assertEqual(written['ratePathProspective']['receiptCount'],1)
        self.assertEqual(before,self.receipt_bytes())
    def test_concurrent_refreshes_append_only_one_receipt(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            result=list(pool.map(lambda _:ledger.update_ledger(self.root,self.now),range(2)))
        self.assertEqual(sum(item['appendedThisRun'] for item in result),1)
        self.assertEqual(len(ledger.read_receipts(self.root/'data/rate-path-receipts.jsonl',self.now)),1)

if __name__=='__main__':unittest.main(verbosity=2)
