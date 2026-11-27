"""New weight records are exercised only in temporary repositories."""

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from build_model import metrics
from test_leading_receipts import snapshot as leading_fixture
from weight_trial import build_weight_trial
import weight_receipts as ledger


class WeightReceiptTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / 'research/raw').mkdir(parents=True)
        (self.root / 'public/data').mkdir(parents=True)
        (self.root / 'data').mkdir()
        for name in ledger.CODE:
            (self.root / name).write_bytes((ledger.ROOT / name).read_bytes())
        self.source = self.root / 'data/snapshot.json'
        self.labels = self.root / 'research/raw/USREC.csv'
        self.file = self.root / 'data/weight-receipts.jsonl'
        self.mirror = self.root / 'public/data/weight-receipts.jsonl'
        self.now = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
        self.labels.write_text('observation_date,USREC\n2026-10-01,0\n')
        s = leading_fixture()
        hist = []
        for j, date in enumerate(pd.date_range('1990-01-01', periods=100, freq='MS')):
            date = date.strftime('%Y-%m-%d')
            hist.append(
                dict(
                    date=date,
                    featureDate=ledger.month_offset(date, -2),
                    target=int(j % 7 == 0),
                    slope=-1 if j % 2 else 1,
                    credit=-0.2,
                    baselineProbability=0.2,
                    originalProbability=0.4,
                    existingBlendProbability=0.3,
                    permitsBlendProbability=0.33,
                )
            )
        s['leadingTrial']['history'] = hist
        s['weightTrial'] = build_weight_trial(s['leadingTrial'], metrics)
        self.source.write_text(json.dumps(s))

    def test_first_capture_revisions_and_maturing_outcomes(self):
        first = ledger.update_receipts(self.root, self.now)
        self.assertEqual(
            (first['receiptCount'], first['maturedCount'], first['downloadUrl']),
            (1, 0, '/api/download?file=weightreceipts'),
        )
        self.assertEqual(self.file.read_bytes(), self.mirror.read_bytes())
        row = first['latestReceipt']
        self.assertFalse(row['fit']['warmup'])
        for k, field in ledger.PREDICTIONS.items():
            self.assertAlmostEqual(
                row['predictions'][k], json.loads(self.source.read_text())['weightTrial']['latest'][field]
            )
        saved = self.file.read_bytes()
        s = json.loads(self.source.read_text())
        s['weightTrial']['latest']['probability'] = 0
        self.source.write_text(json.dumps(s))
        self.assertEqual(ledger.update_receipts(self.root, self.now)['status'], 'already-captured')
        self.labels.write_text(
            'observation_date,USREC\n'
            + ''.join(f'{ledger.month_offset(row["issueDate"],i)},{int(i==6)}\n' for i in range(1, 13))
        )
        after = ledger.update_receipts(self.root, datetime(2027, 12, 2, tzinfo=timezone.utc))
        self.assertEqual(after['maturedCount'], 1)
        self.assertAlmostEqual(
            after['metrics']['candidate']['brier'], (1 - row['predictions']['candidate']) ** 2
        )
        self.assertEqual(self.file.read_bytes(), saved)

    def test_recomputed_hash_cannot_hide_invalid_weight_dates_state_or_comparison(self):
        row = ledger.update_receipts(self.root, self.now)['latestReceipt']

        def corrupt(row, field):
            if field == 'fit':
                row['fit']['trainEnd'] = row['issueDate']
            if field == 'moment':
                row['fit']['permits']['pool']['denominator'] += 2
            if field == 'probability':
                row['predictions']['candidate'] = 0
            if field == 'state':
                row['state'] = 'stress' if row['state'] == 'normal' else 'normal'
            row['hash'] = ledger.receipt_hash(row)

        for key in ['fit', 'moment', 'probability', 'state']:
            with self.subTest(key=key):
                bad = copy.deepcopy(row)
                corrupt(bad, key)
                with self.assertRaises(ValueError):
                    ledger.verify_receipts([bad], self.now)

    def test_missing_or_stale_forecast_is_never_backfilled(self):
        s = json.loads(self.source.read_text())
        empty = copy.deepcopy(s)
        empty['weightTrial']['latest']['available'] = False
        self.source.write_text(json.dumps(empty))
        self.assertEqual(ledger.update_receipts(self.root, self.now)['receiptCount'], 0)
        self.source.write_text(json.dumps(s))
        self.assertEqual(
            ledger.update_receipts(self.root, datetime(2026, 12, 1, tzinfo=timezone.utc))['receiptCount'], 0
        )


if __name__ == '__main__':
    unittest.main()
