"""Check first-issue freezing, stress-only alerts, grid integrity and forward scoring."""

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import curve_stability_receipts as ledger
from forecast_ledger import month_offset
from test_curve_legs_receipts import fixture as treasury_fixture


def fixture(issue='2026-11-01', **kwargs):
    s = treasury_fixture(issue, **kwargs)
    source = s['curveLegsTrial']['latest']
    keys = (*ledger.CLOCK_FIELDS, 'refitDate', 'lagFeatureDate', 'available', 'probability',
            'shortChange', 'longChange', *ledger.CONTROL_FIELDS)
    latest = {k:source[k] for k in keys}
    results = ledger.grid_results(latest['shortChange'], latest['longChange'],
                                  latest['levelAlert'], latest['quarterAlert'])
    s['curveStabilityTrial'] = dict(spec=ledger.SPEC, latest=dict(**latest, results=results))
    return s


class CurveStabilityReceiptTests(unittest.TestCase):
    now = datetime(2026,11,21,tzinfo=timezone.utc)
    matured = datetime(2027,12,1,tzinfo=timezone.utc)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.raw = self.root/'research/raw'
        self.log = self.root/'data/curve-stability-receipts.jsonl'
        self.mirror = self.root/'public/data/curve-stability-receipts.jsonl'
        for d in (self.raw, self.log.parent, self.mirror.parent):
            d.mkdir(parents=True)
        for file in ledger.CODE:
            (self.root/file).write_bytes((ledger.ROOT/file).read_bytes())
        self.write_labels([0])
        self.install(fixture(step=.17))

    def install(self, s):
        path = s['curveLegsTrial']['latest']['yieldPath']
        for sid, field in ledger.legs.YIELDS.items():
            lines = [f'{p["date"]},{p[field]}' for p in path if p[field] is not None]
            (self.raw/f'{sid}.csv').write_text(f'observation_date,{sid}\n'+'\n'.join(lines)+'\n')
        (self.log.parent/'snapshot.json').write_text(json.dumps(s))

    def write_labels(self, labels):
        dates = [f'{month_offset("2026-11-01", i)},{v}' for i,v in enumerate(labels) if v is not None]
        (self.raw/'USREC.csv').write_text('observation_date,USREC\n'+'\n'.join(dates)+'\n')

    def capture(self, when=None):
        return ledger.update_receipts(self.root, when or self.now)

    def test_freezes_every_cell_with_same_vintage_controls_once_per_issue(self):
        summary = self.capture()
        row = summary['latestReceipt']
        parent = row['curveRecord']
        self.assertEqual((summary['receiptCount'],summary['pendingCount'],summary['maturedCount']),(1,1,0))
        self.assertEqual(summary['downloadUrl'],'/api/download?file=stabilityreceipts')
        self.assertEqual(len(row['results']),20)
        self.assertEqual(row['predictions'],{'conditionalRisk':.26})
        self.assertEqual(parent['yieldPath'][0]['date'], '2026-06-01')
        self.assertEqual(parent['yieldPath'][-1]['date'], '2026-09-01')
        self.assertTrue(parent['decisions']['mixedTwoToOneAlert'])
        old = row['results'][ledger.SPEC['originalId']]
        self.assertTrue(old['actual'] and old['possible'] and old['minus3'])
        self.assertFalse(old['guaranteed'] or old['plus3'])
        self.assertTrue(row['results'][ledger.SPEC['referenceId']]['guaranteed'])
        saved = self.log.read_bytes()
        self.assertEqual(saved,self.mirror.read_bytes())
        for sid, digest in parent['rawYieldSha256'].items():
            self.assertEqual(digest,hashlib.sha256((self.raw/f'{sid}.csv').read_bytes()).hexdigest())

        self.install(fixture(step=.18))
        self.assertEqual(self.capture()['latestReceipt'],row)
        self.assertEqual(self.log.read_bytes(),saved)
        self.install(fixture(issue='2026-12-01',step=.18))
        second = self.capture(datetime(2026,12,5,tzinfo=timezone.utc))['latestReceipt']
        self.assertEqual(second['previousHash'],row['hash'])
        self.assertFalse(second['results'][ledger.SPEC['originalId']]['actual'])
        self.assertTrue(self.log.read_bytes().startswith(saved))
        self.assertEqual(self.log.read_bytes(),self.mirror.read_bytes())

    def test_bounds_do_not_count_as_issued_warnings_under_future_outcomes(self):
        self.install(fixture(step=.18))
        self.assertEqual(self.capture(self.matured)['status'],'stale-issue-no-capture')
        row = self.capture()['latestReceipt']
        saved = self.log.read_bytes()
        key = ledger.SPEC['originalId']
        self.assertTrue(row['results'][key]['possible'])
        self.assertFalse(row['results'][key]['actual'])
        self.write_labels([0]*13)
        self.assertEqual(self.capture(datetime(2027,11,30,tzinfo=timezone.utc))['pendingCount'],1)
        result = self.capture(self.matured)
        self.assertEqual(result['decisionMetrics'][key]['newQuietAlerts'],0)
        self.assertEqual(result['decisionMetrics'][ledger.SPEC['referenceId']]['newQuietAlerts'],1)
        self.assertAlmostEqual(result['metrics']['conditionalRisk']['brier'],.26**2)
        self.write_labels([0]*12+[1])
        self.assertEqual(self.capture(self.matured)['decisionMetrics'][key]['preOnsetAlerts'],0)
        self.write_labels([1]*13)
        self.assertEqual(self.capture(self.matured)['excludedCount'],1)
        self.write_labels([0,None]+[0]*11)
        self.assertEqual(self.capture(self.matured)['pendingCount'],1)
        self.assertEqual(saved,self.log.read_bytes())

    def test_recomputed_hash_cannot_hide_tampered_results_rates_or_probabilities(self):
        row=self.capture()['latestReceipt']
        for field in ('possible','actual','lowerBp','grid','source','date','probability','code','recipe'):
            with self.subTest(field=field):
                r=copy.deepcopy(row)
                key=ledger.SPEC['referenceId']
                if field in ('possible','actual'):
                    r['results'][key][field]=not r['results'][key][field]
                elif field=='lowerBp': r['results'][key]['lowerBp']-=.01
                elif field=='grid': r['results'].pop(key)
                elif field=='source':
                    r['curveRecord']['yieldPath'][0]['shortYield']+=.01
                    r['curveRecord']['hash']=ledger.receipt_hash(r['curveRecord'])
                elif field=='date': r['recordedAt']='2026-12-01T01:00:00+00:00'
                elif field=='probability': r['predictions']={'conditionalRisk':.4}
                elif field=='code': r['codeSha256'].pop(ledger.NEW_CODE[-1])
                elif field=='recipe': r['recipe']['stressBp']=0
                r['hash']=ledger.receipt_hash(r)
                with self.assertRaises(ValueError):
                    ledger.verify_receipts([r],self.matured)

    def test_capture_checks_live_results_and_handles_missing_observations(self):
        s=fixture(step=.17)
        s['curveStabilityTrial']['latest']['results'][ledger.SPEC['referenceId']]['actual']=False
        with self.assertRaisesRegex(ValueError,'Stability issue'):
            ledger.create_receipt(s,self.root,self.now,None)
        for endpoint_risk, expected in ((.26,False),(.32,True)):
            s=fixture(probabilities=(.20,.21,.22,endpoint_risk),missing=(0,'shortYield'))
            self.install(s)
            row=ledger.create_receipt(s,self.root,self.now,None)
            self.assertTrue(ledger.verify_receipts([row],self.now))
            for cell in row['results'].values():
                self.assertIs(cell['actual'],expected)
                self.assertIs(cell['possible'],expected)
                self.assertIs(cell['guaranteed'],expected)


if __name__=='__main__':
    unittest.main()
