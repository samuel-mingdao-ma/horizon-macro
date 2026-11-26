"""Offline tests for immutable forecasts and separately revised future outcomes."""
import copy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('forecast_ledger', ROOT/'research'/'forecast_ledger.py')
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)

class LedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads((ROOT/'data'/'snapshot.json').read_text())
        if 'innovation' not in cls.snapshot:
            raise RuntimeError('Build the innovation model before running ledger tests')
        issue = cls.snapshot['latest']['issueDate']
        cls.now = datetime.fromisoformat(issue).replace(day=25, hour=12, tzinfo=timezone.utc)
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='horizon-ledger-test-')
        self.root = Path(self.temp.name)
        (self.root/'data').mkdir()
        (self.root/'public'/'data').mkdir(parents=True)
        (self.root/'research'/'raw').mkdir(parents=True)
        for filename in ['build_model.py','innovation.py','forecast_ledger.py']:
            shutil.copy2(ROOT/'research'/filename,self.root/'research'/filename)
        shutil.copy2(ROOT/'research'/'raw'/'USREC.csv',self.root/'research'/'raw'/'USREC.csv')
        self.save_snapshot(self.snapshot)
    def tearDown(self):
        self.temp.cleanup()
    def save_snapshot(self, value):
        (self.root/'data'/'snapshot.json').write_text(json.dumps(value))
    def ledger_bytes(self):
        return (self.root/'data'/'forecast-ledger.jsonl').read_bytes()
    def test_canonical_hash_independent_of_dictionary_order(self):
        self.assertEqual(ledger.object_hash({'b':2,'a':1}),ledger.object_hash({'a':1,'b':2}))
        with self.assertRaises(ValueError):
            ledger.canonical_json({'missing':float('nan')})
    def test_first_capture_has_actual_time_no_matured_claim_and_real_code_fingerprints(self):
        with patch.dict('os.environ',{'GITHUB_ACTIONS':'','GITHUB_SHA':''}):
            result=ledger.update_ledger(self.root,self.now)
        self.assertEqual(result['receiptCount'],1)
        self.assertEqual(result['maturedCount'],0)
        self.assertTrue(result['chainValid'])
        receipt=result['latestReceipt']
        self.assertEqual(receipt['recordedAt'],self.now.isoformat())
        self.assertNotEqual(receipt['recordedAt'][:10],receipt['issueDate'])
        self.assertIsNone(receipt['codeCommit'])
        self.assertEqual(len(receipt['codeSha256']),3)
        self.assertTrue(all(value is None for value in result['metrics'].values()))
        self.assertEqual(self.ledger_bytes(),(self.root/'public'/'data'/'forecast-ledger.jsonl').read_bytes())
    def test_same_issue_revised_model_never_rewrites_receipt(self):
        first=ledger.update_ledger(self.root,self.now)
        before=self.ledger_bytes()
        revised=copy.deepcopy(self.snapshot)
        revised['latest']['probability']=.99
        revised['model']['intercept']+=.2
        self.save_snapshot(revised)
        second=ledger.update_ledger(self.root,self.now.replace(day=26))
        self.assertEqual(before,self.ledger_bytes())
        self.assertEqual(first['latestReceipt'],second['latestReceipt'])
        self.assertFalse(second['appendedThisRun'])
    def test_new_month_appends_and_hash_links_without_changing_original_bytes(self):
        first=ledger.update_ledger(self.root,self.now)
        before=self.ledger_bytes()
        next_snapshot=copy.deepcopy(self.snapshot)
        latest=next_snapshot['latest']
        for key,offset in [('issueDate',1),('featureDate',1),('forecastStart',1),('forecastEnd',1)]:
            latest[key]=ledger.month_offset(latest[key],offset)
        self.save_snapshot(next_snapshot)
        next_now=(pd.Timestamp(self.now)+pd.DateOffset(months=1)).to_pydatetime()
        second=ledger.update_ledger(self.root,next_now)
        self.assertEqual(second['receiptCount'],2)
        self.assertTrue(self.ledger_bytes().startswith(before))
        self.assertEqual(second['latestReceipt']['previousHash'],first['latestReceipt']['hash'])
    def test_tamper_and_public_mirror_divergence_fail_closed(self):
        result=ledger.update_ledger(self.root,self.now)
        changed=copy.deepcopy(result['receipts'])
        changed[0]['predictions']['baseline']+=.01
        with self.assertRaisesRegex(ValueError,'hash-chain'):
            ledger.verify_chain(changed)
        (self.root/'public'/'data'/'forecast-ledger.jsonl').write_text('changed\n')
        with self.assertRaisesRegex(ValueError,'disagree'):
            ledger.update_ledger(self.root,self.now)
    def test_unknown_outcomes_stay_pending_then_revisions_do_not_touch_receipts(self):
        result=ledger.update_ledger(self.root,self.now)
        before=self.ledger_bytes()
        receipt=result['latestReceipt']
        months=pd.date_range(receipt['forecastStart'],receipt['forecastEnd'],freq='MS')
        only_eleven=pd.Series([0.]*11,index=months[:11])
        evaluation_time=(months[-1]+pd.DateOffset(months=2)).tz_localize('UTC').to_pydatetime()
        pending=ledger.evaluate_outcomes(result['receipts'],only_eleven,evaluation_time)[0]
        self.assertEqual(pending['knownMonths'],11)
        self.assertIsNone(pending['target'])
        complete=pd.Series([0.]*12,index=months)
        first=ledger.evaluate_outcomes(result['receipts'],complete,evaluation_time)[0]
        premature=ledger.evaluate_outcomes(result['receipts'],complete,self.now)[0]
        self.assertEqual(premature['knownMonths'],0)
        self.assertIsNone(premature['target'])
        complete.iloc[2]=1
        revised=ledger.evaluate_outcomes(result['receipts'],complete,evaluation_time)[0]
        self.assertEqual(first['target'],0)
        self.assertEqual(revised['target'],1)
        self.assertEqual(before,self.ledger_bytes())
    def test_protocol_recipe_changes_require_explicit_new_registration(self):
        ledger.update_ledger(self.root,self.now)
        revised=copy.deepcopy(self.snapshot)
        revised['innovation']['spec']['penalty']=2.
        revised['innovation']['model']['penalty']=2.
        self.save_snapshot(revised)
        with self.assertRaisesRegex(ValueError,'recipe changed'):
            ledger.update_ledger(self.root,self.now)
    def test_fitted_challenger_penalty_must_match_the_registered_specification(self):
        changed=copy.deepcopy(self.snapshot)
        changed['innovation']['model']['penalty']=2.
        self.save_snapshot(changed)
        with self.assertRaisesRegex(ValueError,'fitted penalty'):
            ledger.update_ledger(self.root,self.now)
        self.assertFalse((self.root/'data'/'forecast-ledger.jsonl').exists())
    def test_parameter_dimensions_cannot_be_silently_truncated_by_zip(self):
        for field in ['means','scales','coefficients']:
            for delta in [-1,1]:
                with self.subTest(field=field,delta=delta):
                    model=copy.deepcopy(self.snapshot['model'])
                    model[field]=model[field][:-1] if delta<0 else model[field]+[1.]
                    with self.assertRaisesRegex(ValueError,'dimensions'):
                        ledger.model_probability(model,self.snapshot['latest']['features'])
        changed=copy.deepcopy(self.snapshot)
        changed['model']['coefficients']=changed['model']['coefficients'][:-1]
        self.save_snapshot(changed)
        with self.assertRaisesRegex(ValueError,'dimensions'):
            ledger.update_ledger(self.root,self.now)
        self.assertFalse((self.root/'data'/'forecast-ledger.jsonl').exists())
    def test_invalid_scales_and_duplicate_feature_names_cannot_be_scored(self):
        model=copy.deepcopy(self.snapshot['model'])
        model['scales'][0]=0
        with self.assertRaisesRegex(ValueError,'scales'):
            ledger.model_probability(model,self.snapshot['latest']['features'])
        model=copy.deepcopy(self.snapshot['model'])
        model['featureOrder'][1]=model['featureOrder'][0]
        with self.assertRaisesRegex(ValueError,'dimensions'):
            ledger.model_probability(model,self.snapshot['latest']['features'])
    def test_past_horizon_is_not_backfilled_as_a_prospective_capture(self):
        after_start=pd.Timestamp(self.snapshot['latest']['forecastStart'],tz='UTC').to_pydatetime()
        result=ledger.update_ledger(self.root,after_start)
        self.assertEqual(result['receiptCount'],0)
        self.assertEqual(self.ledger_bytes(),b'')

if __name__=='__main__':
    unittest.main(verbosity=2)
