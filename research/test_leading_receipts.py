"""Prospective archive tests run entirely inside temporary project directories."""

import concurrent.futures
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import tempfile
import unittest

import pandas as pd

import leading_receipts as ledger


ROOT = Path(__file__).resolve().parents[1]


def snapshot(issue='2026-11-01'):
    month = lambda n: ledger.month_offset(issue, n)
    fx = {k: 0.1 * (i + 1) for i, k in enumerate(ledger.FEATURES)}

    def model(keys):
        coefficients = [0.40 if i % 2 == 0 else -0.19 for i in range(len(keys))]
        return dict(
            featureOrder=keys,
            means=[0.0] * len(keys),
            scales=[1.0] * len(keys),
            coefficients=coefficients,
            rawCoefficients=coefficients,
            rawIntercept=-1.0,
            intercept=-1.0,
            penalty=1.0,
            refitDate=issue,
            trainedFrom='1990-01-01',
            trainedThrough=month(-13),
            lastTargetMonth=month(-1),
            trainingN=160,
        )

    models = {key: model(features) for key, features in ledger.MODEL_ORDERS.items()}
    raw = {k: ledger.model_probability(m, fx) for k, m in models.items()}
    base = 0.22
    common = dict(issueDate=issue, featureDate=month(-2), forecastStart=month(1), forecastEnd=month(12))
    original = dict(
        **common,
        features={k: fx[k] for k in ledger.BASE},
        probability=raw['original'],
        baselineProbability=base
    )
    latest = dict(
        **common,
        available=True,
        features=fx,
        originalProbability=raw['original'],
        baselineProbability=base,
        rawProbability=raw['joint']
    )
    for name, out in ledger.BLENDS.items():
        latest[ledger.PREDICTIONS[out]] = (raw[name] + base) / 2
    spec = {
        k: v
        for k, v in ledger.RECIPE.items()
        if k
        in (
            'id',
            'featureOrder',
            'penalty',
            'modelWeight',
            'priorWeight',
            'horizonMonths',
            'featureLagMonths',
            'minimumTrainingIssues',
        )
    }
    sources = [
        dict(id=sid, retrievedAt=issue + 'T00:00:00Z', lastDate=month(-1), transportStatus='fixture')
        for sid in ledger.SOURCE_IDS
    ]
    return dict(
        meta=dict(generatedAt=issue + 'T02:00:00Z'),
        sources=sources,
        model=models.pop('original'),
        latest=original,
        leadingTrial=dict(spec=spec, latest=latest, model=models['joint'], currentModels=models),
    )


class LeadingReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'research/raw').mkdir(parents=True)
        for name in ledger.CODE_PATHS:
            (self.root / name).write_bytes((ROOT / name).read_bytes())
        (self.root / 'data').mkdir()
        (self.root / 'public/data').mkdir(parents=True)
        self.snap = self.root / 'data/snapshot.json'
        self.file = self.root / 'data/leading-receipts.jsonl'
        self.mirror = self.root / 'public/data/leading-receipts.jsonl'
        self.labels = self.root / 'research/raw/USREC.csv'
        self.now = datetime(2026, 11, 20, 14, tzinfo=timezone.utc)
        self.snap.write_text(json.dumps(snapshot()))
        self.labels.write_text('observation_date,USREC\n2026-10-01,0\n')

    def run_archive(self, now=None):
        return ledger.update_receipts(self.root, now or self.now)

    def test_first_capture_reproduces_all_models_and_exact_components(self):
        result = self.run_archive()
        self.assertEqual((result['receiptCount'], result['maturedCount'], result['chainValid']), (1, 0, True))
        self.assertEqual(self.file.read_bytes(), self.mirror.read_bytes())
        self.assertEqual(self.snap.read_bytes(), (self.root / 'public/data/snapshot.json').read_bytes())
        r = result['latestReceipt']
        self.assertEqual(r['recordedAt'], self.now.isoformat())
        self.assertEqual(set(r['predictions']), set(ledger.PREDICTIONS))
        self.assertEqual(set(r['models']), set(ledger.MODEL_ORDERS))
        self.assertTrue(all(v is None for v in result['metrics'].values()))
        self.assertEqual(
            r['codeSha256']['research/leading_trial.py'],
            ledger.hashlib.sha256((self.root / 'research/leading_trial.py').read_bytes()).hexdigest(),
        )
        pending = self.file.read_bytes()
        revised = json.loads(self.snap.read_text())
        revised['latest']['probability'] = 0.6
        self.snap.write_text(json.dumps(revised))
        self.assertEqual(self.run_archive()['status'], 'already-captured')
        self.assertEqual(self.file.read_bytes(), pending)

    def test_rejects_incorrect_frozen_probabilities_source_dates_and_training(self):
        raw = self.run_archive()['latestReceipt']
        for path in [
            ('predictions', 'rawFive'),
            ('predictions', 'existingBlend'),
            ('predictions', 'permitsBlend'),
            ('predictions', 'base'),
        ]:
            row = json.loads(json.dumps(raw))
            row[path[0]][path[1]] += 0.03
            row['hash'] = ledger.receipt_hash(row)
            with self.assertRaises(ValueError):
                ledger.verify_receipts([row], self.now)
        contaminated = json.loads(json.dumps(raw))
        m = contaminated['models']['claims']
        m['trainedThrough'] = '2026-10-01'
        contaminated['modelHashes']['claims'] = ledger.object_hash(m)
        contaminated['hash'] = ledger.receipt_hash(contaminated)
        with self.assertRaises(ValueError):
            ledger.verify_receipts([contaminated], self.now)
        damaged = raw.copy()
        damaged['featureDate'] = '2026-10-01'
        damaged['hash'] = ledger.receipt_hash(damaged)
        with self.assertRaises(ValueError):
            ledger.verify_receipts([damaged], self.now)

    def test_outcomes_require_twelve_published_months_and_use_paired_scores(self):
        first = self.run_archive()['latestReceipt']
        months = pd.date_range(first['forecastStart'], first['forecastEnd'], freq='MS')
        labels = pd.Series(0, index=months, name='USREC')
        labels.iloc[-2] = 1
        labels.to_csv(self.labels, index_label='observation_date')
        immature = self.run_archive(datetime(2027, 11, 20, tzinfo=timezone.utc))
        self.assertEqual(immature['maturedCount'], 0)
        self.assertEqual(immature['outcomes'][0]['knownMonths'], 11)
        labels.drop(months[0]).to_csv(self.labels, index_label='observation_date')
        self.assertEqual(self.run_archive(datetime(2027, 12, 1, tzinfo=timezone.utc))['maturedCount'], 0)
        labels.to_csv(self.labels, index_label='observation_date')
        mature = self.run_archive(datetime(2027, 12, 1, tzinfo=timezone.utc))
        self.assertEqual(mature['maturedCount'], 1)
        for key, p in first['predictions'].items():
            m = mature['metrics'][key]
            self.assertEqual(m['n'], 1)
            self.assertAlmostEqual(m['brier'], (1 - p) ** 2)
            self.assertAlmostEqual(m['logLoss'], -math.log(p))
        self.assertEqual(mature['latestReceipt']['hash'], first['hash'])

    def test_missing_signals_do_not_backfill_and_future_dates_fail(self):
        s = snapshot()
        s['leadingTrial']['latest']['available'] = False
        self.snap.write_text(json.dumps(s))
        result = self.run_archive()
        self.assertEqual(result['status'], 'model-unavailable')
        self.assertEqual(result['receiptCount'], 0)
        self.assertEqual(json.loads(self.snap.read_text())['leadingTrial']['prospective']['receiptCount'], 0)
        self.snap.write_text(json.dumps(snapshot('2026-10-01')))
        self.assertEqual(self.run_archive()['status'], 'stale-issue-no-capture')
        self.snap.write_text(json.dumps(snapshot('2026-12-01')))
        with self.assertRaises(ValueError):
            self.run_archive()
        self.assertEqual(self.file.read_bytes(), b'')

    def test_ordered_hashes_corruption_concurrent_retries_and_prefix_repair(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            states = list(pool.map(lambda _: self.run_archive()['status'], range(3)))
        self.assertEqual(sorted(states), ['already-captured', 'already-captured', 'captured'])
        first = self.file.read_bytes()
        self.snap.write_text(json.dumps(snapshot('2026-12-01')))
        next_month = datetime(2026, 12, 4, tzinfo=timezone.utc)
        result = self.run_archive(next_month)
        self.assertEqual(result['receiptCount'], 2)
        self.assertEqual(result['receipts'][0]['hash'], result['receipts'][1]['previousHash'])
        self.mirror.write_bytes(first)
        self.assertEqual(self.run_archive(next_month)['receiptCount'], 2)
        self.assertEqual(self.file.read_bytes(), self.mirror.read_bytes())
        self.mirror.write_text('unrelated record\n')
        with self.assertRaises(ValueError):
            self.run_archive(next_month)
        self.mirror.write_bytes(self.file.read_bytes())
        data = self.file.read_text().replace('leading-indicators-prospective-v1', 'wrong', 1)
        self.file.write_text(data)
        with self.assertRaises(ValueError):
            self.run_archive(next_month)


if __name__ == '__main__':
    unittest.main()
