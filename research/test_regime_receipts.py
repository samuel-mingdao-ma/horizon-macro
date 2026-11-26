"""Temporary synthetic fixtures only: no shared forecasts or existing ledgers are written."""

import concurrent.futures
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
import regime_receipts as ledger

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    model = dict(
        featureOrder=['slope', 'credit', 'labor'],
        means=[0.0, 0.0, 0.0],
        scales=[1.0, 1.0, 1.0],
        coefficients=[-0.3, 0.4, 0.1],
        intercept=-1.0,
        rawCoefficients=[-0.3, 0.4, 0.1],
        rawIntercept=-1.0,
        penalty=1.0,
        trainingN=200,
        trainedFrom='2000-01-01',
        trainedThrough='2025-10-01',
        lastTargetMonth='2026-10-01',
        refitDate='2026-11-01',
    )
    features = dict(slope=1.0, credit=-0.1, labor=0.2)
    p = ledger.model_probability(model, features)
    cells = []
    for (state, flags), n, k in zip(ledger.STATES.items(), [90, 30, 40, 20], [1, 6, 4, 7]):
        cells.append(
            dict(
                id=state,
                creditTight=flags[0],
                laborElevated=flags[1],
                n=n,
                positiveWindows=k,
                rawRate=k / n,
                pooledRate=0.1,
                priorProbability=(k + 24 * 0.1) / (n + 24),
                selected=state == 'loose-low',
            )
        )
    prior = cells[0]['priorProbability']
    alpha = 0.25
    adaptive = (1 - alpha) * 0.1 + alpha * prior
    fit = dict(
        refitDate='2026-11-01',
        trainingCutoff='2025-10-01',
        trainingN=100,
        trainStart='2005-01-01',
        trainEnd='2025-10-01',
        lastTargetMonth='2026-10-01',
        weight=alpha,
        unconstrainedWeight=alpha,
        numerator=1.0,
        denominator=4.0,
        status='fit',
        minimumTrainingN=60,
    )
    latest = dict(
        issueDate='2026-11-01',
        featureDate='2026-09-01',
        forecastStart='2026-12-01',
        forecastEnd='2027-11-01',
        features=features,
        originalProbability=p,
        baselineProbability=0.2,
        fixedBlendProbability=0.5 * (p + 0.2),
        recentPriorProbability=0.1,
        recentBlendProbability=0.5 * (p + 0.1),
        dynamicPriorProbability=prior,
        probability=0.5 * (p + prior),
        state='loose-low',
        stateInputs={'credit': -0.1, 'labor': 0.2},
        trainingCutoff='2025-10-01',
        windowStart='2010-11-01',
        windowEnd='2025-10-01',
        trainingN=180,
        stateMap=cells,
        adaptivePriorProbability=adaptive,
        adaptiveProbability=0.5 * (p + adaptive),
        regimeWeight=alpha,
        weightTrainingN=100,
        weightTrainingCutoff='2025-10-01',
        weightFit=fit,
    )
    spec = dict(
        id='regime-prior-180-24-fixed50-v1',
        pseudoMonths=24,
        windowMonths=180,
        minimumObserved=120,
        creditThreshold=0,
        laborThreshold=0.5,
        statePrecisionDecimals=10,
        rawWeight=0.5,
        priorWeight=0.5,
        adaptiveMinimumTrainingN=60,
        adaptiveDesignId='regime-reliability-prequential-v1',
    )
    return dict(
        meta=dict(generatedAt='2026-11-25T10:00:00Z'),
        model=model,
        latest=dict(
            issueDate='2026-11-01',
            featureDate='2026-09-01',
            probability=p,
            baselineProbability=0.2,
            features=features,
        ),
        sources=[dict(id='USREC', lastDate='2026-10-01', retrievedAt='2026-11-25T10:00:00Z')],
        regimePrior=dict(spec=spec, latest=latest),
    )


class RegimeReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='horizon-regime-receipt-')
        self.root = Path(self.temp.name)
        for folder in ['data', 'public/data', 'research/raw']:
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        for filename in ['build_model.py', 'regime_prior.py', 'regime_receipts.py', 'forecast_ledger.py']:
            source = ROOT / 'research' / filename
            if source.exists():
                shutil.copy2(source, self.root / 'research' / filename)
            else:
                (self.root / 'research' / filename).write_text('# synthetic fingerprint fixture\n')
        pd.DataFrame({'USREC': [0] * 10}, index=pd.date_range('2026-01-01', periods=10, freq='MS')).to_csv(
            self.root / 'research/raw/USREC.csv', index_label='observation_date'
        )
        self.data = fixture()
        self.now = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
        self.save(self.data)
        self.old_paths = [
            'data/forecast-ledger.jsonl',
            'public/data/forecast-ledger.jsonl',
            'data/rate-path-receipts.jsonl',
            'public/data/rate-path-receipts.jsonl',
            'research/prospective-protocol.json',
        ]
        for name in self.old_paths:
            (self.root / name).write_bytes(b'unchanged earlier trial\n')

    def tearDown(self):
        self.temp.cleanup()

    def save(self, value):
        (self.root / 'data/snapshot.json').write_text(json.dumps(value))

    def stored(self):
        return (self.root / 'data/regime-receipts.jsonl').read_bytes()

    def test_first_capture_freezes_primary_and_secondary_with_current_incumbent(self):
        result = ledger.update_receipts(self.root, self.now)
        row = result['latestReceipt']
        self.assertEqual(result['receiptCount'], 1)
        self.assertEqual(result['maturedCount'], 0)
        self.assertTrue(result['chainValid'])
        self.assertEqual(row['recordedAt'], self.now.isoformat())
        self.assertEqual(set(row['predictions']), set(ledger.PREDICTIONS))
        self.assertAlmostEqual(row['predictions']['fixedBlend'], 0.5 * (row['predictions']['original'] + 0.2))
        self.assertTrue(all(value is None for value in result['metrics'].values()))
        for name in self.old_paths:
            self.assertEqual((self.root / name).read_bytes(), b'unchanged earlier trial\n')

    def test_same_issue_revised_forecast_never_rewrites_frozen_record(self):
        ledger.update_receipts(self.root, self.now)
        before = self.stored()
        changed = copy.deepcopy(self.data)
        changed['regimePrior']['latest']['probability'] = 0.99
        self.save(changed)
        result = ledger.update_receipts(self.root, self.now.replace(day=26))
        self.assertEqual(before, self.stored())
        self.assertFalse(result['appendedThisRun'])

    def test_future_issue_and_historical_backfill_are_not_captured(self):
        future = copy.deepcopy(self.data)
        future['regimePrior']['latest']['issueDate'] = '2026-12-01'
        self.save(future)
        with self.assertRaisesRegex(ValueError, 'future'):
            ledger.update_receipts(self.root, self.now)
        self.assertFalse((self.root / 'data/regime-receipts.jsonl').exists())
        self.save(self.data)
        result = ledger.update_receipts(self.root, datetime(2026, 12, 5, tzinfo=timezone.utc))
        self.assertEqual(result['receiptCount'], 0)
        self.assertEqual(result['status'], 'stale-issue-no-capture')

    def test_comparison_dates_cutoff_and_adaptive_future_outcomes_are_guarded(self):
        for key, value, phrase in [
            ('featureDate', '2026-08-01', 'same issue'),
            ('windowEnd', '2025-11-01', '180-month'),
        ]:
            with self.subTest(key=key):
                changed = copy.deepcopy(self.data)
                changed['regimePrior']['latest'][key] = value
                self.save(changed)
                with self.assertRaisesRegex(ValueError, phrase):
                    ledger.update_receipts(self.root, self.now)
        changed = copy.deepcopy(self.data)
        changed['regimePrior']['latest']['weightFit']['trainEnd'] = '2025-11-01'
        self.save(changed)
        with self.assertRaisesRegex(ValueError, 'overlap'):
            ledger.update_receipts(self.root, self.now)

    def test_low_data_adaptive_fit_falls_back_to_zero_weight(self):
        changed = copy.deepcopy(self.data)
        latest = changed['regimePrior']['latest']
        latest.update(
            regimeWeight=0.0,
            weightTrainingN=20,
            adaptivePriorProbability=0.1,
            adaptiveProbability=latest['recentBlendProbability'],
        )
        latest['weightFit'].update(trainingN=20, weight=0.0, status='insufficient-history')
        self.save(changed)
        row = ledger.update_receipts(self.root, self.now)['latestReceipt']
        self.assertEqual(row['predictions']['adaptive'], row['predictions']['recentBlend'])

    def test_tamper_and_divergent_public_mirror_fail_closed(self):
        result = ledger.update_receipts(self.root, self.now)
        changed = copy.deepcopy(result['receipts'])
        changed[0]['predictions']['candidate'] += 0.01
        with self.assertRaisesRegex(ValueError, 'hash chain'):
            ledger.verify_receipts(changed, self.now)
        (self.root / 'public/data/regime-receipts.jsonl').write_text('divergent\n')
        with self.assertRaisesRegex(ValueError, 'diverges'):
            ledger.update_receipts(self.root, self.now)

    def test_append_then_failed_mirror_write_retries_without_duplicate_capture(self):
        real = ledger.stage_write

        def interrupt(path, text):
            if path.name == 'regime-receipts.jsonl':
                raise OSError('synthetic interruption after durable append')
            return real(path, text)

        with patch.object(ledger, 'stage_write', side_effect=interrupt):
            with self.assertRaises(OSError):
                ledger.update_receipts(self.root, self.now)
        before = self.stored()
        self.assertEqual(len(before.splitlines()), 1)
        result = ledger.update_receipts(self.root, self.now)
        self.assertEqual(result['receiptCount'], 1)
        self.assertFalse(result['appendedThisRun'])
        self.assertEqual(before, self.stored())
        self.assertEqual(before, (self.root / 'public/data/regime-receipts.jsonl').read_bytes())

    def test_only_twelve_published_outcomes_mature_and_pairing_uses_identical_rows(self):
        first = ledger.update_receipts(self.root, self.now)
        before = self.stored()
        receipt = first['latestReceipt']
        months = pd.date_range(receipt['forecastStart'], receipt['forecastEnd'], freq='MS')
        later = datetime(2028, 1, 15, tzinfo=timezone.utc)
        pending = ledger.evaluate_outcomes(first['receipts'], pd.Series([0] * 11, index=months[:11]), later)
        self.assertIsNone(pending[0]['target'])
        outcomes = ledger.evaluate_outcomes(first['receipts'], pd.Series([0] * 12, index=months), later)
        result = ledger.summarize(first['receipts'], outcomes, later, False, 'already-captured')
        self.assertEqual(result['maturedCount'], 1)
        for name in ledger.PREDICTIONS:
            self.assertEqual(result['metrics'][name]['n'], 1)
        self.assertAlmostEqual(
            result['pairedComparisons']['candidateVsFixedBlend']['brierDifference'],
            receipt['predictions']['candidate'] ** 2 - receipt['predictions']['fixedBlend'] ** 2,
        )
        early = ledger.evaluate_outcomes(first['receipts'], pd.Series([0] * 12, index=months), self.now)
        self.assertEqual(early[0]['knownMonths'], 0)
        self.assertEqual(before, self.stored())

    def test_incomplete_new_forecast_preserves_and_updates_existing_outcomes(self):
        first = ledger.update_receipts(self.root, self.now)
        before = self.stored()
        receipt = first['latestReceipt']
        months = pd.date_range(receipt['forecastStart'], receipt['forecastEnd'], freq='MS')
        pd.DataFrame({'USREC': [0] * 12}, index=months).to_csv(
            self.root / 'research/raw/USREC.csv', index_label='observation_date'
        )
        changed = copy.deepcopy(self.data)
        changed['regimePrior']['latest']['adaptiveProbability'] = None
        self.save(changed)
        result = ledger.update_receipts(self.root, datetime(2028, 1, 15, tzinfo=timezone.utc))
        self.assertEqual(result['maturedCount'], 1)
        self.assertEqual(result['receiptCount'], 1)
        self.assertEqual(before, self.stored())
        self.assertEqual(
            json.loads((self.root / 'data/snapshot.json').read_text())['regimePrior']['prospective'][
                'maturedCount'
            ],
            1,
        )

    def test_concurrent_same_issue_refresh_has_exactly_one_capture(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: ledger.update_receipts(self.root, self.now), range(2)))
        self.assertEqual(sum(row['appendedThisRun'] for row in results), 1)
        self.assertEqual(len(self.stored().splitlines()), 1)

    def test_absent_legacy_experiment_does_not_create_a_trial(self):
        legacy = copy.deepcopy(self.data)
        del legacy['regimePrior']
        self.save(legacy)
        before = (self.root / 'data/snapshot.json').read_bytes()
        result = ledger.update_receipts(self.root, self.now)
        self.assertEqual(result['receiptCount'], 0)
        self.assertEqual(before, (self.root / 'data/snapshot.json').read_bytes())
        self.assertFalse((self.root / 'data/regime-receipts.jsonl').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
