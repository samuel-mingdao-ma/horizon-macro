"""Use a temporary synthetic repository for all issuance, tampering and maturity checks."""

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import credit_receipts as ledger
from credit_trial import credit_signals
from test_leading_receipts import snapshot as leading_fixture


class CreditReceiptTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'research/raw').mkdir(parents=True)
        (self.root / 'public/data').mkdir(parents=True)
        (self.root / 'data').mkdir()
        for name in ledger.CODE:
            (self.root / name).write_bytes((ledger.ROOT / name).read_bytes())
        self.file = self.root / 'data/credit-receipts.jsonl'
        self.mirror = self.root / 'public/data/credit-receipts.jsonl'
        self.labels = self.root / 'research/raw/USREC.csv'
        self.labels.write_text('observation_date,USREC\n2026-10-01,0\n')
        self.now = datetime(2026, 11, 10, tzinfo=timezone.utc)
        self.snapshot = self.root / 'data/snapshot.json'
        self.fixture()

    def fixture(self, *, gap=False):
        s = leading_fixture()
        lead = s['leadingTrial']
        current = lead['latest']
        feature_date = current['featureDate']
        periods = pd.date_range(end=feature_date, periods=64, freq='MS')
        levels = pd.Series([(i % 7 - 0.5) / 20 for i in range(64)], index=periods)
        levels.iloc[-4:] = [0.30, 0.32, 0.31, 0.9]
        if gap:
            levels.iloc[-40] = float('nan')
        weekly = pd.date_range(periods[0], periods[-1] + pd.offsets.MonthEnd(), freq='W-FRI')
        vals = levels.reindex(weekly.to_period('M').to_timestamp()).values
        pd.Series(vals, index=weekly, name='NFCICREDIT').to_csv(
            self.root / 'research/raw/NFCICREDIT.csv', index_label='observation_date'
        )
        signals = credit_signals(levels).iloc[-1]
        current['features']['credit'] = float(levels.iloc[-1])
        latest = {k: current[k] for k in ledger.CLOCK_FIELDS}
        latest.update(
            available=True,
            baselineProbability=current['baselineProbability'],
            **{k: current['features'][k] for k in ledger.MODEL_ORDERS['benchmark']},
        )
        for k in signals.index:
            value = signals[k]
            latest[k] = (
                None if pd.isna(value) else bool(value) if k in ['sudden', 'persistent'] else float(value)
            )
        benchmark = lead['currentModels']['permits']
        benchmark['trainingCutoff'] = benchmark['trainedThrough']
        models = {}
        for key, order in ledger.MODEL_ORDERS.items():
            m = copy.deepcopy(benchmark)
            m['featureOrder'] = order
            for a, n in [('means', 0), ('scales', 1), ('coefficients', 0.25)]:
                if key != 'benchmark':
                    m[a] = [n] * len(order)
            p = (ledger.model_probability(m, latest) + current['baselineProbability']) / 2
            latest[ledger.PREDICTIONS[key]] = p
            if key == 'benchmark':
                current['permitsBlendProbability'] = p
            else:
                models[key] = m
        s['creditTrial'] = dict(spec=ledger.SPEC, latest=latest, currentModels=models)
        self.snapshot.write_text(json.dumps(s))

    def test_first_capture_revision_and_maturity(self):
        report = ledger.update_receipts(self.root, self.now)
        receipt = report['latestReceipt']
        self.assertEqual(
            (report['receiptCount'], report['maturedCount'], report['downloadUrl']),
            (1, 0, '/api/download?file=creditreceipts'),
        )
        records = self.file.read_bytes()
        self.assertEqual(records, self.mirror.read_bytes())
        proof = receipt['creditEvidence']['monthlyLevels']
        self.assertEqual(len(proof), 64)
        self.assertEqual(proof[-1][0], receipt['featureDate'])
        self.assertEqual(receipt['regime']['sudden'], True)
        self.assertEqual(receipt['regime']['persistent'], True)
        self.assertEqual(set(receipt['predictions']), set(ledger.PREDICTIONS))
        s = json.loads(self.snapshot.read_text())
        s['creditTrial']['latest']['probability'] = 0
        self.snapshot.write_text(json.dumps(s))
        self.assertEqual(ledger.update_receipts(self.root, self.now)['status'], 'already-captured')
        self.labels.write_text(
            'observation_date,USREC\n'
            + ''.join(f'{ledger.month_offset(receipt["issueDate"], i)},{int(i == 5)}\n' for i in range(1, 13))
        )
        mature = ledger.update_receipts(self.root, datetime(2027, 12, 1, tzinfo=timezone.utc))
        self.assertEqual(mature['maturedCount'], 1)
        for key, p in receipt['predictions'].items():
            self.assertAlmostEqual(mature['metrics'][key]['brier'], (1 - p) ** 2)
        self.assertEqual(self.file.read_bytes(), records)

    def test_calculation_and_clock_tampering_fail_even_with_recomputed_hash(self):
        row = ledger.update_receipts(self.root, self.now)['latestReceipt']
        for key in ['date', 'levels', 'flag', 'quantile', 'training', 'benchmark', 'source']:
            with self.subTest(key=key):
                bad = copy.deepcopy(row)
                if key == 'date':
                    bad['creditEvidence']['monthlyLevels'][0][0] = bad['featureDate']
                elif key == 'levels':
                    bad['creditEvidence']['monthlyLevels'][-2][1] += 1
                elif key == 'flag':
                    bad['regime']['persistent'] = False
                elif key == 'quantile':
                    bad['regime']['shockThreshold'] = 3
                elif key == 'training':
                    model = bad['models']['candidate']
                    model['trainedThrough'] = bad['issueDate']
                    bad['modelHashes']['candidate'] = ledger.object_hash(model)
                elif key == 'benchmark':
                    bad['predictions']['benchmark'] = 0
                else:
                    bad['sources'].pop()
                bad['hash'] = ledger.receipt_hash(bad)
                with self.assertRaises(ValueError):
                    ledger.verify_receipts([bad], self.now)

    def test_missing_historical_month_allows_forecast_but_never_invents_sudden_flag(self):
        self.fixture(gap=True)
        row = ledger.update_receipts(self.root, self.now)['latestReceipt']
        self.assertTrue(row['regime']['persistent'])
        self.assertIsNone(row['regime']['sudden'])
        self.assertIsNone(row['regime']['shockThreshold'])
        self.assertTrue(any(v is None for _, v in row['creditEvidence']['monthlyLevels']))

    def test_stale_and_unavailable_issues_are_never_backfilled(self):
        stale = ledger.update_receipts(self.root, datetime(2026, 12, 1, tzinfo=timezone.utc))
        self.assertEqual((stale['status'], stale['receiptCount']), ('stale-issue-no-capture', 0))
        s = json.loads(self.snapshot.read_text())
        s['creditTrial']['latest']['available'] = False
        self.snapshot.write_text(json.dumps(s))
        self.assertEqual(ledger.update_receipts(self.root, self.now)['status'], 'model-unavailable')
        self.assertEqual(self.file.read_bytes(), b'')


if __name__ == '__main__':
    unittest.main()
