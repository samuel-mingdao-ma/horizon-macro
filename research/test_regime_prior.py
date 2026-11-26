"""Numerical, time-boundary and missingness tests; retained data only, no writes."""

import importlib.util
from io import StringIO
import json
from pathlib import Path
import unittest
import numpy as np
import pandas as pd
from regime_prior import (
    BASE_FEATURES,
    PREDICTIONS,
    build_regime_prior,
    fit_state_prior,
    fit_reliability,
    regime_history_csv,
    state_for_inputs,
)

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('regime_test_engine', ROOT / 'research' / 'build_model.py')
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


class RegimePriorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = pd.read_csv(ROOT / 'public' / 'data' / 'panel.csv', index_col=0, parse_dates=True)
        cls.history = pd.read_csv(ROOT / 'public' / 'data' / 'predictions.csv', index_col=0, parse_dates=True)
        cls.latest = json.loads((ROOT / 'data' / 'snapshot.json').read_text())['latest']
        cls.result = build_regime_prior(cls.panel, cls.history, cls.latest, engine.metrics)

    def test_state_thresholds_use_documented_decimal_canonicalization(self):
        self.assertEqual(state_for_inputs(0.0, 0.499), 'loose-low')
        self.assertEqual(state_for_inputs(0.0, 0.50), 'loose-elevated')
        self.assertEqual(state_for_inputs(0.001, 0.0), 'tight-low')
        self.assertEqual(state_for_inputs(0.001, 0.50), 'tight-elevated')
        self.assertEqual(state_for_inputs(-0.01, 0.499999999999999), 'loose-elevated')
        self.assertEqual(state_for_inputs(1e-12, 0.0), 'loose-low')
        self.assertIsNone(state_for_inputs(np.nan, 0.5))
        self.assertIsNone(state_for_inputs(0.0, np.inf))

    def test_sparse_and_empty_states_shrink_to_same_window_pool(self):
        dates = pd.date_range('2000-01-01', periods=180, freq='MS')
        panel = pd.DataFrame({'slope': 1.0, 'credit': -0.1, 'labor': 0.1, 'target': 0.0}, index=dates)
        panel.loc[dates[::3], 'target'] = 1.0
        panel.loc[dates[0], ['credit', 'labor']] = [1.0, 1.0]
        prior = fit_state_prior(panel, '2014-12-01')
        self.assertTrue(prior['available'])
        self.assertEqual(sum(cell['n'] for cell in prior['stateMap']), 180)
        self.assertEqual(sum(cell['positiveWindows'] for cell in prior['stateMap']), 60)
        for cell in prior['stateMap']:
            self.assertAlmostEqual(
                cell['priorProbability'], (cell['positiveWindows'] + 24 * (60 / 180)) / (cell['n'] + 24)
            )
            if not cell['n']:
                self.assertIsNone(cell['rawRate'])
                self.assertEqual(cell['priorProbability'], prior['recentPriorProbability'])

    def test_window_is_180_calendar_months_not_latest_observations(self):
        dates = pd.date_range('2000-01-01', periods=181, freq='MS')
        panel = pd.DataFrame({'slope': 1.0, 'credit': -0.1, 'labor': 0.0, 'target': 0.0}, index=dates)
        panel.loc['2015-01-01', 'target'] = 1.0
        panel.loc[dates[160:180], 'target'] = np.nan
        prior = fit_state_prior(panel, '2014-12-01')
        self.assertEqual(prior['windowStart'], '2000-01-01')
        self.assertEqual(prior['windowEnd'], '2014-12-01')
        self.assertEqual(prior['trainingN'], 160)
        self.assertEqual(prior['recentPriorProbability'], 0.0)
        self.assertEqual(prior['observedEnd'], '2013-04-01')
        self.assertIsNone(fit_state_prior(panel.iloc[1:], '2014-12-01')['recentPriorProbability'])
        panel.loc[dates[:61], 'slope'] = np.nan
        self.assertFalse(fit_state_prior(panel, '2014-12-01')['available'])

    def test_january_cutoffs_state_counts_and_current_recipe_are_exact(self):
        for fold in self.result['folds']:
            refit = pd.Timestamp(fold['refitDate'])
            cutoff = refit - pd.DateOffset(months=13)
            self.assertEqual(pd.Timestamp(fold['windowEnd']), cutoff)
            self.assertEqual(pd.Timestamp(fold['windowStart']), cutoff - pd.DateOffset(months=179))
            self.assertLess(pd.Timestamp(fold['observedEnd']) + pd.DateOffset(months=12), refit)
            expected = fit_state_prior(self.panel, cutoff)
            self.assertEqual(fold['trainingN'], expected['trainingN'])
            self.assertEqual(fold['stateMap'], expected['stateMap'])
        latest = self.result['latest']
        chosen = next(cell for cell in latest['stateMap'] if cell['selected'])
        self.assertEqual(chosen['id'], latest['state'])
        self.assertEqual(latest['dynamicPriorProbability'], chosen['priorProbability'])
        self.assertEqual(
            latest['probability'],
            0.5 * latest['originalProbability'] + 0.5 * latest['dynamicPriorProbability'],
        )
        self.assertEqual(sum(cell['n'] for cell in latest['stateMap']), latest['trainingN'])
        self.assertEqual(
            pd.Timestamp(latest['windowEnd']), pd.Timestamp(latest['issueDate']) - pd.DateOffset(months=13)
        )
        for row in self.result['history']:
            self.assertEqual(
                row['featureDate'], engine.iso(pd.Timestamp(row['date']) - pd.DateOffset(months=2))
            )

    def test_labels_or_features_after_cutoff_cannot_change_that_prior(self):
        cutoff = pd.Timestamp(self.result['folds'][10]['trainingCutoff'])
        original = fit_state_prior(self.panel, cutoff)
        changed = self.panel.copy()
        changed.loc[changed.index > cutoff, 'target'] = 1.0
        changed.loc[changed.index > cutoff, ['credit', 'labor']] = [8.0, 8.0]
        self.assertEqual(fit_state_prior(changed, cutoff), original)

    def test_missing_candidate_does_not_move_true_120_month_endpoint(self):
        last = pd.Timestamp(self.result['coverage']['latestMatureIncumbentIssue'])
        changed = self.panel.copy()
        changed.loc[last, 'credit'] = np.nan
        result = build_regime_prior(changed, self.history, self.latest, engine.metrics)
        rolling = result['metrics']['rolling120']
        self.assertEqual(rolling['windowEnd'], engine.iso(last))
        self.assertEqual(rolling['windowStart'], engine.iso(last - pd.DateOffset(months=119)))
        self.assertEqual(rolling['expectedCalendarMonths'], 120)
        self.assertEqual(rolling['missingCandidateMonths'], 1)
        self.assertLess(rolling['end'], rolling['windowEnd'])
        self.assertEqual(rolling['n'], self.result['metrics']['rolling120']['n'] - 1)

    def test_nested_reliability_is_ols_bounded_frozen_and_does_not_use_boundary_target(self):
        dates = pd.date_range('2000-01-01', periods=61, freq='MS')
        history = [
            dict(date=engine.iso(date), target=i % 2, recentBlendProbability=0.4, probability=0.8)
            for i, date in enumerate(dates)
        ]
        fit = fit_reliability(history, '2006-01-01')
        self.assertEqual(fit['trainingN'], 60)
        self.assertAlmostEqual(fit['weight'], 0.25, places=10)
        self.assertEqual(fit['lastTargetMonth'], '2005-12-01')
        history[-1]['target'] = 1 - history[-1]['target']
        self.assertEqual(fit_reliability(history, '2006-01-01'), fit)
        self.assertEqual(fit_reliability(history[:59], '2006-01-01')['weight'], 0.0)
        equal = [dict(row, probability=0.4) for row in history[:60]]
        self.assertEqual(fit_reliability(equal, '2006-01-01')['status'], 'degenerate-recent-fallback')
        for fold in self.result['folds']:
            rows = [row for row in self.result['history'] if row['refitDate'] == fold['refitDate']]
            self.assertEqual(len(set(row['regimeWeight'] for row in rows)), 1)
            for row in rows:
                self.assertGreaterEqual(row['regimeWeight'], 0.0)
                self.assertLessEqual(row['regimeWeight'], 1.0)
                if row['weightLastTargetMonth']:
                    self.assertLess(row['weightLastTargetMonth'], row['refitDate'])
                expected = row['recentPriorProbability'] + row['regimeWeight'] * (
                    row['dynamicPriorProbability'] - row['recentPriorProbability']
                )
                self.assertAlmostEqual(row['adaptivePriorProbability'], expected, places=12)
                self.assertAlmostEqual(
                    row['adaptiveProbability'], 0.5 * row['originalProbability'] + 0.5 * expected, places=12
                )

    def test_missing_current_features_and_future_live_year_do_not_create_current_fit(self):
        latest = json.loads(json.dumps(self.latest))
        latest['features']['credit'] = None
        missing = build_regime_prior(self.panel, self.history, latest, engine.metrics)['latest']
        self.assertFalse(missing['available'])
        self.assertIsNone(missing['state'])
        self.assertIsNone(missing['probability'])
        self.assertIsNone(missing['adaptiveProbability'])
        latest = json.loads(json.dumps(self.latest))
        future = self.panel.index[-1] + pd.DateOffset(months=2)
        latest['issueDate'] = engine.iso(future)
        result = build_regime_prior(self.panel, self.history, latest, engine.metrics)
        self.assertFalse(result['latest']['available'])
        self.assertIsNone(result['latest']['weightFit'])
        self.assertTrue(all(row['date'] <= engine.iso(self.panel.index[-1]) for row in result['history']))
        self.assertFalse(any(pd.Timestamp(fold['refitDate']).year == future.year for fold in result['folds']))

    def test_csv_recomputes_models_on_identical_dates_and_brier_signs(self):
        text = regime_history_csv(self.result)
        self.assertEqual(text, regime_history_csv(self.result))
        frame = pd.read_csv(StringIO(text), index_col='date', parse_dates=True)
        for key in ['all', 'rolling120']:
            cohort = self.result['metrics'][key]
            group = frame.loc[cohort['windowStart'] : cohort['windowEnd']].dropna(
                subset=['target'] + list(PREDICTIONS.values())
            )
            self.assertEqual(len(group), cohort['n'])
            self.assertEqual(int(group.target.sum()), cohort['positiveWindows'])
            for name, column in PREDICTIONS.items():
                calculated = engine.metrics(group.target, group[column])
                for metric in ['auc', 'brier', 'logLoss']:
                    if calculated[metric] is not None:
                        self.assertAlmostEqual(calculated[metric], cohort['models'][name][metric], places=8)
            incumbent = cohort['models']['fixedBlend']['brier']
            candidate = cohort['models']['candidate']['brier']
            self.assertAlmostEqual(cohort['brierImprovement'], incumbent - candidate, places=12)
            self.assertAlmostEqual(cohort['brierDeltaVsIncumbent'], candidate - incumbent, places=12)
            self.assertAlmostEqual(
                cohort['relativeBrierImprovement'], (incumbent - candidate) / incumbent, places=12
            )
        for name, gate in [
            ('candidate', self.result['publicationGate']),
            ('adaptive', self.result['adaptiveGate']),
        ]:
            checks = [
                self.result['metrics'][key]['models'][name]['brier']
                < self.result['metrics'][key]['models']['fixedBlend']['brier']
                for key in ['all', 'rolling120']
            ]
            self.assertEqual(gate['passed'], all(checks))


if __name__ == '__main__':
    unittest.main(verbosity=2)
