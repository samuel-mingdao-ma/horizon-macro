"""Exercise actual conditional issuance in temporary roots with controlled, revisable USREC labels."""

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import expansion_receipts as ledger
from test_leading_receipts import snapshot as base_fixture


class ExpansionReceiptTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'research/raw').mkdir(parents=True)
        (self.root / 'public/data').mkdir(parents=True)
        (self.root / 'data').mkdir()
        self.raw = self.root / 'research/raw/USREC.csv'
        self.snap = self.root / 'data/snapshot.json'
        self.file = self.root / 'data/expansion-receipts.jsonl'
        self.mirror = self.root / 'public/data/expansion-receipts.jsonl'
        for name in ledger.CODE:
            (self.root / name).write_bytes((ledger.ROOT / name).read_bytes())
        self.during = datetime(2026, 11, 11, tzinfo=timezone.utc)
        self.after = datetime(2027, 12, 1, tzinfo=timezone.utc)
        self.issue = '2026-11-01'
        self.raw.write_text('observation_date,USREC\n2026-10-01,0\n')
        self.fixture(self.issue)

    def fixture(self, issue):
        s = base_fixture(issue)
        lead = s['leadingTrial']
        current = lead['latest']
        bm = lead['currentModels']['permits']
        bm['trainingCutoff'] = ledger.month_offset(issue, -13)
        model = copy.deepcopy(bm)
        model.update(
            trainingN=110,
            trainingPositives=17,
            trainingOnsets=3,
            trainingPrevalence=17 / 110,
            intercept=-1.35,
        )
        f = {k: current['features'][k] for k in ledger.FEATURES}
        p = ledger.model_probability(bm, f)
        q = ledger.model_probability(model, f)
        probs = ledger.forecasts(p, q, current['baselineProbability'], 17 / 110)
        latest = dict(
            **{k: current[k] for k in ledger.CLOCK_FIELDS},
            **f,
            available=True,
            conditionalOnExpansion=True,
            **{k: model[k] for k in ledger.TRAINING_FIELDS},
            baselineProbability=current['baselineProbability'],
            rawPermitsProbability=p,
            rawExpansionProbability=q,
            **{ledger.PREDICTIONS[k]: v for k, v in probs.items()},
        )
        s['expansionTrial'] = dict(spec=ledger.SPEC, latest=latest, currentModel=model)
        self.snap.write_text(json.dumps(s))

    def set_labels(self, values, missing=()):
        with self.raw.open('w') as f:
            f.write('observation_date,USREC\n')
            for idx, v in enumerate(values):
                if idx not in missing:
                    f.write(f'{ledger.month_offset(self.issue,idx)},{v}\n')

    def counts(self, now, expected):
        r = ledger.update_receipts(self.root, now)
        self.assertEqual(tuple(r[k] for k in ('maturedCount', 'pendingCount', 'excludedCount')), expected)
        self.assertEqual(sum(expected), r['receiptCount'])
        return r

    def test_conditional_capture_without_origin_then_pending_matured_excluded_and_revised(self):
        first = self.counts(self.during, (0, 1, 0))
        data = self.file.read_bytes()
        row = first['latestReceipt']
        self.assertEqual(first['downloadUrl'], '/api/download?file=expansionreceipts')
        self.assertEqual(self.mirror.read_bytes(), data)
        self.assertIsNone(first['outcomes'][0]['issueRecession'])
        self.assertEqual(first['outcomes'][0]['requiredMonths'], 13)
        self.assertNotIn('issueRecession', row)
        flags = [0, 0, 0, 1, 1, 0, 0, 0, 1, 1, 0, 0, 0]
        self.set_labels(flags)
        # End-of-horizon label is still the current incomplete month of the evaluation clock.
        pending = self.counts(datetime(2027, 11, 30, tzinfo=timezone.utc), (0, 1, 0))
        self.assertEqual(pending['outcomes'][0]['knownMonths'], 12)
        self.set_labels(flags, missing=[5])
        self.assertIsNone(self.counts(self.after, (0, 1, 0))['outcomes'][0]['target'])
        self.set_labels(flags, missing=[0])
        self.assertEqual(self.counts(self.after, (0, 1, 0))['outcomes'][0]['knownMonths'], 12)
        self.set_labels(flags)
        obs = self.counts(self.after, (1, 0, 0))
        self.assertEqual(obs['outcomes'][0]['onsetDate'], '2027-02-01')
        for key, p in row['predictions'].items():
            self.assertAlmostEqual(obs['metrics'][key]['brier'], (p - 1) ** 2)
        flags[0] = 1
        self.set_labels(flags)
        out = self.counts(self.after, (0, 0, 1))
        self.assertEqual(out['outcomes'][0]['status'], 'excluded')
        self.assertIsNone(out['outcomes'][0]['target'])
        self.assertTrue(all(x is None for x in out['metrics'].values()))
        self.set_labels([0] * 13)
        out = self.counts(self.after, (1, 0, 0))
        self.assertEqual(out['outcomes'][0]['target'], 0)
        self.assertIsNone(out['outcomes'][0]['onsetDate'])
        self.assertAlmostEqual(out['metrics']['candidate']['brier'], row['predictions']['candidate'] ** 2)
        self.assertEqual(self.file.read_bytes(), data)
        self.assertEqual(self.mirror.read_bytes(), data)

    def test_issued_during_recession_is_frozen_and_only_expansions_enter_scores(self):
        # Origin (revised later) will be a recession; capture does not depend on a phase diagnosis.
        self.set_labels([1] * 13 + [0])
        first = self.counts(self.during, (0, 1, 0))['latestReceipt']
        self.fixture('2026-12-01')
        second = self.counts(datetime(2026, 12, 15, tzinfo=timezone.utc), (0, 2, 0))['latestReceipt']
        self.assertEqual(second['previousHash'], first['hash'])
        self.set_labels([1, 0, 1] + [0] * 11)
        result = self.counts(datetime(2028, 1, 1, tzinfo=timezone.utc), (1, 0, 1))
        self.assertEqual(result['metrics']['benchmark']['n'], 1)
        self.assertEqual(result['outcomes'][1]['onsetDate'], '2027-01-01')

    def test_freeze_rejects_corrupt_models_counts_dates_and_forecasts(self):
        row = self.counts(self.during, (0, 1, 0))['latestReceipt']
        for change in (
            'raw',
            'positive',
            'onsets',
            'clock',
            'missing',
            'blend',
            'future',
            'base',
            'provenance',
        ):
            bad = copy.deepcopy(row)
            if change == 'raw':
                bad['models']['candidate']['intercept'] += 1
            elif change == 'positive':
                bad['expansionTraining']['trainingPositives'] += 1
            elif change == 'onsets':
                bad['expansionTraining']['trainingOnsets'] = 0
            elif change == 'clock':
                bad['models']['candidate']['trainedThrough'] = row['issueDate']
            elif change == 'missing':
                del bad['predictions']['baseOnlyChange']
            elif change == 'blend':
                bad['predictions']['signalOnlyChange'] += 0.01
            elif change == 'future':
                bad['recordedAt'] = bad['forecastStart'] + 'T00:00:00Z'
            elif change == 'base':
                bad['benchmarkBaseProbability'] += 0.01
            elif change == 'provenance':
                bad['sources'].pop()
            bad['modelHashes']['candidate'] = ledger.object_hash(bad['models']['candidate'])
            bad['hash'] = ledger.receipt_hash(bad)
            with self.subTest(change=change), self.assertRaises(ValueError):
                ledger.verify_receipts([bad], self.during)

    def test_rebuild_and_stale_issue_do_not_create_retrospective_receipts(self):
        self.assertEqual(self.counts(self.after, (0, 0, 0))['status'], 'stale-issue-no-capture')
        first = self.counts(self.during, (0, 1, 0))['latestReceipt']
        s = json.loads(self.snap.read_text())
        s['expansionTrial']['latest']['probability'] = 0.55
        self.snap.write_text(json.dumps(s))
        result = self.counts(self.during, (0, 1, 0))
        self.assertEqual(result['status'], 'already-captured')
        self.assertEqual(result['latestReceipt'], first)
        self.mirror.write_text(self.mirror.read_text() + 'incomplete')
        with self.assertRaisesRegex(ValueError, 'canonical log'):
            ledger.update_receipts(self.root, self.during)


if __name__ == '__main__':
    unittest.main()
