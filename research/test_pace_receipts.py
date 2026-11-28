"""Exercise first capture, lag reconstruction and later onset adjudication in isolated archives."""

import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import tempfile
import unittest

import pace_receipts as ledger
from test_leading_receipts import snapshot as base_snapshot


class MomentumReceiptTests(unittest.TestCase):
    issue = '2026-11-01'
    during = datetime(2026, 11, 20, tzinfo=timezone.utc)
    after = datetime(2027, 12, 1, tzinfo=timezone.utc)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'research/raw').mkdir(parents=True)
        (self.root / 'data').mkdir()
        (self.root / 'public/data').mkdir(parents=True)
        for name in ledger.CODE:
            (self.root / name).write_bytes((ledger.ROOT / name).read_bytes())
        self.snap = self.root / 'data/snapshot.json'
        self.file = self.root / 'data/momentum-receipts.jsonl'
        self.mirror = self.root / 'public/data/momentum-receipts.jsonl'
        self.raw = self.root / 'research/raw/USREC.csv'
        self.set_labels([0])
        self.publish()

    def publish(self, issue=None, probabilities=(.20, .21, .22, .26)):
        issue = issue or self.issue
        s = base_snapshot(issue)
        m = copy.deepcopy(s['leadingTrial']['currentModels']['permits'])
        m.update(trainingCutoff=ledger.month_offset(issue, -13), trainingN=120, trainingPositives=12,
                 trainingOnsets=2, trainingPrevalence=.10, coefficients=[1, 0, 0, 0], intercept=0)
        path = []
        for i, p in enumerate(probabilities):
            date = ledger.month_offset(issue, i - 3)
            fx = {k: 0. for k in ledger.COMPLETE_CASE}
            if p is None:
                # A missing complete-case control is sufficient to break the pace path.
                fx['claimsGrowth12'] = None
            else:
                raw = 2 * p - m['trainingPrevalence']
                fx['slope'] = math.log(raw / (1 - raw))
            path.append(dict(date=date, featureDate=ledger.month_offset(date, -2), features=fx, probability=p))
        original = dict(available=True, conditionalOnExpansion=True, probability=probabilities[-1],
                        **{k: s['latest'][k] for k in ledger.CLOCK_FIELDS}, **path[-1]['features'])
        latest = dict(available=True, refitDate=issue, **{k: original[k] for k in ledger.CLOCK_FIELDS},
                      path=path, probability=probabilities[-1], **ledger.decisions(probabilities))
        s['expansionTrial'] = dict(currentModel=m, latest=original)
        s['momentumTrial'] = dict(spec=ledger.SPEC, latest=latest)
        self.snap.write_text(json.dumps(s))

    def set_labels(self, labels):
        self.raw.write_text(
            'observation_date,USREC\n' +
            ''.join(f'{ledger.month_offset(self.issue,i)},{v}\n' for i, v in enumerate(labels) if v is not None)
        )

    def update(self, now=None):
        return ledger.update_receipts(self.root, now or self.during)

    def test_one_probability_three_frozen_decisions_and_revisable_outcomes(self):
        first = self.update()
        archive = self.file.read_bytes()
        row = first['latestReceipt']
        self.assertEqual((first['receiptCount'], first['maturedCount'], first['pendingCount']), (1, 0, 1))
        self.assertEqual(row['predictions'], {'conditionalRisk': .26})
        self.assertEqual(row['decisions'], dict(levelAlert=False, quarterAlert=True, monthAlert=False))
        self.assertEqual(len(row['path']), 4)
        self.assertIsNone(first['metrics']['conditionalRisk'])
        self.assertEqual(first['downloadUrl'], '/api/download?file=momentumreceipts')

        self.set_labels([0] * 13)
        result = self.update(self.after)
        quiet = result['decisionMetrics']['quarterAlert']
        self.assertEqual((quiet['n'], quiet['newQuietAlerts'], quiet['quietAlerts']), (1, 1, 1))
        self.assertEqual(result['decisionMetrics']['levelAlert']['quietAlerts'], 0)
        self.assertAlmostEqual(result['metrics']['conditionalRisk']['brier'], .26 ** 2)
        self.set_labels([0] * 12 + [1])
        last_month = self.update(datetime(2027, 11, 30, tzinfo=timezone.utc))
        self.assertEqual(last_month['outcomes'][0]['knownMonths'], 12)
        result = self.update(self.after)
        self.assertEqual(result['outcomes'][0]['onsetDate'], '2027-11-01')
        self.assertEqual(result['decisionMetrics']['quarterAlert']['newPreOnsetAlerts'], 1)
        self.assertAlmostEqual(result['metrics']['conditionalRisk']['brier'], (1 - .26) ** 2)
        self.set_labels([0, None] + [1] * 11)
        self.assertEqual(self.update(self.after)['pendingCount'], 1)
        self.set_labels([1] * 13)
        revised = self.update(self.after)
        self.assertEqual((revised['excludedCount'], revised['maturedCount'], revised['pendingCount']), (1, 0, 0))
        self.assertEqual(revised['decisionMetrics']['quarterAlert']['n'], 0)
        self.assertIsNone(revised['metrics']['conditionalRisk'])
        self.assertEqual(self.file.read_bytes(), archive)
        self.assertEqual(self.mirror.read_bytes(), archive)

    def test_missing_pace_still_captures_base_warning_and_preserves_first_monthly_issue(self):
        self.publish(probabilities=(.2, None, .27, .33))
        row = self.update()['latestReceipt']
        self.assertIs(row['pace']['paceAvailable'], False)
        self.assertEqual(row['decisions'], dict(levelAlert=True, quarterAlert=True, monthAlert=True))
        self.publish()
        self.assertEqual(self.update()['latestReceipt'], row)
        self.publish('2026-12-01')
        result = self.update(datetime(2026, 12, 18, tzinfo=timezone.utc))
        self.assertEqual(result['receiptCount'], 2)
        self.assertEqual(result['latestReceipt']['previousHash'], row['hash'])

    def test_stale_and_unavailable_forecasts_never_backfill(self):
        self.assertEqual(self.update(self.after)['status'], 'stale-issue-no-capture')
        s = json.loads(self.snap.read_text())
        s['momentumTrial']['latest']['available'] = False
        self.snap.write_text(json.dumps(s))
        result = self.update()
        self.assertEqual((result['receiptCount'], result['status']), (0, 'model-unavailable'))
        self.assertEqual(self.file.read_bytes(), b'')

    def test_rejects_rehashed_changes_to_clock_inputs_and_decisions(self):
        raw = self.update()['latestReceipt']
        for change in ('date', 'featureDate', 'input', 'path', 'gap', 'decision', 'rise', 'probability', 'clock', 'training', 'source'):
            row = copy.deepcopy(raw)
            if change == 'date':
                row['path'][0]['date'] = row['path'][1]['date']
            elif change == 'featureDate':
                row['path'][1]['featureDate'] = row['path'][0]['featureDate']
            elif change == 'input':
                row['path'][0]['features']['slope'] += .1
            elif change == 'path':
                row['path'][1]['probability'] += .02
            elif change == 'gap':
                row['path'][1]['features']['claimsGrowth12'] = None
            elif change == 'decision':
                row['decisions']['quarterAlert'] = False
            elif change == 'rise':
                row['pace']['change1m'] += .02
            elif change == 'probability':
                row['predictions']['conditionalRisk'] = 1
            elif change == 'clock':
                row['recordedAt'] = row['forecastStart'] + 'T02:00:00Z'
            elif change == 'training':
                row['model']['trainingPositives'] = 13
                row['modelHash'] = ledger.object_hash(row['model'])
            else:
                row['sources'].pop()
            row['hash'] = ledger.receipt_hash(row)
            with self.subTest(change=change), self.assertRaises(ValueError):
                ledger.verify_receipts([row], self.during)

    def test_rejects_snapshot_mismatch_with_current_expansion_probability(self):
        s = json.loads(self.snap.read_text())
        s['expansionTrial']['latest']['probability'] += .01
        self.snap.write_text(json.dumps(s))
        with self.assertRaisesRegex(ValueError, 'published conditional forecast'):
            self.update()
        self.assertEqual(self.file.read_bytes(), b'')


if __name__ == '__main__':
    unittest.main()
