"""Prospective Treasury evidence, independent tenor-file checks and closed-window adjudication."""

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import curve_legs_receipts as ledger
from test_confirmation_receipts import fixture as risk_fixture


def fixture(issue='2026-11-01', probabilities=(.20,.21,.22,.26), step=.28, missing=None):
    snapshot = risk_fixture(issue, probabilities=probabilities)
    origin = snapshot['expansionTrial']
    origin['currentModel']['coefficients'][0] = -1
    source = snapshot['momentumTrial']['latest']
    curve = []
    for i,point in enumerate(source['path']):
        # A flattening slope raises the fitted risk under a negative slope coefficient.
        point['features']['slope'] *= -1
        short = round(4+i*step,12)
        long = round(short+point['features']['slope'],12)
        item = dict(date=point['featureDate'], shortYield=short, longYield=long)
        if missing and i == missing[0]:
            item[missing[1]] = None
        curve.append(item)
    origin['latest']['slope'] = source['path'][-1]['features']['slope']
    flags = ledger.pace.decisions([p['probability'] for p in source['path']])
    evidence, alerts = ledger.evaluate_decisions(curve,flags)
    latest = {k:source[k] for k in (*ledger.CLOCK_FIELDS,'refitDate','probability','available','change1m','change3m')}
    snapshot['curveLegsTrial'] = dict(spec=ledger.SPEC, latest={
        **latest, **evidence, **alerts, 'yieldPath':curve, 'lagFeatureDate':curve[0]['date'],
    })
    return snapshot


class CurveLegsReceiptTests(unittest.TestCase):
    during = datetime(2026,11,20,tzinfo=timezone.utc)
    matured = datetime(2027,12,1,tzinfo=timezone.utc)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.raw = self.root/'research/raw'
        for d in (self.raw,self.root/'data',self.root/'public/data'):
            d.mkdir(parents=True)
        for name in ledger.CODE:
            (self.root/name).write_bytes((ledger.ROOT/name).read_bytes())
        self.file = self.root/'data/curve-legs-receipts.jsonl'
        self.snapshot = self.root/'data/snapshot.json'
        self.write_labels([0])
        self.load_fixture(fixture())

    def load_fixture(self, snapshot):
        for sid,field in ledger.YIELDS.items():
            yields = snapshot['curveLegsTrial']['latest']['yieldPath']
            values = [f'{p["date"]},{p[field]}' for p in yields if p[field] is not None]
            (self.raw/f'{sid}.csv').write_text(f'observation_date,{sid}\n'+'\n'.join(values)+'\n')
        self.snapshot.write_text(json.dumps(snapshot))

    def write_labels(self, labels):
        rows = [f'{ledger.month_offset("2026-11-01",i)},{flag}' for i,flag in enumerate(labels) if flag is not None]
        (self.raw/'USREC.csv').write_text('observation_date,USREC\n'+'\n'.join(rows)+'\n')

    def capture(self, when=None):
        return ledger.update_receipts(self.root,when or self.during)

    def test_freeze_raw_rates_probabilities_and_each_decision(self):
        result = self.capture()
        row = result['latestReceipt']
        self.assertEqual((result['receiptCount'],result['maturedCount'],result['pendingCount']),(1,0,1))
        self.assertEqual(result['downloadUrl'],'/api/download?file=curvelegsreceipts')
        self.assertEqual(row['predictions'],{'conditionalRisk':.26})
        self.assertEqual(set(row['decisions']),set(ledger.POLICIES))
        self.assertFalse(row['decisions']['levelAlert'])
        for k in ('quarterAlert','shortLeadAlert','bearAlert','sustainedAlert'):
            self.assertTrue(row['decisions'][k])
        self.assertFalse(row['decisions']['mixedTwoToOneAlert'])
        self.assertEqual(row['evidence']['shortRiseCount'],3)
        for sid,digest in row['rawYieldSha256'].items():
            self.assertEqual(digest,hashlib.sha256((self.raw/f'{sid}.csv').read_bytes()).hexdigest())
        expected = [ledger.month_offset(row['issueDate'],i) for i in range(-5,-1)]
        self.assertEqual([p['date'] for p in row['yieldPath']],expected)
        self.assertEqual([p['featureDate'] for p in row['path']],expected)
        self.assertEqual(self.file.read_bytes(),(self.root/'public/data/curve-legs-receipts.jsonl').read_bytes())
        self.load_fixture(fixture(step=.12))
        self.assertEqual(self.capture()['latestReceipt'],row)
        self.load_fixture(fixture(issue='2026-12-01',step=.12))
        next_row = self.capture(datetime(2026,12,6,tzinfo=timezone.utc))['latestReceipt']
        self.assertEqual(next_row['previousHash'],row['hash'])
        self.assertTrue(next_row['decisions']['mixedTwoToOneAlert'])
        self.assertFalse(next_row['decisions']['bearAlert'])

    def test_missing_tenor_does_not_drop_eligible_endpoint_or_level_rules(self):
        for missing,expected in [
            ((1,'shortYield'),(True,True,False)), ((1,'longYield'),(True,True,True)),
            ((3,'longYield'),(False,False,False)),
        ]:
            s = fixture(missing=missing)
            self.load_fixture(s)
            row = ledger.create_receipt(s,self.root,self.during,None)
            self.assertTrue(ledger.verify_receipts([row],self.during))
            self.assertEqual(tuple(row['decisions'][k] for k in ('shortLeadAlert','bearAlert','sustainedAlert')),expected)
        self.load_fixture(fixture(probabilities=(.20,.21,.22,.32),missing=(0,'shortYield')))
        self.assertTrue(all(self.capture()['latestReceipt']['decisions'].values()))

    def test_raw_observations_guard_levels_and_reject_rehashed_corruption(self):
        row=self.capture()['latestReceipt']
        for field in ('date','slope','decision','decomposition','source','clock'):
            with self.subTest(field=field):
                r=copy.deepcopy(row)
                if field=='date':r['yieldPath'][0]['date']=r['yieldPath'][1]['date']
                if field=='slope':r['yieldPath'][1]['longYield']+=.15
                if field=='decision':r['decisions']['shortLeadAlert']=False
                if field=='decomposition':r['evidence']['flattening']+=.01
                if field=='source':r['rawYieldSha256'].pop('GS10')
                if field=='clock':r['recordedAt']=r['forecastStart']+'T00:00:00Z'
                r['hash']=ledger.receipt_hash(r)
                with self.assertRaises(ValueError):
                    ledger.verify_receipts([r],self.matured)
        s=fixture()
        # Shifting both tenors equally preserves every slope and signal. A raw-source check must still catch it.
        for p in s['curveLegsTrial']['latest']['yieldPath']:
            p['shortYield']+=1
            p['longYield']+=1
        with self.assertRaisesRegex(ValueError,'dated research source'):
            ledger.create_receipt(s,self.root,self.during,None)

    def test_stale_issue_no_backfill_and_revised_scoring_excludes_recession_origins(self):
        self.assertEqual(self.capture(self.matured)['status'],'stale-issue-no-capture')
        self.capture()
        archived = self.file.read_bytes()
        self.write_labels([0]*13)
        self.assertEqual(self.capture(datetime(2027,11,30,tzinfo=timezone.utc))['pendingCount'],1)
        quiet = self.capture(self.matured)
        self.assertAlmostEqual(quiet['metrics']['conditionalRisk']['brier'],.26**2)
        self.assertEqual(quiet['decisionMetrics']['shortLeadAlert']['newQuietAlerts'],1)
        self.write_labels([0]*12+[1])
        positive=self.capture(self.matured)
        self.assertEqual(positive['outcomes'][0]['onsetDate'],'2027-11-01')
        self.assertEqual(positive['decisionMetrics']['shortLeadAlert']['newPreOnsetAlerts'],1)
        self.write_labels([1]*13)
        self.assertEqual(self.capture(self.matured)['excludedCount'],1)
        self.write_labels([0,None]+[0]*11)
        self.assertEqual(self.capture(self.matured)['pendingCount'],1)
        self.assertEqual(self.file.read_bytes(),archived)


if __name__=='__main__':
    unittest.main()
