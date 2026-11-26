"""Reproducible fixed-design rate-path and recent-prior checks; no network or writes."""
import importlib.util
from io import StringIO
from pathlib import Path
import unittest
import numpy as np
import pandas as pd
from rate_path import (
    FEATURES, BASE_FEATURES, PREDICTIONS, add_rate_path_features,
    build_rate_path, from_raw, rate_path_history_csv, recent_training_prior,
)

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rate_path_test_engine', ROOT / 'research' / 'build_model.py')
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


class RatePathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = from_raw(ROOT, '2026-11-25')
        cls.panel = pd.read_csv(ROOT / 'public' / 'data' / 'panel.csv', index_col=0, parse_dates=True)
        cls.panel = cls.panel.loc[cls.panel.index <= '2026-11-01']
        series = {}
        for key in ['GS10', 'TB3MS', 'FEDFUNDS', 'USREC']:
            values = pd.read_csv(ROOT / 'research' / 'raw' / f'{key}.csv', index_col=0, parse_dates=True)[key]
            series[key] = pd.to_numeric(values, errors='coerce').loc[values.index < '2026-11-01']
        cls.source = pd.DataFrame(series).sort_index().asfreq('MS')
        cls.expanded = add_rate_path_features(cls.panel, cls.source)

    def test_calendar_changes_and_two_month_lag_do_not_compress_missing_issue_months(self):
        dates = pd.date_range('2019-01-01', periods=40, freq='MS')
        source = pd.DataFrame({'GS10': np.arange(40.), 'TB3MS': 0., 'FEDFUNDS': 2 * np.arange(40.)}, index=dates)
        issues = pd.to_datetime(['2021-01-01', '2021-03-01'])
        panel = pd.DataFrame({'slope': 1., 'credit': 0., 'labor': 0., 'target': 0., 'recession': 0.}, index=issues)
        expanded = add_rate_path_features(panel, source)
        np.testing.assert_allclose(expanded.slopeChange6, [6., 6.])
        np.testing.assert_allclose(expanded.fedFundsChange12, [24., 24.])
        source.loc['2020-07-01', 'GS10'] = np.nan
        missing = add_rate_path_features(panel, source)
        self.assertTrue(pd.isna(missing.loc['2021-03-01', 'slopeChange6']))
        self.assertEqual(missing.loc['2021-03-01', 'fedFundsChange12'], 24.)

    def test_raw_observation_endpoints_match_latest_feature_values(self):
        latest = self.result['latest']
        feature_date = pd.Timestamp(latest['featureDate'])
        slope = self.source.GS10 - self.source.TB3MS
        self.assertAlmostEqual(latest['features']['slopeChange6'], slope.loc[feature_date] - slope.loc[feature_date - pd.DateOffset(months=6)], places=9)
        self.assertAlmostEqual(latest['features']['fedFundsChange12'], self.source.FEDFUNDS.loc[feature_date] - self.source.FEDFUNDS.loc[feature_date - pd.DateOffset(months=12)], places=9)
        self.assertEqual(pd.Timestamp(latest['issueDate']) - pd.DateOffset(months=2), feature_date)
        self.assertEqual(pd.Timestamp(latest['forecastStart']), pd.Timestamp(latest['issueDate']) + pd.DateOffset(months=1))
        self.assertEqual(pd.Timestamp(latest['forecastEnd']), pd.Timestamp(latest['issueDate']) + pd.DateOffset(months=12))

    def test_all_fold_targets_end_before_refit_and_scaling_uses_eligible_training_only(self):
        for fold in self.result['folds']:
            training = self.expanded.loc[self.expanded.index <= fold['trainingCutoff']].dropna(subset=FEATURES + ['target'])
            self.assertEqual(len(training), fold['trainingN'])
            self.assertLess(pd.Timestamp(fold['lastTargetMonth']), pd.Timestamp(fold['refitDate']))
            self.assertEqual(pd.Timestamp(fold['trainEnd']) + pd.DateOffset(months=12), pd.Timestamp(fold['lastTargetMonth']))
            np.testing.assert_allclose(training[FEATURES].mean(), fold['means'], atol=1e-7)
            np.testing.assert_allclose(training[FEATURES].std(ddof=0), fold['scales'], atol=1e-7)
            self.assertAlmostEqual(training.target.mean(), fold['trainingPrevalence'], places=10)

    def test_model_scoring_and_fixed_recipe_are_exact_without_recalibration(self):
        result = self.result
        model, latest = result['model'], result['latest']
        self.assertEqual(model['featureOrder'], FEATURES)
        self.assertEqual(model['penalty'], 1.)
        values = np.array([latest['features'][key] for key in FEATURES])
        raw_logit = model['rawIntercept'] + values @ model['rawCoefficients']
        standardized = model['intercept'] + ((values - model['means']) / model['scales']) @ model['coefficients']
        self.assertAlmostEqual(raw_logit, standardized, places=10)
        self.assertAlmostEqual(float(engine.sigmoid(raw_logit)), latest['rawProbability'], places=10)
        self.assertEqual(latest['probability'], .5 * latest['rawProbability'] + .5 * latest['baselineProbability'])
        self.assertEqual(latest['fixed50Probability'], latest['probability'])
        for row in result['history']:
            self.assertEqual(row['probability'], .5 * row['rawProbability'] + .5 * row['candidateBaseProbability'])
            self.assertEqual(row['matchedThreeBlendProbability'], .5 * row['matchedThreeProbability'] + .5 * row['candidateBaseProbability'])
            self.assertAlmostEqual(row['existingBlendProbability'], .5 * (row['originalProbability'] + row['baselineProbability']), places=12)

    def test_targets_are_not_extended_past_available_usrec_and_missing_rates_stay_missing(self):
        panel = self.panel.copy()
        panel.loc[panel.index > '2025-10-01', 'target'] = 0.
        result = add_rate_path_features(panel, self.source)
        cutoff = self.source.USREC.dropna().index[-1] - pd.DateOffset(months=12)
        self.assertTrue(result.loc[result.index > cutoff, 'target'].isna().all())
        source = self.source.copy()
        source.loc['2026-09-01', 'FEDFUNDS'] = np.nan
        missing = add_rate_path_features(self.panel, source)
        self.assertTrue(pd.isna(missing.loc['2026-11-01', 'fedFundsChange12']))

    def test_csv_recomputes_all_common_slices_and_raw_model_ablations(self):
        text = rate_path_history_csv(self.result)
        self.assertEqual(text, rate_path_history_csv(self.result))
        frame = pd.read_csv(StringIO(text), index_col='date', parse_dates=True)
        mature = frame.dropna(subset=['target'] + list(PREDICTIONS.values()))
        self.assertEqual(len(mature), self.result['metrics']['all']['n'])
        for slice_ in [self.result['metrics']['all'], self.result['metrics']['recent']] + self.result['metrics']['decades']:
            group = mature.loc[slice_['start']:slice_['end']] if slice_['n'] else mature.iloc[:0]
            self.assertEqual(len(group), slice_['n'])
            self.assertEqual(int(group.target.sum()), slice_['positiveWindows'])
            for name, column in PREDICTIONS.items():
                if len(group):
                    measured = engine.metrics(group.target, group[column])
                    for metric in ['auc', 'brier', 'logLoss']:
                        if measured[metric] is None:
                            self.assertIsNone(slice_['models'][name][metric])
                        else:
                            self.assertAlmostEqual(measured[metric], slice_['models'][name][metric], places=8)
        self.assertEqual(len(mature.loc['2016-01-01':]), self.result['metrics']['recent']['n'])
        self.assertTrue(frame.loc[frame.index > mature.index[-1], 'target'].isna().all())
        self.assertIn('matchedThree', self.result['metrics']['all']['models'])
        self.assertIn('candidateBase', self.result['metrics']['all']['models'])

    def test_publication_gates_are_computed_from_precommitted_windows_and_controls(self):
        slices = [self.result['metrics']['all'], self.result['metrics']['recent']]
        rate_checks = [s['models']['candidate']['brier'] < s['models']['existingBlend']['brier'] and s['models']['candidate']['brier'] < s['models']['base']['brier'] for s in slices]
        recent_checks = [s['models']['recentBlend']['brier'] < s['models']['existingBlend']['brier'] and s['models']['recentBlend']['brier'] < s['models']['base']['brier'] for s in slices]
        own_checks = [s['models']['recentBlend']['brier'] < s['models']['recentPrior']['brier'] for s in slices]
        self.assertEqual(self.result['publicationGate']['passed'], all(rate_checks))
        self.assertEqual(self.result['recentPriorGate']['benchmarksPassed'], all(recent_checks))
        self.assertEqual(self.result['recentPriorGate']['incrementalModelContributionSupported'], all(own_checks))
        self.assertEqual(self.result['recentPriorGate']['passed'], all(recent_checks + own_checks))

    def test_recent_window_has_exact_formal_bounds_and_does_not_slide_missing_labels(self):
        dates = pd.date_range('2000-01-01', periods=180, freq='MS')
        panel = pd.DataFrame({'slope': 1., 'credit': 0., 'labor': 0., 'target': 0.}, index=dates)
        panel.loc[dates[::10], 'target'] = 1.
        result = recent_training_prior(panel, '2014-12-01')
        self.assertEqual(result['start'], '2000-01-01')
        self.assertEqual(result['end'], '2014-12-01')
        self.assertEqual(result['n'], 180)
        self.assertEqual(result['probability'], .1)
        panel.loc[dates[-10:], 'target'] = np.nan
        missing = recent_training_prior(panel, '2014-12-01')
        self.assertEqual(missing['start'], result['start'])
        self.assertEqual(missing['end'], result['end'])
        self.assertEqual(missing['observedEnd'], '2014-02-01')
        self.assertEqual(missing['n'], 170)
        self.assertAlmostEqual(missing['probability'], panel.target.mean(), places=12)

    def test_recent_prior_requires_full_span_and_120_observed_original_three_months(self):
        dates = pd.date_range('2000-01-01', periods=180, freq='MS')
        panel = pd.DataFrame({'slope': 1., 'credit': 0., 'labor': 0., 'target': 0.}, index=dates)
        short = recent_training_prior(panel.iloc[1:], '2014-12-01')
        self.assertFalse(short['fullSpan'])
        self.assertIsNone(short['probability'])
        panel.loc[dates[:60], 'credit'] = np.nan
        valid = recent_training_prior(panel, '2014-12-01')
        self.assertEqual(valid['n'], 120)
        self.assertEqual(valid['probability'], 0.)
        panel.loc[dates[60], 'labor'] = np.nan
        self.assertIsNone(recent_training_prior(panel, '2014-12-01')['probability'])

    def test_recent_prior_excludes_after_cutoff_and_annual_values_remain_frozen(self):
        dates = pd.date_range('2000-01-01', periods=181, freq='MS')
        panel = pd.DataFrame({'slope': 1., 'credit': 0., 'labor': 0., 'target': 0.}, index=dates)
        panel.iloc[-1, panel.columns.get_loc('target')] = 1.
        self.assertEqual(recent_training_prior(panel, '2014-12-01')['probability'], 0.)
        for fold in self.result['folds']:
            expected = recent_training_prior(self.expanded, fold['trainingCutoff'])
            self.assertAlmostEqual(fold['recentPrior']['probability'], expected['probability'], places=9)
            self.assertEqual(fold['recentPrior']['n'], expected['n'])
            rows = [row for row in self.result['history'] if row['refitDate'] == fold['refitDate']]
            self.assertEqual(len(set(row['recentPriorProbability'] for row in rows)), 1)
            for row in rows:
                self.assertEqual(row['recentPriorStart'], expected['start'])
                self.assertEqual(row['recentPriorEnd'], expected['end'])
                self.assertEqual(row['recentBlendProbability'], .5 * row['originalProbability'] + .5 * row['recentPriorProbability'])
        current = self.result['latest']
        self.assertEqual(pd.Timestamp(current['recentPriorEnd']), pd.Timestamp(current['issueDate']) - pd.DateOffset(months=13))
        self.assertEqual(pd.Timestamp(current['recentPriorStart']), pd.Timestamp(current['recentPriorEnd']) - pd.DateOffset(months=179))
        self.assertEqual(current['recentBlendProbability'], .5 * current['originalProbability'] + .5 * current['recentPriorProbability'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
