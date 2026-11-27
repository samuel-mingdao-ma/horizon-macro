import unittest
from copy import deepcopy

import pandas as pd

from build_model import metrics
from weight_trial import PREDICTIONS, build_weight_trial, components, fit_weights, state_for


def fixture():
    dates = pd.date_range('1990-01-01', '2007-09-01', freq='MS')
    issue = dates[-1]
    rows = []
    for i, date in enumerate(dates):
        base = 0.20 + 0.02 * (i % 3)
        original = 0.1 + 0.16 * (i % 5)
        raw = 0.25 + 0.1 * (i % 6)
        y = int(i % 6 < 2) if date + pd.DateOffset(months=12) < issue else None
        rows.append(
            dict(
                date=str(date.date()),
                featureDate=str((date - pd.DateOffset(months=2)).date()),
                refitDate=f'{date.year}-01-01',
                slope=-0.1 if i % 2 else 0.4,
                credit=-0.2,
                target=y,
                recession=0,
                originalProbability=original,
                baselineProbability=base,
                permitsBlendProbability=(raw + base) / 2,
                existingBlendProbability=(original + base) / 2,
            )
        )
    latest = dict(
        rows[-1],
        issueDate=str(issue.date()),
        available=True,
        forecastStart='2007-10-01',
        forecastEnd='2008-09-01',
    )
    latest['features'] = {'slope': latest['slope'], 'credit': latest['credit']}
    return dict(latest=latest, history=rows)


class WeightTrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = fixture()
        cls.trial = build_weight_trial(cls.data, metrics)

    def test_state_thresholds_and_missing_inputs(self):
        self.assertEqual(state_for(0.1, 0.01), 'stress')
        self.assertEqual(state_for(-0.1, -0.01), 'stress')
        self.assertEqual(state_for(-1e-12, 2e-12), 'normal')
        self.assertEqual(state_for(0, 0), 'normal')
        self.assertIsNone(state_for(-0.1, None))
        self.assertIsNone(state_for(None, 1))
        self.assertIsNone(state_for(float('inf'), 0))

    def test_audit_moments_match_both_arm_ridge_solutions(self):
        h, fit = self.trial['history'], self.trial['latest']['fit']
        train = [r for r in h if r['date'] <= fit['trainingCutoff'] and r['commonMature']]
        self.assertEqual(len(train), fit['trainingN'])
        self.assertEqual(fit['trainEnd'], '2006-08-01')
        self.assertEqual(fit['lastTargetMonth'], '2007-08-01')
        for arm, field in [('permits', 'rawPermitsProbability'), ('original', 'originalProbability')]:
            for key in ['pool', 'stress', 'normal']:
                group = [r for r in train if key == 'pool' or r['state'] == key]
                d = [r[field] - r['baselineProbability'] for r in group]
                num = sum(x * (r['target'] - r['baselineProbability']) for r, x in zip(group, d))
                den = sum(x * x for x in d)
                anchor = 0.5 if key == 'pool' else fit[arm]['pool']['weight']
                cell = fit[arm][key]
                self.assertEqual(cell['n'], len(group))
                self.assertAlmostEqual(cell['numerator'], num)
                self.assertAlmostEqual(cell['denominator'], den)
                self.assertAlmostEqual(cell['weight'], min(1, max(0, (num + anchor) / (den + 1))))

    def test_warmup_and_empty_state_fallback(self):
        r = [
            dict(
                date=str(date.date()),
                target=1,
                state='stress',
                originalProbability=0.7,
                rawPermitsProbability=0.8,
                baselineProbability=0.2,
                existingBlendProbability=0.45,
            )
            for date in pd.date_range('1980-01-01', periods=60, freq='MS')
        ]
        first = fit_weights(r[:-1], '1994-01-01')
        for arm in ['permits', 'original']:
            self.assertTrue(all(cell['weight'] == 0.5 for cell in first[arm].values()))
        ready = fit_weights(r, '1994-01-01')
        self.assertFalse(ready['warmup'])
        self.assertEqual(ready['permits']['normal']['n'], 0)
        self.assertEqual(ready['permits']['normal']['weight'], ready['permits']['pool']['weight'])
        self.assertEqual(ready['permits']['pool']['weight'], 1)
        self.assertEqual(ready['permits']['stress']['weight'], 1)

    def test_future_mutation_and_cutoff_do_not_change_january_weights(self):
        altered = deepcopy(self.data)
        for row in altered['history']:
            if row['date'] >= '2001-01-01':
                row.update(
                    target=1,
                    originalProbability=0.02,
                    existingBlendProbability=(row['baselineProbability'] + 0.02) / 2,
                )
                row['permitsBlendProbability'] = (row['baselineProbability'] + 0.98) / 2
        other = build_weight_trial(altered, metrics)
        first = next(r for r in self.trial['folds'] if r['refitDate'] == '2002-01-01')
        second = next(r for r in other['folds'] if r['refitDate'] == '2002-01-01')
        self.assertEqual(first, second)
        self.assertEqual(first['trainEnd'], '2000-12-01')
        year_rows = [r for r in other['history'] if r['date'].startswith('2002')]
        self.assertTrue(
            all(r['refitDate'] == '2002-01-01' and r['trainingN'] == second['trainingN'] for r in year_rows)
        )
        cur = self.trial['latest']
        self.assertGreater(cur['trainingN'], self.trial['history'][-1]['trainingN'])

    def test_maturity_anchor_missing_state_and_score_reconstruction(self):
        altered = deepcopy(self.data)
        latest_mature = self.trial['metrics']['rolling120']['windowEnd']
        for row in altered['history']:
            if row['date'] == latest_mature:
                row['credit'] = None
            if row['date'] > latest_mature:
                row['target'] = 1
        t = build_weight_trial(altered, metrics)
        recent = t['metrics']['rolling120']
        self.assertEqual(recent['windowEnd'], latest_mature)
        self.assertEqual(recent['incumbentN'], 120)
        self.assertEqual(recent['n'], 119)
        for k in ['all', 'rolling120']:
            period = t['metrics'][k]
            rows = [
                r
                for r in t['history']
                if r['commonMature'] and period['windowStart'] <= r['date'] <= period['windowEnd']
            ]
            self.assertEqual(period['n'], len(rows))
            for name, field in PREDICTIONS.items():
                self.assertAlmostEqual(
                    period['models'][name]['brier'],
                    sum((r['target'] - r[field]) ** 2 for r in rows) / len(rows),
                )
        self.assertTrue(all(r['target'] is None for r in t['history'] if r['date'] > latest_mature))
        self.assertGreater(t['metrics']['all']['warmupMonths'], 0)

    def test_fixed_policy_and_missing_issue_forecast(self):
        for r in [*self.trial['history'], self.trial['latest']]:
            weight = 0.75 if r['state'] == 'stress' else 0.25
            self.assertEqual(r['fixedRuleWeight'], weight)
            self.assertAlmostEqual(
                r['fixedRuleProbability'],
                weight * r['rawPermitsProbability'] + (1 - weight) * r['baselineProbability'],
            )
        altered = deepcopy(self.data)
        altered['latest'].update(available=False, reason='Late series')
        current = build_weight_trial(altered, metrics)['latest']
        self.assertFalse(current['available'])
        self.assertIsNone(current['probability'])
        self.assertIsNone(current['fixedRuleProbability'])
        self.assertIsNotNone(current['existingBlendProbability'])
        self.assertEqual(current['reason'], 'Late series')

    def test_duplicate_months_mislabeled_refit_and_impossible_blends(self):
        altered = deepcopy(self.data)
        altered['history'].insert(1, altered['history'][0])
        with self.assertRaisesRegex(ValueError, 'unique'):
            build_weight_trial(altered, metrics)
        altered = deepcopy(self.data)
        altered['history'][1]['refitDate'] = altered['history'][1]['date']
        with self.assertRaisesRegex(ValueError, 'annual forecast'):
            build_weight_trial(altered, metrics)
        with self.assertRaisesRegex(ValueError, 'invalid raw'):
            components(dict(baselineProbability=0.2, permitsBlendProbability=0.9))


if __name__ == '__main__':
    unittest.main()
