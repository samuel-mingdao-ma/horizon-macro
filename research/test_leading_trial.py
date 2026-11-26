"""Calendar, leakage, fixed-control and coverage checks for the two leading indicators."""

import unittest

import numpy as np
import pandas as pd

from build_model import fit_logit, run_walk_forward, score, metrics
from leading_trial import BASE, FEATURES, MODELS, PREDICTIONS, add_leading_features, build_leading_trial


class LeadingTrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dates = pd.date_range('1973-01-01', '2007-11-01', freq='MS')
        n = np.arange(len(dates))
        labels = pd.Series(((n % 64 >= 28) & (n % 64 < 33)).astype(float), index=dates)
        # Simulate a label release cutoff three months before the research issue.
        labels.iloc[-3:] = np.nan
        future = pd.concat([labels.shift(-i) for i in range(1, 13)], axis=1)
        target = future.max(axis=1).where(future.notna().all(axis=1))
        cls.panel = pd.DataFrame(
            dict(
                slope=np.sin(n / 13),
                credit=np.cos(n / 8),
                labor=0.3 + 0.2 * np.cos(n / 19),
                target=target,
                recession=labels,
            ),
            index=dates,
        )
        cls.source = pd.DataFrame(
            dict(PERMIT=600 + n + 48 * np.sin(n / 9), ICSA=230000 + 21000 * np.cos(n / 13), USREC=labels),
            index=dates,
        )
        # Missing early permit months deliberately make the joint and incumbent training samples differ.
        cls.source.loc[:'1975-02-01', 'PERMIT'] = np.nan
        history, _ = run_walk_forward(cls.panel)
        cls.official = pd.DataFrame(history).set_index('date')
        cls.latest = dict(
            issueDate=dates[-1].strftime('%Y-%m-%d'), probability=0.32, baselineProbability=0.28
        )
        cls.result = cls.build(cls.panel, cls.source, cls.official, cls.latest)

    @staticmethod
    def build(panel, source, original, latest):
        return build_leading_trial(panel, source, original, latest, fit_logit, score, metrics)

    def test_calendar_lag_three_complete_months_and_no_future_read(self):
        panel = self.panel.iloc[-5:].drop(self.panel.index[-3])
        source = self.source.copy()
        actual = add_leading_features(panel, source)
        issue = actual.index[-1]
        month = issue - pd.DateOffset(months=2)

        def three(series, end):
            return np.mean([source.at[end - pd.DateOffset(months=j), series] for j in range(3)])

        for series, key, lag in [('ICSA', 'claimsGrowth12', 12), ('PERMIT', 'permitGrowth6', 6)]:
            expected = 100 * (three(series, month) / three(series, month - pd.DateOffset(months=lag)) - 1)
            self.assertAlmostEqual(actual.at[issue, key], expected, places=11)
        before = actual.loc[issue, FEATURES].copy()
        source.loc[source.index > month, ['ICSA', 'PERMIT']] *= 20
        pd.testing.assert_series_equal(before, add_leading_features(panel, source).loc[issue, FEATURES])
        # Removing an entire calendar month cannot pull an older observation into its place.
        source = source.drop(month - pd.DateOffset(months=7))
        gaps = add_leading_features(panel, source)
        self.assertTrue(pd.isna(gaps.at[issue, 'permitGrowth6']))
        self.assertAlmostEqual(gaps.at[issue, 'claimsGrowth12'], before['claimsGrowth12'])

    def test_each_fold_fits_on_one_common_purged_training_set_and_official_base(self):
        expanded = add_leading_features(self.panel, self.source)
        folds = self.result['folds']
        fold = folds[0]
        train = expanded.loc[: fold['trainingCutoff']].dropna(subset=FEATURES + ['target'])
        self.assertEqual(len(train), fold['trainingN'])
        self.assertLess(fold['lastTargetMonth'], fold['refitDate'])
        self.assertAlmostEqual(fold['trainingPrevalence'], train.target.mean())
        row = self.result['history'][0]
        official = self.official.loc[row['date']]
        self.assertNotAlmostEqual(fold['trainingPrevalence'], official.baseline, places=5)
        self.assertAlmostEqual(
            row['existingBlendProbability'], (official.probability + official.baseline) / 2
        )
        names = dict(
            matchedThree='matchedThreeBlendProbability',
            permits='permitsBlendProbability',
            claims='claimsBlendProbability',
            joint='probability',
        )
        for key, columns in MODELS.items():
            model = fit_logit(train[columns], train.target)
            np.testing.assert_allclose(model['means'], fold['models'][key]['means'])
            predicted = score(model, [[row[c] for c in columns]])[0]
            self.assertAlmostEqual(row[names[key]], (predicted + official.baseline) / 2)
        self.assertAlmostEqual(row['probability'], (row['rawProbability'] + row['baselineProbability']) / 2)
        self.assertAlmostEqual(self.result['latest']['existingBlendProbability'], 0.30)
        current = self.result['latest']
        for key, columns in MODELS.items():
            params = self.result['currentModels'][key]
            raw = score(params, [[current['features'][c] for c in columns]])[0]
            self.assertAlmostEqual(current[names[key]], (raw + self.latest['baselineProbability']) / 2)

    def test_future_labels_and_features_do_not_enter_older_predictions(self):
        # Chronological truncation leaves the 1991 replay forecasts/references exactly as issued.
        cutoff = '1992-01-01'
        truncated = self.build(
            self.panel.loc[:cutoff],
            self.source.loc[:cutoff],
            self.official,
            dict(self.latest, issueDate=cutoff),
        )
        current = {r['date']: r for r in self.result['history']}
        for row in truncated['history']:
            parent = current[row['date']]
            for key in (*PREDICTIONS.values(), *FEATURES):
                self.assertAlmostEqual(row[key], parent[key], places=12)
        self.assertTrue(any(r['target'] is None for r in truncated['history']))

    def test_anchored_window_pending_labels_and_missing_candidate(self):
        recent = self.result['metrics']['rolling120']
        self.assertEqual(recent['n'], 120)
        latest_mature = pd.Timestamp(recent['windowEnd'])
        depleted = self.source.copy()
        depleted.loc[latest_mature - pd.DateOffset(months=2), 'PERMIT'] = np.nan
        changed = self.build(self.panel, depleted, self.official, self.latest)
        subset = changed['metrics']['rolling120']
        self.assertEqual(
            (subset['windowStart'], subset['windowEnd']), (recent['windowStart'], recent['windowEnd'])
        )
        self.assertEqual(subset['incumbentN'], 120)
        self.assertLess(subset['n'], 120)
        self.assertEqual(subset['n'] + subset['missingCandidateMonths'], 120)
        pending = [r for r in changed['history'] if r['date'] > subset['windowEnd']]
        self.assertTrue(pending)
        self.assertTrue(all(r['target'] is None and not r['commonMature'] for r in pending))
        for span in changed['metrics'].values():
            grouped = [
                r
                for r in changed['history']
                if span['windowStart'] <= r['date'] <= span['windowEnd'] and r['commonMature']
            ]
            self.assertEqual(len(grouped), span['n'])
            for key, col in PREDICTIONS.items():
                self.assertAlmostEqual(
                    span['models'][key]['brier'], np.mean([(r[col] - r['target']) ** 2 for r in grouped])
                )

    def test_missing_trial_issue_preserves_mature_incumbent_anchor(self):
        expected = self.result['metrics']['rolling120']
        missing_date = pd.Timestamp(expected['windowEnd'])
        changed = self.build(self.panel.drop(missing_date), self.source, self.official, self.latest)
        actual = changed['metrics']['rolling120']
        self.assertEqual(actual['windowEnd'], expected['windowEnd'])
        self.assertEqual(actual['incumbentN'], expected['incumbentN'])
        self.assertEqual(actual['n'], expected['n'] - 1)

    def test_current_forecast_is_not_backdated_or_imputed_when_a_signal_is_late(self):
        month = pd.Timestamp(self.latest['issueDate']) - pd.DateOffset(months=2)
        broken = self.source.copy()
        broken.loc[month, 'ICSA'] = np.nan
        result = self.build(self.panel, broken, self.official, self.latest)
        now = result['latest']
        self.assertEqual(now['issueDate'], self.latest['issueDate'])
        self.assertFalse(now['available'])
        self.assertIsNone(now['probability'])
        self.assertIsNone(now['features']['claimsGrowth12'])
        self.assertAlmostEqual(now['existingBlendProbability'], 0.30)
        self.assertIn('claimsGrowth12', now['reason'])

    def test_unpublished_or_missing_labels_remain_pending_in_every_comparison(self):
        source = self.source.copy()
        missing = pd.Timestamp('2001-04-01')
        source.loc[missing, 'USREC'] = np.nan
        result = self.build(self.panel, source, self.official, self.latest)
        affected = [
            r
            for r in result['history']
            if missing - pd.DateOffset(months=12) <= pd.Timestamp(r['date']) < missing
        ]
        self.assertEqual(len(affected), 12)
        self.assertTrue(all(r['target'] is None and not r['commonMature'] for r in affected))

    def test_gate_requires_lower_brier_in_both_windows_and_null_when_data_absent(self):
        for tag, key in [('all', 'allPassed'), ('rolling120', 'rolling120Passed')]:
            models = self.result['metrics'][tag]['models']
            self.assertEqual(
                self.result['gate'][key], models['candidate']['brier'] < models['existingBlend']['brier']
            )
        self.assertEqual(
            self.result['gate']['passed'],
            self.result['gate']['allPassed'] and self.result['gate']['rolling120Passed'],
        )
        result = self.build(self.panel, self.source.drop(columns=['ICSA']), self.official, self.latest)
        self.assertFalse(result['gate']['passed'])
        self.assertFalse(result['latest']['available'])
        self.assertIsNone(result['model'])
        self.assertIsNone(result['metrics']['all']['models']['candidate']['brier'])
        self.assertEqual(result['metrics']['rolling120']['incumbentN'], 120)


if __name__ == '__main__':
    unittest.main()
