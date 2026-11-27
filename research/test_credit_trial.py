"""Calendar clocks, matched refits, benchmark preservation and credit-flag attribution."""

import copy
import unittest

import numpy as np
import pandas as pd

from build_model import fit_logit, metrics, run_walk_forward, score
from credit_trial import MODELS, PREDICTIONS, REQUIRED, build_credit_trial, credit_signals, issue_features
from leading_trial import build_leading_trial


class CreditTrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dates = pd.date_range('1972-01-01', '2004-10-01', freq='MS')
        i = np.arange(len(dates))
        levels = pd.Series(.5*np.sin(i/13) + .13*np.cos(i/2), index=dates)
        labels = pd.Series(((i % 81 > 43) & (i % 81 < 54)).astype(float), index=dates)
        labels.iloc[-3:] = np.nan
        future = pd.concat([labels.shift(-offset) for offset in range(1, 13)], axis=1)
        cls.source = pd.DataFrame(dict(
            NFCICREDIT=levels, PERMIT=1100+40*np.cos(i/7)+i,
            ICSA=190000+40000*np.sin(i/19), USREC=labels,
        ), index=dates)
        cls.panel = pd.DataFrame(dict(slope=np.cos(i/8), labor=.3+np.sin(i/5)*.21,
                                      credit=levels.shift(2), target=future.max(axis=1).where(future.notna().all(axis=1)),
                                      recession=labels), index=dates).dropna(subset=['credit'])
        history, _ = run_walk_forward(cls.panel)
        latest = dict(issueDate=dates[-1].strftime('%Y-%m-%d'), probability=.2, baselineProbability=.21)
        cls.leading = build_leading_trial(cls.panel, cls.source, pd.DataFrame(history), latest, fit_logit, score, metrics)
        cls.trial = cls.build()

    @classmethod
    def build(cls, panel=None, source=None, leading=None):
        return build_credit_trial(
            cls.panel if panel is None else panel, cls.source if source is None else source,
            cls.leading if leading is None else leading, fit_logit, score, metrics,
        )

    def test_observation_window_excludes_current_and_shock_references_preceding_sixty(self):
        levels = self.source.NFCICREDIT.copy()
        end = levels.index[-2]
        get = lambda d: levels.loc[d] - np.mean([levels.loc[d - pd.DateOffset(months=j)] for j in range(1, 4)])
        actual = credit_signals(levels).loc[end]
        shocks = [get(end-pd.DateOffset(months=j)) for j in range(1, 61)]
        self.assertAlmostEqual(actual.creditShock, get(end))
        self.assertAlmostEqual(actual.creditSlow, levels.loc[end]-get(end))
        self.assertAlmostEqual(actual.shockThreshold, np.quantile(shocks, .9))
        self.assertEqual(bool(actual.persistent), min(levels.loc[:end].iloc[-4:-1]) > 0)
        self.assertEqual(bool(actual.sudden), get(end) > max(0, np.quantile(shocks, .9)))
        levels.loc[end] += 20
        levels.iloc[-1] += 15
        after = credit_signals(levels).loc[end]
        self.assertEqual(after.shockThreshold, actual.shockThreshold)
        self.assertEqual(after.creditSlow, actual.creditSlow)
        self.assertAlmostEqual(after.creditShock - actual.creditShock, 20)
        self.assertEqual(after.persistent, actual.persistent)
        self.assertTrue(after.sudden)

    def test_flag_overlap_ties_and_exact_calendar_gaps(self):
        dates = pd.date_range('2000-01-01', periods=100, freq='MS')
        levels = pd.Series(2., index=dates)
        levels.iloc[-1] += .4
        vals = credit_signals(levels)
        self.assertTrue(vals.persistent.iloc[-1] and vals.sudden.iloc[-1])
        self.assertFalse(vals.sudden.iloc[-2])  # exactly equal to zero threshold
        ramp = credit_signals(pd.Series(1.0 + np.arange(len(dates))*.01, index=dates))
        self.assertAlmostEqual(ramp.creditShock.iloc[-1], ramp.shockThreshold.iloc[-1])
        self.assertFalse(ramp.sudden.iloc[-1])  # a numerically tied positive change
        gap = credit_signals(levels.drop(dates[-24])).iloc[-1]
        self.assertTrue(pd.isna(gap.shockThreshold) and pd.isna(gap.sudden))
        self.assertTrue(gap.persistent)
        self.assertAlmostEqual(gap.creditShock, .4)
        gap = credit_signals(levels.drop(dates[-3])).iloc[-1]
        self.assertTrue(all(pd.isna(gap[k]) for k in ['creditSlow', 'creditShock', 'persistent', 'sudden']))

    def test_training_and_fixed_benchmark_use_their_original_clocks(self):
        old = {r['date']: r for r in self.leading['history']}
        data = issue_features(self.panel, self.source)
        for row in self.trial['history']:
            self.assertEqual(row['benchmarkProbability'], old[row['date']]['permitsBlendProbability'])
            self.assertEqual(row['baselineProbability'], old[row['date']]['baselineProbability'])
            self.assertEqual(row['refitDate'], row['date'][:4]+'-01-01')
        for fold in [self.trial['folds'][0], self.trial['folds'][-1]]:
            train = data.loc[:fold['trainingCutoff']].dropna(subset=[*REQUIRED, 'target'])
            self.assertEqual(fold['lastTargetMonth'], (train.index.max()+pd.DateOffset(months=12)).strftime('%Y-%m-%d'))
            self.assertLess(fold['lastTargetMonth'], fold['refitDate'])
            self.assertEqual(len(train), fold['trainingN'])
            row = next(r for r in self.trial['history'] if r['refitDate'] == fold['refitDate'])
            for arm, cols in MODELS.items():
                model = fit_logit(train[cols], train.target)
                p = score(model, [[row[k] for k in cols]])[0]
                self.assertAlmostEqual(row[PREDICTIONS[arm]], (p+row['baselineProbability'])/2, places=12)
        latest = self.trial['latest']
        self.assertEqual(latest['benchmarkProbability'], self.leading['latest']['permitsBlendProbability'])
        for arm, m in self.trial['currentModels'].items():
            expected = score(m, [[latest[key] for key in MODELS[arm]]])[0]
            self.assertAlmostEqual((expected+latest['baselineProbability'])/2, latest[PREDICTIONS[arm]])
            self.assertEqual(m['refitDate'], latest['issueDate'])

    def test_truncation_preserves_earlier_features_thresholds_and_probabilities(self):
        end = pd.Timestamp('1994-10-01')
        small = copy.deepcopy(self.leading)
        small['history'] = [r for r in small['history'] if pd.Timestamp(r['date']) <= end]
        for r in small['history']:
            if pd.Timestamp(r['date']) + pd.DateOffset(months=12) >= end:
                r['target'] = None
        old_current = next(r for r in small['history'] if pd.Timestamp(r['date']) == end)
        small['latest'] = dict(old_current, issueDate='1994-10-01', forecastStart='1994-11-01', forecastEnd='1995-10-01')
        tested = self.build(self.panel.loc[:end], self.source.loc[:end], small)
        originals = {r['date']: r for r in self.trial['history']}
        for r in tested['history']:
            prev = originals[r['date']]
            for field in [*PREDICTIONS.values(), 'creditSlow', 'creditShock', 'shockThreshold']:
                self.assertAlmostEqual(r[field], prev[field], places=12)

    def test_replay_endpoint_belongs_to_published_benchmark_and_source_gaps_are_visible(self):
        end = self.trial['metrics']['rolling120']['windowEnd']
        date = pd.Timestamp(end)
        # Missing candidate issue leaves its published probability and outcome available for coverage reporting.
        result = self.build(panel=self.panel.drop(date))
        subset = result['metrics']['rolling120']
        self.assertEqual(subset['windowEnd'], end)
        self.assertEqual(subset['incumbentN'], 120)
        self.assertEqual(subset['n'], 119)
        self.assertEqual(subset['missingCandidateMonths'], 1)
        for k in ['all', 'rolling120']:
            span = result['metrics'][k]
            paired = [r for r in result['history'] if span['windowStart'] <= r['date'] <= span['windowEnd'] and r['commonMature']]
            for key, field in PREDICTIONS.items():
                e = np.mean([(r['target']-r[field])**2 for r in paired])
                self.assertAlmostEqual(e,span['models'][key]['brier'],places=13)
            self.assertEqual(result['gate'][k+'Passed'], span['models']['candidate']['brier'] < span['models']['benchmark']['brier'])

    def test_missing_inputs_and_descriptive_flag_coverage(self):
        source = self.source.copy()
        issue = pd.Timestamp(self.trial['latest']['issueDate'])
        # One missing observation in the flag reference period does not disable the risk forecast.
        gap = issue - pd.DateOffset(months=25)
        source.loc[gap, 'NFCICREDIT'] = np.nan
        result = self.build(source=source)
        self.assertTrue(result['latest']['available'])
        self.assertIsNone(result['latest']['sudden'])
        self.assertIsNone(result['latest']['shockThreshold'])
        source.loc[issue-pd.DateOffset(months=3), 'NFCICREDIT'] = np.nan
        result = self.build(source=source)
        self.assertFalse(result['latest']['available'])
        self.assertIsNone(result['latest']['probability'])
        self.assertEqual(result['latest']['benchmarkProbability'], self.leading['latest']['permitsBlendProbability'])

    def test_empty_replay_and_guard_against_different_credit_or_incomplete_targets(self):
        leading = dict(self.leading, history=[])
        result = self.build(leading=leading)
        self.assertFalse(result['gate']['passed'])
        self.assertEqual(result['metrics']['all']['n'], 0)
        broken = self.panel.copy()
        broken.loc[broken.index[-1], 'credit'] += 0.1
        with self.assertRaisesRegex(ValueError, 'benchmark input'):
            self.build(panel=broken)
        invalid = copy.deepcopy(self.leading)
        invalid['history'][-1]['target'] = 1
        with self.assertRaisesRegex(ValueError, 'incomplete benchmark outcome'):
            self.build(leading=invalid)


if __name__ == '__main__':
    unittest.main()
