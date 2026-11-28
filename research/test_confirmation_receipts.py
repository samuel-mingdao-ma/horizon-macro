"""Check first capture, reproducible votes and mature-outcome scoring, using temporary ledgers."""

import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import tempfile
import unittest

import confirmation_receipts as ledger
from test_leading_receipts import snapshot as base_snapshot


def fixture(issue='2026-11-01', probabilities=(.20, .21, .22, .26), no_lag=False):
    s = base_snapshot(issue)
    model = copy.deepcopy(s['leadingTrial']['currentModels']['permits'])
    model.update(trainingCutoff=ledger.month_offset(issue, -13), trainingN=120, trainingPositives=12,
                 trainingOnsets=2, trainingPrevalence=.10, coefficients=[1, 0, 0, 0], intercept=0)
    path = []
    for i, p in enumerate(probabilities):
        date = ledger.month_offset(issue, i - 3)
        raw = 2 * p - model['trainingPrevalence']
        features = dict(slope=math.log(raw/(1-raw)), credit=i/10, labor=0., permitGrowth6=-float(i),
                        claimsGrowth12=float(i))
        if no_lag and i == 0:
            features['credit'] = None
            p = None
        path.append(dict(date=date, featureDate=ledger.month_offset(date,-2), features=features, probability=p))
    clock = {k: s['latest'][k] for k in ledger.CLOCK_FIELDS}
    s['expansionTrial'] = dict(currentModel=model, latest=dict(
        available=True, conditionalOnExpansion=True, probability=path[-1]['probability'], **clock, **path[-1]['features']))
    flags = ledger.pace.decisions([r['probability'] for r in path])
    latest = dict(available=True, refitDate=issue, **clock, probability=path[-1]['probability'], **flags)
    s['momentumTrial'] = dict(spec=ledger.pace.SPEC, latest={**latest, 'path':path})
    evidence, decisions = ledger.decision_evidence(path, flags)
    s['confirmationTrial'] = dict(spec=ledger.SPEC, latest={
        **latest, 'lagFeatureDate':path[0]['featureDate'], **evidence, **decisions,
    })
    return s


class ConfirmationReceiptTests(unittest.TestCase):
    during = datetime(2026,11,20,tzinfo=timezone.utc)
    after = datetime(2027,12,1,tzinfo=timezone.utc)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for d in ('research/raw', 'data', 'public/data'):
            (self.root / d).mkdir(parents=True)
        for p in ledger.CODE:
            (self.root / p).write_bytes((ledger.ROOT / p).read_bytes())
        self.snap = self.root / 'data/snapshot.json'
        self.file = self.root / 'data/confirmation-receipts.jsonl'
        self.mirror = self.root / 'public/data/confirmation-receipts.jsonl'
        self.labels = self.root / 'research/raw/USREC.csv'
        self.write_labels([0])
        self.snap.write_text(json.dumps(fixture()))

    def write_labels(self, labels):
        issues = [ledger.month_offset('2026-11-01',i) for i in range(len(labels))]
        self.labels.write_text('observation_date,USREC\n'+''.join(
            f'{d},{y}\n' for d,y in zip(issues,labels) if y is not None))

    def issue(self, now=None):
        return ledger.update_receipts(self.root,now or self.during)

    def test_comparable_forecasts_idempotency_and_chain(self):
        s = self.issue()
        row = s['latestReceipt']
        self.assertEqual((s['receiptCount'],s['pendingCount'],s['maturedCount']),(1,1,0))
        self.assertEqual(s['downloadUrl'],'/api/download?file=confirmationreceipts')
        self.assertEqual(row['predictions'],{'conditionalRisk':.26})
        self.assertIsNone(s['metrics']['conditionalRisk'])
        self.assertEqual(row['decisions'],dict(levelAlert=False,quarterAlert=True,pressureAlert=True,
                                                directionAlert=True,breadthAlert=True))
        self.assertEqual(row['evidence']['pressureVotes'],3)
        self.assertEqual(row['evidence']['directionVotes'],3)
        self.assertEqual(row['path'][0]['featureDate'],row['lagFeatureDate'])
        self.assertEqual(self.file.read_bytes(),self.mirror.read_bytes())
        self.assertEqual(self.snap.read_bytes(),(self.root/'public/data/snapshot.json').read_bytes())
        self.snap.write_text(json.dumps(fixture(no_lag=True)))
        self.assertEqual(self.issue()['latestReceipt'],row)
        self.assertFalse((self.root/'data/momentum-receipts.jsonl').exists())
        self.snap.write_text(json.dumps(fixture(issue='2026-12-01')))
        next_month = self.issue(datetime(2026,12,5,tzinfo=timezone.utc))
        self.assertEqual(next_month['receiptCount'],2)
        self.assertEqual(next_month['latestReceipt']['previousHash'],row['hash'])

    def test_outcomes_pending_scored_excluded_and_revised(self):
        self.issue()
        old=self.file.read_bytes()
        self.write_labels([0]*13)
        self.assertEqual(self.issue(datetime(2027,11,30,tzinfo=timezone.utc))['pendingCount'],1)
        quiet = self.issue(self.after)
        self.assertEqual((quiet['excludedCount'],quiet['maturedCount'],quiet['pendingCount']),(0,1,0))
        self.assertEqual(quiet['decisionMetrics']['pressureAlert']['newQuietAlerts'],1)
        self.assertEqual(quiet['decisionMetrics']['levelAlert']['quietAlerts'],0)
        self.assertAlmostEqual(quiet['metrics']['conditionalRisk']['brier'], .26**2)
        self.write_labels([0]*12+[1])
        onset = self.issue(self.after)
        self.assertEqual(onset['decisionMetrics']['pressureAlert']['newPreOnsetAlerts'],1)
        self.assertEqual(onset['outcomes'][0]['onsetDate'],'2027-11-01')
        self.write_labels([1]*13)
        self.assertEqual(self.issue(self.after)['excludedCount'],1)
        self.write_labels([0,None]+[0]*11)
        self.assertEqual(self.issue(self.after)['pendingCount'],1)
        self.assertEqual(self.file.read_bytes(),old)

    def test_missing_lag_keeps_level_forecast_and_stale_month_never_backfills(self):
        self.assertEqual(self.issue(self.after)['status'],'stale-issue-no-capture')
        self.snap.write_text(json.dumps(fixture(probabilities=(.20,.21,.22,.32),no_lag=True)))
        row=self.issue()['latestReceipt']
        self.assertFalse(row['pace']['paceAvailable'])
        self.assertIsNone(row['evidence']['pressureVotes'])
        self.assertIsNone(row['evidence']['directionVotes'])
        self.assertTrue(all(row['decisions'].values()))

    def test_rejects_rehashed_tampering_and_mismatched_snapshot(self):
        row = self.issue()['latestReceipt']
        for field in ('vote','decision','pace','lag','probability','clock','source'):
            r=copy.deepcopy(row)
            if field=='vote':
                r['evidence']['pressureVotes'] -= 1
            elif field=='decision':
                r['decisions']['quarterAlert'] = False
            elif field=='pace':
                r['pace']['change3m'] += .01
            elif field=='lag':
                r['path'][0]['features']['credit'] += .4
            elif field=='probability':
                r['predictions']['conditionalRisk'] += .01
            elif field=='clock':
                r['lagFeatureDate'] = r['featureDate']
            else:
                r['sources'].pop()
            r['hash']=ledger.receipt_hash(r)
            with self.subTest(field=field),self.assertRaises(ValueError):
                ledger.verify_receipts([r],self.during)
        bad=fixture(issue='2026-12-01')
        bad['confirmationTrial']['latest']['pressureAlert']=False
        self.snap.write_text(json.dumps(bad))
        with self.assertRaisesRegex(ValueError,'co-issued'):
            self.issue(datetime(2026,12,5,tzinfo=timezone.utc))
        self.assertEqual(len(self.file.read_text().splitlines()),1)


if __name__=='__main__':
    unittest.main()
